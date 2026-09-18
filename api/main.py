# =============================================================
# API REST FastAPI -- expose la logique métier déjà écrite dans
# trieur/db.py (et quelques helpers purs de views/) sans la dupliquer,
# pour permettre une migration progressive de l'interface vers React.
# Ne remplace pas l'app Streamlit (app.py) : les deux peuvent tourner en
# parallèle, branchées sur la même base Supabase.
#
# Auth : le même schéma que views/_auth.py (Supabase Auth), mais sans
# session serveur -- chaque requête porte son propre jeton d'accès en
# "Authorization: Bearer <token>", vérifié via client.auth.get_user().
# =============================================================

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from typing import Any, Optional

import pandas as pd
from fastapi import Depends, FastAPI, File, Form, HTTPException, Header, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from fastapi.responses import StreamingResponse

from trieur.db import (
    LIST_PAGE_SIZE,
    add_chantier_message,
    add_chantier_todo,
    add_org_master_columns,
    append_pipeline_rows,
    count_records,
    create_chantier,
    create_pipeline_session,
    create_section,
    delete_record,
    delete_saved_view,
    get_last_import_batch,
    get_my_memberships,
    get_my_profile,
    get_org_master_columns,
    get_pipeline_session,
    get_record,
    import_dataframe,
    list_all_records,
    list_chantier_messages,
    list_chantier_todos,
    list_chantiers,
    list_dedup_alerts,
    list_pipeline_rows,
    list_records,
    list_saved_views,
    list_sections,
    resolve_dedup_alert,
    save_org_master_columns,
    save_saved_view,
    set_chantier_todo_done,
    update_chantier_status,
    update_pipeline_row_data,
    update_pipeline_session_status,
    update_record,
)
from trieur.export import export_csv_safe, export_excel_safe, sanitize_filename
from trieur.io_excel import read_csv_file, read_excel_all_sheets_from_file
from trieur.matching import apply_header_inference_excel, auto_assign_columns_fast
from views._auth import accessible_organizations
from views._ui import unknown_columns
from views.tab_database import (
    _build_rows,
    _filter_by_columns,
    _filter_by_search,
    _resolve_modifier_names,
    diff_rows,
)

app = FastAPI(title="Trieur de Data API", description="API REST sur trieur/db.py")

# CORS : dev local (Vite) + domaine de production (à ajuster une fois le
# vrai nom de domaine Render connu -- placeholder demandé explicitement).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "https://trieur-data.onrender.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_supabase_client():
    """Un client Supabase NEUF à chaque requête -- volontairement PAS le
    singleton `trieur.db.get_client()` (@st.cache_resource) : ce dernier
    est un objet UNIQUE, partagé par tout le process, sur lequel Streamlit
    pose le jeton de la session courante (client.postgrest.auth(...)/
    client.auth.set_session(...)). Le réutiliser tel quel ici ferait
    courir le jeton d'un utilisateur sur la requête concurrente d'un
    autre (FastAPI/uvicorn traite plusieurs requêtes en parallèle,
    contrairement à un rerun Streamlit synchrone) -- un vrai bug de
    fuite de données entre comptes, pas une hypothèse. La construction
    (URL + clé anon depuis les Secrets) reste la même que get_client() ;
    toute la LOGIQUE MÉTIER, elle, continue de passer par trieur/db.py
    sans rien dupliquer."""
    from supabase import create_client
    import streamlit as st

    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["anon_key"]
    return create_client(url, key)


@dataclass
class AuthCtx:
    client: Any
    user: Any
    profile: dict
    memberships: list


def get_current_ctx(
    authorization: Optional[str] = Header(default=None),
    client=Depends(get_supabase_client),
) -> AuthCtx:
    """Valide le jeton Supabase porté par la requête et renvoie le
    contexte utilisateur (client authentifié, profil, appartenances) --
    équivalent de views/_auth.py:require_login(), sans session serveur."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="En-tête 'Authorization: Bearer <token>' requis.")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Jeton vide.")

    try:
        user_res = client.auth.get_user(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Jeton invalide ou expiré.")
    if not user_res or not getattr(user_res, "user", None):
        raise HTTPException(status_code=401, detail="Jeton invalide ou expiré.")
    user = user_res.user

    # Applique le jeton aux requêtes PostgREST suivantes sur CE client (RLS
    # scopée à cet utilisateur) -- équivalent de client.auth.set_session()
    # côté Streamlit, sans avoir besoin d'un refresh_token ici (on ne porte
    # qu'un access_token côté API, jamais de refresh_token).
    client.postgrest.auth(token)

    profile = get_my_profile(client, user.id)
    if not profile:
        raise HTTPException(
            status_code=401,
            detail="Compte connecté mais aucun profil Trieur de Data associé.",
        )
    memberships = get_my_memberships(client, user.id)

    return AuthCtx(client=client, user=user, profile=profile, memberships=memberships)


def require_org_access(org_id: str, ctx: AuthCtx = Depends(get_current_ctx)) -> AuthCtx:
    """Vérifie que l'utilisateur connecté a accès à `org_id` (membre, ou
    super-admin) -- même règle que views/_auth.py:accessible_organizations,
    appliquée ici côté API en plus de la RLS Supabase (défense en
    profondeur)."""
    orgs = accessible_organizations(
        {"client": ctx.client, "profile": ctx.profile, "memberships": ctx.memberships}
    )
    if org_id not in {o["id"] for o in orgs}:
        raise HTTPException(status_code=403, detail="Accès refusé à cet environnement.")
    return ctx


def require_cockpit_access(ctx: AuthCtx = Depends(require_org_access)) -> AuthCtx:
    """Le Cockpit sert au développement du logiciel lui-même (chantiers),
    pas aux données clients -- réservé aux administrateurs, même règle
    que views/tab_cockpit.py:render()."""
    if not ctx.profile.get("is_super_admin"):
        raise HTTPException(status_code=403, detail="Le Cockpit est réservé aux administrateurs.")
    return ctx


# ---------------------------------------------------------------
# Profil courant
# ---------------------------------------------------------------

@app.get("/me")
def get_me(ctx: AuthCtx = Depends(get_current_ctx)):
    """Profil du compte connecté -- notamment `is_super_admin`, dont le
    frontend a besoin pour savoir s'il doit proposer les contrôles
    d'édition des colonnes maîtres (write endpoint déjà réservé aux
    admins ci-dessous ; ceci évite de laisser un membre simple ouvrir un
    formulaire qui échouera systématiquement en 403)."""
    return {"profile": ctx.profile}


# ---------------------------------------------------------------
# Orgs
# ---------------------------------------------------------------

@app.get("/orgs")
def list_orgs(ctx: AuthCtx = Depends(get_current_ctx)):
    return accessible_organizations(
        {"client": ctx.client, "profile": ctx.profile, "memberships": ctx.memberships}
    )


# ---------------------------------------------------------------
# Tableau de bord
# ---------------------------------------------------------------

@app.get("/orgs/{org_id}/dashboard")
def get_dashboard(org_id: str, ctx: AuthCtx = Depends(require_org_access)):
    total = count_records(ctx.client, org_id)
    alerts = list_dedup_alerts(ctx.client, org_id, status="pending")
    last_import = get_last_import_batch(ctx.client, org_id)
    return {
        "total_records": total,
        "alerts_pending": len(alerts),
        "last_import": last_import,
    }


# ---------------------------------------------------------------
# Clients (records)
# ---------------------------------------------------------------

def _parse_col_filters(raw: str) -> dict:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"col_filters n'est pas un JSON valide : {exc}")
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="col_filters doit être un objet JSON {colonne: {op, value}}.")
    return parsed


@app.get("/orgs/{org_id}/records")
def list_org_records(
    org_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(LIST_PAGE_SIZE, ge=1, le=2000),
    search: str = Query(""),
    col_filters: str = Query("{}", description="JSON : {colonne: {op, value}}"),
    ctx: AuthCtx = Depends(require_org_access),
):
    """Liste paginée des clients de l'environnement. NOTE (limite
    connue, cohérente avec l'existant côté Streamlit -- voir
    views/tab_database.py:_render_client_list) : `search`/`col_filters`
    filtrent le LOT chargé pour cette page, pas tout l'historique --
    même comportement que le "Charger plus" de l'interface actuelle,
    pas une régression introduite ici."""
    parsed_filters = _parse_col_filters(col_filters)
    master_cols = get_org_master_columns(ctx.client, org_id)
    total = count_records(ctx.client, org_id)
    records = list_records(ctx.client, org_id, limit=page_size, offset=(page - 1) * page_size)

    rows = _resolve_modifier_names(ctx.client, _build_rows(records, master_cols))
    rows = _filter_by_search(rows, search)
    rows = _filter_by_columns(rows, parsed_filters)

    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "fetched": len(records),
        "rows": rows,
    }


class BulkDelete(BaseModel):
    ids: list[str]


@app.delete("/orgs/{org_id}/records")
def bulk_delete_records(org_id: str, body: BulkDelete, ctx: AuthCtx = Depends(require_org_access)):
    """Suppression groupée -- même logique que la sélection multiple de
    views/tab_database.py:_render_client_list (boucle sur delete_record,
    pas de nouvelle requête SQL en masse : une seule fonction de
    suppression, réutilisée, jamais deux chemins qui pourraient diverger)."""
    n_deleted = 0
    for record_id in body.ids:
        delete_record(ctx.client, record_id)
        n_deleted += 1
    return {"n_deleted": n_deleted}


class BulkUpdate(BaseModel):
    ids: list[str]
    field: str
    # Valeur "fausse" (0, False, "") : une vraie valeur, pas une case
    # vide -- seule une chaîne vide explicite efface le champ, comme
    # views/tab_database.py:_render_bulk_edit_form (`new_value.strip() or
    # None`). `Any` (pas `Optional[str]`) pour ne jamais convertir 0/False
    # en None avant même d'atteindre cette règle.
    value: Any = None


@app.patch("/orgs/{org_id}/records/bulk")
def bulk_update_records(org_id: str, body: BulkUpdate, ctx: AuthCtx = Depends(require_org_access)):
    """Modification en masse d'UN SEUL champ pour toute la sélection --
    même limite que côté Streamlit (pas d'édition multi-champs en masse :
    des valeurs différentes par ligne n'ont pas de "nouvelle valeur"
    commune qui aurait un sens). Boucle sur get_record/update_record
    (trieur/db.py), comme views/tab_database.py:_render_bulk_edit_form --
    aucune logique de modification dupliquée ici."""
    value = body.value.strip() if isinstance(body.value, str) else body.value
    new_value = value if value not in ("", None) else None
    n_updated = 0
    for record_id in body.ids:
        raw = get_record(ctx.client, record_id)
        if raw is None:
            continue
        data = dict(raw.get("data") or {})
        data[body.field] = new_value
        if update_record(ctx.client, record_id, data, ctx.user.id):
            n_updated += 1
    return {"n_updated": n_updated, "n_requested": len(body.ids)}


# ---------------------------------------------------------------
# Alertes de doublon IBAN
# ---------------------------------------------------------------

@app.get("/orgs/{org_id}/dedup-alerts")
def get_dedup_alerts(org_id: str, ctx: AuthCtx = Depends(require_org_access)):
    """Alertes en attente, avec le diff champ par champ déjà calculé
    côté serveur (diff_rows(), views/tab_database.py) -- pour ne jamais
    réimplémenter cette comparaison en TypeScript, même règle que
    _build_rows/_filter_by_columns réutilisés ailleurs dans cette API."""
    alerts = list_dedup_alerts(ctx.client, org_id, status="pending")
    return [
        {
            "id": a["id"],
            "note": a.get("note") or "",
            "created_at": a.get("created_at"),
            "diff": diff_rows(a["record"]["data"], a["matched"]["data"]),
        }
        for a in alerts
    ]


class DedupAlertResolve(BaseModel):
    status: str  # "confirmed_duplicate" ou "confirmed_different"


@app.post("/orgs/{org_id}/dedup-alerts/{alert_id}/resolve")
def resolve_dedup_alert_endpoint(
    org_id: str, alert_id: str, body: DedupAlertResolve, ctx: AuthCtx = Depends(require_org_access),
):
    if body.status not in ("confirmed_duplicate", "confirmed_different"):
        raise HTTPException(status_code=400, detail="Statut invalide.")
    # Vérifie que l'alerte appartient bien à cet environnement avant de la
    # résoudre -- même garde que delete_saved_view_endpoint (un id deviné
    # ne suffit pas à agir sur l'alerte d'un autre environnement).
    pending = list_dedup_alerts(ctx.client, org_id, status="pending")
    if not any(a["id"] == alert_id for a in pending):
        raise HTTPException(status_code=404, detail="Alerte introuvable ou déjà résolue.")
    resolve_dedup_alert(ctx.client, alert_id, body.status, ctx.user.id)
    return {"id": alert_id, "status": body.status}


# ---------------------------------------------------------------
# Export CSV/Excel
# ---------------------------------------------------------------

@app.get("/orgs/{org_id}/records/export")
def export_org_records(
    org_id: str,
    format: str = Query("csv", pattern="^(csv|xlsx)$"),
    search: str = Query(""),
    col_filters: str = Query("{}", description="JSON : {colonne: {op, value}}"),
    visible_cols: str = Query("", description="Colonnes affichées à l'écran, séparées par des virgules"),
    known_cols: str = Query(
        "", description="Colonnes connues du lot déjà chargé côté écran (référence pour détecter un masquage explicite)",
    ),
    ctx: AuthCtx = Depends(require_org_access),
):
    """Exporte TOUT l'environnement (pas seulement la page déjà chargée à
    l'écran), avec la même recherche/les mêmes filtres par colonne que la
    liste -- mirroir de views/tab_database.py:_render_export. Une colonne
    connue du lot affiché (`known_cols`) mais absente de `visible_cols` a
    été explicitement masquée par l'utilisateur et reste hors export ;
    toute colonne HORS de `known_cols` (jamais vue à l'écran, ex. une
    colonne d'un import plus ancien pas encore chargé) est incluse quand
    même, pour ne jamais perdre de donnée en silence -- même règle que
    côté Streamlit. Si `known_cols` n'est pas fourni, rien n'est considéré
    comme masqué (comportement par défaut : tout exporter)."""
    parsed_filters = _parse_col_filters(col_filters)
    requested_visible = {c for c in visible_cols.split(",") if c}
    reference_known = {c for c in known_cols.split(",") if c} or requested_visible

    master_cols = get_org_master_columns(ctx.client, org_id)
    all_records = list_all_records(ctx.client, org_id)
    rows = _resolve_modifier_names(ctx.client, _build_rows(all_records, master_cols))
    rows = _filter_by_search(rows, search)
    rows = _filter_by_columns(rows, parsed_filters)

    full_cols: list[str] = []
    for row in rows:
        for c in row.keys():
            if c != "_id" and c not in full_cols:
                full_cols.append(c)
    explicitly_hidden = reference_known - requested_visible
    export_cols = [c for c in full_cols if c not in explicitly_hidden] or full_cols

    df = pd.DataFrame(rows) if rows else pd.DataFrame()
    for c in export_cols:
        if c not in df.columns:
            df[c] = None
    df = df[export_cols] if export_cols else df

    orgs = accessible_organizations(
        {"client": ctx.client, "profile": ctx.profile, "memberships": ctx.memberships}
    )
    org_name = next((o["name"] for o in orgs if o["id"] == org_id), org_id)
    file_base = sanitize_filename(org_name, default="export_base")

    if format == "csv":
        content = export_csv_safe(df)
        if content is None:
            raise HTTPException(status_code=500, detail="Échec de la génération du CSV.")
        return StreamingResponse(
            io.BytesIO(content),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{file_base}.csv"'},
        )

    buf = export_excel_safe(df)
    if buf is None:
        raise HTTPException(status_code=500, detail="Échec de la génération de l'Excel.")
    return StreamingResponse(
        io.BytesIO(buf.getvalue()),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{file_base}.xlsx"'},
    )


@app.get("/orgs/{org_id}/records/{record_id}")
def get_org_record(org_id: str, record_id: str, ctx: AuthCtx = Depends(require_org_access)):
    record = get_record(ctx.client, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Client introuvable.")
    return record


class RecordUpdate(BaseModel):
    data: dict


@app.patch("/orgs/{org_id}/records/{record_id}")
def patch_org_record(org_id: str, record_id: str, body: RecordUpdate, ctx: AuthCtx = Depends(require_org_access)):
    ok = update_record(ctx.client, record_id, body.data, ctx.user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="Client introuvable (déjà supprimé ?).")
    return {"id": record_id, "data": body.data, "updated": True}


# ---------------------------------------------------------------
# Import CSV/Excel
# ---------------------------------------------------------------

@app.post("/orgs/{org_id}/import")
async def import_records(
    org_id: str,
    file: UploadFile = File(...),
    iban_col: Optional[str] = Form(None),
    add_unknown_columns: bool = Form(False),
    dry_run: bool = Form(False),
    ctx: AuthCtx = Depends(require_org_access),
):
    """`dry_run=true` : lit et renvoie l'aperçu (colonnes détectées,
    quelques lignes, colonnes inconnues) SANS rien écrire en base --
    permet au frontend d'afficher un aperçu et de choisir la colonne
    IBAN avant de confirmer, comme le fait `st.dataframe(df.head(10))`
    côté Streamlit (views/tab_database.py:_render_import), sans dupliquer
    la lecture CSV/Excel (pandas) côté navigateur."""
    content = await file.read()
    filename = file.filename or "import"
    try:
        if filename.lower().endswith(".csv"):
            df = pd.read_csv(io.BytesIO(content))
        else:
            df = pd.read_excel(io.BytesIO(content))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Impossible de lire le fichier : {exc}")

    master_cols = get_org_master_columns(ctx.client, org_id)
    unknown = unknown_columns(df.columns, master_cols)

    if dry_run:
        preview = df.head(10).where(pd.notnull(df.head(10)), None)
        return {
            "columns": list(df.columns),
            "unknown_columns": unknown,
            "preview_rows": preview.to_dict(orient="records"),
            "row_count": len(df),
        }

    added: list[str] = []
    if unknown and add_unknown_columns:
        if not ctx.profile.get("is_super_admin"):
            raise HTTPException(
                status_code=403,
                detail="Seul un administrateur peut ajouter des colonnes maîtres.",
            )
        add_org_master_columns(ctx.client, org_id, unknown)
        added = unknown

    n_imported, n_alerts = import_dataframe(
        ctx.client, org_id, filename, ctx.user.id, df,
        iban_col=iban_col if iban_col else None,
    )
    return {
        "n_imported": n_imported,
        "n_alerts": n_alerts,
        "unknown_columns": unknown,
        "added_to_master_columns": added,
    }


# ---------------------------------------------------------------
# Pipeline "Trieur de Data" -- étape 1 : import + mapping des colonnes
# (équivalent onglets 1-2 Streamlit, sans porter chaque nuance d'UI --
# voir supabase/migrations/0010_pipeline_staging.sql et trieur/db.py pour
# la couche de données). Les colonnes MAÎTRES restent celles de
# l'environnement (trieur_data.organizations.master_columns) : mêmes
# GET/POST que le CRM ci-dessous (get_master_columns/set_master_columns),
# volontairement PAS une deuxième liste -- voir la note au-dessus de
# get_master_columns.
#
# Limite connue, volontaire pour ce premier incrément : un fichier PDF
# (relevés SEPA, trieur/io_pdf.py) n'est pas encore couvert par cette
# route -- seuls Excel/CSV (trieur/io_excel.py) le sont ici. Un fichier
# multi-onglets est fusionné en une seule session (onglet d'origine gardé
# sous la clé "_sheet" de chaque ligne, jamais proposée au mapping) : le
# mapping par onglet séparé de views/tab2_import_mapping.py n'est pas
# reproduit, ce n'est pas nécessaire pour le flux de données.
# ---------------------------------------------------------------

PIPELINE_PREVIEW_SIZE = 10
# Taille de lot pour le staging (append_pipeline_rows) : évite d'envoyer
# un unique insert de plusieurs centaines de milliers de lignes à
# PostgREST en un seul appel HTTP.
PIPELINE_APPEND_BATCH = 500


def _parse_pipeline_file(filename: str, content: bytes) -> dict[str, pd.DataFrame]:
    """Lit un fichier Excel/CSV avec les lecteurs déjà écrits pour
    l'onglet 2 (trieur/io_excel.py, trieur/matching.py:apply_header_inference_excel)
    -- jamais une deuxième façon de lire un fichier qui pourrait diverger
    (moteurs, repli, déduction d'en-tête absente...)."""
    bio = io.BytesIO(content)
    if filename.lower().endswith(".csv"):
        sheets, _inferred = read_csv_file(bio, filename)
    else:
        sheets = read_excel_all_sheets_from_file(bio, filename)
        sheets, _inferred = apply_header_inference_excel(sheets, bio)
    if not sheets:
        raise HTTPException(status_code=400, detail=f"Impossible de lire le fichier : {filename}")
    return sheets


def _merge_pipeline_sheets(sheets: dict[str, pd.DataFrame]) -> tuple[list[dict], list[str]]:
    """Fusionne tous les onglets lus en une seule liste de lignes à mettre
    en staging, et renvoie (lignes, colonnes détectées -- union dans
    l'ordre de première apparition). Chaque ligne garde son onglet
    d'origine sous "_sheet" (préfixe "_" : ne peut jamais entrer en
    collision avec un vrai nom de colonne source, donc jamais proposée au
    mapping ni comptée dans les colonnes détectées)."""
    rows: list[dict] = []
    columns: list[str] = []
    for sheet_name, df in sheets.items():
        for col in df.columns:
            if col not in columns:
                columns.append(str(col))
        for row in df.to_dict(orient="records"):
            # Même conversion NaN -> None que import_dataframe (trieur/db.py) :
            # une cellule vide devient NaN cote pandas, non serialisable en jsonb.
            clean = {str(k): (None if isinstance(v, float) and v != v else v) for k, v in row.items()}
            clean["_sheet"] = sheet_name
            rows.append(clean)
    return rows, columns


def _without_sheet_key(data: dict) -> dict:
    return {k: v for k, v in data.items() if k != "_sheet"}


def _get_pipeline_session_or_404(ctx: AuthCtx, org_id: str, session_id: str) -> dict:
    """Une session appartenant à un AUTRE environnement, ou expirée/déjà
    nettoyée par cleanup_expired_pipeline_sessions(), est traitée comme
    introuvable -- jamais une erreur serveur (voir trieur/db.py:get_pipeline_session)."""
    session = get_pipeline_session(ctx.client, session_id)
    if not session or session["org_id"] != org_id:
        raise HTTPException(status_code=404, detail="Session de pipeline introuvable ou expirée.")
    return session


def _detected_columns(rows: list[dict]) -> list[str]:
    columns: list[str] = []
    for r in rows:
        for k in r.keys():
            if k != "_sheet" and k not in columns:
                columns.append(k)
    return columns


@app.post("/orgs/{org_id}/pipeline/sessions")
async def create_pipeline_session_endpoint(
    org_id: str,
    file: UploadFile = File(...),
    ctx: AuthCtx = Depends(require_org_access),
):
    """Ouvre une session de pipeline : lit le fichier, met les lignes en
    staging (trieur_data.pipeline_rows, TTL 24h), et renvoie un aperçu +
    les colonnes détectées pour l'étape de mapping suivante. N'écrit
    jamais dans trieur_data.records (donnée permanente) -- ça reste la
    validation finale du pipeline, pas encore portée ici."""
    content = await file.read()
    filename = file.filename or "import"
    sheets = _parse_pipeline_file(filename, content)
    rows, columns = _merge_pipeline_sheets(sheets)
    if not rows:
        raise HTTPException(status_code=400, detail="Fichier vide ou sans ligne exploitable.")

    session = create_pipeline_session(ctx.client, org_id, ctx.user.id, source_filename=filename)
    for start in range(0, len(rows), PIPELINE_APPEND_BATCH):
        append_pipeline_rows(
            ctx.client, session["id"], rows[start:start + PIPELINE_APPEND_BATCH], start_index=start,
        )

    master_cols = get_org_master_columns(ctx.client, org_id)
    return {
        "session_id": session["id"],
        "status": session.get("status", "importing"),
        "row_count": len(rows),
        "columns": columns,
        "unknown_columns": unknown_columns(columns, master_cols),
        "preview_rows": [_without_sheet_key(r) for r in rows[:PIPELINE_PREVIEW_SIZE]],
    }


@app.get("/orgs/{org_id}/pipeline/sessions/{session_id}")
def get_pipeline_session_endpoint(org_id: str, session_id: str, ctx: AuthCtx = Depends(require_org_access)):
    session = _get_pipeline_session_or_404(ctx, org_id, session_id)
    preview = list_pipeline_rows(ctx.client, session_id, limit=PIPELINE_PREVIEW_SIZE)
    return {
        "session_id": session_id,
        "status": session["status"],
        "source_filename": session.get("source_filename"),
        "row_count": session["row_count"],
        "columns": _detected_columns([r["data"] for r in preview]),
        "preview_rows": [_without_sheet_key(r["data"]) for r in preview],
    }


class PipelineMapping(BaseModel):
    # `None` : pas de mapping fourni -> la suggestion d'auto-assignation
    # est appliquée telle quelle. Fournir un dict explicite, même partiel,
    # remplace entièrement la suggestion (l'appelant doit envoyer le
    # mapping COMPLET qu'il veut appliquer, pas un patch).
    mapping: Optional[dict[str, str]] = None
    # true : renvoie la suggestion sans rien écrire (aperçu avant
    # confirmation côté frontend, même principe que dry_run sur /import).
    dry_run: bool = False


@app.post("/orgs/{org_id}/pipeline/sessions/{session_id}/mapping")
def apply_pipeline_mapping(
    org_id: str, session_id: str, body: PipelineMapping, ctx: AuthCtx = Depends(require_org_access),
):
    """Propose (dry_run) ou applique le mapping colonnes source -> colonnes
    maîtres. La suggestion réutilise trieur/matching.py:auto_assign_columns_fast
    -- même logique que le bouton "Auto" de views/tab2_import_mapping.py,
    jamais réimplémentée ici (échantillon = le même aperçu que le GET
    ci-dessus, pas tout le fichier : suffisant pour la détection par
    contenu -- téléphone/IBAN -- sans charger des millions de lignes).

    En dehors d'un dry_run, applique le mapping (fourni, ou la suggestion
    si omis) : chaque ligne de la session est réécrite avec les clés
    COLONNES MAÎTRES (une colonne source sur "(non assigne)" disparaît de
    la ligne), puis la session passe au statut 'mapped'. Limite connue,
    simplification volontaire par rapport à l'onglet 2 : si deux colonnes
    source sont mappées sur la MÊME colonne maître, la dernière écrase la
    précédente (l'onglet 2 garde la première valeur non vide) -- à revoir
    si un vrai cas d'usage l'exige."""
    _get_pipeline_session_or_404(ctx, org_id, session_id)
    master_cols = get_org_master_columns(ctx.client, org_id)

    sample = list_pipeline_rows(ctx.client, session_id, limit=PIPELINE_PREVIEW_SIZE)
    real_columns = _detected_columns([r["data"] for r in sample])
    sample_df = pd.DataFrame([_without_sheet_key(r["data"]) for r in sample]) if sample else None
    suggestion = auto_assign_columns_fast(real_columns, master_cols, sheet_df=sample_df)

    if body.dry_run:
        return {"session_id": session_id, "suggested_mapping": suggestion, "columns": real_columns}

    mapping = body.mapping if body.mapping is not None else suggestion
    if not any(m and m != "(non assigne)" for m in mapping.values()):
        raise HTTPException(status_code=400, detail="Aucune colonne assignée dans ce mapping.")

    n_updated = 0
    offset = 0
    while True:
        page = list_pipeline_rows(ctx.client, session_id, limit=LIST_PAGE_SIZE, offset=offset)
        if not page:
            break
        for row in page:
            new_data = {
                master: row["data"][src]
                for src, master in mapping.items()
                if master and master != "(non assigne)" and src in row["data"]
            }
            update_pipeline_row_data(ctx.client, row["id"], new_data)
            n_updated += 1
        offset += len(page)

    update_pipeline_session_status(ctx.client, session_id, "mapped")
    return {"session_id": session_id, "status": "mapped", "mapping": mapping, "n_rows_updated": n_updated}


# ---------------------------------------------------------------
# Colonnes maîtres. UNE seule notion de "colonnes maîtres" pour tout
# l'environnement (trieur_data.organizations.master_columns) : le
# pipeline (import + mapping ci-dessus) réutilise CES DEUX routes comme
# cible de mapping, ce n'est PAS une deuxième liste. `trieur/persistence.py`
# (load_master_columns/save_master_columns, fichier JSON local) est un
# reliquat pré-multi-tenant de l'app Streamlit -- global au process, pas
# par organisation -- donc un concept différent, jamais utilisé ici.
# ---------------------------------------------------------------

@app.get("/orgs/{org_id}/master-columns")
def get_master_columns(org_id: str, ctx: AuthCtx = Depends(require_org_access)):
    return {"columns": get_org_master_columns(ctx.client, org_id)}


class MasterColumnsUpdate(BaseModel):
    columns: list[str]


@app.post("/orgs/{org_id}/master-columns")
def set_master_columns(org_id: str, body: MasterColumnsUpdate, ctx: AuthCtx = Depends(require_org_access)):
    if not ctx.profile.get("is_super_admin"):
        raise HTTPException(status_code=403, detail="Réservé aux administrateurs.")
    save_org_master_columns(ctx.client, org_id, body.columns)
    return {"columns": body.columns}


# ---------------------------------------------------------------
# Vues enregistrées
# ---------------------------------------------------------------

@app.get("/orgs/{org_id}/saved-views")
def get_saved_views(org_id: str, ctx: AuthCtx = Depends(require_org_access)):
    return list_saved_views(ctx.client, ctx.user.id, org_id)


class SavedViewCreate(BaseModel):
    name: str
    search: str = ""
    col_filters: dict = {}
    visible_cols: list[str] = []


@app.post("/orgs/{org_id}/saved-views")
def post_saved_view(org_id: str, body: SavedViewCreate, ctx: AuthCtx = Depends(require_org_access)):
    view = save_saved_view(
        ctx.client, ctx.user.id, org_id, body.name, body.search, body.col_filters, body.visible_cols,
    )
    return view


@app.delete("/orgs/{org_id}/saved-views/{view_id}")
def delete_saved_view_endpoint(org_id: str, view_id: str, ctx: AuthCtx = Depends(require_org_access)):
    # delete_saved_view() ne filtre que par id (trieur/db.py) -- on vérifie
    # ici que la vue appartient bien à ce compte/cet environnement avant de
    # supprimer, pour qu'un identifiant deviné ne suffise pas à effacer la
    # vue enregistrée d'un autre utilisateur.
    own_views = list_saved_views(ctx.client, ctx.user.id, org_id)
    if not any(v["id"] == view_id for v in own_views):
        raise HTTPException(status_code=404, detail="Vue enregistrée introuvable.")
    delete_saved_view(ctx.client, view_id)
    return {"id": view_id, "deleted": True}


# ---------------------------------------------------------------
# Cockpit -- chantiers de développement du logiciel lui-même.
# Réservé aux administrateurs (require_cockpit_access), même périmètre
# que views/tab_cockpit.py : aucune logique métier n'est réécrite ici,
# uniquement des appels aux fonctions déjà en place dans trieur/db.py.
# ---------------------------------------------------------------

def _get_chantier_or_404(ctx: AuthCtx, org_id: str, chantier_id: str) -> dict:
    """`update_chantier_status`/`list_chantier_messages`/etc. (trieur/db.py)
    ne filtrent que par id de chantier, pas par org -- comme
    delete_saved_view_endpoint ci-dessus, on vérifie ici que le chantier
    appartient bien à CET environnement avant d'agir, pour qu'un id
    deviné ne suffise pas à lire/modifier le chantier d'un autre org."""
    chantiers = list_chantiers(ctx.client, org_id)
    chantier = next((c for c in chantiers if c["id"] == chantier_id), None)
    if chantier is None:
        raise HTTPException(status_code=404, detail="Chantier introuvable.")
    return chantier


@app.get("/orgs/{org_id}/chantiers")
def get_chantiers(org_id: str, ctx: AuthCtx = Depends(require_cockpit_access)):
    return list_chantiers(ctx.client, org_id)


@app.get("/orgs/{org_id}/sections")
def get_sections(org_id: str, ctx: AuthCtx = Depends(require_cockpit_access)):
    return list_sections(ctx.client, org_id)


class ChantierCreate(BaseModel):
    title: str
    priority: str = "normale"
    theme: Optional[str] = None


@app.post("/orgs/{org_id}/chantiers")
def post_chantier(org_id: str, body: ChantierCreate, ctx: AuthCtx = Depends(require_cockpit_access)):
    if not body.title.strip():
        raise HTTPException(status_code=400, detail="Le titre du chantier est obligatoire.")
    if body.priority not in ("basse", "normale", "haute"):
        raise HTTPException(status_code=400, detail="Priorité invalide.")
    chantier = create_chantier(
        ctx.client, org_id, body.title.strip(), body.priority, ctx.user.id,
        theme=body.theme.strip() if body.theme and body.theme.strip() else None,
    )
    return chantier


class SectionCreate(BaseModel):
    nom: str


@app.post("/orgs/{org_id}/sections")
def post_section(org_id: str, body: SectionCreate, ctx: AuthCtx = Depends(require_cockpit_access)):
    if not body.nom.strip():
        raise HTTPException(status_code=400, detail="Le nom de la section est obligatoire.")
    return create_section(ctx.client, org_id, body.nom.strip())


CHANTIER_STATUSES = ("a_faire", "en_cours", "attente_retour", "termine", "abandonne")


class ChantierStatusUpdate(BaseModel):
    status: str


@app.patch("/orgs/{org_id}/chantiers/{chantier_id}/status")
def patch_chantier_status(
    org_id: str, chantier_id: str, body: ChantierStatusUpdate, ctx: AuthCtx = Depends(require_cockpit_access),
):
    if body.status not in CHANTIER_STATUSES:
        raise HTTPException(status_code=400, detail="Statut invalide.")
    _get_chantier_or_404(ctx, org_id, chantier_id)
    update_chantier_status(ctx.client, chantier_id, body.status)
    return {"id": chantier_id, "status": body.status}


@app.get("/orgs/{org_id}/chantiers/{chantier_id}/messages")
def get_chantier_messages(org_id: str, chantier_id: str, ctx: AuthCtx = Depends(require_cockpit_access)):
    _get_chantier_or_404(ctx, org_id, chantier_id)
    return list_chantier_messages(ctx.client, chantier_id)


class ChantierMessageCreate(BaseModel):
    body: str


@app.post("/orgs/{org_id}/chantiers/{chantier_id}/messages")
def post_chantier_message(
    org_id: str, chantier_id: str, body: ChantierMessageCreate, ctx: AuthCtx = Depends(require_cockpit_access),
):
    if not body.body.strip():
        raise HTTPException(status_code=400, detail="Le message est vide.")
    _get_chantier_or_404(ctx, org_id, chantier_id)
    add_chantier_message(ctx.client, chantier_id, body.body.strip(), ctx.user.id)
    return list_chantier_messages(ctx.client, chantier_id)


@app.get("/orgs/{org_id}/chantiers/{chantier_id}/todos")
def get_chantier_todos(org_id: str, chantier_id: str, ctx: AuthCtx = Depends(require_cockpit_access)):
    _get_chantier_or_404(ctx, org_id, chantier_id)
    return list_chantier_todos(ctx.client, chantier_id)


class ChantierTodoCreate(BaseModel):
    body: str


@app.post("/orgs/{org_id}/chantiers/{chantier_id}/todos")
def post_chantier_todo(
    org_id: str, chantier_id: str, body: ChantierTodoCreate, ctx: AuthCtx = Depends(require_cockpit_access),
):
    if not body.body.strip():
        raise HTTPException(status_code=400, detail="Le point à suivre est vide.")
    _get_chantier_or_404(ctx, org_id, chantier_id)
    add_chantier_todo(ctx.client, chantier_id, body.body.strip())
    return list_chantier_todos(ctx.client, chantier_id)


class ChantierTodoUpdate(BaseModel):
    done: bool


@app.patch("/orgs/{org_id}/chantiers/{chantier_id}/todos/{todo_id}")
def patch_chantier_todo(
    org_id: str,
    chantier_id: str,
    todo_id: str,
    body: ChantierTodoUpdate,
    ctx: AuthCtx = Depends(require_cockpit_access),
):
    _get_chantier_or_404(ctx, org_id, chantier_id)
    todos = list_chantier_todos(ctx.client, chantier_id)
    if not any(t["id"] == todo_id for t in todos):
        raise HTTPException(status_code=404, detail="Point à suivre introuvable.")
    set_chantier_todo_done(ctx.client, todo_id, body.done)
    return {"id": todo_id, "done": body.done}
