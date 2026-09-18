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
    add_org_master_columns,
    count_records,
    delete_record,
    delete_saved_view,
    get_last_import_batch,
    get_my_memberships,
    get_my_profile,
    get_org_master_columns,
    get_record,
    import_dataframe,
    list_all_records,
    list_dedup_alerts,
    list_records,
    list_saved_views,
    resolve_dedup_alert,
    save_org_master_columns,
    save_saved_view,
    update_record,
)
from trieur.export import export_csv_safe, export_excel_safe, sanitize_filename
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
# Colonnes maîtres
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
