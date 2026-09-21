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

import asyncio
import io
import json
import os
import uuid
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
    add_chantier_question,
    add_chantier_todo,
    answer_chantier_question,
    add_org_master_columns,
    add_record_tag,
    adjust_pipeline_row_count,
    append_pipeline_rows,
    can_write_org,
    cancel_import_batch,
    claim_pipeline_session_for_mapping,
    count_records,
    create_chantier,
    create_pipeline_session,
    create_section,
    delete_expired_pipeline_sessions_for_org,
    delete_pipeline_rows,
    delete_pipeline_session,
    delete_record,
    delete_saved_view,
    delete_user_column_set,
    get_last_import_batch,
    get_my_memberships,
    get_my_profile,
    get_org_master_columns,
    get_pipeline_session,
    get_prelevement_rules,
    get_record,
    get_record_tags_map,
    import_dataframe,
    infer_chantier_theme,
    insert_pipeline_rows_only,
    is_pipeline_dedupe_lock_owner,
    list_all_records,
    list_chantier_messages,
    list_chantier_questions,
    list_chantier_todos,
    list_chantiers,
    list_dedup_alerts,
    list_org_memberships,
    list_org_tags,
    list_pipeline_rows,
    list_pipeline_rows_for_sheet,
    list_recent_import_batches,
    list_records,
    list_saved_views,
    list_sections,
    list_user_column_sets,
    remove_membership,
    remove_record_tag,
    resolve_dedup_alert,
    save_org_master_columns,
    save_prelevement_rules,
    save_saved_view,
    save_user_column_set,
    set_active_column_set,
    set_chantier_todo_done,
    try_lock_pipeline_dedupe,
    unlock_pipeline_dedupe,
    update_chantier_status,
    update_membership_role,
    update_pipeline_row_data,
    update_record,
)
from trieur.export import export_csv_safe, export_excel_safe, sanitize_filename
from trieur.prelevement import PrelevementRules, generate_mandats
from trieur.io_excel import read_csv_file, read_excel_all_sheets_from_file, stream_excel_sheets
from trieur.io_pdf import read_pdf_sepa
from trieur.matching import apply_header_inference_excel, auto_assign_columns_fast, iban_is_valid
from views._auth import accessible_organizations
from views._ui import unknown_columns
from views.tab_database import (
    _apply_tags,
    _build_rows,
    _filter_by_columns,
    _filter_by_search,
    _resolve_modifier_names,
    diff_rows,
)

from api import pipeline_engine
from api.pipeline_mapping import detect_iban_master_columns, merge_mapped_row

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
    # Sans ça, le navigateur reçoit bien les en-têtes personnalisés mais les
    # cache au JS -- res.headers.get('x-ooff-count') renvoie null côté
    # frontend même si le fichier généré contient de vraies données
    # (confirmé : Raphaël a eu "0/0/0" affiché avec un classeur de 66
    # mandats OOFF réels dedans -- CORS, pas un bug du moteur).
    expose_headers=["X-Ooff-Count", "X-Rcur-Count", "X-Exclus-Count"],
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


def require_write_access(org_id: str, ctx: AuthCtx = Depends(require_org_access)) -> AuthCtx:
    """Comme require_org_access, mais refuse en plus un membre
    'lecture_seule' (migration 0018) -- même règle que
    views/tab_database.py:can_write_org, en plus de la RLS Supabase
    (trieur_data.can_write) qui reste la vraie barrière de sécurité."""
    role = next((m["role"] for m in ctx.memberships if m["org_id"] == org_id), None)
    if not can_write_org(role, ctx.profile.get("is_super_admin")):
        raise HTTPException(
            status_code=403, detail="Accès en lecture seule à cet environnement : action non autorisée.",
        )
    return ctx


def require_admin_access(ctx: AuthCtx = Depends(require_org_access)) -> AuthCtx:
    """Réservé aux administrateurs -- même règle que la gestion des
    colonnes maîtres (POST .../master-columns)."""
    if not ctx.profile.get("is_super_admin"):
        raise HTTPException(status_code=403, detail="Réservé aux administrateurs.")
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


_ALLOWED_FILTER_KINDS = {"departements", "valeurs"}


def _validate_filter_groups(parsed: list) -> None:
    """Valide la STRUCTURE de `groups` avant de la transmettre au moteur
    (trieur/filters.py:apply_filter_groups). Ce moteur ignore déjà
    gracieusement un groupe/critère incomplet (colonne ou valeurs pas
    encore choisies, cf sa docstring) -- ce n'est PAS une erreur. Ce qui
    doit être rejeté ici, c'est une structure qui ferait planter
    `c.get(...)` dans le moteur (critère qui n'est pas un objet, groupe
    qui n'est pas une liste) ou un champ mal typé/hors valeurs attendues."""
    for i, group in enumerate(parsed):
        if not isinstance(group, list):
            raise HTTPException(
                status_code=400, detail=f"groups[{i}] doit être une liste de critères."
            )
        for j, criterion in enumerate(group):
            if not isinstance(criterion, dict):
                raise HTTPException(
                    status_code=400,
                    detail=f"groups[{i}][{j}] doit être un objet {{column, kind, values}}.",
                )
            column = criterion.get("column")
            if column is not None and not isinstance(column, str):
                raise HTTPException(
                    status_code=400, detail=f"groups[{i}][{j}].column doit être une chaîne."
                )
            kind = criterion.get("kind")
            if kind is not None and kind not in _ALLOWED_FILTER_KINDS:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"groups[{i}][{j}].kind invalide (attendu "
                        f"{sorted(_ALLOWED_FILTER_KINDS)})."
                    ),
                )
            values = criterion.get("values")
            if values is not None and not isinstance(values, list):
                raise HTTPException(
                    status_code=400, detail=f"groups[{i}][{j}].values doit être une liste."
                )


def _parse_filter_groups(raw: str) -> list:
    """`groups` : liste de groupes (OU) de critères (ET), exactement le
    format de trieur/filters.py:apply_filter_groups -- voir
    api/pipeline_engine.py:filter_rows. Un critère =
    {"column": str, "kind": "departements"|"valeurs", "values": [...]}."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"groups n'est pas un JSON valide : {exc}")
    if not isinstance(parsed, list):
        raise HTTPException(
            status_code=400,
            detail="groups doit être une liste de groupes, chacun une liste de critères.",
        )
    _validate_filter_groups(parsed)
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

    rows = _apply_tags(ctx.client, _resolve_modifier_names(ctx.client, _build_rows(records, master_cols)))
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
def bulk_delete_records(org_id: str, body: BulkDelete, ctx: AuthCtx = Depends(require_write_access)):
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
def bulk_update_records(org_id: str, body: BulkUpdate, ctx: AuthCtx = Depends(require_write_access)):
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
    org_id: str, alert_id: str, body: DedupAlertResolve, ctx: AuthCtx = Depends(require_write_access),
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
    rows = _apply_tags(ctx.client, _resolve_modifier_names(ctx.client, _build_rows(all_records, master_cols)))
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
def patch_org_record(org_id: str, record_id: str, body: RecordUpdate, ctx: AuthCtx = Depends(require_write_access)):
    ok = update_record(ctx.client, record_id, body.data, ctx.user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="Client introuvable (déjà supprimé ?).")
    return {"id": record_id, "data": body.data, "updated": True}


# ---------------------------------------------------------------
# Étiquettes libres sur un client (migration 0021) -- mirroir de
# views/tab_database.py:_render_tags_editor.
# ---------------------------------------------------------------

@app.get("/orgs/{org_id}/tags")
def get_org_tags(org_id: str, ctx: AuthCtx = Depends(require_org_access)):
    return {"tags": list_org_tags(ctx.client, org_id)}


class RecordTagCreate(BaseModel):
    tag: str


@app.post("/orgs/{org_id}/records/{record_id}/tags")
def post_record_tag(org_id: str, record_id: str, body: RecordTagCreate, ctx: AuthCtx = Depends(require_write_access)):
    tag = body.tag.strip()
    if not tag:
        raise HTTPException(status_code=400, detail="Étiquette vide.")
    add_record_tag(ctx.client, org_id, record_id, tag, ctx.user.id)
    return {"record_id": record_id, "tag": tag}


@app.delete("/orgs/{org_id}/records/{record_id}/tags/{tag}")
def delete_record_tag(org_id: str, record_id: str, tag: str, ctx: AuthCtx = Depends(require_write_access)):
    remove_record_tag(ctx.client, record_id, tag)
    return {"record_id": record_id, "tag": tag, "removed": True}


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
    la lecture CSV/Excel (pandas) côté navigateur.

    Même plafond que l'import du Trieur de Data (PIPELINE_MAX_UPLOAD_BYTES,
    voir POST .../pipeline/sessions) -- ce parcours-ci (import direct côté
    Base de données) lit aussi tout le fichier en DataFrame pandas d'un
    coup, exactement le même risque d'OOM mesuré en conditions réelles
    sur un gros .xlsx (revue Copilot, PR #28)."""
    if file.size is None:
        # Défense en profondeur (même raisonnement que POST .../pipeline/sessions,
        # revue Copilot) : un total silencieusement compté à 0 octet
        # contournerait ce plafond -- on refuse plutôt que de deviner.
        raise HTTPException(
            status_code=413,
            detail="Taille de fichier indéterminable -- réessayez l'import.",
        )
    if file.size > PIPELINE_MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Fichier trop volumineux ({file.size / 1_048_576:.1f} Mo, max "
                f"{PIPELINE_MAX_UPLOAD_BYTES / 1_048_576:.0f} Mo) -- utilisez le format CSV "
                "(bien plus léger que .xlsx pour le même volume) ou importez en plusieurs fois."
            ),
        )
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

    role = next((m["role"] for m in ctx.memberships if m["org_id"] == org_id), None)
    if not can_write_org(role, ctx.profile.get("is_super_admin")):
        raise HTTPException(
            status_code=403, detail="Accès en lecture seule à cet environnement : import non autorisé.",
        )

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
# Imports récents / annulation d'un import entier (migration -- aucune,
# repose sur les cascades déjà en place, voir trieur/db.py:cancel_import_batch)
# -- mirroir de views/tab_database.py:_render_import_history.
# ---------------------------------------------------------------

@app.get("/orgs/{org_id}/import-batches")
def get_import_batches(org_id: str, ctx: AuthCtx = Depends(require_org_access)):
    return {"batches": list_recent_import_batches(ctx.client, org_id)}


@app.delete("/orgs/{org_id}/import-batches/{batch_id}")
def delete_import_batch(org_id: str, batch_id: str, ctx: AuthCtx = Depends(require_write_access)):
    cancel_import_batch(ctx.client, batch_id)
    return {"id": batch_id, "cancelled": True}


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
# Un fichier peut avoir PLUSIEURS onglets (Excel) ; CSV/PDF n'en ont
# qu'un implicite. Toutes les lignes de TOUS les onglets/fichiers sont
# fusionnées dans le MÊME staging (trieur_data.pipeline_rows), chaque
# ligne gardant son onglet d'origine sous la clé technique "_sheet"
# (jamais proposée au mapping ni comptée dans les colonnes détectées --
# voir _without_sheet_key/_detected_columns). Le MAPPING, lui, est PAR
# ONGLET (voir PipelineMapping/apply_pipeline_mapping ci-dessous) :
# fidèle à views/tab2_import_mapping.py, une carte par onglet côté écran,
# chacune avec son propre mapping colonnes source -> colonnes maîtres.
# ---------------------------------------------------------------

PIPELINE_PREVIEW_SIZE = 10
# Taille de l'échantillon utilisé pour la détection IBAN par CONTENU
# (trieur/matching.py:detect_iban_column) lors du mapping -- volontairement
# bien plus grand que PIPELINE_PREVIEW_SIZE (qui ne sert qu'à la suggestion
# de colonnes affichée à l'écran) : une colonne au nom générique ("Compte")
# dont les vraies valeurs IBAN n'apparaissent qu'après les 10 premières
# lignes doit quand même être détectée. Alignée sur le plafond interne de
# detect_iban_column (sample*5 = 1000 lignes lues au maximum) : aller
# au-delà ne changerait rien à sa détection, donc inutile de charger plus.
IBAN_DETECTION_SAMPLE_SIZE = 1000
# Taille de lot pour le staging (append_pipeline_rows) : évite d'envoyer
# un unique insert de plusieurs centaines de milliers de lignes à
# PostgREST en un seul appel HTTP.
PIPELINE_APPEND_BATCH = 500
# Plafond de lignes chargées pour calculer une SUGGESTION de mapping
# (dry_run, ou repli quand aucun mapping explicite n'est fourni) --
# distinct du chargement complet nécessaire pour APPLIQUER un mapping
# (qui doit forcément réécrire chaque ligne). Sans ce plafond, un simple
# dry_run (appelé automatiquement par le frontend juste après chaque
# import, avant même que l'utilisateur ait pu regarder quoi que ce soit)
# matérialisait toute la session en mémoire -- risque réel d'épuisement
# mémoire sur les gros volumes documentés (>600 000 lignes). Un onglet
# entièrement au-delà de ce plafond n'aura simplement pas de suggestion
# automatique (l'utilisateur mappe à la main) -- dégradation, jamais une
# perte de données.
PIPELINE_SUGGESTION_ROW_CAP = 3000
# Seuil (en octets, somme des fichiers d'UN import) qui bascule en mode
# import EN FLUX (voir _iter_pipeline_sheets/stream_excel_sheets,
# trieur/io_excel.py) plutôt que le chemin classique (tout le fichier
# matérialisé en DataFrame pandas). Mesuré en conditions réelles (Render,
# plan 512 Mo) : un .xlsx de 8,5 Mo a fait grimper le process à ~490 Mo de
# RAM par le chemin classique, déclenchant un OOM-kill en cours de
# requête -- l'utilisateur ne voit qu'une connexion coupée côté
# navigateur, rien côté serveur (le process meurt avant de répondre). En
# dessous de ce seuil, le chemin classique reste utilisé tel quel (simple,
# déjà testé, aucune régression pour l'usage courant) -- le mode flux
# n'apporte rien pour un petit fichier et coûterait juste un peu de
# complexité pour rien.
PIPELINE_STREAM_THRESHOLD_BYTES = 8 * 1024 * 1024
# Plafond ABSOLU (accepté même en mode flux) : protège le disque
# (spooling des uploads) et le temps de requête, pas la RAM -- le mode
# flux garde la RAM bornée quelle que soit la taille du fichier. Fixé à
# 550 Mo (marge au-dessus du besoin réel signalé : imports "jusqu'à 500
# Mo", ancien Streamlit maxUploadSize=500) plutôt qu'un plafond plus bas
# choisi arbitrairement -- revue Copilot, PR #29 (un plafond sous le
# besoin réel aurait ré-introduit la régression que ce PR corrige, juste
# déplacée du "plante en RAM" au "rejeté en 413"). Non encore vérifié
# EN CONDITIONS RÉELLES au-delà de quelques dizaines de Mo à ce jour :
# un import de plusieurs centaines de Mo prend réellement plusieurs
# minutes (des milliers d'allers-retours DB) et reste soumis aux
# éventuels délais d'expiration de la plateforme (proxy Render) -- voir
# le test réel prévu après déploiement dans la description du PR.
PIPELINE_MAX_UPLOAD_BYTES = 550 * 1024 * 1024


def _parse_pipeline_file(filename: str, content: bytes) -> dict[str, pd.DataFrame]:
    """Lit un fichier Excel/CSV/PDF avec les lecteurs déjà écrits pour
    les onglets 2 (trieur/io_excel.py, trieur/io_pdf.py,
    trieur/matching.py:apply_header_inference_excel) -- jamais une
    deuxième façon de lire un fichier qui pourrait diverger (moteurs,
    repli, déduction d'en-tête absente, format des relevés SEPA...)."""
    bio = io.BytesIO(content)
    if filename.lower().endswith(".csv"):
        sheets, _inferred = read_csv_file(bio, filename)
    elif filename.lower().endswith(".pdf"):
        # [PDF] Prélèvements SEPA -> une ligne par prélèvement (trieur/io_pdf.py) --
        # même lecteur que views/tab2_import_mapping.py, plus couvert par un
        # "limite connue" côté API depuis le premier incrément du pipeline.
        sheets, _inferred = read_pdf_sepa(bio, filename)
    else:
        sheets = read_excel_all_sheets_from_file(bio, filename)
        sheets, _inferred = apply_header_inference_excel(sheets, bio)
    if not sheets:
        raise HTTPException(status_code=400, detail=f"Impossible de lire le fichier : {filename}")
    return sheets


def _sheet_key_deduper():
    """Fabrique une fonction `next_key(base_key) -> clé unique`, en
    suffixant " (2)", " (3)"... sur collision -- même politique partagée
    par le chemin classique (_parse_and_merge_pipeline_files) et le
    chemin en flux (_iter_pipeline_sheets) pour ne jamais diverger sur ce
    point, quel que soit le mode d'import utilisé."""
    used_keys: set[str] = set()

    def next_key(base_key: str) -> str:
        key, n = base_key, 2
        while key in used_keys:
            key = f"{base_key} ({n})"
            n += 1
        used_keys.add(key)
        return key

    return next_key


def _parse_and_merge_pipeline_files(files: list[tuple[str, bytes]]) -> dict[str, pd.DataFrame]:
    """Lit PLUSIEURS fichiers et fusionne tous leurs onglets en un seul
    dict -- équivalent de la boucle `for f in files` de
    views/tab2_import_mapping.py::render (st.file_uploader(...,
    accept_multiple_files=True)), un seul fichier restant le cas
    particulier à 1 élément. Les clés (`_sheet` posé ensuite par
    `_merge_pipeline_sheets`) sont préfixées par le nom de fichier dès
    qu'il y en a plus d'un, pour ne jamais faire collision entre deux
    fichiers Excel qui auraient chacun un onglet nommé pareil (ex.
    "Feuil1") -- même souci que le "[FIX doublons de nom]" de l'original,
    réglé ici en dédupliquant la clé finale plutôt que le nom affiché."""
    combined: dict[str, pd.DataFrame] = {}
    multi = len(files) > 1
    next_key = _sheet_key_deduper()
    for filename, content in files:
        for sheet_name, df in _parse_pipeline_file(filename, content).items():
            key = next_key(f"{filename} :: {sheet_name}" if multi else sheet_name)
            combined[key] = df
    return combined


def _iter_pipeline_sheets(files: list[tuple[str, UploadFile]]):
    """Générateur UNIFIÉ (clé d'onglet déjà dédupliquée, colonnes,
    n_duplicates_sample, itérateur de lignes) sur TOUS les fichiers d'un
    import EN MODE FLUX (voir PIPELINE_STREAM_THRESHOLD_BYTES) :
      - .xlsx (SEUL format Excel géré par openpyxl -- l'ancien .xls binaire
        n'est PAS un zip/XML et ne peut pas être lu par
        stream_excel_sheets ; un .xls volumineux reste donc sur le chemin
        classique ci-dessous, comme avant ce chantier -- revue Copilot,
        PR #29) : stream_excel_sheets (trieur/io_excel.py) -- jamais toute
        une feuille en mémoire, seule voie qui tient sur de gros volumes
        avec une RAM bornée (mesuré : ~45x la taille du fichier via le
        chemin classique, quel que soit le moteur).
      - .xls/.csv/.pdf : lecteurs existants (déjà nettement plus légers en
        mémoire pour un volume de données équivalent côté csv, mesuré ~6x
        contre ~45x pour le xlsx ; .xls et .pdf rarement volumineux en
        pratique) -- matérialisés normalement puis itérés, une réécriture
        en flux n'était pas la priorité de ce chantier.
    Même dédoublonnage de clé que le chemin classique (_sheet_key_deduper,
    partagé) -- aucune divergence entre les deux modes sur ce point."""
    multi = len(files) > 1
    next_key = _sheet_key_deduper()
    for filename, upload in files:
        if filename.lower().endswith(".xlsx"):
            upload.file.seek(0)
            for sheet_name, columns, n_dup_sample, row_iter in stream_excel_sheets(upload.file):
                key = next_key(f"{filename} :: {sheet_name}" if multi else sheet_name)
                yield key, columns, n_dup_sample, row_iter
        else:
            upload.file.seek(0)
            content = upload.file.read()
            for sheet_name, df in _parse_pipeline_file(filename, content).items():
                key = next_key(f"{filename} :: {sheet_name}" if multi else sheet_name)
                columns = [str(c) for c in df.columns]
                n_dup_sample = int(df.duplicated().sum())
                row_iter = (_nan_to_none(row) for row in df.to_dict(orient="records"))
                yield key, columns, n_dup_sample, row_iter


def _stream_import_pipeline_files(client, session_id: str, files: list[tuple[str, UploadFile]]) -> dict:
    """Insère tous les fichiers d'un import EN MODE FLUX (voir
    _iter_pipeline_sheets), par lots bornés (PIPELINE_APPEND_BATCH),
    SANS jamais construire la liste complète des lignes en mémoire comme
    le fait le chemin classique -- fonction 100% synchrone (le client
    Supabase l'est déjà), appelée via asyncio.to_thread par l'endpoint.
    Renvoie le même résumé que le chemin classique (row_count, columns,
    sheets, preview_rows) pour que la réponse HTTP soit identique quel
    que soit le mode utilisé."""
    sheet_summaries: list[dict] = []
    columns_seen: list[str] = []
    preview_rows: list[dict] = []
    row_index = 0
    total_rows = 0

    for sheet_key, columns, n_dup_sample, row_iter in _iter_pipeline_sheets(files):
        for c in columns:
            if c not in columns_seen:
                columns_seen.append(c)
        sheet_row_count = 0
        sheet_preview: list[dict] = []
        batch: list[dict] = []
        for row in row_iter:
            if len(sheet_preview) < 6:
                sheet_preview.append(dict(row))
            if len(preview_rows) < PIPELINE_PREVIEW_SIZE:
                preview_rows.append(dict(row))
            tagged = dict(row)
            tagged["_sheet"] = sheet_key
            batch.append(tagged)
            sheet_row_count += 1
            total_rows += 1
            if len(batch) >= PIPELINE_APPEND_BATCH:
                insert_pipeline_rows_only(client, session_id, batch, row_index)
                row_index += len(batch)
                batch = []
        if batch:
            insert_pipeline_rows_only(client, session_id, batch, row_index)
            row_index += len(batch)

        sheet_summaries.append({
            "sheet_key": sheet_key,
            "columns": columns,
            "row_count": sheet_row_count,
            "n_duplicates": n_dup_sample,
            "preview_rows": sheet_preview,
        })

    return {
        "row_count": total_rows,
        "columns": columns_seen,
        "sheets": sheet_summaries,
        "preview_rows": preview_rows,
    }


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


def _nan_to_none(row: dict) -> dict:
    """Même conversion que `_merge_pipeline_sheets` : une cellule vide
    devient NaN côté pandas, non sérialisable en JSON/jsonb."""
    return {str(k): (None if isinstance(v, float) and v != v else v) for k, v in row.items()}


def _sheet_summary_from_df(sheet_key: str, df: pd.DataFrame) -> dict:
    """Résumé d'UN onglet tel que lu à l'import (avant staging) : colonnes,
    lignes, doublons (df.duplicated(), même calcul que
    views/tab2_import_mapping.py) et un aperçu (6 premières lignes) --
    de quoi construire côté écran UNE carte par onglet (structure [7] de
    la référence Streamlit) sans tout re-télécharger."""
    preview_rows = [_nan_to_none(row) for row in df.head(6).to_dict(orient="records")]
    return {
        "sheet_key": sheet_key,
        "columns": [str(c) for c in df.columns],
        "row_count": len(df),
        "n_duplicates": int(df.duplicated().sum()),
        "preview_rows": preview_rows,
    }


def _sheet_data_by_key(all_rows: list[dict]) -> dict[str, list[dict]]:
    """Regroupe les lignes de staging déjà chargées ({id, row_index, data})
    par onglet d'origine (`_sheet`) -- ordre de première apparition
    conservé. Sert de base à la suggestion/application du mapping PAR
    ONGLET (apply_pipeline_mapping ci-dessous)."""
    by_sheet: dict[str, list[dict]] = {}
    for r in all_rows:
        sheet_key = r["data"].get("_sheet") or ""
        by_sheet.setdefault(sheet_key, []).append(r)
    return by_sheet


def _get_pipeline_session_or_404(ctx: AuthCtx, org_id: str, session_id: str) -> dict:
    """Une session appartenant à un AUTRE environnement, ou expirée/déjà
    nettoyée par cleanup_expired_pipeline_sessions(), est traitée comme
    introuvable -- jamais une erreur serveur (voir trieur/db.py:get_pipeline_session)."""
    session = get_pipeline_session(ctx.client, session_id)
    if not session or session["org_id"] != org_id:
        raise HTTPException(status_code=404, detail="Session de pipeline introuvable ou expirée.")
    return session


def _paginate_list(rows: list[dict], page_size: int):
    """Découpe une liste déjà en mémoire en pages -- pour que le chemin de
    mutation par onglet (voir apply_pipeline_mapping) puisse traiter
    indifféremment une liste préchargée (ancien appelant, sans
    sheet_keys) ou un flux paginé depuis la base (_pages_for_sheet
    ci-dessous), avec la même fonction de traitement des deux côtés."""
    for start in range(0, len(rows), page_size):
        yield rows[start:start + page_size]


def _pages_for_sheet(client, session_id: str, sheet_key: str, page_size: int):
    """Générateur qui page à travers TOUTES les lignes d'un onglet SANS
    jamais les charger toutes en mémoire -- toujours `limit=page_size,
    offset=0` (list_pipeline_rows_for_sheet ne prend pas d'offset) : ça
    marche car chaque page est "consommée" par l'appelant avant que ce
    générateur ne redemande (update qui retire `_sheet` de `data`, ou
    delete qui retire la ligne) -- la page suivante devient donc
    naturellement la nouvelle "première page" de cet onglet. Boucle
    jusqu'à page vide."""
    while True:
        page = list_pipeline_rows_for_sheet(client, session_id, sheet_key, limit=page_size)
        if not page:
            return
        yield page


def _delete_sheet_pages(client, session_id: str, pages) -> int:
    n_excluded = 0
    for page in pages:
        ids = [r["id"] for r in page]
        n_excluded += delete_pipeline_rows(client, session_id, ids)
    return n_excluded


def _update_sheet_pages(
    client, pages, sheet_map: dict[str, str], master_cols: list[str],
    source_label: str | None, iban_masters: set[str],
) -> tuple[int, dict[str, int], dict[str, list[str]]]:
    n_updated = 0
    iban_invalid_counts: dict[str, int] = {}
    iban_invalid_samples: dict[str, list[str]] = {}
    for page in pages:
        for row in page:
            new_data = merge_mapped_row(
                _without_sheet_key(row["data"]), sheet_map, master_cols, source_label, iban_masters,
            )
            for col in iban_masters:
                if col in new_data and iban_is_valid(new_data[col]) is False:
                    iban_invalid_counts[col] = iban_invalid_counts.get(col, 0) + 1
                    samples = iban_invalid_samples.setdefault(col, [])
                    if len(samples) < 20:
                        samples.append(row["id"])
            update_pipeline_row_data(client, row["id"], new_data)
            n_updated += 1
    return n_updated, iban_invalid_counts, iban_invalid_samples


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
    files: list[UploadFile] = File(...),
    ctx: AuthCtx = Depends(require_org_access),
):
    """Ouvre une session de pipeline : lit UN OU PLUSIEURS fichiers (comme
    st.file_uploader(accept_multiple_files=True) de l'onglet 2 d'origine,
    voir views/tab2_import_mapping.py), fusionne tous leurs onglets en une
    seule session de staging (trieur_data.pipeline_rows, TTL 24h), et
    renvoie un aperçu + les colonnes détectées pour l'étape de mapping
    suivante. N'écrit jamais dans trieur_data.records (donnée permanente)
    -- ça reste la validation finale du pipeline, pas encore portée ici.

    Au-delà de PIPELINE_STREAM_THRESHOLD_BYTES, bascule en MODE FLUX
    (_stream_import_pipeline_files) : Raphaël importe régulièrement des
    .xlsx allant jusqu'à plusieurs centaines de Mo (ancien Streamlit,
    maxUploadSize=500) -- le chemin classique ci-dessous (tout le fichier
    en DataFrame pandas) ferait planter le serveur en mémoire bien avant
    ça (mesuré : ~45x la taille du fichier en RAM)."""
    if any(f.size is None for f in files):
        # Starlette initialise toujours UploadFile.size dès la lecture du
        # multipart (vérifié sur MultiPartParser) -- si jamais absent, on
        # refuse plutôt que de compter silencieusement 0 octet : un total
        # sous-estimé pourrait contourner le hard cap ET le seuil de
        # streaming, et retomber sur le chemin classique (risque OOM).
        raise HTTPException(
            status_code=413,
            detail="Taille de fichier indéterminable -- réessayez l'import.",
        )
    total_bytes = sum(f.size for f in files)
    if total_bytes > PIPELINE_MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Fichier(s) trop volumineux ({total_bytes / 1_048_576:.1f} Mo, max "
                f"{PIPELINE_MAX_UPLOAD_BYTES / 1_048_576:.0f} Mo par import) -- importez en plusieurs fois."
            ),
        )

    # Nettoyage opportuniste des sessions expirées de CET org avant d'en
    # ouvrir une nouvelle (revue PR #24, point #8 -- voir docstring de
    # delete_expired_pipeline_sessions_for_org) -- best-effort : un échec
    # ici ne doit jamais empêcher l'import en cours, juste laisser un peu
    # plus de sessions périmées trainer jusqu'au prochain appel.
    try:
        delete_expired_pipeline_sessions_for_org(ctx.client, org_id)
    except Exception:
        pass

    filenames = [f.filename or "import" for f in files]
    source_label = (
        filenames[0] if len(filenames) == 1
        else f"{len(filenames)} fichiers ({', '.join(filenames[:3])}{'…' if len(filenames) > 3 else ''})"
    )

    if total_bytes > PIPELINE_STREAM_THRESHOLD_BYTES:
        session = create_pipeline_session(ctx.client, org_id, ctx.user.id, source_filename=source_label)
        try:
            result = await asyncio.to_thread(
                _stream_import_pipeline_files, ctx.client, session["id"], list(zip(filenames, files)),
            )
        except Exception as exc:
            try:
                delete_pipeline_session(ctx.client, session["id"])
            except Exception:
                pass
            raise HTTPException(
                status_code=500,
                detail="Échec de l'import (un ou plusieurs lots n'ont pas pu être enregistrés). Réessayez.",
            ) from exc
        if result["row_count"] == 0:
            try:
                delete_pipeline_session(ctx.client, session["id"])
            except Exception:
                pass
            raise HTTPException(status_code=400, detail="Fichier(s) vide(s) ou sans ligne exploitable.")
        try:
            adjust_pipeline_row_count(ctx.client, session["id"], result["row_count"])
        except Exception as exc:
            try:
                delete_pipeline_session(ctx.client, session["id"])
            except Exception:
                pass
            raise HTTPException(
                status_code=500,
                detail="Échec de l'import (mise à jour du compteur). Réessayez.",
            ) from exc

        master_cols = get_org_master_columns(ctx.client, org_id)
        return {
            "session_id": session["id"],
            "status": session.get("status", "importing"),
            "row_count": result["row_count"],
            "columns": result["columns"],
            "unknown_columns": unknown_columns(result["columns"], master_cols),
            "preview_rows": result["preview_rows"],
            "sheets": result["sheets"],
        }

    # MODE CLASSIQUE (import sous le seuil de flux) -- inchangé, chemin le
    # plus emprunté et déjà couvert par la suite de tests existante.
    parsed = [(filename, await f.read()) for filename, f in zip(filenames, files)]
    sheets = _parse_and_merge_pipeline_files(parsed)
    rows, columns = _merge_pipeline_sheets(sheets)
    if not rows:
        raise HTTPException(status_code=400, detail="Fichier(s) vide(s) ou sans ligne exploitable.")

    # [7] Un résumé PAR ONGLET (avant toute écriture en staging) -- permet à
    # l'écran de construire une carte par onglet (menus + aperçu alignés)
    # sans re-télécharger les fichiers.
    sheet_summaries = [_sheet_summary_from_df(key, df) for key, df in sheets.items()]

    session = create_pipeline_session(ctx.client, org_id, ctx.user.id, source_filename=source_label)

    # Import rapide : tous les lots insérés EN PARALLÈLE (asyncio.gather +
    # to_thread, le client Supabase est synchrone) au lieu d'un aller-retour
    # séquentiel par lot -- puis UN SEUL appel RPC pour tout le compteur à
    # la fin, au lieu d'un par lot (voir insert_pipeline_rows_only). Pour un
    # fichier de plusieurs milliers de lignes, ça change l'import de
    # plusieurs dizaines d'allers-retours réseau séquentiels à une poignée
    # en parallèle -- cause réelle de lenteur signalée par l'utilisateur,
    # mesurée avant ce correctif (revue PR #26 après merge).
    batches = [
        (start, rows[start:start + PIPELINE_APPEND_BATCH])
        for start in range(0, len(rows), PIPELINE_APPEND_BATCH)
    ]
    # `return_exceptions=True` : ATTEND que tous les lots terminent, même si
    # l'un d'eux plante -- sans ça, la 1re exception fait sortir `gather`
    # immédiatement pendant que les autres `to_thread` déjà lancés
    # continuent d'insérer EN ARRIÈRE-PLAN après la réponse HTTP (des
    # threads qu'on ne peut pas annuler une fois démarrés), sur une session
    # qu'on est par ailleurs en train de supprimer juste en dessous --
    # course entre l'écriture et la suppression (revue Copilot, PR #27).
    results = await asyncio.gather(*(
        asyncio.to_thread(insert_pipeline_rows_only, ctx.client, session["id"], batch, start)
        for start, batch in batches
    ), return_exceptions=True)
    failures = [r for r in results if isinstance(r, BaseException)]
    if failures:
        try:
            delete_pipeline_session(ctx.client, session["id"])
        except Exception:
            pass
        raise HTTPException(
            status_code=500,
            detail="Échec de l'import (un ou plusieurs lots n'ont pas pu être enregistrés). Réessayez.",
        ) from failures[0]
    try:
        adjust_pipeline_row_count(ctx.client, session["id"], len(rows))
    except Exception as exc:
        # Même raison que le nettoyage ci-dessus (revue Copilot, PR #27) :
        # si CE dernier appel échoue après que toutes les lignes ont bien
        # été insérées, la session resterait sinon en base avec toutes ses
        # lignes mais row_count à 0 et le statut "importing" -- invisible
        # comme "en cours d'import" jusqu'au TTL (24h) au lieu d'échouer
        # proprement maintenant.
        try:
            delete_pipeline_session(ctx.client, session["id"])
        except Exception:
            pass
        raise HTTPException(
            status_code=500,
            detail="Échec de l'import (mise à jour du compteur). Réessayez.",
        ) from exc

    master_cols = get_org_master_columns(ctx.client, org_id)
    return {
        "session_id": session["id"],
        "status": session.get("status", "importing"),
        "row_count": len(rows),
        "columns": columns,
        "unknown_columns": unknown_columns(columns, master_cols),
        "preview_rows": [_without_sheet_key(r) for r in rows[:PIPELINE_PREVIEW_SIZE]],
        "sheets": sheet_summaries,
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
    # sheet_key -> {colonne source: colonne maître}. `None` : pas de
    # mapping fourni -> la suggestion d'auto-assignation (par onglet) est
    # appliquée telle quelle. Fournir un dict explicite, même partiel,
    # remplace entièrement la suggestion pour CHAQUE onglet qu'il
    # contient (l'appelant envoie le mapping COMPLET qu'il veut appliquer
    # pour cet onglet, pas un patch). Un onglet du staging ABSENT de ce
    # dict (décoché par l'utilisateur, cf. [3] de la référence Streamlit)
    # est traité comme sans assignation : voir apply_pipeline_mapping.
    mapping: Optional[dict[str, dict[str, str]]] = None
    # true : renvoie la suggestion sans rien écrire (aperçu avant
    # confirmation côté frontend, même principe que dry_run sur /import).
    dry_run: bool = False
    # Onglets réels de cette session, tels que renvoyés par
    # POST .../pipeline/sessions (`sheets[].sheet_key`) -- utilisé PAR LES
    # DEUX CHEMINS :
    #   - dry_run : échantillonne un nombre borné de lignes PAR ONGLET
    #     (voir list_pipeline_rows_for_sheet) plutôt qu'un LIMIT global sur
    #     toute la session -- sans ça, un onglet à lui seul plus gros que
    #     PIPELINE_SUGGESTION_ROW_CAP masque tous les onglets suivants de
    #     la suggestion (revue Copilot, PR #27) ;
    #   - application réelle : déclenche le traitement PAR PAGES (voir
    #     claim_pipeline_session_for_mapping et la boucle plus bas) au lieu
    #     de _all_pipeline_rows -- indispensable pour les gros imports
    #     désormais acceptés en mode flux côté import (revue Copilot,
    #     PR #29).
    # Si omis (anciens appelants), les deux chemins retombent sur l'ancien
    # chargement complet -- moins précis/moins économe en mémoire, mais
    # toujours correct.
    sheet_keys: Optional[list[str]] = None


def _all_pipeline_rows(client, session_id: str) -> list[dict]:
    """Toutes les lignes d'une session de pipeline (pas juste l'aperçu),
    paginées avec LIST_PAGE_SIZE -- même boucle que apply_pipeline_mapping
    ci-dessous, pour filtrer/exporter sur l'INTÉGRALITÉ de la session, pas
    seulement le lot déjà affiché à l'écran (même principe que
    list_all_records côté CRM)."""
    all_rows: list[dict] = []
    offset = 0
    while True:
        page = list_pipeline_rows(client, session_id, limit=LIST_PAGE_SIZE, offset=offset)
        if not page:
            break
        all_rows.extend(page)
        offset += len(page)
    return all_rows


def _apply_pipeline_filters(
    all_rows: list[dict], groups: list, search: str, col_filters: dict,
) -> list[dict]:
    """Filtre les lignes brutes d'une session de pipeline (telles que
    renvoyées par `_all_pipeline_rows`, [{"id", "row_index", "data"}, ...])
    en deux temps :
      1) le filtre multi-critères groupes OU / critères ET, EXACTEMENT
         celui de l'onglet 3 (trieur/filters.py:apply_filter_groups, via
         api/pipeline_engine.py:filter_rows) -- pas de traitement
         spécial du département CP par une deuxième logique ;
      2) recherche/filtres par colonne à la Google Sheets
         (_filter_by_search/_filter_by_columns, même fonctions que
         GET /orgs/{org_id}/records) -- extra additif par rapport à
         l'onglet 3 d'origine, gardé pour ne pas casser le contrat déjà
         utilisé par le frontend actuel.
    Renvoie le sous-ensemble filtré de `all_rows` (mêmes dicts, même
    ordre) -- l'appelant garde donc "id" et "row_index" pour les étapes
    suivantes (pagination, export, doublons, suppression)."""
    working = [{"id": r["id"], "data": _without_sheet_key(r["data"])} for r in all_rows]
    if groups:
        working = pipeline_engine.filter_rows(working, groups)

    plain = [w["data"] for w in working]
    plain = _filter_by_search(plain, search)
    plain = _filter_by_columns(plain, col_filters)
    kept_ids = {id(d) for d in plain}

    by_id = {r["id"]: r for r in all_rows}
    return [by_id[w["id"]] for w in working if id(w["data"]) in kept_ids]


@app.get("/orgs/{org_id}/pipeline/sessions/{session_id}/rows")
def list_pipeline_session_rows(
    org_id: str,
    session_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(LIST_PAGE_SIZE, ge=1, le=2000),
    search: str = Query(""),
    col_filters: str = Query("{}", description="JSON : {colonne: {op, value}}"),
    groups: str = Query(
        "[]",
        description="JSON : filtre multi-critères de l'onglet 3, groupes (OU) de critères "
                    "(ET) -- format EXACT de trieur/filters.py:apply_filter_groups : "
                    "[[{\"column\": str, \"kind\": \"departements\"|\"valeurs\", \"values\": [...]}]]. "
                    "\"departements\" filtre sur les 2 premiers chiffres du code postal "
                    "(valeurs = préfixes, ex: [\"33\",\"77\"]) ; \"valeurs\" filtre sur une "
                    "égalité exacte. Appliqué AVANT search/col_filters ci-dessus.",
    ),
    ctx: AuthCtx = Depends(require_org_access),
):
    """Lignes en staging (trieur_data.pipeline_rows) de cette session,
    filtrées avec le VRAI moteur de filtre de l'onglet 3
    (trieur/filters.py:apply_filter_groups, via `groups`) puis, en plus,
    les mêmes fonctions que /orgs/{org_id}/records
    (_filter_by_search/_filter_by_columns) -- voir _apply_pipeline_filters.
    Porte sur trieur_data.pipeline_rows (staging TTL 24h), jamais
    trieur_data.records (donnée permanente).

    Paginée (`page`/`page_size`, même contrat que GET /orgs/{org_id}/records)
    depuis la revue PR #24 (point #7) : avant, cette route renvoyait
    TOUTE la session en une réponse (potentiellement des centaines de
    milliers de lignes) alors que l'écran n'en affiche que 50 à la fois.
    Contrairement à /records, les filtres portent ici sur TOUTE la
    session (pas seulement la page renvoyée) : `_all_pipeline_rows`
    charge et filtre l'intégralité du staging côté serveur (comme avant),
    seule la DÉCOUPE en page change -- `count` reste le total filtré réel,
    pas juste la taille de la page renvoyée."""
    _get_pipeline_session_or_404(ctx, org_id, session_id)
    parsed_filters = _parse_col_filters(col_filters)
    parsed_groups = _parse_filter_groups(groups)

    all_rows = _all_pipeline_rows(ctx.client, session_id)
    kept = _apply_pipeline_filters(all_rows, parsed_groups, search, parsed_filters)
    rows = [_without_sheet_key(r["data"]) for r in kept]

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
    search: str = Query(""),
    col_filters: str = Query("{}", description="JSON : {colonne: {op, value}}"),
    groups: str = Query("[]", description="JSON : mêmes groupes de filtre multi-critères que GET .../rows"),
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
    parsed_filters = _parse_col_filters(col_filters)
    parsed_groups = _parse_filter_groups(groups)

    all_rows = _all_pipeline_rows(ctx.client, session_id)
    kept = _apply_pipeline_filters(all_rows, parsed_groups, search, parsed_filters)
    rows = [_without_sheet_key(r["data"]) for r in kept]

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


@app.post("/orgs/{org_id}/pipeline/sessions/{session_id}/mapping")
def apply_pipeline_mapping(
    org_id: str, session_id: str, body: PipelineMapping, ctx: AuthCtx = Depends(require_org_access),
):
    """Propose (dry_run) ou applique le mapping colonnes source -> colonnes
    maîtres, PAR ONGLET (structure [7] de views/tab2_import_mapping.py --
    voir la note au-dessus de PipelineMapping). La suggestion réutilise
    trieur/matching.py:auto_assign_columns_fast pour CHAQUE onglet -- même
    logique que le bouton "Auto" local ou "Auto-assigner TOUS les
    onglets" de la référence Streamlit, jamais réimplémentée ici.

    En dehors d'un dry_run, applique le mapping (fourni par onglet, ou la
    suggestion par onglet si omis) : chaque ligne de la session est
    réécrite avec les clés COLONNES MAÎTRES SELON LE MAPPING DE SON PROPRE
    ONGLET (`_sheet`) -- une même colonne maître peut ainsi recevoir des
    colonnes sources différentes selon l'onglet. Puis la session passe au
    statut 'mapped'. Mêmes règles que le bouton "Construire la base de
    travail fusionnée" de views/tab2_import_mapping.py (voir
    api/pipeline_mapping.py) :
      - un onglet ABSENT du mapping fourni, ou sans aucune colonne
        assignée, est exclu de la base fusionnée -- ses lignes sont
        retirées du staging (équivalent d'un onglet décoché à l'étape [3]
        ou "Aucune colonne assignée, ignoré") ;
      - si deux colonnes source du MÊME onglet pointent vers la MÊME
        colonne maître, la PREMIÈRE valeur non vide gagne (pas "la
        dernière écrase") ;
      - "Source Data" (si présente dans les colonnes maîtres) est
        toujours renseignée automatiquement (fichier + onglet d'origine),
        jamais depuis une colonne source ;
      - les colonnes IBAN détectées (nom ou contenu, sur un échantillon
        mêlant tous les onglets mappés) ont leurs espaces internes
        retirés (clean_iban) ; leur checksum (mod 97) est vérifié et les
        lignes invalides remontées dans `iban_warnings` (rien n'est
        bloqué ni supprimé automatiquement -- même choix que Streamlit, à
        vérifier avant l'export)."""
    session = _get_pipeline_session_or_404(ctx, org_id, session_id)
    # Copié à part MAINTENANT (avant toute mutation) : delete_pipeline_rows
    # (appelé plus bas pour les onglets exclus) décrémente row_count sur
    # CE MÊME dict `session` en place côté client Postgrest -- relire
    # session["row_count"] après coup donnerait un total déjà partiellement
    # décompté, faussant la garde de traitement complet ci-dessous.
    expected_row_count = session["row_count"]
    master_cols = get_org_master_columns(ctx.client, org_id)

    # Rejet rapide et lisible dans le cas courant (session déjà mappée,
    # page pas rechargée) -- PAS la seule garde : c'est un simple test du
    # statut déjà lu ci-dessus, donc pas fiable seul contre deux requêtes
    # concurrentes (voir la réservation ATOMIQUE juste avant les
    # mutations, plus bas -- claim_pipeline_session_for_mapping, revue
    # Copilot PR #27).
    if not body.dry_run and session["status"] != "importing":
        raise HTTPException(
            status_code=409,
            detail="Cette session a déjà été mappée (ou n'est plus au statut 'importing') -- rechargez la page.",
        )

    def _sheet_suggestion(sheet_rows: list[dict]) -> dict[str, str]:
        sample_df = (
            pd.DataFrame([_without_sheet_key(r["data"]) for r in sheet_rows[:PIPELINE_PREVIEW_SIZE]])
            if sheet_rows else None
        )
        return auto_assign_columns_fast(_detected_columns([r["data"] for r in sheet_rows]), master_cols, sheet_df=sample_df)

    if body.dry_run:
        # Suggestion seule : PAS besoin de charger toute la session (voir
        # PIPELINE_SUGGESTION_ROW_CAP) -- ce endpoint est appelé
        # automatiquement par le frontend juste après CHAQUE import, avant
        # même que l'utilisateur ait pu regarder quoi que ce soit. Charger
        # l'intégralité ici matérialisait toute la session en mémoire pour
        # une simple suggestion, risque réel sur les gros volumes
        # documentés (>600 000 lignes) -- revue Copilot, PR #27.
        if body.sheet_keys:
            # Échantillon PAR ONGLET (filtré côté SQL, voir
            # list_pipeline_rows_for_sheet) : chaque onglet reçoit ses
            # PROPRES lignes, quelle que soit la taille des onglets
            # précédents -- corrige le cas où un LIMIT global (ci-dessous)
            # masquait entièrement les onglets suivants (revue Copilot,
            # PR #27). PIPELINE_PREVIEW_SIZE suffit : _sheet_suggestion ne
            # regarde de toute façon jamais plus que ça pour construire
            # son échantillon de détection.
            suggestion = {
                sheet_key: _sheet_suggestion(
                    list_pipeline_rows_for_sheet(ctx.client, session_id, sheet_key, limit=PIPELINE_PREVIEW_SIZE)
                )
                for sheet_key in body.sheet_keys
            }
        else:
            # Anciens appelants (pas de sheet_keys fourni) : échantillon
            # global, moins précis sur une session à plusieurs onglets
            # inégaux, mais toujours borné en mémoire.
            sample_rows = list_pipeline_rows(ctx.client, session_id, limit=PIPELINE_SUGGESTION_ROW_CAP)
            sheets_sample = _sheet_data_by_key(sample_rows)
            suggestion = {sheet_key: _sheet_suggestion(sheet_rows) for sheet_key, sheet_rows in sheets_sample.items()}
        return {"session_id": session_id, "suggested_mapping": suggestion}

    # Application réelle : chaque ligne doit être réécrite. Avec
    # `body.sheet_keys` fourni (même contrat que le dry_run ci-dessus --
    # le frontend le transmet toujours depuis session.sheets), tout se
    # fait PAR PAGES depuis la base (_pages_for_sheet), sans jamais
    # charger la session entière en mémoire -- indispensable pour les
    # gros imports désormais acceptés en mode flux côté import (voir
    # PIPELINE_STREAM_THRESHOLD_BYTES) : sans ça, cette étape aurait
    # simplement déplacé le même risque d'OOM un peu plus loin dans le
    # pipeline. Sans sheet_keys (anciens appelants), repli sur l'ancien
    # chargement complet -- comportement identique à avant, sans risque
    # de régression pour ce cas.
    streaming_apply = bool(body.sheet_keys)
    sheets_data: dict[str, list[dict]] | None = None
    if streaming_apply:
        known_sheet_keys = body.sheet_keys
    else:
        all_rows = _all_pipeline_rows(ctx.client, session_id)
        sheets_data = _sheet_data_by_key(all_rows)
        known_sheet_keys = list(sheets_data.keys())

    def _suggestion_sample(sheet_key: str) -> list[dict]:
        if sheets_data is not None:
            return sheets_data.get(sheet_key, [])[:PIPELINE_PREVIEW_SIZE]
        return list_pipeline_rows_for_sheet(ctx.client, session_id, sheet_key, limit=PIPELINE_PREVIEW_SIZE)

    if body.mapping is not None:
        # Une clé d'onglet qui ne correspond à AUCUN onglet réel de cette
        # session (typo cliente, session périmée) laisserait sinon TOUS
        # les vrais onglets sans assignation (absents du dict fourni) et
        # donc TOUS supprimés par la boucle d'exclusion plus bas, avec une
        # réponse "mapped" à zéro ligne -- rejeté avant toute mutation
        # plutôt que de laisser ça se produire silencieusement (revue
        # Copilot, PR #27).
        unknown_keys = sorted(set(body.mapping) - set(known_sheet_keys))
        if unknown_keys:
            raise HTTPException(
                status_code=400,
                detail=f"Mapping fourni pour des onglets absents de cette session : {unknown_keys}.",
            )
        mapping_by_sheet = body.mapping
    else:
        mapping_by_sheet = {sheet_key: _sheet_suggestion(_suggestion_sample(sheet_key)) for sheet_key in known_sheet_keys}

    if not any(
        m and m != "(non assigne)"
        for sheet_map in mapping_by_sheet.values()
        for m in sheet_map.values()
    ):
        raise HTTPException(status_code=400, detail="Aucune colonne assignée dans ce mapping.")

    # Réservation ATOMIQUE de la session, juste avant toute mutation des
    # lignes -- UPDATE ... WHERE status='importing' en un seul
    # aller-retour SQL (voir claim_pipeline_session_for_mapping), pas un
    # simple test du statut lu plus haut au début de la fonction : sinon
    # deux requêtes concurrentes (double clic, deux onglets navigateur)
    # passeraient toutes les deux les validations ci-dessus avant
    # qu'aucune n'ait écrit 'mapped', et muteraient chacune les lignes de
    # l'autre -- revue Copilot, PR #27. Placée APRÈS les validations
    # (400 sur onglet inconnu / mapping vide) pour qu'une requête rejetée
    # ne consomme jamais la réservation d'une session encore réellement
    # 'importing'.
    if not claim_pipeline_session_for_mapping(ctx.client, session_id):
        raise HTTPException(
            status_code=409,
            detail="Cette session a déjà été mappée (ou n'est plus au statut 'importing') -- rechargez la page.",
        )

    # À partir d'ici, la session est réservée ('mapped') mais les lignes
    # ne sont pas encore réécrites : pas de vraie transaction possible sur
    # des centaines/milliers d'appels REST individuels. Si CE bloc échoue
    # en cours de route (panne réseau, timeout), la session resterait
    # sinon visible comme "mapped" avec un staging à moitié réécrit -- et
    # tout retry serait rejeté en 409 (déjà réservée) sans espoir de
    # réparation propre, puisque merge_mapped_row retire `_sheet` des
    # lignes déjà traitées (un retry regrouperait le reste sous une clé
    # vide, cf. plus haut). Même choix que create_pipeline_session_endpoint
    # sur un échec de lot : on supprime la session entière plutôt que de
    # la laisser dans un état à moitié transformé -- revue Copilot, PR #27.
    try:
        # Colonnes IBAN (nom OU contenu) détectées sur un échantillon
        # MÊLANT TOUS les onglets réellement mappés (pas seulement le
        # premier) -- plafonné par onglet (IBAN_DETECTION_SAMPLE_SIZE
        # réparti) pour rester borné en mémoire même avec beaucoup
        # d'onglets, en mode flux comme en mode classique.
        per_sheet_cap = max(50, IBAN_DETECTION_SAMPLE_SIZE // max(len(known_sheet_keys), 1))
        iban_sample_rows = []
        for sheet_key, sheet_map in mapping_by_sheet.items():
            if not any(m and m != "(non assigne)" for m in sheet_map.values()):
                continue
            sample = (
                sheets_data.get(sheet_key, [])[:per_sheet_cap] if sheets_data is not None
                else list_pipeline_rows_for_sheet(ctx.client, session_id, sheet_key, limit=per_sheet_cap)
            )
            if not sample:
                continue
            iban_sample_rows.extend(
                merge_mapped_row(_without_sheet_key(r["data"]), sheet_map, master_cols, None, set())
                for r in sample
            )
        iban_masters = detect_iban_master_columns(iban_sample_rows, master_cols)

        n_updated = 0
        n_excluded = 0
        iban_invalid_counts: dict[str, int] = {}
        iban_invalid_samples: dict[str, list[str]] = {}
        applied_mapping: dict[str, dict[str, str]] = {}

        for sheet_key in known_sheet_keys:
            sheet_map = mapping_by_sheet.get(sheet_key, {})
            has_assignment = any(m and m != "(non assigne)" for m in sheet_map.values())
            # Pages LAZY (rien n'est encore exécuté/chargé ici) -- soit
            # depuis la liste préchargée (repli ancien appelant), soit
            # depuis la base PAR LOTS bornés (PIPELINE_APPEND_BATCH,
            # même taille que l'import) : un seul .in_("id", ...) avec les
            # ids de tout un onglet dépasserait les limites de taille de
            # requête PostgREST sur les gros volumes -- revue Copilot,
            # PR #27, désormais vrai aussi côté SOURCE des pages, pas
            # seulement leur taille d'envoi.
            pages = (
                _paginate_list(sheets_data.get(sheet_key, []), PIPELINE_APPEND_BATCH) if sheets_data is not None
                else _pages_for_sheet(ctx.client, session_id, sheet_key, PIPELINE_APPEND_BATCH)
            )

            if not has_assignment:
                # Onglet décoché par l'utilisateur (absent de `mapping`) ou
                # sans aucune assignation : exclu de la base fusionnée,
                # comme "Aucune colonne assignée, ignoré" / l'étape [3] de
                # la référence -- ses lignes de staging sont retirées
                # plutôt que de rester à moitié mappées.
                n_excluded += _delete_sheet_pages(ctx.client, session_id, pages)
                continue

            applied_mapping[sheet_key] = sheet_map
            source_label = None
            if "Source Data" in master_cols:
                base = session.get("source_filename") or "import"
                source_label = f"{base} ({sheet_key})" if sheet_key else base

            updated, invalid_counts, invalid_samples = _update_sheet_pages(
                ctx.client, pages, sheet_map, master_cols, source_label, iban_masters,
            )
            n_updated += updated
            for col, cnt in invalid_counts.items():
                iban_invalid_counts[col] = iban_invalid_counts.get(col, 0) + cnt
            for col, samples in invalid_samples.items():
                bucket = iban_invalid_samples.setdefault(col, [])
                for row_id in samples:
                    if len(bucket) < 20:
                        bucket.append(row_id)

        if streaming_apply and n_updated + n_excluded != expected_row_count:
            # sheet_keys vient du client (session.sheets côté frontend) --
            # normalement exhaustif, mais un état désynchronisé (onglet
            # ajouté entre l'aperçu et l'application, appel manuel de
            # l'API...) laisserait sinon des lignes avec `_sheet` encore
            # présent, jamais traitées, alors que la session serait quand
            # même marquée 'mapped' : un staging à moitié transformé,
            # invisible pour l'utilisateur. Même filet de sécurité que
            # l'échec en cours de route ci-dessous (revue Copilot, PR #29).
            raise RuntimeError(
                f"Traitement partiel : {n_updated + n_excluded} ligne(s) traitée(s) sur "
                f"{expected_row_count} attendue(s) -- sheet_keys incomplet ou désynchronisé."
            )
    except Exception as exc:
        try:
            delete_pipeline_session(ctx.client, session_id)
        except Exception:
            pass
        raise HTTPException(
            status_code=500,
            detail="Échec de l'application du mapping en cours de route -- la session a été "
            "supprimée pour éviter un état à moitié transformé. Réimportez vos fichiers.",
        ) from exc

    # Statut déjà passé à 'mapped' par claim_pipeline_session_for_mapping
    # ci-dessus (réservation atomique en tout début de fonction) -- pas de
    # deuxième écriture ici.
    return {
        "session_id": session_id,
        "status": "mapped",
        "mapping": applied_mapping,
        "n_rows_updated": n_updated,
        "n_rows_excluded": n_excluded,
        "iban_columns_detected": sorted(iban_masters),
        "iban_warnings": [
            {"column": col, "n_invalid": iban_invalid_counts[col], "sample_row_ids": iban_invalid_samples[col]}
            for col in sorted(iban_invalid_counts)
        ],
    }


# ---------------------------------------------------------------
# Pipeline -- étape 3 : filtrage + moteur de dédoublonnage/rapprochement,
# EXACTEMENT trieur/filters.py (le "cœur métier" de l'onglet 3 Streamlit),
# adapté aux lignes {id, data} du staging Postgres par
# api/pipeline_engine.py -- aucune règle métier réécrite ici.
#
# Écart volontaire par rapport à Streamlit : là où l'onglet 3 gardait la
# ligne dédoublonnée dans `st.session_state` (annulable par un bouton
# "↩️ Annuler", car le DataFrame source restait intact), un backend
# FastAPI stateless n'a pas d'équivalent -- POST .../dedupe SUPPRIME
# réellement les lignes perdantes du staging (trieur_data.pipeline_rows).
# Pas d'"annuler" possible après coup (documenté ici, pas caché) : c'est
# une conséquence directe du choix d'architecture "staging Postgres, pas
# de session serveur" déjà pris pour tout le pipeline (voir migration
# 0010), pas une simplification de la RÈGLE de dédoublonnage elle-même,
# qui reste identique bit à bit à trieur/filters.py.
# ---------------------------------------------------------------

# Au-delà de ce nombre de GROUPES de doublons, la revue manuelle
# groupe-par-groupe devient impraticable côté écran -- même seuil que
# views/tab3_filtrage_dedup.py:DEDUP_GROUP_THRESHOLD, renvoyé par GET
# .../duplicates pour que le frontend propose la même bascule
# automatique vers une règle globale (pas une limite technique imposée
# ici, une simple UX à reproduire côté React).
DEDUP_GROUP_THRESHOLD = 50


@app.get("/orgs/{org_id}/pipeline/sessions/{session_id}/duplicates")
def get_pipeline_duplicates(
    org_id: str,
    session_id: str,
    column: str = Query(..., description="Colonne maître sur laquelle détecter les doublons"),
    search: str = Query(""),
    col_filters: str = Query("{}", description="JSON : {colonne: {op, value}}"),
    groups: str = Query("[]", description="JSON : mêmes groupes de filtre multi-critères que GET .../rows"),
    ctx: AuthCtx = Depends(require_org_access),
):
    """Groupes de doublons sur `column`, PARMI les lignes qui passent le
    filtre actif (mêmes paramètres que GET .../rows) -- même portée que
    l'analyse de doublons de l'onglet 3, qui opère sur `filtered_df`, pas
    sur la session entière. Pour chaque groupe : les ids des lignes
    concernées et l'id suggéré à garder (la ligne la plus complète,
    trieur/filters.py:most_complete_row_index) -- même pré-sélection que
    la revue manuelle groupe par groupe côté Streamlit."""
    _get_pipeline_session_or_404(ctx, org_id, session_id)
    parsed_filters = _parse_col_filters(col_filters)
    parsed_groups = _parse_filter_groups(groups)

    all_rows = _all_pipeline_rows(ctx.client, session_id)
    kept = _apply_pipeline_filters(all_rows, parsed_groups, search, parsed_filters)
    id_rows = [{"id": r["id"], "data": _without_sheet_key(r["data"])} for r in kept]

    dup_groups = pipeline_engine.duplicate_groups_for_rows(id_rows, column)
    return {
        "session_id": session_id,
        "column": column,
        "group_count": len(dup_groups),
        "duplicate_row_count": sum(len(g["row_ids"]) for g in dup_groups),
        "filtered_row_count": len(id_rows),
        "group_threshold": DEDUP_GROUP_THRESHOLD,
        "groups": dup_groups,
    }


class PipelineDedupe(BaseModel):
    column: str
    # "rule"   : une règle globale appliquée à TOUS les groupes de doublons
    #            (garder la 1re ligne importée, ou la plus complète).
    # "manual" : un id choisi par groupe (revue groupe par groupe côté écran) ;
    #            au-delà de DEDUP_GROUP_THRESHOLD groupes, Streamlit bascule
    #            automatiquement sur "rule" -- laissé au choix du frontend ici.
    mode: str = "rule"
    keep: str = "first"  # "first" | "complete", utilisé seulement si mode="rule"
    keep_ids: list[str] = []  # utilisé seulement si mode="manual" : 1 id par groupe
    search: str = ""
    col_filters: dict = {}
    groups: list = []


@app.post("/orgs/{org_id}/pipeline/sessions/{session_id}/dedupe")
def apply_pipeline_dedupe(
    org_id: str, session_id: str, body: PipelineDedupe, ctx: AuthCtx = Depends(require_org_access),
):
    """Supprime les doublons sur `column`, PARMI les lignes qui passent
    le filtre actif (`search`/`col_filters`/`groups`, mêmes paramètres
    que GET .../rows) -- même portée que "Supprimer les doublons" de
    l'onglet 3 (qui n'agit que sur `filtered_df`, jamais sur les lignes
    déjà exclues par le filtre). Voir la note d'architecture au-dessus de
    GET .../duplicates : contrairement à Streamlit, cette suppression est
    DÉFINITIVE (pas de bouton "annuler" possible après coup)."""
    _get_pipeline_session_or_404(ctx, org_id, session_id)
    if body.mode not in ("rule", "manual"):
        raise HTTPException(status_code=400, detail="mode invalide (attendu 'rule' ou 'manual').")
    _validate_filter_groups(body.groups)

    # Verrou court (migrations 0013/0014) : sans lui, deux appels
    # concurrents sur la même session pourraient chacun analyser le même
    # groupe de doublons, retenir une ligne différente à garder, puis
    # supprimer chacun celle que l'autre voulait garder -- le groupe
    # entier disparaîtrait alors qu'aucun appel pris isolément n'est
    # incorrect (revue GitHub Copilot, PR #25). Un deuxième appel pendant
    # qu'un premier est en cours reçoit un 409 plutôt que de risquer ça.
    # `lock_owner` (jeton unique par appel) : une requête qui dépasse la
    # TTL et perd la propriété du verrou ne doit jamais pouvoir libérer,
    # dans son `finally`, le verrou d'un appel plus récent.
    lock_owner = str(uuid.uuid4())
    if not try_lock_pipeline_dedupe(ctx.client, session_id, lock_owner):
        raise HTTPException(
            status_code=409,
            detail="Un dédoublonnage est déjà en cours sur cette session, réessayez dans quelques secondes.",
        )
    try:
        all_rows = _all_pipeline_rows(ctx.client, session_id)
        kept = _apply_pipeline_filters(all_rows, body.groups, body.search, body.col_filters)
        id_rows = [{"id": r["id"], "data": _without_sheet_key(r["data"])} for r in kept]

        if body.mode == "manual":
            if not body.keep_ids:
                raise HTTPException(status_code=400, detail="keep_ids requis en mode 'manual' (1 id par groupe).")
            # `keep_ids` vient du client, à partir d'une analyse de doublons
            # potentiellement périmée (filtre changé entretemps, sélection
            # incomplète côté écran) : on revérifie ICI, sur le périmètre
            # filtré ACTUEL, qu'il couvre bien CHAQUE groupe de doublons
            # (exactement 1 id à garder par groupe, et aucun id hors de son
            # groupe) -- sinon dedupe_dataframe_manual (trieur/filters.py)
            # ne garderait AUCUNE ligne du groupe non couvert et supprimerait
            # tout le groupe par erreur. On ne supprime rien tant que ce
            # n'est pas vérifié.
            dup_groups = pipeline_engine.duplicate_groups_for_rows(id_rows, body.column)
            keep_id_set = set(body.keep_ids)
            row_id_set = {r["id"] for r in id_rows}
            unknown_ids = sorted(keep_id_set - row_id_set)
            if unknown_ids:
                raise HTTPException(
                    status_code=400,
                    detail=f"keep_ids contient des id hors du périmètre filtré actuel : {unknown_ids}.",
                )
            for g in dup_groups:
                matched = keep_id_set & set(g["row_ids"])
                if len(matched) != 1:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"keep_ids périmé ou incomplet : le groupe de doublons "
                            f"'{g['value']}' doit avoir exactement 1 id à conserver dans "
                            f"keep_ids ({len(matched)} trouvé(s)). Relancez l'analyse de "
                            f"doublons avant de réessayer."
                        ),
                    )
            _, removed_ids = pipeline_engine.dedupe_manual(id_rows, body.column, body.keep_ids)
        else:
            if body.keep not in ("first", "complete"):
                raise HTTPException(status_code=400, detail="keep invalide (attendu 'first' ou 'complete').")
            _, removed_ids = pipeline_engine.dedupe_rule(id_rows, body.column, keep=body.keep)

        # Revérifie qu'on est TOUJOURS propriétaire du verrou juste avant
        # le DELETE (migration 0015) : le calcul ci-dessus peut avoir
        # dépassé la TTL, auquel cas un autre appel a pu reprendre le
        # verrou entretemps -- continuer sur cette analyse périmée
        # supprimerait des lignes incohérentes avec ce nouvel appel en
        # cours. Réduit la fenêtre de course de toute la durée de
        # l'opération à l'instant entre cette revérification et le DELETE.
        if not is_pipeline_dedupe_lock_owner(ctx.client, session_id, lock_owner):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Le dédoublonnage a pris trop de temps et un autre appel a repris la main "
                    "sur cette session entretemps, rien n'a été supprimé. Réessayez."
                ),
            )
        n_removed = delete_pipeline_rows(ctx.client, session_id, removed_ids)
        session = get_pipeline_session(ctx.client, session_id)
        return {
            "session_id": session_id,
            "column": body.column,
            "mode": body.mode,
            "n_removed": n_removed,
            "row_count": session["row_count"] if session else None,
        }
    finally:
        unlock_pipeline_dedupe(ctx.client, session_id, lock_owner)


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
# Membres (rôles par environnement, migration 0018) -- réservé aux
# administrateurs, mirroir de views/tab_database.py:_render_members.
# Ajouter un tout premier accès pour un nouveau compte reste manuel
# (aucun flux d'invitation, hors périmètre de ce chantier) : ces routes
# ne permettent que de changer le rôle d'un membre déjà présent, ou de
# retirer son accès.
# ---------------------------------------------------------------

@app.get("/orgs/{org_id}/members")
def get_org_members(org_id: str, ctx: AuthCtx = Depends(require_admin_access)):
    return list_org_memberships(ctx.client, org_id)


class MembershipRoleUpdate(BaseModel):
    role: str


@app.patch("/orgs/{org_id}/members/{user_id}")
def patch_org_member(
    org_id: str, user_id: str, body: MembershipRoleUpdate, ctx: AuthCtx = Depends(require_admin_access),
):
    if body.role not in ("member", "org_admin", "lecture_seule"):
        raise HTTPException(status_code=400, detail="Rôle invalide.")
    update_membership_role(ctx.client, user_id, org_id, body.role)
    return {"user_id": user_id, "org_id": org_id, "role": body.role}


@app.delete("/orgs/{org_id}/members/{user_id}")
def delete_org_member(org_id: str, user_id: str, ctx: AuthCtx = Depends(require_admin_access)):
    remove_membership(ctx.client, user_id, org_id)
    return {"user_id": user_id, "org_id": org_id, "removed": True}


# ---------------------------------------------------------------
# Génération des mandats de prélèvement (environnement Prélèvement) --
# voir trieur/prelevement.py pour les règles métier. Réservé aux
# administrateurs (require_cockpit_access) : ce sont des données
# bancaires de clients, pas un simple export de la Base de données.
# ---------------------------------------------------------------

@app.get("/orgs/{org_id}/prelevement/rules")
def get_prelevement_rules_endpoint(org_id: str, ctx: AuthCtx = Depends(require_cockpit_access)):
    return get_prelevement_rules(ctx.client, org_id)


class PrelevementRulesUpdate(BaseModel):
    ics: Optional[str] = None
    nature: str = "CORE"
    delay_days: int = 3
    frais_setup_eur: float = 20.0


@app.post("/orgs/{org_id}/prelevement/rules")
def post_prelevement_rules(
    org_id: str, body: PrelevementRulesUpdate, ctx: AuthCtx = Depends(require_cockpit_access),
):
    if body.nature not in ("CORE", "B2B"):
        raise HTTPException(status_code=400, detail="Nature invalide (CORE ou B2B).")
    if body.delay_days < 0:
        raise HTTPException(status_code=400, detail="Le délai ne peut pas être négatif.")
    if body.frais_setup_eur < 0:
        raise HTTPException(status_code=400, detail="Les frais de dossier ne peuvent pas être négatifs.")
    return save_prelevement_rules(
        ctx.client, org_id, body.ics, body.nature, body.delay_days, body.frais_setup_eur, ctx.user.id,
    )


@app.post("/orgs/{org_id}/prelevement/generate")
async def post_prelevement_generate(
    org_id: str, files: list[UploadFile] = File(...), ctx: AuthCtx = Depends(require_cockpit_access),
):
    """Prend un ou plusieurs exports CRM bruts (mêmes colonnes que le
    fichier Excel de référence), les fusionne en une seule liste de
    lignes, et renvoie un classeur avec 4 onglets : Mandat (tout,
    FRST+RCUR mélangés), First, RCUR (mêmes mandats en détail par type),
    Exclus (avec la raison de chaque exclusion) -- rien n'est écrit en
    base, ce endpoint ne fait que transformer des fichiers en un autre,
    comme l'import multi-fichiers du Trieur de Data. Plusieurs fichiers
    = simplement plusieurs lots de clients à traiter en un seul export
    (ex. un export par mois) -- pas de dédoublonnage entre eux ici."""
    dfs = []
    for file in files:
        if file.size is None or file.size > PIPELINE_MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Fichier \"{file.filename}\" trop volumineux ou taille indéterminable "
                    f"(max {PIPELINE_MAX_UPLOAD_BYTES / 1_048_576:.0f} Mo)."
                ),
            )
        content = await file.read()
        filename = file.filename or "export"
        try:
            if filename.lower().endswith(".csv"):
                dfs.append(pd.read_csv(io.BytesIO(content)))
            else:
                dfs.append(pd.read_excel(io.BytesIO(content)))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Impossible de lire \"{filename}\" : {exc}")
    df = pd.concat(dfs, ignore_index=True) if len(dfs) > 1 else dfs[0]
    filename = files[0].filename or "export"

    rules_row = get_prelevement_rules(ctx.client, org_id)
    rules = PrelevementRules(
        ics=rules_row.get("ics"),
        nature=rules_row.get("nature") or "CORE",
        delay_days=rules_row.get("delay_days") if rules_row.get("delay_days") is not None else 3,
        frais_setup_eur=(
            rules_row.get("frais_setup_eur") if rules_row.get("frais_setup_eur") is not None else 20.0
        ),
    )
    rows = df.where(pd.notnull(df), None).to_dict(orient="records")
    result = generate_mandats(rows, rules)

    def _mandat_dict(m):
        return {
            "Référence client": m.reference_client,
            "Nom": m.nom,
            "RUM": m.rum,
            "Type séquence": m.type_sequence,
            "Motif": m.motif,
            "Montant EUR": m.montant_eur,
            "Devise": m.devise,
            "IBAN": m.iban,
            "BIC": m.bic,
            "Adresse": m.adresse,
            "Ville": m.ville,
            "Code postal": m.code_postal,
            "Pays": m.pays,
            "Email": m.email,
            "Téléphone": m.telephone,
            "Date signature mandat": m.date_signature_mandat,
            "Date première échéance": m.date_premiere_echeance,
            "Date d'effet": m.date_effet,
            "Périodicité": m.periodicite,
            "Explication périodicité": m.explication_periodicite,
            "ICS": rules.ics or "",
        }

    df_mandat = pd.DataFrame([_mandat_dict(m) for m in result.mandats])
    df_first = pd.DataFrame([_mandat_dict(m) for m in result.ooff])
    df_rcur = pd.DataFrame([_mandat_dict(m) for m in result.rcur])
    df_exclus = pd.DataFrame(
        [{"Référence client": e.reference_client, "Nom": e.nom, "Raison": e.raison} for e in result.exclus]
    )

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        (df_mandat if not df_mandat.empty else pd.DataFrame(columns=["Aucun mandat"])).to_excel(
            writer, index=False, sheet_name="Mandat",
        )
        (df_first if not df_first.empty else pd.DataFrame(columns=["Aucun mandat First"])).to_excel(
            writer, index=False, sheet_name="First",
        )
        (df_rcur if not df_rcur.empty else pd.DataFrame(columns=["Aucun mandat RCUR"])).to_excel(
            writer, index=False, sheet_name="RCUR",
        )
        (df_exclus if not df_exclus.empty else pd.DataFrame(columns=["Aucune ligne exclue"])).to_excel(
            writer, index=False, sheet_name="Exclus",
        )
    buffer.seek(0)

    file_base = sanitize_filename(filename, default="mandats_prelevement")
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="mandats_{file_base}.xlsx"',
            "X-Ooff-Count": str(len(result.ooff)),
            "X-Rcur-Count": str(len(result.rcur)),
            "X-Exclus-Count": str(len(result.exclus)),
        },
    )


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
    theme = body.theme.strip() if body.theme and body.theme.strip() else None
    if theme is None:
        # Raphaël (2026-09-21) : les sections doivent se créer et se
        # trier seules -- plus de choix manuel à la création.
        existing_sections = list_sections(ctx.client, org_id)
        theme = infer_chantier_theme(existing_sections, body.title)
        if not any(s["nom"] == theme for s in existing_sections):
            create_section(ctx.client, org_id, theme)
    chantier = create_chantier(
        ctx.client, org_id, body.title.strip(), body.priority, ctx.user.id, theme=theme,
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


@app.get("/orgs/{org_id}/chantiers/{chantier_id}/questions")
def get_chantier_questions(org_id: str, chantier_id: str, ctx: AuthCtx = Depends(require_cockpit_access)):
    _get_chantier_or_404(ctx, org_id, chantier_id)
    return list_chantier_questions(ctx.client, chantier_id)


class ChantierQuestionCreate(BaseModel):
    question: str
    options: list[str] = []


@app.post("/orgs/{org_id}/chantiers/{chantier_id}/questions")
def post_chantier_question(
    org_id: str, chantier_id: str, body: ChantierQuestionCreate, ctx: AuthCtx = Depends(require_cockpit_access),
):
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="La question est vide.")
    _get_chantier_or_404(ctx, org_id, chantier_id)
    add_chantier_question(ctx.client, chantier_id, body.question.strip(), body.options)
    return list_chantier_questions(ctx.client, chantier_id)


class ChantierQuestionAnswer(BaseModel):
    answer: str
    comment: Optional[str] = None


@app.patch("/orgs/{org_id}/chantiers/{chantier_id}/questions/{question_id}")
def patch_chantier_question(
    org_id: str,
    chantier_id: str,
    question_id: str,
    body: ChantierQuestionAnswer,
    ctx: AuthCtx = Depends(require_cockpit_access),
):
    if not body.answer.strip():
        raise HTTPException(status_code=400, detail="La réponse est vide.")
    _get_chantier_or_404(ctx, org_id, chantier_id)
    questions = list_chantier_questions(ctx.client, chantier_id)
    if not any(q["id"] == question_id for q in questions):
        raise HTTPException(status_code=404, detail="Question introuvable.")
    answer_chantier_question(
        ctx.client, question_id, body.answer.strip(), body.comment.strip() if body.comment else None,
    )
    return list_chantier_questions(ctx.client, chantier_id)
