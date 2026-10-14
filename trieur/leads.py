# =============================================================
# Base "Leads" à très grand volume (dizaines de millions de lignes) --
# chantier cockpit 6547bd6a, migration supabase/migrations/0035_leads_massifs.sql.
#
# Ce module ne contient AUCUNE règle de normalisation ni de dédoublonnage :
# elles vivent dans la base (fonctions leads_dept / leads_cle / leads_importer_lot,
# testées par scripts/verifier_leads_sql.py). Ici : lire un fichier par morceaux,
# envoyer des lots, parcourir un export fenêtre par fenêtre, suivre une tâche.
#
# Contrainte de fond : l'API ne dispose que de PostgREST avec le jeton de
# l'utilisateur (aucune connexion Postgres directe), et la base coupe toute
# requête à 8 s. Tout travail long est donc découpé en requêtes courtes
# (lot d'import, fenêtre de lecture) enchaînées par l'API, avec reprise.
# =============================================================

from __future__ import annotations

import csv
import io
import os
import secrets
import threading
import time
import unicodedata
from typing import Any, Callable, Iterator, Optional

SCHEMA = "trieur_data"

# Colonnes canoniques attendues par leads_importer_lot, et les intitulés
# (normalisés : minuscules, sans accents, sans ponctuation) qui y mènent.
# Une seule table : ajouter un synonyme = une ligne ici.
SYNONYMES: dict[str, tuple[str, ...]] = {
    "nom": ("nom", "lastname", "nomdefamille", "surname", "name"),
    "prenom": ("prenom", "firstname", "givenname"),
    "email": ("email", "mail", "courriel", "adresseemail", "emailperso", "adressemail"),
    "tel_mobile": ("telephonemobile", "mobile", "portable", "telmobile", "telephoneportable", "gsm",
                   "telephone", "tel", "numerodetelephone", "phone", "telephone1"),
    "tel_fixe": ("telephonefixe", "fixe", "telfixe", "telephonedomicile", "telephone2"),
    "adresse": ("adresse", "address", "adresse1", "rue", "voie"),
    "cp": ("cp", "codepostal", "zip", "zipcode", "postalcode"),
    "ville": ("ville", "city", "commune"),
    "civilite": ("civilite", "genrecivilite", "genre", "titre", "gender"),
    "naissance": ("datedenaissance", "naissance", "ddn", "birthdate", "dob", "datenaissance"),
}
# Au moins une de ces colonnes est indispensable (la base ne garde pas une ligne sans clé)
COLONNES_CLE = ("tel_mobile", "tel_fixe", "email")

# Erreurs rendues à l'écran : code du message SQL -> (statut HTTP, texte)
ERREURS_SQL = {
    "acces_refuse": (403, "Accès refusé à la base Leads."),
    "colonne_inconnue": (400, "Filtre sur une colonne inconnue."),
    "source_vide": (400, "Donne un nom de source."),
    "statut_invalide": (400, "Statut de source invalide."),
    "source_inconnue": (404, "Source inconnue."),
    "reglage_inconnu": (404, "Réglage inconnu."),
    "tache_inconnue": (404, "Tâche inconnue."),
    "tache_annule": (409, "Tâche annulée."),
    "tache_termine": (409, "Tâche déjà terminée."),
    "tache_interrompu": (409, "Tâche interrompue."),
    "tache_erreur": (409, "Tâche en erreur."),
}


class LeadsError(Exception):
    """Erreur lisible (statut HTTP + texte) levée par ce module."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _exc_text(exc: Exception) -> str:
    return f"{getattr(exc, 'code', '')} {getattr(exc, 'message', '')} {exc}"


def traduire_erreur(exc: Exception) -> LeadsError:
    """Rend une erreur PostgREST/SQL en erreur lisible."""
    text = _exc_text(exc)
    if "PGRST202" in text or "Could not find the function" in text:
        return LeadsError(503, "La base Leads n'est pas encore installée (migration 0035 à appliquer).")
    if "57014" in text or "statement timeout" in text:
        return LeadsError(504, "La base a mis trop de temps à répondre. Réduis la sélection et réessaie.")
    for code, (status, msg) in ERREURS_SQL.items():
        if code in text:
            return LeadsError(status, msg)
    return LeadsError(502, "La base Leads n'a pas répondu comme prévu. Réessaie.")


def est_timeout(exc: Exception) -> bool:
    text = _exc_text(exc)
    return "57014" in text or "statement timeout" in text


def appel(client: Any, fonction: str, params: Optional[dict] = None) -> Any:
    """Appelle une fonction du schéma trieur_data ; les erreurs deviennent LeadsError."""
    try:
        return client.postgrest.schema(SCHEMA).rpc(fonction, params or {}).execute().data
    except LeadsError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise traduire_erreur(exc) from exc


def appel_brut(client: Any, fonction: str, params: Optional[dict] = None) -> Any:
    """Comme `appel` mais laisse remonter l'exception d'origine (pour distinguer un délai dépassé)."""
    return client.postgrest.schema(SCHEMA).rpc(fonction, params or {}).execute().data


def reglages(client: Any) -> dict[str, str]:
    """Réglages de la base Leads : {clé: valeur texte}."""
    data = appel(client, "leads_reglages_lire") or {}
    return {k: v["valeur"] for k, v in data.items()}


def reglage_int(regl: dict[str, str], cle: str) -> int:
    return int(regl[cle])


# ---------------------------------------------------------------
# Colonnes d'un fichier
# ---------------------------------------------------------------

def normaliser_entete(texte: Any) -> str:
    s = unicodedata.normalize("NFKD", str(texte)).encode("ascii", "ignore").decode()
    return "".join(c for c in s.lower() if c.isalnum())


def reconnaitre_colonnes(colonnes: list[str]) -> tuple[dict[str, str], list[str]]:
    """({colonne canonique: intitulé du fichier}, intitulés ignorés). Premier intitulé reconnu gagne."""
    mapping: dict[str, str] = {}
    pris: set[str] = set()
    for col in colonnes:
        n = normaliser_entete(col)
        for canon, noms in SYNONYMES.items():
            if canon not in mapping and n in noms:
                mapping[canon] = col
                pris.add(col)
                break
    return mapping, [c for c in colonnes if c not in pris]


def verifier_mapping(mapping: dict[str, str]) -> None:
    if not any(c in mapping for c in COLONNES_CLE):
        raise LeadsError(
            400,
            "Aucune colonne de téléphone ou d'e-mail reconnue : sans elle, impossible de supprimer les "
            "doublons. Renomme une colonne (ex. « TELEPHONE MOBILE » ou « EMAIL ») et réessaie.",
        )


# ---------------------------------------------------------------
# Lecture d'un fichier par morceaux (mémoire constante pour un CSV)
# ---------------------------------------------------------------

def _detecter_encodage(chemin: str) -> str:
    with open(chemin, "rb") as f:
        tete = f.read(1_048_576)
    try:
        tete.decode("utf-8-sig")
        return "utf-8-sig"
    except UnicodeDecodeError as exc:
        # une coupure en plein caractère à la fin de l'échantillon n'est pas une erreur de codage
        if exc.start >= len(tete) - 4:
            return "utf-8-sig"
        return "cp1252"


def _detecter_separateur(chemin: str, encodage: str) -> str:
    with open(chemin, "r", encoding=encodage, errors="replace", newline="") as f:
        ligne = f.readline()
    candidats = [";", ",", "\t", "|"]
    return max(candidats, key=lambda c: ligne.count(c)) if any(c in ligne for c in candidats) else ","


def est_excel(nom: str) -> bool:
    return nom.lower().endswith((".xlsx", ".xlsm", ".xls"))


def lire_entete(chemin: str, nom: str) -> list[str]:
    import pandas as pd

    if est_excel(nom):
        return [str(c) for c in pd.read_excel(chemin, dtype=str, nrows=0).columns]
    enc = _detecter_encodage(chemin)
    sep = _detecter_separateur(chemin, enc)
    with open(chemin, "r", encoding=enc, errors="replace", newline="") as f:
        return [c.strip() for c in next(csv.reader(f, delimiter=sep), [])]


def compter_lignes(chemin: str, nom: str) -> Optional[int]:
    """Nombre de lignes de données (pour la barre de progression). CSV : comptage des fins de ligne
    (approximatif si des champs contiennent des retours à la ligne). Excel : inconnu avant lecture."""
    if est_excel(nom):
        return None
    n = 0
    with open(chemin, "rb") as f:
        while bloc := f.read(8_388_608):
            n += bloc.count(b"\n")
    return max(n - 1, 0)


def morceaux(chemin: str, nom: str, taille: int, a_sauter: int = 0) -> Iterator[Any]:
    """Morceaux (DataFrame de textes) d'au plus `taille` lignes, après avoir sauté `a_sauter` lignes."""
    import pandas as pd

    if est_excel(nom):
        df = pd.read_excel(chemin, dtype=str).fillna("")
        for i in range(a_sauter, len(df), taille):
            yield df.iloc[i:i + taille]
        return
    enc = _detecter_encodage(chemin)
    sep = _detecter_separateur(chemin, enc)
    restant = a_sauter
    for df in pd.read_csv(chemin, sep=sep, dtype=str, keep_default_na=False, encoding=enc,
                          encoding_errors="replace", chunksize=taille, on_bad_lines="skip"):
        if restant >= len(df):
            restant -= len(df)
            continue
        if restant:
            df = df.iloc[restant:]
            restant = 0
        yield df


def charge_utile(df: Any, mapping: dict[str, str]) -> list[dict[str, str]]:
    """Lignes au format attendu par leads_importer_lot (clés canoniques, textes bruts)."""
    sel = df[[orig for orig in mapping.values()]].copy()
    sel.columns = list(mapping.keys())
    return sel.to_dict(orient="records")


# ---------------------------------------------------------------
# Import
# ---------------------------------------------------------------

def _etat(client: Any, job_id: str, **kw: Any) -> None:
    params = {"p_job": job_id}
    for k, v in kw.items():
        params["p_" + k] = v
    try:
        appel_brut(client, "leads_job_etat", params)
    except Exception:  # noqa: BLE001 -- ne jamais masquer l'erreur principale
        pass


def _envoyer_lot(client: Any, job_id: str, source_id: int, df: Any, mapping: dict[str, str],
                 essais: int, pause_s: float) -> None:
    """Envoie un lot ; si la base coupe (délai), le lot est coupé en deux (l'appel est atomique :
    un lot coupé n'a rien écrit). Les erreurs de réseau sont réessayées."""
    params = {"p_job": job_id, "p_source": source_id, "p_rows": charge_utile(df, mapping), "p_lues": len(df)}
    for essai in range(essais):
        try:
            appel_brut(client, "leads_importer_lot", params)
            return
        except Exception as exc:  # noqa: BLE001
            if est_timeout(exc) and len(df) > 1:
                milieu = len(df) // 2
                _envoyer_lot(client, job_id, source_id, df.iloc[:milieu], mapping, essais, pause_s)
                _envoyer_lot(client, job_id, source_id, df.iloc[milieu:], mapping, essais, pause_s)
                return
            texte = _exc_text(exc)
            if "tache_" in texte or "acces_refuse" in texte or essai == essais - 1:
                raise traduire_erreur(exc) from exc
            time.sleep(pause_s * (essai + 1))


def lancer_import(client: Any, job_id: str, source_id: int, chemin: str, nom: str, mapping: dict[str, str],
                  regl: dict[str, str], a_sauter: int = 0, essais: int = 3, pause_s: float = 2.0,
                  supprimer_fichier: bool = True) -> str:
    """Boucle d'import (à lancer dans un fil). Rend l'état final : termine / annule / interrompu."""
    lot = reglage_int(regl, "lot_import")
    try:
        for df in morceaux(chemin, nom, lot, a_sauter):
            _envoyer_lot(client, job_id, source_id, df, mapping, essais, pause_s)
        _etat(client, job_id, status="termine", message="Import terminé.")
        return "termine"
    except LeadsError as exc:
        if exc.status == 409 and "annul" in exc.message.lower():
            return "annule"
        _etat(client, job_id, status="interrompu",
              message=f"{exc.message} Reprends l'import avec le même fichier : il repart là où il s'est arrêté.")
        return "interrompu"
    except Exception as exc:  # noqa: BLE001
        _etat(client, job_id, status="interrompu",
              message=f"Import arrêté ({type(exc).__name__}). Reprends-le avec le même fichier.")
        return "interrompu"
    finally:
        if supprimer_fichier:
            try:
                os.remove(chemin)
            except OSError:
                pass


# ---------------------------------------------------------------
# Lecture : comptage exact en tâche de fond, export en flux
# ---------------------------------------------------------------

def _params_lecture(depts: Optional[list[int]], exclues: Optional[list[int]], filtres: Optional[dict],
                    dept: Optional[int], apres: Optional[str], limite: Optional[int], blocs_max: Optional[int],
                    mode: str) -> dict:
    return {
        "p_depts": depts or None, "p_exclues": exclues or None, "p_filters": filtres or {},
        "p_dept": dept, "p_apres": apres, "p_limite": limite, "p_blocs_max": blocs_max, "p_mode": mode,
    }


def lancer_comptage(client: Any, job_id: str, depts: Optional[list[int]], exclues: Optional[list[int]],
                    filtres: Optional[dict], regl: dict[str, str]) -> str:
    """Comptage exact (avec filtres de colonne) fenêtre par fenêtre ; résultat dans params.resultat."""
    blocs = reglage_int(regl, "fenetre_blocs")
    total, dept, apres = 0, None, None
    try:
        while True:
            etat = appel_brut(client, "leads_job_lire", {"p_job": job_id}) or {}
            if etat.get("status") != "en_cours":
                return etat.get("status", "annule")
            r = appel_brut(client, "leads_lire",
                           _params_lecture(depts, exclues, filtres, dept, apres, None, blocs, "compte"))
            total += int(r["n"])
            suite = r.get("suite")
            _etat(client, job_id, lues=total)
            if not suite:
                _etat(client, job_id, lues=total, status="termine", params={"resultat": total},
                      message="Comptage terminé.")
                return "termine"
            dept, apres = suite["dept"], suite["apres"]
    except Exception as exc:  # noqa: BLE001
        _etat(client, job_id, status="erreur", message=f"Comptage arrêté : {traduire_erreur(exc).message}")
        return "erreur"


class ExportInterrompu(Exception):
    """L'export s'arrête (annulé, ou erreur) : le flux HTTP doit être coupé net, pour que le
    navigateur n'enregistre pas un fichier incomplet comme s'il était complet."""


def flux_export(client: Any, job_id: str, depts: Optional[list[int]], exclues: Optional[list[int]],
                filtres: Optional[dict], regl: dict[str, str], reprise: Optional[dict] = None,
                pause: Callable[[float], None] = time.sleep) -> Iterator[bytes]:
    """Génère le CSV par fenêtres (mémoire constante). `reprise` = {dept, apres} pour continuer un
    export interrompu (le fichier de la reprise n'a pas d'entête : il se colle à la suite)."""
    blocs = reglage_int(regl, "fenetre_blocs")
    blocs_min = max(10, blocs // 20)
    pause_s = reglage_int(regl, "export_pause_ms") / 1000.0
    dept = reprise.get("dept") if reprise else None
    apres = reprise.get("apres") if reprise else None
    lignes = 0
    try:
        if not reprise:
            entete = appel_brut(client, "leads_entete_csv")
            yield b"\xef\xbb\xbf" + (entete + "\n").encode("utf-8")
        else:
            lignes = int((appel_brut(client, "leads_job_lire", {"p_job": job_id}) or {}).get("lignes_lues") or 0)
        while True:
            etat = appel_brut(client, "leads_job_lire", {"p_job": job_id}) or {}
            if etat.get("status") != "en_cours":
                raise ExportInterrompu(etat.get("status", "annule"))
            try:
                r = appel_brut(client, "leads_lire",
                               _params_lecture(depts, exclues, filtres, dept, apres, None, blocs, "csv"))
            except Exception as exc:  # noqa: BLE001
                if est_timeout(exc) and blocs > blocs_min:
                    blocs = max(blocs_min, blocs // 2)  # la base est lente : fenêtres plus petites
                    continue
                raise
            # Point de reprise = DÉBUT de la fenêtre en cours, écrit avant de l'envoyer : si le navigateur
            # coupe pendant qu'elle part, on ne sait pas ce qu'il a reçu ; reprendre à son début ne perd
            # jamais de ligne (au pire quelques lignes de la jonction arrivent deux fois).
            _etat(client, job_id, lues=lignes, params={"suite": {"dept": dept, "apres": apres}})
            if r.get("csv"):
                yield (r["csv"] + "\n").encode("utf-8")
            lignes += int(r["n"])
            suite = r.get("suite")
            if not suite:
                _etat(client, job_id, lues=lignes, status="termine", message="Export terminé.")
                return
            dept, apres = suite["dept"], suite["apres"]
            if pause_s:
                pause(pause_s)
    except ExportInterrompu:
        raise
    except GeneratorExit:
        _etat(client, job_id, status="interrompu",
              message="Téléchargement interrompu. Utilise « Reprendre » pour recevoir la suite.")
        raise
    except Exception as exc:  # noqa: BLE001
        _etat(client, job_id, status="interrompu",
              message=f"Export arrêté : {traduire_erreur(exc).message} Utilise « Reprendre » pour la suite.")
        raise ExportInterrompu("erreur") from exc


# ---------------------------------------------------------------
# Liens de téléchargement à usage unique
# ---------------------------------------------------------------
# Un lien <a href> ne peut pas porter l'en-tête Authorization : l'API remet un jeton aléatoire,
# valable `jeton_telechargement_s` secondes et pour UN téléchargement, lié au client authentifié
# de la personne qui l'a demandé. Gardé en mémoire (un seul processus) : un redémarrage de
# l'API invalide les liens en attente, la page en redemande un.

_jetons: dict[str, dict] = {}
_verrou = threading.Lock()


def creer_jeton(client: Any, job_id: str, duree_s: int) -> str:
    jeton = secrets.token_urlsafe(24)
    with _verrou:
        maintenant = time.time()
        for k in [k for k, v in _jetons.items() if v["expire"] < maintenant]:
            del _jetons[k]
        _jetons[jeton] = {"client": client, "job": job_id, "expire": maintenant + duree_s}
    return jeton


def consommer_jeton(jeton: str, job_id: str) -> Any:
    with _verrou:
        v = _jetons.pop(jeton, None)
    if not v or v["expire"] < time.time() or v["job"] != job_id:
        raise LeadsError(403, "Lien de téléchargement expiré ou déjà utilisé. Reviens sur la page et relance l'export.")
    return v["client"]


# ---------------------------------------------------------------
# Tâches de fond (un petit nombre à la fois)
# ---------------------------------------------------------------

_pool: Optional[Any] = None


def executer_en_fond(fonction: Callable[..., Any], *args: Any, paralleles: int = 2, **kw: Any) -> None:
    global _pool
    from concurrent.futures import ThreadPoolExecutor

    with _verrou:
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=max(1, paralleles), thread_name_prefix="leads")
        pool = _pool
    pool.submit(fonction, *args, **kw)


def silencieuse(tache: dict, silence_s: int, maintenant: Optional[float] = None) -> bool:
    """Une tâche « en cours » sans nouvelle depuis trop longtemps est affichée comme interrompue."""
    from datetime import datetime

    if tache.get("status") != "en_cours" or not tache.get("updated_at"):
        return False
    try:
        t = datetime.fromisoformat(str(tache["updated_at"]).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return False
    return (maintenant or time.time()) - t > silence_s


def csv_en_lignes(texte: str, sep: str = ",") -> list[list[str]]:
    """Utilitaire de test : relit un CSV produit par l'export."""
    return list(csv.reader(io.StringIO(texte), delimiter=sep))
