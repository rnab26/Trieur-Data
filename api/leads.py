# =============================================================
# Routes de la base "Leads" à très grand volume (page dédiée du frontend).
# Toute la logique est dans trieur/leads.py (et, pour les règles de données,
# dans la migration 0035) ; ici : validation des entrées, droits, HTTP.
# Le routeur est fabriqué par `creer_routeur(get_ctx)` pour réutiliser la
# dépendance d'authentification d'api/main.py sans import circulaire.
# =============================================================

from __future__ import annotations

import json
import os
import shutil
import tempfile
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from trieur import leads as L

# Dossier des fichiers en cours d'import (variable d'environnement, jamais en dur)
DOSSIER_IMPORTS = os.environ.get("LEADS_TMP_DIR") or tempfile.gettempdir()
# Nombre maximal d'éléments dans une liste de départements / sources (borne les requêtes)
LISTE_MAX = 200
FILTRES_MAX = 8


def _http(exc: L.LeadsError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.message)


def _entiers(texte: str, nom: str) -> Optional[list[int]]:
    if not texte.strip():
        return None
    try:
        vals = [int(x) for x in texte.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail=f"« {nom} » doit être une liste de nombres.")
    if len(vals) > LISTE_MAX or any(v < 0 or v > 32000 for v in vals):
        raise HTTPException(status_code=400, detail=f"« {nom} » : valeurs invalides.")
    return vals


def _filtres(texte: str) -> dict:
    try:
        f = json.loads(texte or "{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="« filtres » doit être un JSON valide.")
    if not isinstance(f, dict) or len(f) > FILTRES_MAX:
        raise HTTPException(status_code=400, detail="« filtres » : format invalide.")
    for col, spec in f.items():
        if not isinstance(spec, dict) or col not in ("nom", "prenom", "email", "adresse", "cp", "ville"):
            raise HTTPException(status_code=400, detail=f"Filtre sur une colonne inconnue : {col}.")
    return f


class Selection(BaseModel):
    depts: list[int] = Field(default_factory=list, max_length=LISTE_MAX)
    exclues: list[int] = Field(default_factory=list, max_length=LISTE_MAX)
    filtres: dict = Field(default_factory=dict)


class ReglageSource(BaseModel):
    statut: str
    note: Optional[str] = None


class ReglageValeur(BaseModel):
    valeur: str


def creer_routeur(get_ctx: Callable[..., Any]) -> APIRouter:
    r = APIRouter(prefix="/leads", tags=["leads"])

    def appel(ctx, fonction, params=None):
        try:
            return L.appel(ctx.client, fonction, params)
        except L.LeadsError as exc:
            raise _http(exc)

    def regl(ctx) -> dict:
        try:
            return L.reglages(ctx.client)
        except L.LeadsError as exc:
            raise _http(exc)

    # ---------- réglages
    @r.get("/reglages")
    def lire_reglages(ctx=Depends(get_ctx)):
        return {"reglages": appel(ctx, "leads_reglages_lire")}

    @r.put("/reglages/{cle}")
    def poser_reglage(cle: str, corps: ReglageValeur, ctx=Depends(get_ctx)):
        if not ctx.profile.get("is_super_admin"):
            raise HTTPException(status_code=403, detail="Réservé aux administrateurs.")
        appel(ctx, "leads_reglage_poser", {"p_cle": cle, "p_valeur": corps.valeur})
        return {"cle": cle, "valeur": corps.valeur}

    # ---------- sources
    @r.get("/sources")
    def lister_sources(ctx=Depends(get_ctx)):
        return {"sources": appel(ctx, "leads_sources_lister") or []}

    @r.patch("/sources/{source_id}")
    def regler_source(source_id: int, corps: ReglageSource, ctx=Depends(get_ctx)):
        appel(ctx, "leads_source_regler", {"p_id": source_id, "p_statut": corps.statut, "p_note": corps.note})
        return {"id": source_id, "statut": corps.statut}

    # ---------- comptes et aperçu
    @r.get("/compter")
    def compter(depts: str = Query(""), exclues: str = Query(""), ctx=Depends(get_ctx)):
        """Lignes par département pour la sélection : instantané et exact (statistiques tenues par l'import)."""
        par_dept = appel(ctx, "leads_compter",
                         {"p_depts": _entiers(depts, "depts"), "p_exclues": _entiers(exclues, "exclues")}) or []
        return {"par_departement": par_dept, "total": sum(int(x["n"]) for x in par_dept)}

    @r.get("/apercu")
    def apercu(depts: str = Query(""), exclues: str = Query(""), filtres: str = Query("{}"),
               dept: Optional[int] = Query(None), apres: Optional[str] = Query(None, max_length=32),
               ctx=Depends(get_ctx)):
        """Une page de l'aperçu (taille = réglage `apercu_taille`), curseur (dept, apres) → suite."""
        regl_ = regl(ctx)
        res = appel(ctx, "leads_lire", {
            "p_depts": _entiers(depts, "depts"), "p_exclues": _entiers(exclues, "exclues"),
            "p_filters": _filtres(filtres), "p_dept": dept, "p_apres": apres,
            "p_limite": L.reglage_int(regl_, "apercu_taille"), "p_blocs_max": None, "p_mode": "apercu",
        })
        return {"rows": res["rows"], "suite": res["suite"], "taille_page": L.reglage_int(regl_, "apercu_taille")}

    # ---------- tâches
    def _tache(ctx, job_id: str) -> dict:
        t = appel(ctx, "leads_job_lire", {"p_job": job_id})
        if not t:
            raise HTTPException(status_code=404, detail="Tâche introuvable.")
        return t

    def _avec_silence(ctx, t: dict, silence_s: int) -> dict:
        t = dict(t)
        t["silencieuse"] = L.silencieuse(t, silence_s)
        return t

    @r.get("/jobs")
    def lister_jobs(kind: Optional[str] = Query(None, pattern="^(import|export|comptage)$"),
                    limite: int = Query(20, ge=1, le=100), ctx=Depends(get_ctx)):
        silence = L.reglage_int(regl(ctx), "silence_job_s")
        jobs = appel(ctx, "leads_jobs_lister", {"p_kind": kind, "p_limite": limite}) or []
        return {"jobs": [_avec_silence(ctx, j, silence) for j in jobs]}

    @r.get("/jobs/{job_id}")
    def lire_job(job_id: str, ctx=Depends(get_ctx)):
        return _avec_silence(ctx, _tache(ctx, job_id), L.reglage_int(regl(ctx), "silence_job_s"))

    @r.post("/jobs/{job_id}/annuler")
    def annuler_job(job_id: str, ctx=Depends(get_ctx)):
        t = appel(ctx, "leads_job_annuler", {"p_job": job_id})
        if not t:
            raise HTTPException(status_code=409, detail="Cette tâche n'est plus en cours.")
        return t

    @r.post("/jobs/{job_id}/abandonner")
    def abandonner_job(job_id: str, ctx=Depends(get_ctx)):
        """Une tâche restée « en cours » sans nouvelles (serveur redémarré) : la marquer interrompue."""
        t = _tache(ctx, job_id)
        if t["status"] != "en_cours":
            return t
        return appel(ctx, "leads_job_etat", {
            "p_job": job_id, "p_status": "interrompu", "p_message": "Marquée comme interrompue par l'utilisateur."})

    @r.get("/jobs/{job_id}/doublons")
    def doublons(job_id: str, ctx=Depends(get_ctx)):
        """Exemples de doublons rejetés par cet import (le total exact est dans la tâche)."""
        _tache(ctx, job_id)
        return {"doublons": appel(ctx, "leads_doublons_lister", {"p_job": job_id}) or []}

    # ---------- import
    @r.post("/imports")
    def importer(source: str = Form(...), reprendre: Optional[str] = Form(None),
                 file: UploadFile = File(...), ctx=Depends(get_ctx)):
        """Reçoit un fichier CSV/Excel, le range sur disque, puis l'importe par lots en tâche de fond.
        `reprendre` = identifiant d'une tâche interrompue : repart après les lignes déjà traitées
        (renvoyer le MÊME fichier)."""
        regl_ = regl(ctx)
        nom = file.filename or "import"
        limite = L.reglage_int(regl_, "import_max_mo") * 1_048_576
        os.makedirs(DOSSIER_IMPORTS, exist_ok=True)
        fd, chemin = tempfile.mkstemp(prefix="leads_", suffix=os.path.splitext(nom)[1] or ".csv", dir=DOSSIER_IMPORTS)
        octets = 0
        try:
            with os.fdopen(fd, "wb") as out:
                while bloc := file.file.read(8_388_608):
                    octets += len(bloc)
                    if octets > limite:
                        raise HTTPException(
                            status_code=413,
                            detail=f"Fichier trop gros (plus de {limite // 1_048_576} Mo). Découpe-le en plusieurs fichiers.")
                    out.write(bloc)
            if octets == 0:
                raise HTTPException(status_code=400, detail="Le fichier est vide.")
            try:
                entete = L.lire_entete(chemin, nom)
            except Exception:  # noqa: BLE001
                raise HTTPException(status_code=400, detail="Impossible de lire ce fichier (CSV ou Excel attendu).")
            mapping, ignorees = L.reconnaitre_colonnes(entete)
            try:
                L.verifier_mapping(mapping)
            except L.LeadsError as exc:
                raise _http(exc)

            source_id = appel(ctx, "leads_source_obtenir", {"p_nom": source})
            a_sauter = 0
            if reprendre:
                ancien = _tache(ctx, reprendre)
                reprenable = ancien["status"] in ("interrompu", "erreur") \
                    or L.silencieuse(ancien, L.reglage_int(regl_, "silence_job_s"))
                if ancien["kind"] != "import" or not reprenable:
                    raise HTTPException(status_code=409, detail="Cette tâche ne peut pas être reprise.")
                if ancien.get("source_id") != source_id or ancien.get("filename") != nom:
                    raise HTTPException(status_code=409, detail="Reprise : il faut le même fichier et la même source.")
                a_sauter = int(ancien["lignes_lues"] or 0)
                job = appel(ctx, "leads_job_etat", {
                    "p_job": reprendre, "p_status": "en_cours", "p_message": "Import repris."})
                # leads_job_etat ne ré-ouvre pas une tâche annulée ; une tâche interrompue repasse « en cours »
                if not job or job["status"] != "en_cours":
                    raise HTTPException(status_code=409, detail="Cette tâche ne peut pas être reprise.")
                total = job.get("lignes_total")
            else:
                total = L.compter_lignes(chemin, nom)
                job = appel(ctx, "leads_job_creer", {
                    "p_kind": "import", "p_source": source_id, "p_filename": nom, "p_total": total,
                    "p_params": {"colonnes_reconnues": mapping, "colonnes_ignorees": ignorees}})
            L.executer_en_fond(L.lancer_import, ctx.client, job["id"], source_id, chemin, nom, mapping, regl_,
                               a_sauter, paralleles=L.reglage_int(regl_, "jobs_paralleles"))
            return {"job": job, "colonnes_reconnues": mapping, "colonnes_ignorees": ignorees}
        except BaseException:
            # rien n'a démarré : ne pas laisser le fichier sur le disque
            if os.path.exists(chemin):
                try:
                    os.remove(chemin)
                except OSError:
                    pass
            raise

    # ---------- comptage exact avec filtres de colonne
    @r.post("/comptages")
    def lancer_comptage(sel: Selection, ctx=Depends(get_ctx)):
        regl_ = regl(ctx)
        filtres = _filtres(json.dumps(sel.filtres))
        job = appel(ctx, "leads_job_creer", {
            "p_kind": "comptage", "p_source": None, "p_filename": None, "p_total": None,
            "p_params": {"depts": sel.depts, "exclues": sel.exclues, "filtres": filtres}})
        L.executer_en_fond(L.lancer_comptage, ctx.client, job["id"], sel.depts, sel.exclues, filtres, regl_,
                           paralleles=L.reglage_int(regl_, "jobs_paralleles"))
        return {"job": job}

    # ---------- export en flux
    @r.post("/exports")
    def creer_export(sel: Selection, ctx=Depends(get_ctx)):
        """Prépare un export : crée la tâche (suivi, annulation) et un lien de téléchargement à usage unique."""
        regl_ = regl(ctx)
        filtres = _filtres(json.dumps(sel.filtres))
        total = None
        if not filtres:
            par = appel(ctx, "leads_compter", {"p_depts": sel.depts or None, "p_exclues": sel.exclues or None}) or []
            total = sum(int(x["n"]) for x in par)
            if total == 0:
                raise HTTPException(status_code=400, detail="Aucune ligne à exporter avec cette sélection.")
        job = appel(ctx, "leads_job_creer", {
            "p_kind": "export", "p_source": None, "p_filename": None, "p_total": total,
            "p_params": {"depts": sel.depts, "exclues": sel.exclues, "filtres": filtres}})
        jeton = L.creer_jeton(ctx.client, job["id"], L.reglage_int(regl_, "jeton_telechargement_s"))
        return {"job": job, "url": f"/leads/exports/{job['id']}/fichier?jeton={jeton}"}

    @r.post("/exports/{job_id}/reprise")
    def reprendre_export(job_id: str, ctx=Depends(get_ctx)):
        t = _tache(ctx, job_id)
        regl_ = regl(ctx)
        if t["kind"] != "export" or (t["status"] not in ("interrompu", "erreur")
                                     and not L.silencieuse(t, L.reglage_int(regl_, "silence_job_s"))):
            raise HTTPException(status_code=409, detail="Cet export ne peut pas être repris.")
        suite = (t.get("params") or {}).get("suite")
        if not suite:
            raise HTTPException(status_code=409, detail="Rien à reprendre : relance un nouvel export.")
        appel(ctx, "leads_job_etat", {"p_job": job_id, "p_status": "en_cours", "p_message": "Reprise de l'export."})
        jeton = L.creer_jeton(ctx.client, job_id, L.reglage_int(regl_, "jeton_telechargement_s"))
        return {"job": _tache(ctx, job_id), "url": f"/leads/exports/{job_id}/fichier?jeton={jeton}&reprise=1"}

    @r.get("/exports/{job_id}/fichier")
    def telecharger(job_id: str, jeton: str = Query(..., max_length=100), reprise: int = Query(0)):
        """CSV en flux, sans en-tête Authorization (lien à usage unique, voir creer_jeton)."""
        try:
            client = L.consommer_jeton(jeton, job_id)
            t = L.appel(client, "leads_job_lire", {"p_job": job_id})
            if not t or t["kind"] != "export" or t["status"] != "en_cours":
                raise L.LeadsError(409, "Cet export n'est plus en cours.")
            regl_ = L.reglages(client)
        except L.LeadsError as exc:
            raise _http(exc)
        p = t.get("params") or {}
        rep = (p.get("suite") if reprise else None) or None
        nom = "leads_export" + ("_suite" if rep else "") + ".csv"
        flux = L.flux_export(client, job_id, p.get("depts") or None, p.get("exclues") or None,
                             p.get("filtres") or None, regl_, reprise=rep)
        return StreamingResponse(flux, media_type="text/csv; charset=utf-8",
                                 headers={"Content-Disposition": f'attachment; filename="{nom}"',
                                          "Cache-Control": "no-store"})

    return r
