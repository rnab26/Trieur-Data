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


def count_records(client: Client, org_id: str) -> int:
    res = _td(client, "records").select("id", count="exact").eq("org_id", org_id).limit(1).execute()
    return res.count or 0


def list_records(client: Client, org_id: str, limit: int = 300) -> list[dict]:
    """Derniers clients importés pour cet environnement, avec le fichier et
    la date d'import d'origine -- vue "liste" simple (recherche/filtre côté
    Python pour l'instant, le format final dépendra du modèle réel une fois
    l'Excel de référence reçu)."""
    res = (
        _td(client, "records")
        .select("id, data, created_at, import_batches(source_filename, imported_at)")
        .eq("org_id", org_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data or []


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
