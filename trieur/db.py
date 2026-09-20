# =============================================================
# Connexion Supabase (Auth + Postgres via schéma dédié `trieur_data`).
#
# Le projet Supabase est partagé avec l'app Jarvis : toutes les données
# du Trieur de Data vivent dans le schéma `trieur_data`, jamais `public`
# (qui appartient à Jarvis). Voir supabase/migrations/0001_init.sql.
# =============================================================

from __future__ import annotations

import streamlit as st

# Import differe (dans la fonction, pas au niveau module) : la librairie
# `supabase` alourdit sensiblement le temps de demarrage de l'app si elle
# est importee pour tout le monde. Comme seuls les onglets Cockpit, Base de
# donnees et (si connecte) Colonnes maitres en ont besoin, on ne paie ce
# cout que quand quelqu'un les ouvre reellement -- un visiteur anonyme sur
# les onglets 1 a 4 ne charge jamais cette librairie.


@st.cache_resource(show_spinner=False)
def get_client():
    """Client Supabase authentifié avec la session courante (RLS active)."""
    from supabase import create_client

    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["anon_key"]
    return create_client(url, key)


def _td(client, table: str):
    """Raccourci vers une table du schéma trieur_data."""
    return client.postgrest.schema("trieur_data").table(table)


# ---------------------------------------------------------------
# Lectures mises en cache (TTL court) : profil, appartenances,
# organisations, colonnes maîtres, sections -- des données qui changent
# rarement mais qui étaient relues par requête réseau à CHAQUE clic
# n'importe où dans l'app (require_login() les appelle sur chaque rendu
# de Base de données/Cockpit). `_client` (underscore) : convention
# Streamlit pour exclure un paramètre du calcul de la clé de cache --
# l'objet client ne se hash pas de façon fiable.
# Chaque écriture correspondante appelle .clear() explicitement : jamais
# de données obsolètes affichées après une action de l'utilisateur.
# ---------------------------------------------------------------

@st.cache_data(ttl=30, show_spinner=False)
def get_my_profile(_client: Client, user_id: str) -> dict | None:
    res = _td(_client, "profiles").select("*").eq("id", user_id).limit(1).execute()
    return res.data[0] if res.data else None


@st.cache_data(ttl=30, show_spinner=False)
def get_profiles_map(_client: Client, user_ids: tuple[str, ...]) -> dict[str, dict]:
    """Nom (si connu) pour un lot d'identifiants -- affichage "modifié par
    X" dans l'historique court par ligne. La RLS (migration 0001) limite
    la lecture du profil d'un AUTRE utilisateur aux super-admins : pour un
    membre simple, un identifiant qui n'est pas le sien reste absent du
    résultat (comportement RLS existant, pas une erreur) -- l'appelant
    doit donc traiter une clé manquante comme "quelqu'un", pas comme un
    échec. `user_ids` en tuple (pas liste) : requis pour la mise en cache
    (clé hashable) -- sinon un appel a chaque rerun (ex: chaque clic de
    selection dans la liste), pour une info qui ne change quasiment
    jamais."""
    ids = tuple(sorted({uid for uid in user_ids if uid}))
    if not ids:
        return {}
    res = _td(_client, "profiles").select("id, full_name").in_("id", ids).execute()
    return {p["id"]: p for p in (res.data or [])}


@st.cache_data(ttl=30, show_spinner=False)
def get_my_memberships(_client: Client, user_id: str) -> list[dict]:
    res = (
        _td(_client, "memberships")
        .select("org_id, role, organizations(slug, name)")
        .eq("user_id", user_id)
        .execute()
    )
    return res.data or []


@st.cache_data(ttl=30, show_spinner=False)
def list_organizations(_client: Client) -> list[dict]:
    res = _td(_client, "organizations").select("*").order("slug").execute()
    return res.data or []


def list_chantiers(client: Client, org_id: str) -> list[dict]:
    res = (
        _td(client, "chantiers")
        .select("*")
        .eq("org_id", org_id)
        .order("updated_at", desc=True)
        .execute()
    )
    return res.data or []


def create_chantier(
    client: Client, org_id: str, title: str, priority: str, user_id: str, theme: str | None = None
) -> dict:
    res = (
        _td(client, "chantiers")
        .insert({
            "org_id": org_id,
            "title": title,
            "priority": priority,
            "created_by": user_id,
            "theme": theme,
        })
        .execute()
    )
    return res.data[0]


# ---------------------------------------------------------------
# Sections (regroupement des chantiers -- cockpit-kit/FONCTIONNALITES.md,
# point 3). `theme` sur `chantiers` reste le texte libre affiché ; cette
# table ne porte que ce qu'un texte libre ne sait pas porter : exister
# sans chantier, avoir un ordre.
# ---------------------------------------------------------------

@st.cache_data(ttl=30, show_spinner=False)
def list_sections(_client: Client, org_id: str) -> list[dict]:
    res = (
        _td(_client, "sections")
        .select("*")
        .eq("org_id", org_id)
        .order("position")
        .execute()
    )
    return res.data or []


def create_section(client: Client, org_id: str, nom: str) -> dict:
    existing = list_sections(client, org_id)
    next_pos = (max((s["position"] for s in existing), default=-1)) + 1
    res = (
        _td(client, "sections")
        .insert({"org_id": org_id, "nom": nom, "position": next_pos})
        .execute()
    )
    list_sections.clear()
    return res.data[0]


def update_chantier_status(client: Client, chantier_id: str, status: str) -> None:
    _td(client, "chantiers").update({"status": status}).eq("id", chantier_id).execute()


def list_chantier_messages(client: Client, chantier_id: str) -> list[dict]:
    res = (
        _td(client, "chantier_messages")
        .select("*")
        .eq("chantier_id", chantier_id)
        .order("created_at")
        .execute()
    )
    return res.data or []


def add_chantier_message(client: Client, chantier_id: str, body: str, user_id: str) -> None:
    _td(client, "chantier_messages").insert({
        "chantier_id": chantier_id,
        "author_type": "user",
        "author": user_id,
        "body": body,
    }).execute()


# ---------------------------------------------------------------
# Points cochables par chantier ("journal : coche ce qui est fait
# plutôt que de le supprimer, note les points restés ouverts").
# ---------------------------------------------------------------

def list_chantier_todos(client: Client, chantier_id: str) -> list[dict]:
    res = (
        _td(client, "chantier_todos")
        .select("*")
        .eq("chantier_id", chantier_id)
        .order("position")
        .execute()
    )
    return res.data or []


def add_chantier_todo(client: Client, chantier_id: str, body: str) -> None:
    existing = list_chantier_todos(client, chantier_id)
    next_pos = (max((t["position"] for t in existing), default=-1)) + 1
    _td(client, "chantier_todos").insert({
        "chantier_id": chantier_id,
        "body": body,
        "position": next_pos,
    }).execute()


def set_chantier_todo_done(client: Client, todo_id: str, done: bool) -> None:
    from datetime import datetime, timezone

    _td(client, "chantier_todos").update({
        "done": done,
        "done_at": datetime.now(timezone.utc).isoformat() if done else None,
    }).eq("id", todo_id).execute()


# ---------------------------------------------------------------
# Résumé "où j'en suis" et repère "depuis ta dernière visite"
# (cockpit-kit/FONCTIONNALITES.md, points 1 et 2).
# ---------------------------------------------------------------

def get_derniere_visite_cockpit(client: Client, user_id: str) -> str | None:
    """`None` si l'utilisateur n'a jamais marqué le cockpit comme vu --
    dans ce cas on ne réannonce PAS tout comme si c'était nouveau (pas de
    repère = pas de comparaison possible), voir tab_cockpit.py."""
    res = (
        _td(client, "visites_cockpit")
        .select("vu_le")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    return res.data[0]["vu_le"] if res.data else None


def marquer_cockpit_vu(client: Client) -> str:
    """Le repère ne recule jamais : la fonction SQL fait le `greatest()`,
    pas ce code (deux écrans ouverts en même temps ne doivent pas pouvoir
    s'écraser l'un l'autre en arrière)."""
    res = client.postgrest.schema("trieur_data").rpc("marquer_cockpit_vu", {}).execute()
    return res.data


# ---------------------------------------------------------------
# Environnements personnalisés : colonnes maîtres par organisation +
# import avec vérification de doublon IBAN contre tout l'historique.
# ---------------------------------------------------------------

@st.cache_data(ttl=30, show_spinner=False)
def get_org_master_columns(_client: Client, org_id: str) -> list[str]:
    res = _td(_client, "organizations").select("master_columns").eq("id", org_id).limit(1).execute()
    return (res.data[0]["master_columns"] if res.data else []) or []


def save_org_master_columns(client: Client, org_id: str, columns: list[str]) -> None:
    _td(client, "organizations").update({"master_columns": columns}).eq("id", org_id).execute()
    get_org_master_columns.clear()


def add_org_master_columns(client: Client, org_id: str, new_cols: list[str]) -> None:
    """Ajoute des colonnes aux colonnes maîtres existantes d'un
    environnement -- utilisé quand un import détecte des colonnes que
    l'environnement ne connaît pas encore (voir
    views/_ui.py:render_unknown_columns_prompt), depuis les deux chemins
    d'import (upload direct et bouton "Enregistrer dans la base de
    données") : UNE seule fonction, pour que les deux ne divergent
    jamais. Insensible à la casse (même convention que
    views/tab1_colonnes_maitres.py) -- une colonne déjà présente sous
    une autre casse n'est jamais dupliquée."""
    existing = get_org_master_columns(client, org_id)
    existing_lower = {c.lower() for c in existing}
    to_add = [c for c in new_cols if c.lower() not in existing_lower]
    if to_add:
        save_org_master_columns(client, org_id, existing + to_add)


# ---------------------------------------------------------------
# Vues enregistrées, nommées (recherche + filtres par colonne + colonnes
# affichées de la Base de données) -- liées au compte, comme les jeux de
# colonnes maîtres (voir user_master_column_sets), pas à l'organisation.
# ---------------------------------------------------------------

@st.cache_data(ttl=30, show_spinner=False)
def list_saved_views(_client: Client, user_id: str, org_id: str) -> list[dict]:
    res = (
        _td(_client, "db_saved_views")
        .select("*")
        .eq("user_id", user_id)
        .eq("org_id", org_id)
        .order("name")
        .execute()
    )
    return res.data or []


def save_saved_view(
    client: Client, user_id: str, org_id: str, name: str,
    search: str, col_filters: dict, visible_cols: list[str],
) -> dict:
    """Crée ou remplace (même nom, même compte, même environnement) une
    vue enregistrée."""
    res = (
        _td(client, "db_saved_views")
        .upsert(
            {
                "user_id": user_id,
                "org_id": org_id,
                "name": name,
                "search": search,
                "col_filters": col_filters,
                "visible_cols": visible_cols,
            },
            on_conflict="user_id,org_id,name",
        )
        .execute()
    )
    list_saved_views.clear()
    return res.data[0]


def delete_saved_view(client: Client, view_id: str) -> None:
    _td(client, "db_saved_views").delete().eq("id", view_id).execute()
    list_saved_views.clear()


def create_import_batch(client: Client, org_id: str, source_filename: str, imported_by: str, row_count: int) -> dict:
    res = (
        _td(client, "import_batches")
        .insert({
            "org_id": org_id,
            "source_filename": source_filename,
            "imported_by": imported_by,
            "row_count": row_count,
        })
        .execute()
    )
    return res.data[0]


def get_last_import_batch(client: Client, org_id: str) -> dict | None:
    """Dernier import (fichier + date) pour cet environnement -- résumé
    "où j'en suis" affiché en haut de la Base de données (voir
    views/tab_database.py:_render_dashboard). Pas de cache : un import
    tout juste terminé doit apparaître immédiatement, pas jusqu'à 30s
    plus tard."""
    res = (
        _td(client, "import_batches")
        .select("source_filename, imported_at")
        .eq("org_id", org_id)
        .order("imported_at", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def find_iban_matches(client: Client, org_id: str, iban: str) -> list[dict]:
    """Historique complet des lignes déjà en base avec ce même IBAN,
    quel que soit le fichier ou la date d'import -- détecte les mandats
    renvoyés sous un nom différent."""
    res = client.postgrest.schema("trieur_data").rpc(
        "find_iban_matches", {"p_org_id": org_id, "p_iban": iban}
    ).execute()
    return res.data or []


def get_sepa_sequence_type(client: Client, org_id: str, iban: str, exclude_record_id: str | None = None) -> str:
    """FRST/RCUR pour un IBAN donné, déduit de l'historique déjà en base
    pour cette organisation. Voir trieur/sepa.py pour la règle elle-même."""
    from trieur.sepa import determine_sequence_type

    matches = find_iban_matches(client, org_id, iban)
    if exclude_record_id:
        matches = [m for m in matches if m["record_id"] != exclude_record_id]
    return determine_sequence_type(has_prior_debit=bool(matches))


def insert_record(client: Client, org_id: str, batch_id: str, row: dict) -> dict:
    res = _td(client, "records").insert({
        "org_id": org_id,
        "batch_id": batch_id,
        "data": row,
    }).execute()
    return res.data[0]


def import_dataframe(
    client: Client,
    org_id: str,
    source_filename: str,
    imported_by: str,
    df,
    iban_col: str | None = None,
    on_progress=None,
) -> tuple[int, int]:
    """Importe chaque ligne de `df` dans l'environnement `org_id`, avec
    vérification de doublon IBAN contre TOUT l'historique déjà en base
    (pas seulement ce fichier) -- unique chemin d'import, que ce soit
    depuis l'upload direct de l'onglet Base de données ou depuis le
    bouton "Enregistrer dans la base de données" du Trieur de Data
    (onglet Export), pour ne jamais avoir deux logiques de dédoublonnage
    qui divergent. Retourne (n_imported, n_alerts)."""
    batch = create_import_batch(client, org_id, source_filename, imported_by, len(df))
    rows = df.to_dict(orient="records")
    n_imported, n_alerts = 0, 0
    for i, row in enumerate(rows):
        # Une cellule vide devient NaN (float) cote pandas -- vrai en
        # booleen (`if row.get(...)`) et non serialisable en JSON standard
        # (jsonb Postgres refuse le token NaN) : converti en None avant tout
        # usage, sinon l'import plante sur la premiere colonne vide venue.
        row = {k: (None if isinstance(v, float) and v != v else v) for k, v in row.items()}
        # La colonne générée `records.iban_normalized` (voir
        # supabase/migrations/0001_init.sql) lit la clé JSON fixe "iban"
        # (minuscule) -- jamais le nom réel choisi pour la colonne IBAN
        # dans le fichier importé (ex: "IBAN", "Référence bancaire"...).
        if iban_col and row.get(iban_col):
            row["iban"] = row[iban_col]
        record = insert_record(client, org_id, batch["id"], row)
        n_imported += 1
        if iban_col and row.get(iban_col):
            matches = find_iban_matches(client, org_id, str(row[iban_col]))
            matches = [m for m in matches if m["record_id"] != record["id"]]
            if matches:
                for m in matches:
                    create_dedup_alert(
                        client, org_id, record["id"], m["record_id"],
                        note=f"IBAN déjà vu dans {m['source_filename']} ({m['imported_at']})",
                    )
                n_alerts += 1
        if on_progress:
            on_progress(i + 1, len(rows))
    return n_imported, n_alerts


# Taille de page par defaut pour lister les clients d'un environnement --
# une seule source de verite, partagee par l'affichage pagine ("Charger
# plus" cote UI) et par list_all_records ci-dessous (export complet).
LIST_PAGE_SIZE = 300


def count_records(client: Client, org_id: str) -> int:
    res = _td(client, "records").select("id", count="exact").eq("org_id", org_id).limit(1).execute()
    return res.count or 0


def list_records(client: Client, org_id: str, limit: int = LIST_PAGE_SIZE, offset: int = 0) -> list[dict]:
    """Clients de cet environnement, du plus récent au plus ancien, avec le
    fichier et la date d'import d'origine -- vue "liste" simple
    (recherche/filtre côté Python pour l'instant, le format final dépendra
    du modèle réel une fois l'Excel de référence reçu). `offset` permet de
    charger la suite au-delà de `limit` (bouton "charger plus" côté UI)."""
    res = (
        _td(client, "records")
        .select("id, data, created_at, updated_at, updated_by, import_batches(source_filename, imported_at)")
        .eq("org_id", org_id)
        .order("created_at", desc=True)
        .limit(limit)
        .offset(offset)
        .execute()
    )
    return res.data or []


def list_all_records(client: Client, org_id: str, page_size: int = LIST_PAGE_SIZE) -> list[dict]:
    """Tout l'historique de cet environnement, en enchaînant les pages --
    utilisé uniquement pour un export complet (jamais pour l'affichage
    courant, qui reste paginé). Avance de la taille RÉELLEMENT renvoyée par
    chaque page (jamais de `page_size` supposé) : une limite serveur
    silencieuse plus petite que `page_size` (ex: max_rows PostgREST) ne
    tronque donc jamais le résultat -- on continue tant qu'on n'a pas
    récupéré `total` lignes, mesuré par un vrai comptage indépendant.

    Limite connue, non corrigée : pagination par offset triée sur
    `created_at`. Un import concurrent PENDANT ce scan (nouvelles lignes
    plus récentes, donc insérées en tête) décale les pages suivantes et
    peut dupliquer ou sauter des lignes -- même risque, déjà présent,
    que "Charger plus" côté UI, mais sur une fenêtre plus longue ici (un
    export complet enchaîne plus de pages). Corrigible par une pagination
    par curseur (created_at, id) plutôt que par offset, si ça devient
    gênant en usage réel -- pas fait maintenant, le volume actuel ne le
    justifie pas."""
    total = count_records(client, org_id)
    all_rows: list[dict] = []
    offset = 0
    while len(all_rows) < total:
        page = list_records(client, org_id, limit=page_size, offset=offset)
        if not page:
            break
        all_rows.extend(page)
        offset += len(page)
    return all_rows


def get_record(client: Client, record_id: str) -> dict | None:
    """Une seule ligne, valeur fraîche -- utilisé pour ouvrir le
    formulaire d'édition sans dépendre du lot mis en cache de session
    (potentiellement périmé si quelqu'un d'autre a importé/modifié
    depuis)."""
    res = _td(client, "records").select("id, data").eq("id", record_id).limit(1).execute()
    return res.data[0] if res.data else None


def update_record(client: Client, record_id: str, data: dict, user_id: str) -> bool:
    """Modifie le contenu d'un client déjà importé (`data` remplace
    entièrement le jsonb existant -- l'appelant doit donc partir du
    contenu actuel, pas d'un sous-ensemble). Trace `updated_at`/
    `updated_by` (migration 0008) -- historique court, volontairement
    minimal : juste de quoi savoir quand/par qui, pas un journal complet
    des valeurs changées. Retourne False si `record_id` n'existe plus
    (ex: supprimé par quelqu'un d'autre entre l'ouverture du formulaire
    et l'enregistrement) -- l'appelant doit alors prévenir plutôt
    qu'annoncer un succès qui n'a pas eu lieu. Limite connue, non
    traitée : la dernière écriture gagne sans détection de conflit --
    une modification concurrente par un autre membre sur le même client
    peut être silencieusement écrasée."""
    from datetime import datetime, timezone

    res = _td(client, "records").update({
        "data": data,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "updated_by": user_id,
    }).eq("id", record_id).execute()
    return bool(res.data)


def delete_record(client: Client, record_id: str) -> None:
    _td(client, "records").delete().eq("id", record_id).execute()


def create_dedup_alert(client: Client, org_id: str, record_id: str, matched_record_id: str, note: str = "") -> None:
    _td(client, "dedup_alerts").insert({
        "org_id": org_id,
        "record_id": record_id,
        "matched_record_id": matched_record_id,
        "note": note,
    }).execute()


def list_dedup_alerts(client: Client, org_id: str, status: str = "pending") -> list[dict]:
    res = (
        _td(client, "dedup_alerts")
        .select("*, record:records!dedup_alerts_record_id_fkey(data), matched:records!dedup_alerts_matched_record_id_fkey(data)")
        .eq("org_id", org_id)
        .eq("status", status)
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []


def resolve_dedup_alert(client: Client, alert_id: str, status: str, user_id: str, note: str = "") -> None:
    from datetime import datetime, timezone

    _td(client, "dedup_alerts").update({
        "status": status,
        "resolved_by": user_id,
        "resolved_at": datetime.now(timezone.utc).isoformat(),
        "note": note,
    }).eq("id", alert_id).execute()


# ---------------------------------------------------------------
# Jeux de colonnes maîtres liés au COMPTE (pas à l'organisation) --
# onglet 1 "Colonnes maîtres", uniquement pour un utilisateur connecté.
# ---------------------------------------------------------------

def list_user_column_sets(client: Client, user_id: str) -> list[dict]:
    res = (
        _td(client, "user_master_column_sets")
        .select("*")
        .eq("user_id", user_id)
        .order("name")
        .execute()
    )
    return res.data or []


def save_user_column_set(client: Client, user_id: str, name: str, columns: list[str]) -> dict:
    from datetime import datetime, timezone

    res = (
        _td(client, "user_master_column_sets")
        .upsert(
            {
                "user_id": user_id,
                "name": name,
                "columns": columns,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="user_id,name",
        )
        .execute()
    )
    return res.data[0]


def delete_user_column_set(client: Client, set_id: str) -> None:
    _td(client, "user_master_column_sets").delete().eq("id", set_id).execute()


def set_active_column_set(client: Client, user_id: str, set_id: str | None) -> None:
    _td(client, "profiles").update({"active_master_column_set_id": set_id}).eq("id", user_id).execute()
    get_my_profile.clear()


def get_active_column_set(client: Client, profile: dict) -> dict | None:
    set_id = profile.get("active_master_column_set_id")
    if not set_id:
        return None
    res = _td(client, "user_master_column_sets").select("*").eq("id", set_id).limit(1).execute()
    return res.data[0] if res.data else None


# ---------------------------------------------------------------
# Staging du pipeline "Trieur de Data" (import -> mapping colonnes ->
# filtre/dedup -> export, onglets 1-4 encore à porter vers FastAPI) --
# voir supabase/migrations/0010_pipeline_staging.sql et PROJECT_LOG.md
# ("Migration React", décision d'architecture du 2026-09-18). Ces
# fonctions remplacent ce que `st.session_state` portait jusqu'ici
# (all_sheets/final_df/filtered_df) : un backend FastAPI stateless n'a
# rien d'équivalent, donc l'état intermédiaire passe désormais par ces
# deux tables scratch (TTL 24h, jamais une donnée permanente -- la
# donnée permanente reste `trieur_data.records`, écrite seulement à la
# validation finale du pipeline). Pas encore appelées par une route API
# (portage des onglets 2-4 non commencé) -- juste la couche de données.
# ---------------------------------------------------------------

def create_pipeline_session(client: Client, org_id: str, created_by: str, source_filename: str | None = None) -> dict:
    """Ouvre une nouvelle session de pipeline (étape import) -- statut
    initial 'importing', expire par défaut 24h après création (colonne
    générée côté SQL, voir migration 0010). `row_count` est mis à jour
    ensuite par `append_pipeline_rows`, jamais fourni ici (il n'y a
    encore aucune ligne à l'ouverture de la session)."""
    res = _td(client, "pipeline_sessions").insert({
        "org_id": org_id,
        "created_by": created_by,
        "source_filename": source_filename,
    }).execute()
    return res.data[0]


def delete_expired_pipeline_sessions_for_org(client: Client, org_id: str) -> int:
    """Nettoie les sessions de pipeline expirées (TTL 24h, colonne
    `expires_at`) de CET environnement seulement -- appelé opportunément
    au début de la création d'une nouvelle session (voir
    api/main.py:create_pipeline_session_endpoint), pour borner le
    problème "les sessions abandonnées ne sont jamais nettoyées" sans
    dépendre d'une tâche planifiée externe (revue PR #24, point #8).

    Volontairement PAS `trieur_data.cleanup_expired_pipeline_sessions()`
    (le RPC SECURITY DEFINER de la migration 0010) : ce nettoyage-ci
    passe par le client normal de l'appelant, scopé à son propre org_id,
    permis nativement par la policy RLS `pipeline_sessions_rw` (un membre
    peut déjà supprimer les sessions de sa propre org) -- pas besoin d'un
    rôle privilégié. Le RPC cross-org reste réservé à service_role/pg_cron
    (voir migration 0011) : un vrai nettoyage global periodique serait
    préférable à long terme, mais suppose une tâche planifiée externe
    (pg_cron ou un scheduler type Render Cron Job appelant ce RPC avec la
    clé service_role) -- décision d'infra hors périmètre de ce correctif."""
    from datetime import datetime, timezone

    res = (
        _td(client, "pipeline_sessions")
        .delete()
        .eq("org_id", org_id)
        .lt("expires_at", datetime.now(timezone.utc).isoformat())
        .execute()
    )
    return len(res.data or [])


def get_pipeline_session(client: Client, session_id: str) -> dict | None:
    """Une session de pipeline, ou `None` si elle n'existe plus --
    supprimée par `cleanup_expired_pipeline_sessions()` (TTL dépassée) ou
    jamais créée dans cette organisation (RLS). L'appelant doit traiter
    ce cas comme "session introuvable/expirée", pas comme une erreur
    serveur."""
    res = _td(client, "pipeline_sessions").select("*").eq("id", session_id).limit(1).execute()
    return res.data[0] if res.data else None


def update_pipeline_session_status(client: Client, session_id: str, status: str) -> None:
    """Fait avancer une session d'une étape à l'autre du pipeline
    (importing -> mapped -> filtered -> exported). Ne valide pas la
    valeur ici -- la contrainte `check` de la migration 0010 est la seule
    source de vérité, pour ne jamais avoir deux listes de statuts
    valides qui divergent."""
    _td(client, "pipeline_sessions").update({"status": status}).eq("id", session_id).execute()


def append_pipeline_rows(client: Client, session_id: str, rows: list[dict], start_index: int = 0) -> int:
    """Ajoute des lignes à une session de pipeline, à partir de
    `start_index` (0-based, voir `pipeline_rows.row_index`) -- permet un
    import par lots (fichier volumineux envoyé en plusieurs appels) sans
    jamais recalculer l'index depuis le nombre de lignes déjà en base à
    chaque appel (l'appelant connaît déjà sa position dans le fichier
    source). Met aussi à jour `pipeline_sessions.row_count` en conséquence
    -- une seule source de vérité pour ce compteur, jamais recalculé par
    un `count` séparé côté appelant. Retourne le nombre de lignes
    insérées."""
    if not rows:
        return 0
    payload = [
        {"session_id": session_id, "row_index": start_index + i, "data": row}
        for i, row in enumerate(rows)
    ]
    _td(client, "pipeline_rows").insert(payload).execute()
    # UPDATE atomique côté SQL (migration 0012), même RPC et même raison
    # que delete_pipeline_rows : un read (get_pipeline_session) puis write
    # séparés laisserait deux imports par lots concurrents sur la même
    # session lire le même ancien compteur et écraser le travail l'un de
    # l'autre au lieu de s'additionner.
    client.postgrest.schema("trieur_data").rpc(
        "adjust_pipeline_row_count", {"p_session_id": session_id, "p_delta": len(rows)}
    ).execute()
    return len(rows)


def list_pipeline_rows(client: Client, session_id: str, limit: int = LIST_PAGE_SIZE, offset: int = 0) -> list[dict]:
    """Lignes d'une session de pipeline, dans l'ordre du fichier importé
    d'origine (`row_index`, pas l'ordre d'insertion Postgres) -- même
    convention de pagination que `list_records` (`LIST_PAGE_SIZE`), pour
    ne pas charger des millions de lignes en une seule réponse HTTP."""
    res = (
        _td(client, "pipeline_rows")
        .select("id, row_index, data")
        .eq("session_id", session_id)
        .order("row_index")
        .limit(limit)
        .offset(offset)
        .execute()
    )
    return res.data or []


def update_pipeline_row_data(client: Client, row_id: str, data: dict) -> None:
    """Remplace entièrement le jsonb d'une ligne de pipeline déjà en
    staging -- utilisé par l'étape de mapping (onglet 2, voir api/main.py)
    pour réécrire chaque ligne avec les clés COLONNES MAÎTRES une fois le
    mapping appliqué. `data` remplace tout le contenu existant (même
    convention que `update_record`) : l'appelant construit le dict final,
    pas un patch partiel."""
    _td(client, "pipeline_rows").update({"data": data}).eq("id", row_id).execute()


def delete_pipeline_rows(client: Client, session_id: str, row_ids: list[str]) -> int:
    """Supprime des lignes précises d'une session de pipeline (utilisé
    par la suppression de doublons -- onglet 3 -- voir
    api/pipeline_engine.py) et met à jour `row_count` en conséquence,
    même principe que `append_pipeline_rows`. Scopé à `session_id` en
    plus des ids : un id d'une AUTRE session ne peut jamais être
    supprimé par erreur via cet appel. Retourne le nombre de lignes
    réellement supprimées."""
    if not row_ids:
        return 0
    res = (
        _td(client, "pipeline_rows")
        .delete()
        .eq("session_id", session_id)
        .in_("id", row_ids)
        .execute()
    )
    n_deleted = len(res.data or [])
    if n_deleted:
        # UPDATE atomique côté SQL (migration 0012) -- PAS un
        # read (get_pipeline_session) puis write séparés comme avant :
        # deux suppressions concurrentes sur la même session liraient le
        # même ancien compteur et écriraient chacune "ancien - n",
        # laissant row_count au-dessus du nombre réel de lignes
        # restantes. Voir trieur_data.adjust_pipeline_row_count.
        client.postgrest.schema("trieur_data").rpc(
            "adjust_pipeline_row_count", {"p_session_id": session_id, "p_delta": -n_deleted}
        ).execute()
    return n_deleted


def try_lock_pipeline_dedupe(client: Client, session_id: str, ttl_seconds: int = 30) -> bool:
    """Tente de poser un verrou court sur la session (voir migration 0013)
    avant un dédoublonnage : True si obtenu, False si un autre
    dédoublonnage est déjà en cours sur cette session (verrou récent, pas
    encore expiré). Empêche deux appels concurrents de choisir chacun une
    ligne différente à garder dans le même groupe de doublons puis de
    supprimer chacun celle que l'autre voulait garder."""
    res = client.postgrest.schema("trieur_data").rpc(
        "try_lock_pipeline_dedupe", {"p_session_id": session_id, "p_ttl_seconds": ttl_seconds}
    ).execute()
    return bool(res.data)


def unlock_pipeline_dedupe(client: Client, session_id: str) -> None:
    """Libère le verrou posé par `try_lock_pipeline_dedupe`, à appeler
    dans un `finally` pour ne jamais laisser une session verrouillée par
    erreur au-delà de sa TTL."""
    client.postgrest.schema("trieur_data").rpc(
        "unlock_pipeline_dedupe", {"p_session_id": session_id}
    ).execute()


def delete_pipeline_session(client: Client, session_id: str) -> None:
    """Supprime une session de pipeline et toutes ses lignes (cascade,
    voir migration 0010) -- abandon explicite du pipeline en cours par
    l'utilisateur, distinct du nettoyage automatique par TTL
    (`cleanup_expired_pipeline_sessions`, appelé séparément, jamais
    depuis cette fonction)."""
    _td(client, "pipeline_sessions").delete().eq("id", session_id).execute()
