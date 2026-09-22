"""Génération des mandats de prélèvement SEPA (environnement Prélèvement).

Règles reconstruites à partir des 3 fichiers Excel de référence + le
classeur Drive historique que Raphaël a fournis (2026-09-21), et
confirmées avec lui question par question -- voir PROJECT_LOG.md pour
le détail. Chaque règle ici correspond à une formule ou une décision
du fichier Excel d'origine du père de Raphaël ; ne rien changer sans
l'avoir revérifié avec lui, c'est un domaine "zéro droit à l'erreur".

Portée de cette première version (Raphaël a explicitement demandé de
NE PAS faire plus pour l'instant) :
- prend un export CRM brut (mêmes colonnes que le fichier "1_récupération
  du CRM") ;
- nettoie/valide chaque ligne, calcule les dates ;
- ÉCLATE chaque client en un mandat PAR PRODUIT actif (pas un mandat
  combiné) -- chaque produit garde son propre montant et son propre
  motif "MGS-{RUM}-{suffixe}" ;
- classe chaque mandat en OOFF (1er prélèvement, +frais de dossier fixe
  par produit) ou RCUR (récurrent, sans frais) ;
- exclut proprement (avec la raison) tout ce qui ne peut pas partir en
  banque.

PAS dans cette version (chantier séparé, voir Cockpit "Historique,
doublons, impayés et relevé bancaire") : comparaison à l'historique
des remises passées, détection de doublons/noms inversés, suivi des
impayés, réconciliation du relevé bancaire.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

# ---------------------------------------------------------------
# Colonnes attendues dans l'export CRM (mêmes noms que le fichier Excel
# de référence -- espaces superflus compris, volontairement pas
# nettoyés à la source pour rester reconnaissable si Raphaël compare
# avec l'original). `_norm_key` ci-dessous absorbe ces espaces à la
# lecture, donc l'ordre/l'espacement exact du fichier importé n'a pas
# besoin d'être identique au caractère près.
# ---------------------------------------------------------------

COL_NOM = "Nom complet"
COL_REFERENCE = "Référence du client"
COL_RUM = "RUM"
COL_STATUT = "Statut"
COL_TYPE_PRELEVEMENT = "Type de prélèvement"
COL_PERIODICITE = "Périodicité (Mensuel/trimestre/annuel)"
COL_IBAN = "IBAN"
COL_BIC = "BIC"
COL_DATE_PREMIER = "Date de premier prélèvement"
COL_DATE_CREATION = "Date création"
COL_ADRESSE = "Adresse"
COL_VILLE = "Ville"
COL_CODE_POSTAL = "Code postal"
COL_EMAIL = "Email"
# "Statut agent IA" -- champ jusque-là inexploité, découvert le
# 2026-09-22 en revérifiant les 3 fichiers maîtres du père de Raphaël à
# sa demande (le bug ci-dessous avait fait fuir TOUS les mandats en
# FRST, jamais un seul RCUR). Porte deux signaux distincts, confirmés
# avec Raphaël avant de coder :
# 1. "Notifié le {jour}" = notification préalable obligatoire (règle
#    SEPA) avant un prélèvement RÉCURRENT -- vérifié sur le fichier de
#    référence (291 lignes) : le jour de notification correspond au
#    jour de prélèvement récurrent du client dans 95,3% des cas
#    (204/214). Bien plus fiable que l'ancienne règle ("Total frais de
#    dossier" > 0 pour FRST), qui ne concordait qu'à 63% (557/878) avec
#    le vrai historique des remises bancaires du Drive.
# 2. "Refusé par le client" / "Nrp J-1 - Annuler contrat" -- le client a
#    refusé ou son contrat doit être annulé : jamais envoyé en banque,
#    même règle qu'un IBAN invalide.
COL_STATUT_IA = "Statut agent IA"
COL_TELEPHONE = "Téléphone"
# "Mobile" -- repli si "Téléphone" (fixe) est vide. Vérifié sur le
# fichier CRM de référence (2026-09-22, signalé par Raphaël) : "Mobile"
# est rempli pour 100% des 291 clients, "Téléphone" seulement pour 68%
# -- ne lire que "Téléphone" laissait donc ~32% des mandats sans aucun
# numéro alors que le vrai numéro du client était présent dans l'autre
# colonne de la même ligne. Jamais inventé : juste la bonne colonne.
COL_MOBILE = "Mobile"

# Colonnes produit -- montants en euros. "Optivie" est fusionné dans
# "Optilife" (Raphaël, 2026-09-21 : "les deux mêmes produits avec les
# deux mêmes règles d'utilisation"). "Contrat MYMO casse & perte
# appareil auditif" est délibérément IGNORÉ (Raphaël : "je ne la prends
# pas en compte pour l'instant") -- jamais additionné, jamais dans le
# motif.
COL_OPTILIFE = "Optilife"
COL_OPTIVIE = "Optivie"
COL_CARTE_MGS = "Carte MGS"
COL_MYJURIS = "MYJURIS & MYHOSPI"
COL_ADMIN_AIDE = "Admin & Aide a dom"
COL_AUDITIF = "Auditif"
COL_IMMO = "IMMO"
COL_VETO = "Total cotisation MYMO VETO SUR"
COL_DATE_EFFET = "Date d'effet du nouveau contrat (OPTILIFE)"

# Suffixe du motif par produit -- ordre et lettres copiés de la formule
# `="MGS-"&RUM&IF(Optilife>0,"-O","")&IF(CarteMGS>0,"-M","")&...` du
# fichier "3_creations_des_mandats" (onglet "3 Sheet1", colonne Motif).
# Sert aussi maintenant à ÉCLATER un client en plusieurs mandats -- voir
# generate_mandats.
# "-AU"/IMMO et non "-IM" -- corrigé le 2026-09-21 en croisant 5 clients
# du CRM avec le vrai fichier de remise bancaire du Drive (lecture
# seule) : la colonne IMMO correspond systématiquement au suffixe
# "-AU" dans les vraies remises envoyées, jamais "-IM" (la formule
# d'origine reverse-engineered avait les deux lettres inversées).
# "Auditif" n'apparaît jamais rempli dans aucun fichier vu jusqu'ici --
# suffixe "-IM" laissé par déduction, à revérifier le jour où elle sera
# utilisée pour de vrai.
_MOTIF_SUFFIXES: list[tuple[str, str]] = [
    (COL_OPTILIFE, "-O"),
    (COL_CARTE_MGS, "-M"),
    (COL_MYJURIS, "-J"),
    (COL_ADMIN_AIDE, "-AD"),
    (COL_AUDITIF, "-IM"),
    (COL_IMMO, "-AU"),
    (COL_VETO, "-V"),
]


def _norm_key(s: str) -> str:
    """Espaces (y compris multiples/en fin de chaîne) et casse ignorés --
    les en-têtes du fichier Excel d'origine ont des espaces parasites
    (ex. "IBAN  ", "Référence du client ") qu'un import réel ne
    reproduira pas forcément à l'identique."""
    return re.sub(r"\s+", " ", s or "").strip().lower()


@dataclass
class PrelevementRules:
    """Réglages ajustables sans toucher au code -- stockés par
    organisation dans trieur_data.prelevement_rules, jamais codés en
    dur dans ce module."""

    ics: str | None = None
    nature: str = "CORE"
    delay_days: int = 3
    # Frais de dossier facturés UNE FOIS PAR PRODUIT au 1er prélèvement
    # (jamais sur les suivants) -- confirmé à 20€/produit en croisant le
    # fichier CRM de référence avec le vrai fichier de remise bancaire du
    # Drive (2026-09-21) : un client avec 2 produits actifs a "Total
    # frais de dossier"=40€ (2x20), pas un montant client indivis.
    frais_setup_eur: float = 20.0


@dataclass
class MandatRow:
    reference_client: str
    nom: str
    rum: str
    iban: str
    bic: str
    adresse: str
    ville: str
    code_postal: str
    pays: str
    email: str
    telephone: str
    type_sequence: str  # "FRST" (OOFF) ou "RCUR"
    montant_eur: float
    devise: str
    date_signature_mandat: str
    date_premiere_echeance: str
    date_effet: str
    periodicite: str
    explication_periodicite: str
    motif: str


@dataclass
class ExclusionRow:
    reference_client: str
    nom: str
    raison: str


@dataclass
class GenerationResult:
    # Tous les mandats (FRST + RCUR), dans l'ordre de génération -- pour
    # l'onglet "Mandat" combiné demandé par Raphaël (2026-09-21) : "un
    # onglet mandat où il y a tout dessus". ooff/rcur restent en plus
    # pour le détail par type.
    mandats: list[MandatRow] = field(default_factory=list)
    ooff: list[MandatRow] = field(default_factory=list)
    rcur: list[MandatRow] = field(default_factory=list)
    exclus: list[ExclusionRow] = field(default_factory=list)


def normalize_iban(raw: object) -> str:
    """Retire tous les espaces, met en majuscules -- règle donnée par
    Raphaël (2026-09-21) : "le seul correctif qu'on fait sur l'IBAN
    c'est supprimer les blancs entre les chiffres et changer le fr
    minuscule en FR majuscule"."""
    if raw is None:
        return ""
    return re.sub(r"\s+", "", str(raw)).upper()


def iban_checksum_valid(iban: str) -> bool:
    """Contrôle mod-97 (ISO 7064 MOD 97-10) -- le VRAI calcul de
    validité d'un IBAN, pas juste "il y a quelque chose". Reproduit la
    colonne "IBAN ctrl" du fichier de référence (onglet "3 Sheet1"),
    qui fait le même calcul en plusieurs cellules à la suite."""
    iban = normalize_iban(iban)
    if len(iban) < 15 or not re.fullmatch(r"[A-Z]{2}[0-9]{2}[A-Z0-9]+", iban):
        return False
    rearranged = iban[4:] + iban[:4]
    digits = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(digits) % 97 == 1


def pad_bic(raw: object) -> str:
    """BIC à 8 caractères -> complété à 11 avec "XXX" (code d'agence
    générique), comme la formule `IF(LEN(bic)=8,UPPER(bic)&"XXX",...)`
    du fichier de référence -- un BIC à 11 caractères est déjà complet,
    laissé tel quel (juste mis en majuscules)."""
    if raw is None:
        return ""
    bic = str(raw).strip().upper()
    return bic + "XXX" if len(bic) == 8 else bic


def to_amount(raw: object) -> float:
    """Convertit un montant qui peut arriver en texte avec virgule OU
    point comme séparateur décimal (l'export CRM d'origine mélange les
    deux selon les colonnes -- la formule Excel de référence fait
    `SUBSTITUTE(valeur,".",",")* 1` pour forcer la conversion). Une
    valeur vide/invalide vaut 0, jamais une erreur bloquante : un
    montant manquant sur UN produit ne doit pas faire échouer toute la
    ligne du client.

    Bug réel trouvé le 2026-09-21 (client MACEDO ANNIE / MGS-18397,
    signalé par Raphaël) : `pandas.DataFrame.where(pd.notnull(df), None)`
    ne remplace PAS toujours une cellule vide par `None` sur une colonne
    de nombres (repli connu de pandas -- une colonne float ne peut pas
    contenir `None`, donc `where()` la recase discrètement en NaN). Le
    "vide" arrive alors ici comme `float('nan')`, PAS `None` -- sans ce
    contrôle, `49.9 + nan = nan`, et `nan > 0` vaut `False` : un client
    avec un vrai produit actif (Optilife 49,90€) était exclu à tort
    ("aucun produit actif") juste parce qu'une AUTRE colonne produit
    (Optivie) avait une cellule vide plutôt qu'un 0 explicite."""
    if raw is None or raw == "":
        return 0.0
    if isinstance(raw, float) and raw != raw:  # NaN (jamais égal à lui-même)
        return 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip().replace(" ", "")
    if not text:
        return 0.0
    # Un seul séparateur présent -> c'est le séparateur décimal, quel
    # qu'il soit. Les deux présents -> celui qui vient en dernier est
    # le décimal (l'autre est un séparateur de milliers).
    if "," in text and "." in text:
        text = text.replace(",", "") if text.rfind(".") > text.rfind(",") else text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return 0.0


def to_telephone(raw: object) -> str:
    """Corrige la REPRÉSENTATION d'un numéro déjà présent dans la
    cellule -- ne comble jamais un numéro manquant, ne devine jamais un
    chiffre.

    Bug réel (2026-09-22, signalé par Raphaël sur un lot réel) : quand
    une cellule numéro est enregistrée comme un NOMBRE dans le fichier
    source (pas du texte, contrairement à la majorité des lignes),
    pandas la lit en float64 -- `str(33630653771.0)` donne
    "33630653771.0", un ".0" qui n'a jamais existé dans le vrai numéro
    (même famille de bug que le NaN corrigé sur to_amount, 2026-09-21).

    Repli de mise en forme : un numéro à 11 chiffres commençant par
    "33" (le préfixe pays, sans le "+" -- perdu par le passage en
    nombre) est reformaté en "+33..." pour rester cohérent avec les
    cellules déjà en texte du même fichier (ex. "+33630653771"). Toute
    autre forme est renvoyée telle quelle."""
    if raw is None or raw == "":
        return ""
    if isinstance(raw, float) and raw != raw:  # NaN (jamais égal à lui-même)
        return ""
    if isinstance(raw, (int, float)):
        # Un numéro n'a jamais de vraie décimale -- int() ne perd donc
        # aucun chiffre, seulement le ".0" ajouté à tort par pandas.
        digits = str(int(raw))
    else:
        digits = str(raw).strip()
    if not digits:
        return ""
    if digits.startswith("+"):
        return digits
    if digits.startswith("33") and len(digits) == 11:
        return "+" + digits
    return digits


def _parse_date(raw: object) -> date | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    text = str(raw).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def compute_first_prelevement_date(raw_scheduled: object, today: date, delay_days: int) -> date | None:
    """La date du 1er prélèvement n'est JAMAIS avant aujourd'hui +
    délai (3 jours par défaut, toujours le même -- confirmé par
    Raphaël) : `MAX(TODAY()+3, date_prévue)` dans le fichier de
    référence. Si aucune date n'était prévue au départ, retourne None
    -- ce cas est exclu du lot par `generate_mandats` plutôt que
    d'inventer une date."""
    scheduled = _parse_date(raw_scheduled)
    if scheduled is None:
        return None
    plancher = today + timedelta(days=delay_days)
    return max(plancher, scheduled)


def build_motif(rum: str, suffix: str) -> str:
    """"MGS-{RUM}{suffixe du produit}" -- un mandat par produit, PAS un
    motif combiné (ex. "MGS-42-O-M") : croisé avec le vrai fichier de
    remise bancaire du Drive (2026-09-21), qui a bien une ligne "MGS-
    {RUM}-O" ET une ligne séparée "MGS-{RUM}-J" pour un même client avec
    2 produits, chacune avec SON PROPRE montant -- jamais un montant
    total mélangeant plusieurs produits."""
    return f"MGS-{rum}{suffix}"


def _get(row: dict, col: str, keyed: dict[str, str]) -> object:
    key = keyed.get(_norm_key(col))
    return row.get(key) if key is not None else None


def generate_mandats(rows: list[dict], rules: PrelevementRules, today: date | None = None) -> GenerationResult:
    """Traite chaque ligne de l'export CRM brut et la range dans OOFF,
    RCUR, ou "exclus" avec la raison. Ne lève jamais d'exception sur
    une ligne individuelle mal formée -- elle part en exclusion avec la
    raison, le reste du lot continue (un fichier de 300 clients ne doit
    pas échouer en entier à cause d'une seule ligne cassée)."""
    today = today or date.today()
    result = GenerationResult()
    if not rows:
        return result

    # Colonnes réellement présentes dans CE fichier, normalisées --
    # construit une fois, pas à chaque ligne.
    keyed = {_norm_key(c): c for c in rows[0].keys()}

    for row in rows:
        ref_client = str(_get(row, COL_REFERENCE, keyed) or "")
        nom = str(_get(row, COL_NOM, keyed) or "")

        def exclure(raison: str) -> None:
            result.exclus.append(ExclusionRow(reference_client=ref_client, nom=nom, raison=raison))

        type_prelevement = str(_get(row, COL_TYPE_PRELEVEMENT, keyed) or "").strip()
        if type_prelevement.lower() != "prélèvement":
            exclure(f"Mode de paiement \"{type_prelevement or 'non renseigné'}\", pas un prélèvement SEPA")
            continue

        iban = normalize_iban(_get(row, COL_IBAN, keyed))
        if not iban or not iban_checksum_valid(iban):
            exclure("IBAN manquant ou invalide")
            continue

        rum = str(_get(row, COL_RUM, keyed) or "").strip()
        if not rum:
            exclure("RUM manquant")
            continue

        statut_ia = str(_get(row, COL_STATUT_IA, keyed) or "").strip()
        statut_ia_lower = statut_ia.lower()
        if "refus" in statut_ia_lower or "annuler" in statut_ia_lower:
            exclure(f"Statut agent IA \"{statut_ia}\" -- client refusé ou contrat à annuler")
            continue

        date_premiere = compute_first_prelevement_date(
            _get(row, COL_DATE_PREMIER, keyed), today, rules.delay_days,
        )
        if date_premiere is None:
            exclure("Pas de date de premier prélèvement renseignée")
            continue

        optilife_optivie = to_amount(_get(row, COL_OPTILIFE, keyed)) + to_amount(_get(row, COL_OPTIVIE, keyed))
        amounts = {
            COL_OPTILIFE: optilife_optivie,
            COL_CARTE_MGS: to_amount(_get(row, COL_CARTE_MGS, keyed)),
            COL_MYJURIS: to_amount(_get(row, COL_MYJURIS, keyed)),
            COL_ADMIN_AIDE: to_amount(_get(row, COL_ADMIN_AIDE, keyed)),
            COL_AUDITIF: to_amount(_get(row, COL_AUDITIF, keyed)),
            COL_IMMO: to_amount(_get(row, COL_IMMO, keyed)),
            COL_VETO: to_amount(_get(row, COL_VETO, keyed)),
        }
        produits_actifs = [(col, suffix) for col, suffix in _MOTIF_SUFFIXES if amounts[col] > 0]
        if not produits_actifs:
            exclure("Aucun produit actif (tous les montants produits sont à 0)")
            continue

        # MYJURIS + IMMO fusionnés en UN SEUL mandat "-J-AU" quand les
        # deux sont actifs -- seule exception à la règle "un mandat par
        # produit" ci-dessous, trouvée le 2026-09-21 en croisant le vrai
        # fichier de remise bancaire (2 clients confirmés : montant RCUR
        # = somme exacte des deux colonnes, FRST = RCUR + 2x les frais
        # de dossier -- jamais observé combiné avec un autre produit).
        if amounts[COL_MYJURIS] > 0 and amounts[COL_IMMO] > 0:
            reste = [(c, s) for c, s in produits_actifs if c not in (COL_MYJURIS, COL_IMMO)]
            mandats_bundles: list[tuple[str, list[str]]] = [("-J-AU", [COL_MYJURIS, COL_IMMO])]
            mandats_bundles += [(s, [c]) for c, s in reste]
        else:
            mandats_bundles = [(s, [c]) for c, s in produits_actifs]

        # FRST (1er prélèvement, avec frais de dossier) vs RCUR
        # (récurrent, sans frais) -- "Statut agent IA" commence par
        # "Notifié" = le client a reçu la notification obligatoire
        # avant un prélèvement RÉCURRENT (règle SEPA), donc RCUR. Sinon
        # (vide, "Validé par le client", autre) -- FRST. Bug réel
        # corrigé le 2026-09-22 (signalé par Raphaël : "aucun
        # prélèvement n'est récurrent") : l'ancienne règle ("Total frais
        # de dossier" > 0 -> FRST) ne concordait qu'à 63% avec le vrai
        # historique des remises bancaires du Drive -- voir COL_STATUT_IA
        # ci-dessus pour le détail de la vérification (95,3% de
        # concordance sur le nouveau signal).
        type_sequence = "RCUR" if statut_ia_lower.startswith("notifié") else "FRST"

        # Date de signature du mandat = la date de création du contrat
        # dans le CRM, PAS la date à laquelle ce fichier est généré --
        # vérifié contre le fichier de référence (2026-09-21) : un
        # client créé le 21/08 garde cette date, même généré des
        # semaines après. Repli sur aujourd'hui seulement si absente.
        date_signature = _parse_date(_get(row, COL_DATE_CREATION, keyed)) or today
        date_effet_raw = _parse_date(_get(row, COL_DATE_EFFET, keyed))
        date_effet = date_effet_raw.strftime("%d/%m/%Y") if date_effet_raw else ""

        # "Explication périodicité" (ex. "Tous les 1 mois") : laissée
        # vide pour un 1er prélèvement (FRST) -- elle ne décrit que la
        # récurrence des prélèvements SUIVANTS, vérifié contre le
        # fichier de référence.
        explication = "" if type_sequence == "FRST" else _explication_periodicite(
            _get(row, COL_PERIODICITE, keyed),
        )

        # UN MANDAT PAR PRODUIT ACTIF (sauf le duo MYJURIS+IMMO ci-dessus),
        # jamais un mandat unique combinant tous les produits -- règle
        # trouvée le 2026-09-21 en croisant ce fichier CRM avec le vrai
        # fichier de remise bancaire du Drive (lecture seule) : un
        # client avec Optilife (49,90€) ET MYJURIS (29,89€) a DEUX
        # lignes dans la vraie remise ("MGS-{RUM}-O" à 49,90€/69,90€ et
        # "MGS-{RUM}-J" à 29,89€/49,89€), jamais une ligne unique à
        # 79,79€. Le montant est la somme BRUTE des colonnes du/des
        # produit(s) du mandat -- "Total cotisation et frais de dossier"
        # ne sert plus à rien ici, il ne correspond à aucun montant réel
        # (vérifié faux sur plus de 10 clients croisés). Les frais de
        # dossier sont comptés une fois PAR PRODUIT du mandat (2x pour
        # le duo MYJURIS+IMMO, confirmé sur le vrai fichier).
        for suffix, cols in mandats_bundles:
            montant_produits = sum(amounts[c] for c in cols)
            frais = rules.frais_setup_eur * len(cols) if type_sequence == "FRST" else 0.0
            montant = montant_produits + frais
            mandat = MandatRow(
                reference_client=ref_client,
                nom=nom,
                rum=rum,
                iban=iban,
                bic=pad_bic(_get(row, COL_BIC, keyed)),
                adresse=str(_get(row, COL_ADRESSE, keyed) or ""),
                ville=str(_get(row, COL_VILLE, keyed) or ""),
                code_postal=str(_get(row, COL_CODE_POSTAL, keyed) or ""),
                pays="FR",
                email=str(_get(row, COL_EMAIL, keyed) or ""),
                telephone=(
                    to_telephone(_get(row, COL_TELEPHONE, keyed))
                    or to_telephone(_get(row, COL_MOBILE, keyed))
                ),
                type_sequence=type_sequence,
                montant_eur=round(montant, 2),
                devise="EUR",
                date_signature_mandat=date_signature.strftime("%d/%m/%Y"),
                date_premiere_echeance=date_premiere.strftime("%d/%m/%Y"),
                date_effet=date_effet,
                periodicite=str(_get(row, COL_PERIODICITE, keyed) or ""),
                explication_periodicite=explication,
                motif=build_motif(rum, suffix),
            )
            result.mandats.append(mandat)
            (result.ooff if type_sequence == "FRST" else result.rcur).append(mandat)

    return result


_PERIODICITE_EXPLICATIONS = {
    "mensuelle": "Tous les 1 mois",
    "bimestrielle": "Tous les 2 mois",
    "trimestrielle": "Tous les 3 mois",
    "semestrielle": "Tous les 6 mois",
    "annuel": "Tous les 12 mois",
    "annuelle": "Tous les 12 mois",
}


def _explication_periodicite(raw: object) -> str:
    return _PERIODICITE_EXPLICATIONS.get(str(raw or "").strip().lower(), "")
