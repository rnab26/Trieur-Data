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
import os
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
    count_records,
    create_chantier,
    create_section,
    delete_pipeline_export_preset,
    delete_pipeline_saved_filter,
    delete_record,
    delete_saved_view,
    delete_user_column_set,
    get_last_import_batch,
    get_my_memberships,
    get_my_profile,
    get_org_master_columns,
    get_record,
    get_remembered_mapping_for_shape,
    import_dataframe,
    list_all_records,
    list_chantier_messages,
    list_chantier_todos,
    list_chantiers,
    list_dedup_alerts,
    list_pipeline_export_presets,
    list_pipeline_saved_filters,
    list_records,
    list_saved_views,
    list_sections,
    list_user_column_sets,
    rename_pipeline_export_preset,
    rename_pipeline_saved_filter,
    resolve_dedup_alert,
    save_org_master_columns,
    save_pipeline_export_preset,
    save_pipeline_saved_filter,
    save_remembered_mapping_for_shape,
    save_saved_view,
    save_user_column_set,
    set_active_column_set,
    set_chantier_todo_done,
    update_chantier_status,
    update_record,
)
from trieur import pipeline_memory
from trieur.export import export_csv_safe, export_excel_safe, sanitize_filename
from trieur.filters import (
    apply_filter_groups,
    dedupe_dataframe,
    dedupe_dataframe_manual,
    duplicate_groups,
    most_complete_row_index,
)
from trieur.persistence import decode_filters_code, encode_filters_code
from trieur.io_excel import is_google_sheet_url, read_csv_file, read_excel_all_sheets_from_file, read_google_sheets_all_sheets
from trieur.matching import (
    apply_header_inference_excel,
    auto_assign_with_memory,
    clean_iban,
    column_fingerprint,
    detect_iban_column,
    iban_is_valid,
    is_iban_master,
    mapping_to_remembered,
)
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
        "https://trieur-data-app.onrender.com",
        "https://trieur-data-app-test.onrender.com",
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

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_ANON_KEY")
    if not url or not key:
        # Repli sur les secrets Streamlit UNIQUEMENT si l'API tourne dans le
        # même process que l'app Streamlit (dev local partagé) -- ce service
        # tourne seul en production (uvicorn), sans st.secrets disponible.
        try:
            import streamlit as st
            url = url or st.secrets["supabase"]["url"]
            key = key or st.secrets["supabase"]["anon_key"]
        except Exception as exc:
            raise RuntimeError(
                "SUPABASE_URL/SUPABASE_ANON_KEY manquantes (variables "
                "d'environnement) et aucun secrets.toml Streamlit disponible."
            ) from exc
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
# Jeux de colonnes maîtres personnels (liés au COMPTE, pas à
# l'organisation) -- mirroir de views/tab1_colonnes_maitres.py
# (`_render_account_memory`). Distinct des colonnes maîtres par
# environnement ci-dessous (`/orgs/{org_id}/master-columns`) : ceci
# n'est jamais scopé à un org_id, `trieur_data.user_master_column_sets`
# n'a que `user_id` (voir supabase/migrations/0003). L'ensemble
# actif (`profiles.active_master_column_set_id`) est déjà renvoyé par
# `/me` ci-dessus (fait partie de `select("*")` sur profiles) -- le
# frontend n'a besoin que de la liste des jeux pour retrouver son nom
# et ses colonnes au chargement.
# ---------------------------------------------------------------

@app.get("/me/column-sets")
def get_my_column_sets(ctx: AuthCtx = Depends(get_current_ctx)):
    return {"sets": list_user_column_sets(ctx.client, ctx.user.id)}


class UserColumnSetCreate(BaseModel):
    name: str
    columns: list[str]


@app.post("/me/column-sets")
def post_my_column_set(body: UserColumnSetCreate, ctx: AuthCtx = Depends(get_current_ctx)):
    """Enregistre (ou remplace, même nom -- `upsert` sur
    `user_id,name` côté trieur/db.py) un jeu de colonnes sous ce nom, et
    le marque actif pour la prochaine connexion -- même comportement que
    le bouton "Enregistrer" côté Streamlit."""
    name = body.name.strip()
    columns = [c.strip() for c in body.columns if c.strip()]
    if not name:
        raise HTTPException(status_code=400, detail="Donne un nom à ce jeu de colonnes.")
    if not columns:
        raise HTTPException(status_code=400, detail="Aucune colonne à enregistrer.")
    saved = save_user_column_set(ctx.client, ctx.user.id, name, columns)
    set_active_column_set(ctx.client, ctx.user.id, saved["id"])
    return saved


def _get_own_column_set_or_404(ctx: AuthCtx, set_id: str) -> dict:
    own_sets = list_user_column_sets(ctx.client, ctx.user.id)
    match = next((s for s in own_sets if s["id"] == set_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail="Jeu de colonnes introuvable.")
    return match


@app.post("/me/column-sets/{set_id}/apply")
def apply_my_column_set(set_id: str, ctx: AuthCtx = Depends(get_current_ctx)):
    """Marque ce jeu comme actif pour la prochaine connexion ET renvoie
    ses colonnes tout de suite, pour que le frontend les applique sans
    un deuxième aller-retour."""
    matched = _get_own_column_set_or_404(ctx, set_id)
    set_active_column_set(ctx.client, ctx.user.id, set_id)
    return matched


@app.delete("/me/column-sets/{set_id}")
def delete_my_column_set(set_id: str, ctx: AuthCtx = Depends(get_current_ctx)):
    # delete_user_column_set() ne filtre que par id (trieur/db.py) -- on
    # vérifie ici que le jeu appartient bien à ce compte avant de
    # supprimer, même garde que delete_saved_view_endpoint ci-dessous.
    _get_own_column_set_or_404(ctx, set_id)
    delete_user_column_set(ctx.client, set_id)
    return {"id": set_id, "deleted": True}


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


def _parse_filter_groups(raw: str) -> list:
    """Parse le filtre multi-critères du Pipeline (onglet "Filtrer",
    views/tab3_filtrage_dedup.py) : liste de GROUPES (OU entre eux),
    chaque groupe une liste de CRITÈRES (ET entre eux) -- voir
    trieur/filters.py:apply_filter_groups, jamais réimplémenté ici."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"filter_groups n'est pas un JSON valide : {exc}")
    if not isinstance(parsed, list):
        raise HTTPException(status_code=400, detail="filter_groups doit être une liste de groupes.")
    return parsed


def _apply_filter_groups_to_rows(rows: list[dict], groups: list) -> list[dict]:
    """Applique trieur/filters.py:apply_filter_groups à une liste de
    lignes (dicts) -- même contrat NaN -> None que le reste de ce
    fichier (une cellule vide redevient NaN pendant le passage par
    pandas, jamais serialisable en JSON telle quelle)."""
    if not rows or not groups:
        return rows
    df = pd.DataFrame(rows)
    filtered = apply_filter_groups(df, groups)
    filtered = filtered.where(pd.notnull(filtered), None)
    return filtered.to_dict(orient="records")


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
# Pipeline "Trieur de Data" -- étape 1-2 : import multi-fichiers/Google
# Sheets + mapping des colonnes (équivalent onglets 1-2 Streamlit). Les
# données de travail (lignes + métadonnées de session) vivent EN MÉMOIRE
# process (trieur/pipeline_memory.py), pas en Postgres -- voir la
# docstring de ce module pour le pourquoi (parité avec `st.session_state`
# de l'app Streamlit d'origine, jamais d'écriture réseau avant la
# validation finale du pipeline) et les conséquences réelles (sécurité,
# perte au restart, mono-instance). trieur_data.pipeline_sessions /
# pipeline_rows (migrations 0010/0011/0012) restent en base mais ne sont
# plus lues/écrites par cette route -- code mort côté API, décision de
# suppression laissée à un humain (voir PROJECT_LOG.md).
#
# Les colonnes MAÎTRES restent celles de l'environnement
# (trieur_data.organizations.master_columns) : mêmes GET/POST que le CRM
# ci-dessous (get_master_columns/set_master_columns), volontairement PAS
# une deuxième liste -- voir la note au-dessus de get_master_columns.
#
# Limite connue, volontaire : un fichier PDF (relevés SEPA,
# trieur/io_pdf.py) n'est pas encore couvert par cette route -- seuls
# Excel/CSV/Google Sheets (trieur/io_excel.py) le sont ici. Tous les
# fichiers + le Google Sheets éventuel d'un même import sont fusionnés en
# UNE session (onglet/fichier d'origine gardé sous la clé "_sheet" de
# chaque ligne, jamais proposée au mapping) : le mapping PAR ONGLET
# séparé de views/tab2_import_mapping.py (une UI par feuille, checkbox
# d'inclusion par fichier/onglet) n'est pas reproduit -- seul le résultat
# fusionné est mappé, ce qui couvre le flux de données mais pas encore
# "choisir quel onglet exclure avant mapping" (limite connue, à ajouter
# si un vrai usage l'exige).
# ---------------------------------------------------------------

PIPELINE_PREVIEW_SIZE = 10


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


def _unique_display_name(base: str, used: set[str]) -> str:
    """Suffixe " (2)", " (3)"... pour deux fichiers/classeurs de même nom
    dans le même batch d'import -- même règle que
    views/tab2_import_mapping.py (comparée à TOUS les noms déjà utilisés
    dans le batch, pas juste un compteur)."""
    name = base
    n = 2
    while name in used:
        name = f"{base} ({n})"
        n += 1
    used.add(name)
    return name


def _read_pipeline_sources(
    files_data: list[tuple[str, bytes]], google_sheet_url: str | None,
) -> dict[str, pd.DataFrame]:
    """Lit TOUS les fichiers Excel/CSV uploadés + l'éventuel Google Sheets
    dans le MÊME batch (import multi-fichiers, voir
    views/tab2_import_mapping.py) et renvoie un unique dict
    {"<nom affiché> :: <onglet>": dataframe} -- le nom affiché est
    dédupliqué par fichier/classeur (voir _unique_display_name), l'onglet
    reste celui du fichier source."""
    combined: dict[str, pd.DataFrame] = {}
    used_names: set[str] = set()
    for filename, content in files_data:
        display = _unique_display_name(filename, used_names)
        sheets = _parse_pipeline_file(filename, content)
        for sheet_name, df in sheets.items():
            combined[f"{display} :: {sheet_name}"] = df

    if google_sheet_url:
        sheets, _inferred, source_name = read_google_sheets_all_sheets(google_sheet_url)
        if not sheets:
            raise HTTPException(
                status_code=400,
                detail=f"Impossible de lire le Google Sheets : {google_sheet_url}",
            )
        display = _unique_display_name(source_name, used_names)
        for sheet_name, df in sheets.items():
            combined[f"{display} :: {sheet_name}"] = df

    return combined


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


# Même sentinelle que trieur/matching.py:auto_assign_columns_fast (chaîne
# littérale "(non assigne)") -- une seule source de vérité, jamais une
# deuxième valeur qui pourrait diverger.
PIPELINE_UNASSIGNED = "(non assigne)"


def _group_rows_by_sheet(session_id: str) -> dict[str, list[dict]]:
    """Lignes de la session groupées par onglet d'origine (`_sheet`,
    voir _merge_pipeline_sheets côté import), dans l'ordre de première
    apparition -- un groupe = un fichier/feuille importé, mappé et
    fusionné séparément (voir apply_pipeline_mapping), jamais une union
    de toutes les colonnes de tous les fichiers."""
    sheets: dict[str, list[dict]] = {}
    for r in pipeline_memory.list_rows(session_id):
        sheet_key = r["data"].get("_sheet") or ""
        sheets.setdefault(sheet_key, []).append(_without_sheet_key(r["data"]))
    return sheets


def _split_sheet_key(sheet_key: str) -> tuple[str, str]:
    """Sépare une clé d'onglet "<fichier> :: <feuille>" (voir
    _merge_pipeline_sheets) en (fichier, feuille) -- pour remplir
    "Source Data" par onglet, même règle que views/tab2_import_mapping.py."""
    if " :: " in sheet_key:
        file_part, sheet_part = sheet_key.split(" :: ", 1)
        return file_part, sheet_part
    return sheet_key, "Unknown"


def _get_pipeline_session_or_404(ctx: AuthCtx, org_id: str, session_id: str) -> dict:
    """Une session appartenant à un AUTRE environnement, ou expirée/déjà
    purgée par le TTL (voir trieur/pipeline_memory.py), est traitée comme
    introuvable -- jamais une erreur serveur. `ctx` n'est plus utilisé
    pour lire cette session (elle ne passe plus par Supabase/RLS) mais
    reste au même endroit dans la signature pour ne pas changer tous les
    appelants -- la vérification `org_id` ci-dessous est DÉSORMAIS LA
    SEULE protection contre l'accès cross-org, voir la docstring de
    trieur/pipeline_memory.py, point 1."""
    session = pipeline_memory.get_session(session_id)
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
    files: list[UploadFile] = File(default=[]),
    google_sheet_url: Optional[str] = Form(None),
    ctx: AuthCtx = Depends(require_org_access),
):
    """Ouvre une session de pipeline : lit UN OU PLUSIEURS fichiers
    Excel/CSV et/ou un Google Sheets public (tous ses onglets), DANS LE
    MÊME BATCH -- même import multi-fichiers que
    views/tab2_import_mapping.py (`st.file_uploader(accept_multiple_files=True)`
    + champ URL) -- garde les lignes EN MÉMOIRE process (TTL 24h, voir
    trieur/pipeline_memory.py -- plus aucune écriture réseau ici,
    contrairement à l'ancien staging Postgres), et renvoie un aperçu +
    les colonnes détectées pour l'étape de mapping suivante. N'écrit
    jamais dans trieur_data.records (donnée permanente) -- ça reste la
    validation finale du pipeline, pas encore portée ici."""
    url = (google_sheet_url or "").strip()
    if url and not is_google_sheet_url(url):
        raise HTTPException(status_code=400, detail="URL Google Sheets invalide.")
    if not files and not url:
        raise HTTPException(status_code=400, detail="Aucun fichier ni URL Google Sheets fourni.")

    files_data: list[tuple[str, bytes]] = []
    for f in files:
        content = await f.read()
        files_data.append((f.filename or "import", content))

    sheets = _read_pipeline_sources(files_data, url or None)
    rows, columns = _merge_pipeline_sheets(sheets)
    if not rows:
        raise HTTPException(status_code=400, detail="Fichier(s) vide(s) ou sans ligne exploitable.")

    # Nettoyage opportuniste des sessions expirées de CET org avant d'en
    # ouvrir une nouvelle (revue PR #24, point #8 -- même principe que
    # l'ancien trieur.db.delete_expired_pipeline_sessions_for_org, mais en
    # mémoire, voir trieur/pipeline_memory.py) -- ne peut plus échouer
    # pour une raison réseau, mais on garde le même filet de sécurité :
    # un souci ici ne doit jamais empêcher l'import en cours.
    try:
        pipeline_memory.delete_expired_sessions_for_org(org_id)
    except Exception:
        pass

    display_names = [name for name, _ in files_data] + ([url] if url else [])
    source_filename = display_names[0] if len(display_names) == 1 else f"{len(display_names)} fichiers"
    session = pipeline_memory.create_session(
        org_id, ctx.user.id, source_filename=source_filename, columns=columns,
    )
    pipeline_memory.append_rows(session["id"], rows)

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
    preview = pipeline_memory.list_rows(session_id, limit=PIPELINE_PREVIEW_SIZE)
    return {
        "session_id": session_id,
        "status": session["status"],
        "source_filename": session.get("source_filename"),
        "row_count": session["row_count"],
        "columns": session.get("columns") or _detected_columns([r["data"] for r in preview]),
        "preview_rows": [_without_sheet_key(r["data"]) for r in preview],
    }


# Seuil au-delà duquel le sélecteur de valeurs d'un critère de filtre
# (voir POST .../filter-values ci-dessous) bascule sur un champ texte
# libre côté écran -- même seuil que views/tab3_filtrage_dedup.py:
# _render_value_picker (n_unique > 1000).
PIPELINE_FILTER_UNIQUE_VALUES_MAX = 1000


@app.get("/orgs/{org_id}/pipeline/sessions/{session_id}/columns/{column}/unique-values")
def get_pipeline_column_unique_values(
    org_id: str, session_id: str, column: str, ctx: AuthCtx = Depends(require_org_access),
):
    """Valeurs distinctes non vides de `column` sur TOUTE la session
    (jamais juste la page affichée), pour peupler le multiselect de
    valeurs d'un critère de filtre -- même besoin que `df[column]
    .dropna().unique()` dans views/tab3_filtrage_dedup.py:
    _render_value_picker, qui lisait `st.session_state.final_df` (base
    complète) en mémoire. Au-delà de PIPELINE_FILTER_UNIQUE_VALUES_MAX
    valeurs distinctes, ne renvoie que le compte -- l'écran retombe sur
    un champ texte libre, comme l'original, plutôt que de transférer
    des milliers de valeurs inutilisables dans un menu."""
    _get_pipeline_session_or_404(ctx, org_id, session_id)
    rows = pipeline_memory.list_rows(session_id)
    values: set[str] = set()
    for r in rows:
        v = r["data"].get(column)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            values.add(s)
    if len(values) > PIPELINE_FILTER_UNIQUE_VALUES_MAX:
        return {"count": len(values), "values": None}
    return {"count": len(values), "values": sorted(values)}


class PipelineMapping(BaseModel):
    # `None` : pas de mapping fourni -> la suggestion d'auto-assignation
    # est appliquée telle quelle pour CHAQUE onglet. Fournir un dict
    # explicite {sheet_key: {src_col: master_col}}, même partiel,
    # remplace entièrement la suggestion pour les onglets qu'il couvre
    # (l'appelant doit envoyer le mapping COMPLET qu'il veut appliquer
    # pour chaque onglet donné, pas un patch) -- un onglet fourni sans
    # aucune colonne assignée est ignoré (voir views/tab2_import_mapping.py :
    # "Aucune colonne assignée, ignoré").
    mapping: Optional[dict[str, dict[str, str]]] = None
    # Onglets à exclure de la fusion (voir "🗂️ Choisir les fichiers et
    # onglets à inclure" -- views/tab2_import_mapping.py) -- une clé de
    # `sheet_key` (voir GET .../mapping dry_run) par onglet exclu.
    excluded_sheets: list[str] = []
    # true : renvoie la suggestion PAR ONGLET sans rien écrire (aperçu
    # avant confirmation côté frontend, même principe que dry_run sur
    # /import).
    dry_run: bool = False


def _all_pipeline_rows(client, session_id: str) -> list[dict]:
    """Toutes les lignes d'une session de pipeline (pas juste l'aperçu),
    pour filtrer/exporter sur l'INTÉGRALITÉ de la session, pas seulement
    le lot déjà affiché à l'écran (même principe que list_all_records
    côté CRM). `client` n'est plus utilisé (les lignes ne passent plus
    par Supabase, voir trieur/pipeline_memory.py) -- gardé dans la
    signature pour ne pas changer tous les appelants ; la pagination par
    lots (LIST_PAGE_SIZE) n'a plus de raison d'être ici non plus : plus
    de coût réseau à amortir en chargeant tout d'un coup depuis la
    mémoire du process."""
    return pipeline_memory.list_rows(session_id)


def _apply_active_dedup(rows: list[dict], session: dict) -> list[dict]:
    """Réapplique le dédoublonnage ACTIF de cette session (voir
    trieur/db.py:update_pipeline_session_dedup) aux lignes déjà
    filtrées, avec trieur/filters.py:dedupe_dataframe(_manual) -- mêmes
    fonctions que l'onglet 3 Streamlit, jamais réimplémentées ici.
    Persiste tant qu'il n'est pas explicitement annulé (POST/DELETE
    .../dedup ci-dessous), donc appliqué aussi bien par /rows que par
    /export, pour qu'un export ne "dé-déduplique" jamais silencieusement.

    mode="manual" (revue groupe par groupe, <=50 groupes, voir
    apply_pipeline_dedup) : `keep_indices` sont des positions dans CE
    même jeu de lignes déjà filtré (index 0-based reconstruit ici par
    pandas) -- valides UNIQUEMENT si le filtre actif au moment de la
    revue est le même qu'ici, ce qui est garanti par construction
    (dédoublonnage réappliqué après le MÊME filtre à chaque lecture)."""
    dedup_config = session.get("dedup_config")
    if not dedup_config or not rows:
        return rows
    column = dedup_config.get("column")
    if not column:
        return rows
    df = pd.DataFrame(rows)
    if column not in df.columns:
        return rows
    if dedup_config.get("mode") == "manual":
        deduped = dedupe_dataframe_manual(df, column, set(dedup_config.get("keep_indices", [])))
    else:
        deduped = dedupe_dataframe(df, column, keep=dedup_config.get("keep", "first"))
    deduped = deduped.where(pd.notnull(deduped), None)
    return deduped.to_dict(orient="records")


@app.get("/orgs/{org_id}/pipeline/sessions/{session_id}/rows")
def list_pipeline_session_rows(
    org_id: str,
    session_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(LIST_PAGE_SIZE, ge=1, le=2000),
    filter_groups: str = Query(
        "[]", description="JSON : liste de groupes (OU), chaque groupe une liste de critères "
                          "(ET) -- voir trieur/filters.py:apply_filter_groups, même modèle que "
                          "l'onglet Filtrer (views/tab3_filtrage_dedup.py). PAS le même filtre "
                          "que /orgs/{org_id}/records (col_filters) : le Pipeline n'a jamais eu "
                          "de recherche libre ni de filtre par colonne façon Google Sheets dans "
                          "l'original -- seulement ce filtre multi-critères.",
    ),
    ctx: AuthCtx = Depends(require_org_access),
):
    """Lignes de cette session (mémoire process, voir
    trieur/pipeline_memory.py, TTL 24h), filtrées avec
    trieur/filters.py:apply_filter_groups -- même logique de filtre
    multi-critères (groupes OU de critères ET) que l'onglet "Filtrer"
    d'origine, jamais réimplémentée ici. Jamais trieur_data.records
    (donnée permanente).

    Paginée (`page`/`page_size`, même contrat que GET /orgs/{org_id}/records)
    depuis la revue PR #24 (point #7) : avant, cette route renvoyait
    TOUTE la session en une réponse (potentiellement des centaines de
    milliers de lignes) alors que l'écran n'en affiche que 50 à la fois.
    Le filtre porte ici sur TOUTE la session (pas seulement la page
    renvoyée) : `_all_pipeline_rows` charge et filtre l'intégralité de
    la session côté serveur (comme avant), seule la DÉCOUPE en page
    change -- `count` reste le total filtré réel, pas juste la taille
    de la page renvoyée. Le dédoublonnage ACTIF de la session (voir
    .../dedup ci-dessous) est réappliqué ici aussi, après le filtre --
    même ordre que l'onglet 3 Streamlit (filtre PUIS dédoublonnage)."""
    session = _get_pipeline_session_or_404(ctx, org_id, session_id)
    parsed_groups = _parse_filter_groups(filter_groups)

    all_rows = _all_pipeline_rows(ctx.client, session_id)
    rows = [_without_sheet_key(r["data"]) for r in all_rows]
    rows = _apply_filter_groups_to_rows(rows, parsed_groups)
    rows = _apply_active_dedup(rows, session)

    start = (page - 1) * page_size
    page_rows = rows[start:start + page_size]

    return {
        "session_id": session_id,
        "page": page,
        "page_size": page_size,
        "row_count": len(all_rows),
        "count": len(rows),
        "rows": page_rows,
    }


@app.get("/orgs/{org_id}/pipeline/sessions/{session_id}/export")
def export_pipeline_session_rows(
    org_id: str,
    session_id: str,
    format: str = Query("csv", pattern="^(csv|xlsx)$"),
    filter_groups: str = Query("[]", description="JSON : voir GET .../rows ci-dessus."),
    columns: str = Query(
        "", description="Ordre + sélection des colonnes à l'export, séparées par des virgules "
                        "(équivalent du glisser-déposer streamlit-sortables de l'onglet 4 : une "
                        "colonne absente de cette liste est exclue de l'export). Vide = toutes les "
                        "colonnes détectées, dans leur ordre d'apparition (comportement par défaut).",
    ),
    ctx: AuthCtx = Depends(require_org_access),
):
    """Exporte les lignes en staging de cette session (mêmes filtres que
    la route /rows ci-dessus), avec les mêmes fonctions d'export
    (trieur/export.py:export_csv_safe/export_excel_safe) et le même
    StreamingResponse que /orgs/{org_id}/records/export -- aucune
    logique dupliquée."""
    session = _get_pipeline_session_or_404(ctx, org_id, session_id)
    parsed_groups = _parse_filter_groups(filter_groups)

    all_rows = _all_pipeline_rows(ctx.client, session_id)
    rows = [_without_sheet_key(r["data"]) for r in all_rows]
    rows = _apply_filter_groups_to_rows(rows, parsed_groups)
    rows = _apply_active_dedup(rows, session)

    full_cols: list[str] = []
    for row in rows:
        for c in row.keys():
            if c not in full_cols:
                full_cols.append(c)

    # `columns` (ordre + sélection choisis côté écran, voir docstring) --
    # ne garde que les colonnes demandées ET réellement présentes (une
    # colonne du preset absente des données actuelles est ignorée
    # silencieusement, jamais ajoutée vide), dans l'ordre demandé. Une
    # colonne présente mais pas dans `columns` est explicitement exclue --
    # même règle que "Colonnes incluses/exclues" de views/tab4_export.py.
    requested_cols = [c for c in columns.split(",") if c]
    export_cols = [c for c in requested_cols if c in full_cols] if requested_cols else full_cols

    df = pd.DataFrame(rows) if rows else pd.DataFrame()
    for c in export_cols:
        if c not in df.columns:
            df[c] = None
    df = df[export_cols] if export_cols else df

    file_base = sanitize_filename(session.get("source_filename") or session_id, default="export_pipeline")

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


class PipelineSaveToDatabaseRequest(BaseModel):
    target_org_id: str
    filter_groups: list = []
    iban_col: Optional[str] = None
    add_unknown_columns: bool = False
    import_name: Optional[str] = None
    # true : renvoie juste l'aperçu (colonnes, colonnes inconnues) sans
    # rien écrire -- même principe que dry_run sur /import.
    dry_run: bool = False


@app.post("/orgs/{org_id}/pipeline/sessions/{session_id}/save-to-database")
def save_pipeline_session_to_database(
    org_id: str, session_id: str, body: PipelineSaveToDatabaseRequest, ctx: AuthCtx = Depends(require_org_access),
):
    """Enregistre le résultat FILTRÉ (pas juste les colonnes de l'export,
    voir docstring de _render_save_to_database) de cette session dans
    `body.target_org_id`, avec la MÊME vérification de doublon IBAN que
    l'import direct de la Base de données (trieur/db.py:import_dataframe)
    -- copie conforme de la section "💾 Enregistrer dans la base de
    données (CRM)" de views/tab4_export.py. `target_org_id` peut être un
    environnement différent de `org_id` (celui de la session pipeline) :
    vérifié séparément via `accessible_organizations`, jamais supposé
    identique à `org_id`."""
    session = _get_pipeline_session_or_404(ctx, org_id, session_id)
    target_orgs = accessible_organizations(
        {"client": ctx.client, "profile": ctx.profile, "memberships": ctx.memberships}
    )
    if body.target_org_id not in {o["id"] for o in target_orgs}:
        raise HTTPException(status_code=403, detail="Accès refusé à cet environnement de destination.")

    parsed_groups = _parse_filter_groups(body.filter_groups if isinstance(body.filter_groups, list) else [])
    all_rows = _all_pipeline_rows(ctx.client, session_id)
    rows = [_without_sheet_key(r["data"]) for r in all_rows]
    rows = _apply_filter_groups_to_rows(rows, parsed_groups)
    rows = _apply_active_dedup(rows, session)

    if not rows:
        raise HTTPException(status_code=400, detail="Aucune donnée à enregistrer après filtrage.")

    df = pd.DataFrame(rows)
    master_cols = get_org_master_columns(ctx.client, body.target_org_id)
    unknown = unknown_columns(df.columns, master_cols)

    if body.dry_run:
        return {"row_count": len(df), "unknown_columns": unknown}

    added: list[str] = []
    if unknown and body.add_unknown_columns:
        if not ctx.profile.get("is_super_admin"):
            raise HTTPException(
                status_code=403,
                detail="Seul un administrateur peut ajouter des colonnes maîtres.",
            )
        add_org_master_columns(ctx.client, body.target_org_id, unknown)
        added = unknown

    import_name = body.import_name or session.get("source_filename") or "export_trieur"
    n_imported, n_alerts = import_dataframe(
        ctx.client, body.target_org_id, import_name, ctx.user.id, df,
        iban_col=body.iban_col if body.iban_col else None,
    )
    return {
        "n_imported": n_imported,
        "n_alerts": n_alerts,
        "unknown_columns": unknown,
        "added_to_master_columns": added,
    }


@app.post("/orgs/{org_id}/pipeline/sessions/{session_id}/mapping")
def apply_pipeline_mapping(
    org_id: str, session_id: str, body: PipelineMapping, ctx: AuthCtx = Depends(require_org_access),
):
    """Propose (dry_run) ou applique le mapping colonnes source -> colonnes
    maîtres, PAR ONGLET (un fichier/feuille importé = un onglet, voir
    trieur/pipeline_memory.py:create_session/_merge_pipeline_sheets côté
    import) -- copie conforme de views/tab2_import_mapping.py, qui mappe
    et fusionne chaque onglet séparément plutôt qu'un mapping unique sur
    l'union de toutes les colonnes de tous les fichiers importés (l'un
    des deux onglets d'un import de 2 fichiers différents aurait sinon
    ses colonnes mélangées à celles de l'autre).

    dry_run : suggestion par onglet (trieur/matching.py:
    auto_assign_single_sheet_with_memory, + mémoire du mapping par forme
    de fichier propre à CET onglet, jamais réimplémentée ici), avec un
    aperçu (colonnes, quelques lignes, doublons) pour chaque onglet.

    Sinon : fusionne les onglets NON exclus (`body.excluded_sheets`) avec
    leur mapping respectif (fourni, ou la suggestion par onglet si
    omis) -- même logique que la boucle de "✅ Construire la base de
    travail fusionnée" : "Source Data" auto-rempli par onglet (fichier +
    feuille), colonnes source multiples mappées sur la MÊME colonne
    maître combinées en gardant la première valeur non vide (jamais
    juste la dernière écrite), nettoyage IBAN (trieur/matching.py:
    clean_iban) sur toute colonne détectée comme IBAN par le nom OU le
    contenu, lignes entièrement vides retirées, colonnes maîtres jamais
    assignées sur aucun onglet retirées du résultat. Le résultat
    REMPLACE les lignes de la session (voir
    trieur/pipeline_memory.py:replace_rows -- le nombre de lignes/
    colonnes peut changer, contrairement à une simple réécriture ligne à
    ligne), le mapping CONFIRMÉ de chaque onglet fusionné est mémorisé
    par sa propre forme de fichier, puis la session passe au statut
    'mapped'."""
    session = _get_pipeline_session_or_404(ctx, org_id, session_id)
    master_cols = get_org_master_columns(ctx.client, org_id)

    sheets = _group_rows_by_sheet(session_id)
    if not sheets:
        raise HTTPException(status_code=400, detail="Session de pipeline vide.")

    if body.dry_run:
        sheet_results = []
        for sheet_key, rows in sheets.items():
            sheet_df = pd.DataFrame(rows)
            real_columns = list(sheet_df.columns)
            fingerprint = column_fingerprint(real_columns)
            remembered = get_remembered_mapping_for_shape(ctx.client, org_id, fingerprint)
            suggestion = auto_assign_with_memory(
                real_columns, master_cols, sheet_df=sheet_df, remembered_for_shape=remembered,
            )
            preview = sheet_df.head(PIPELINE_PREVIEW_SIZE).where(
                pd.notnull(sheet_df.head(PIPELINE_PREVIEW_SIZE)), None,
            )
            sheet_results.append({
                "sheet_key": sheet_key,
                "columns": real_columns,
                "row_count": len(sheet_df),
                "n_duplicates": int(sheet_df.duplicated().sum()),
                "preview_rows": preview.to_dict(orient="records"),
                "suggested_mapping": suggestion,
                "unknown_columns": unknown_columns(real_columns, master_cols),
                "remembered_for_shape": bool(remembered),
            })
        return {"session_id": session_id, "sheets": sheet_results}

    mapping_by_sheet = body.mapping or {}
    excluded = set(body.excluded_sheets or [])
    used_master_cols: set[str] = set()
    merged_parts: list[pd.DataFrame] = []
    remembered_updates: list[tuple[str, dict]] = []

    for sheet_key, rows in sheets.items():
        if sheet_key in excluded:
            continue
        sheet_df = pd.DataFrame(rows)
        mapping = mapping_by_sheet.get(sheet_key)
        if mapping is None:
            fingerprint = column_fingerprint(list(sheet_df.columns))
            remembered = get_remembered_mapping_for_shape(ctx.client, org_id, fingerprint)
            mapping = auto_assign_with_memory(
                list(sheet_df.columns), master_cols, sheet_df=sheet_df, remembered_for_shape=remembered,
            )
        assigned_cols = [m for m in mapping.values() if m and m != PIPELINE_UNASSIGNED]
        if not assigned_cols:
            continue

        source_file, source_sheet = _split_sheet_key(sheet_key)
        sub = pd.DataFrame(index=sheet_df.index)
        for master_col in master_cols:
            src_cols_for_master = [s for s, m in mapping.items() if m == master_col and s in sheet_df.columns]
            if master_col == "Source Data":
                sub[master_col] = f"{source_file} ({source_sheet})"
                used_master_cols.add(master_col)
            elif not src_cols_for_master:
                sub[master_col] = None
            elif len(src_cols_for_master) == 1:
                sub[master_col] = sheet_df[src_cols_for_master[0]]
                used_master_cols.add(master_col)
            else:
                # Plusieurs colonnes source sur la MÊME colonne maître :
                # garde la première valeur non vide, jamais juste la
                # dernière écrite -- même règle que
                # views/tab2_import_mapping.py (revue PR #24 levée).
                combined = sheet_df[src_cols_for_master[0]].copy()
                for extra_col in src_cols_for_master[1:]:
                    is_empty = combined.isna() | (combined.astype(str).str.strip() == "")
                    combined = combined.where(~is_empty, sheet_df[extra_col])
                sub[master_col] = combined
                used_master_cols.add(master_col)

            if is_iban_master(master_col) or detect_iban_column(sub[master_col]):
                sub[master_col] = sub[master_col].map(clean_iban)

        merged_parts.append(sub)
        fingerprint = column_fingerprint(list(sheet_df.columns))
        remembered_updates.append((fingerprint, mapping_to_remembered(mapping)))

    if not merged_parts:
        raise HTTPException(status_code=400, detail="Aucun onglet avec assignation trouvé.")

    final_df = pd.concat(merged_parts, ignore_index=True)
    cols_hors_source = [c for c in final_df.columns if c != "Source Data"]
    if cols_hors_source:
        final_df = final_df.dropna(how="all", subset=cols_hors_source)
    final_df = final_df[[c for c in final_df.columns if c in used_master_cols]]

    if len(final_df) == 0:
        raise HTTPException(status_code=400, detail="La base fusionnée est vide après nettoyage.")

    # Checksum IBAN (ISO 7064 mod 97) -- signale sans jamais rien
    # supprimer, même principe que views/tab2_import_mapping.py.
    iban_warnings = []
    for c in final_df.columns:
        if is_iban_master(c) or detect_iban_column(final_df[c]):
            n_invalid = int((final_df[c].map(iban_is_valid) == False).sum())  # noqa: E712 (None != False)
            if n_invalid:
                iban_warnings.append({"column": c, "n_invalid": n_invalid})

    final_df = final_df.where(pd.notnull(final_df), None)
    n_updated = pipeline_memory.replace_rows(session_id, final_df.to_dict(orient="records"))

    for fingerprint, remembered_mapping in remembered_updates:
        save_remembered_mapping_for_shape(ctx.client, org_id, fingerprint, remembered_mapping)

    pipeline_memory.update_session_status(session_id, "mapped")
    return {
        "session_id": session_id,
        "status": "mapped",
        "n_rows_updated": n_updated,
        "used_master_columns": sorted(used_master_cols),
        "iban_warnings": iban_warnings,
    }


# ---------------------------------------------------------------
# Dédoublonnage (étape 3, voir views/tab3_filtrage_dedup.py) -- opère
# sur le résultat déjà filtré (filter_groups) de la session, avec
# trieur/filters.py:dedupe_dataframe(_manual)/duplicate_groups, jamais
# une deuxième logique de détection de doublon.
#
# Au-delà de DEDUP_GROUP_THRESHOLD groupes, la revue manuelle groupe par
# groupe devient impraticable -- même seuil que l'original, voir
# views/tab3_filtrage_dedup.py:DEDUP_GROUP_THRESHOLD.
# ---------------------------------------------------------------

DEDUP_GROUP_THRESHOLD = 50


class PipelineDedupRequest(BaseModel):
    column: str
    keep: str = "first"  # "first" ou "complete" (voir trieur/filters.py:dedupe_dataframe) -- mode="rule"
    filter_groups: list = []
    # "rule" (règle globale, `keep`) ou "manual" (revue groupe par
    # groupe, `keep_indices` -- un index CHOISI par groupe, voir
    # trieur/filters.py:dedupe_dataframe_manual).
    mode: str = "rule"
    keep_indices: list[int] = []
    # true : renvoie juste les groupes de doublons détectés (aperçu avant
    # confirmation), sans activer le dédoublonnage sur la session.
    dry_run: bool = False


@app.post("/orgs/{org_id}/pipeline/sessions/{session_id}/dedup")
def apply_pipeline_dedup(
    org_id: str, session_id: str, body: PipelineDedupRequest, ctx: AuthCtx = Depends(require_org_access),
):
    """Détecte (dry_run) ou active le dédoublonnage sur `body.column` pour
    cette session -- appliqué au résultat déjà filtré par `filter_groups`
    (même filtre que GET .../rows), avec trieur/filters.py:duplicate_groups
    (aperçu) ou dedupe_dataframe(_manual) (activation), jamais
    réimplémentés. Une fois activé, le dédoublonnage reste ACTIF (voir
    trieur/db.py:update_pipeline_session_dedup) et est réappliqué à
    chaque lecture (GET .../rows, GET .../export) jusqu'à annulation
    explicite (DELETE .../dedup ci-dessous).

    dry_run, mode="manual" implicite : si <= DEDUP_GROUP_THRESHOLD
    groupes, chaque groupe est renvoyé avec ses lignes complètes (revue
    groupe par groupe, choix de la ligne à garder, pré-sélection = la
    plus complète -- most_complete_row_index) ; au-delà, seul le compte
    est renvoyé et l'écran doit proposer la règle globale (`keep`)."""
    if body.mode not in ("rule", "manual"):
        raise HTTPException(status_code=400, detail="`mode` doit être 'rule' ou 'manual'.")
    if body.keep not in ("first", "complete"):
        raise HTTPException(status_code=400, detail="`keep` doit être 'first' ou 'complete'.")
    _get_pipeline_session_or_404(ctx, org_id, session_id)

    all_rows = _all_pipeline_rows(ctx.client, session_id)
    rows = [_without_sheet_key(r["data"]) for r in all_rows]
    rows = _apply_filter_groups_to_rows(rows, body.filter_groups)

    df = pd.DataFrame(rows) if rows else None
    if df is None or body.column not in df.columns:
        groups: list[tuple] = []
    else:
        groups = duplicate_groups(df, body.column)

    if body.dry_run:
        n_groups = len(groups)
        manual_groups = None
        if 0 < n_groups <= DEDUP_GROUP_THRESHOLD:
            preview_df = df.where(pd.notnull(df), None)
            manual_groups = [
                {
                    "value": value,
                    "default_keep_index": int(most_complete_row_index(df, idx_list)),
                    "rows": [
                        {"index": int(i), "data": preview_df.loc[i].to_dict()}
                        for i in idx_list
                    ],
                }
                for value, idx_list in groups
            ]
        return {
            "session_id": session_id,
            "column": body.column,
            "n_duplicate_groups": n_groups,
            "n_duplicate_rows": sum(len(idx) for _, idx in groups),
            "manual_review_available": manual_groups is not None,
            "groups": manual_groups if manual_groups is not None
            else [{"value": value, "n_rows": len(idx)} for value, idx in groups[:50]],
        }

    if body.mode == "manual":
        if not body.keep_indices:
            raise HTTPException(status_code=400, detail="Choisis une ligne à garder pour chaque groupe.")
        dedup_config = {"column": body.column, "mode": "manual", "keep_indices": body.keep_indices}
    else:
        dedup_config = {"column": body.column, "keep": body.keep}
    pipeline_memory.update_session_dedup(session_id, dedup_config)
    remaining = _apply_active_dedup(rows, {"dedup_config": dedup_config})
    return {
        "session_id": session_id,
        "dedup_config": dedup_config,
        "n_before": len(rows),
        "n_after": len(remaining),
        "n_removed": len(rows) - len(remaining),
    }


@app.delete("/orgs/{org_id}/pipeline/sessions/{session_id}/dedup")
def clear_pipeline_dedup(org_id: str, session_id: str, ctx: AuthCtx = Depends(require_org_access)):
    """Annule le dédoublonnage actif de cette session -- GET .../rows et
    .../export renvoient de nouveau toutes les lignes filtrées, sans
    suppression de doublons."""
    _get_pipeline_session_or_404(ctx, org_id, session_id)
    pipeline_memory.update_session_dedup(session_id, None)
    return {"session_id": session_id, "dedup_config": None}


# ---------------------------------------------------------------
# Presets d'export nommés (ordre + sélection des colonnes, onglet 4) --
# liés au compte + à l'organisation, même patron que les vues
# enregistrées (GET/POST/DELETE .../saved-views ci-dessous) -- remplace
# export_presets.json (voir trieur/db.py et
# supabase/migrations/0012_pipeline_parity.sql).
# ---------------------------------------------------------------

@app.get("/orgs/{org_id}/pipeline/export-presets")
def get_pipeline_export_presets(org_id: str, ctx: AuthCtx = Depends(require_org_access)):
    return list_pipeline_export_presets(ctx.client, ctx.user.id, org_id)


class PipelineExportPresetCreate(BaseModel):
    name: str
    included: list[str] = []
    excluded: list[str] = []


@app.post("/orgs/{org_id}/pipeline/export-presets")
def post_pipeline_export_preset(
    org_id: str, body: PipelineExportPresetCreate, ctx: AuthCtx = Depends(require_org_access),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Donne un nom à ce preset d'export.")
    return save_pipeline_export_preset(ctx.client, ctx.user.id, org_id, name, body.included, body.excluded)


@app.delete("/orgs/{org_id}/pipeline/export-presets/{preset_id}")
def delete_pipeline_export_preset_endpoint(
    org_id: str, preset_id: str, ctx: AuthCtx = Depends(require_org_access),
):
    # save_pipeline_export_preset()/delete_pipeline_export_preset() ne
    # filtrent que par id (trieur/db.py) -- même garde que
    # delete_saved_view_endpoint : on vérifie que le preset appartient
    # bien à ce compte/cet environnement avant de supprimer.
    own_presets = list_pipeline_export_presets(ctx.client, ctx.user.id, org_id)
    if not any(p["id"] == preset_id for p in own_presets):
        raise HTTPException(status_code=404, detail="Preset d'export introuvable.")
    delete_pipeline_export_preset(ctx.client, preset_id)
    return {"id": preset_id, "deleted": True}


class RenameRequest(BaseModel):
    name: str


@app.post("/orgs/{org_id}/pipeline/export-presets/{preset_id}/rename")
def rename_pipeline_export_preset_endpoint(
    org_id: str, preset_id: str, body: RenameRequest, ctx: AuthCtx = Depends(require_org_access),
):
    """Renomme un preset SANS toucher à son contenu -- bouton "Renommer"
    séparé de "Enregistrer" dans views/tab4_export.py."""
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Donne un nom à ce preset d'export.")
    own_presets = list_pipeline_export_presets(ctx.client, ctx.user.id, org_id)
    if not any(p["id"] == preset_id for p in own_presets):
        raise HTTPException(status_code=404, detail="Preset d'export introuvable.")
    return rename_pipeline_export_preset(ctx.client, preset_id, name)


# ---------------------------------------------------------------
# Filtres multi-critères pré-enregistrés (onglet "Filtrer", voir
# views/tab3_filtrage_dedup.py) -- même patron CRUD que les presets
# d'export ci-dessus (liés au compte + à l'organisation).
# ---------------------------------------------------------------

@app.get("/orgs/{org_id}/pipeline/saved-filters")
def get_pipeline_saved_filters(org_id: str, ctx: AuthCtx = Depends(require_org_access)):
    return list_pipeline_saved_filters(ctx.client, ctx.user.id, org_id)


class PipelineSavedFilterCreate(BaseModel):
    name: str
    groups: list = []


@app.post("/orgs/{org_id}/pipeline/saved-filters")
def post_pipeline_saved_filter(
    org_id: str, body: PipelineSavedFilterCreate, ctx: AuthCtx = Depends(require_org_access),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Donne un nom à ce filtre.")
    if not body.groups:
        raise HTTPException(status_code=400, detail="Aucun critère complet à enregistrer.")
    return save_pipeline_saved_filter(ctx.client, ctx.user.id, org_id, name, body.groups)


@app.post("/orgs/{org_id}/pipeline/saved-filters/{filter_id}/rename")
def rename_pipeline_saved_filter_endpoint(
    org_id: str, filter_id: str, body: RenameRequest, ctx: AuthCtx = Depends(require_org_access),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Donne un nom à ce filtre.")
    own_filters = list_pipeline_saved_filters(ctx.client, ctx.user.id, org_id)
    if not any(f["id"] == filter_id for f in own_filters):
        raise HTTPException(status_code=404, detail="Filtre introuvable.")
    return rename_pipeline_saved_filter(ctx.client, filter_id, name)


@app.delete("/orgs/{org_id}/pipeline/saved-filters/{filter_id}")
def delete_pipeline_saved_filter_endpoint(
    org_id: str, filter_id: str, ctx: AuthCtx = Depends(require_org_access),
):
    own_filters = list_pipeline_saved_filters(ctx.client, ctx.user.id, org_id)
    if not any(f["id"] == filter_id for f in own_filters):
        raise HTTPException(status_code=404, detail="Filtre introuvable.")
    delete_pipeline_saved_filter(ctx.client, filter_id)
    return {"id": filter_id, "deleted": True}


class FiltersCodeEncodeRequest(BaseModel):
    filters: list = []


@app.post("/orgs/{org_id}/pipeline/saved-filters/encode")
def encode_pipeline_filters_code(org_id: str, body: FiltersCodeEncodeRequest, ctx: AuthCtx = Depends(require_org_access)):
    """Encode la liste de filtres enregistrés en un code texte copiable
    -- même fonction que le "🔗 Sauvegarde texte" de
    views/tab3_filtrage_dedup.py (trieur/persistence.py:encode_filters_code),
    pour un secours en dehors de cet environnement (note, message...)."""
    return {"code": encode_filters_code(body.filters)}


class FiltersCodeDecodeRequest(BaseModel):
    code: str


@app.post("/orgs/{org_id}/pipeline/saved-filters/decode")
def decode_pipeline_filters_code(org_id: str, body: FiltersCodeDecodeRequest, ctx: AuthCtx = Depends(require_org_access)):
    filters, err = decode_filters_code(body.code)
    if err:
        raise HTTPException(status_code=400, detail=err)
    return {"filters": filters}


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
