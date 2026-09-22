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


WRITE_ROLES = ("member", "org_admin")
ROLE_LABELS = {"member": "Membre", "org_admin": "Administrateur", "lecture_seule": "Lecture seule"}


def can_write_org(role: str | None, is_super_admin: bool) -> bool:
    """Un membre 'lecture_seule' peut consulter mais jamais écrire (import,
    modification, suppression, résolution d'alerte) -- voir migration 0018,
    `trieur_data.can_write()` (même règle appliquée côté RLS, la vraie
    barrière de sécurité ; ceci ne sert qu'à adapter l'interface). Un
    super-admin ou un membre sans rôle reconnu (donnée future) garde
    l'accès en écriture par défaut."""
    return is_super_admin or role in WRITE_ROLES or role is None


def list_org_memberships(client: Client, org_id: str) -> list[dict]:
    """Membres d'un environnement (admin uniquement, voir migration 0018 --
    la RLS `memberships_select` ne renvoie toutes les lignes qu'à un
    super-admin). Noms résolus séparément via get_profiles_map (pas de
    relation PostgREST directe entre memberships et profiles -- toutes
    deux référencent auth.users, mais pas l'une l'autre)."""
    res = (
        _td(client, "memberships")
        .select("user_id, role, created_at")
        .eq("org_id", org_id)
        .order("created_at")
        .execute()
    )
    rows = res.data or []
    profiles = get_profiles_map(client, tuple(r["user_id"] for r in rows))
    for r in rows:
        r["full_name"] = (profiles.get(r["user_id"]) or {}).get("full_name")
    return rows


def update_membership_role(client: Client, user_id: str, org_id: str, role: str) -> None:
    _td(client, "memberships").update({"role": role}).eq("user_id", user_id).eq("org_id", org_id).execute()
    get_my_memberships.clear()


def remove_membership(client: Client, user_id: str, org_id: str) -> None:
    """Retire l'accès d'un membre à cet environnement -- ne supprime pas
    son compte ni son profil, seulement cette appartenance."""
    _td(client, "memberships").delete().eq("user_id", user_id).eq("org_id", org_id).execute()
    get_my_memberships.clear()


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


# Familles de mots-clés du domaine (repris de PROJECT_LOG.md/CockpitScreen) --
# ordre = priorité en cas de titre qui matcherait plusieurs familles.
_THEME_KEYWORDS: list[tuple[str, list[str]]] = [
    ("Import & mapping", ["import", "mapping", "fichier", "excel", "xlsx", "csv", "colonne", "upload"]),
    ("Filtrage & doublons", ["doublon", "dedup", "quasi-doublon", "iban", "filtre"]),
    ("Export", ["export", "telecharg", "xml", "sepa", "pain.008", "pain008"]),
    ("Base de donnees", ["base de donnee", "client", "ligne", "enregistrement", "historique", "etiquette"]),
    ("Cockpit & suivi", ["cockpit", "chantier", "routine", "journal"]),
    ("Comptes & securite", ["role", "admin", "permission", "droit", "securite", "compte", "login", "connexion"]),
    ("Interface & navigation", ["ecran", "onglet", "menu", "affichage", "bascule", "interface"]),
    ("Performance & fiabilite", ["lent", "lenteur", "performance", "bug", "erreur", "plante", "crash", "timeout"]),
    ("Deploiement & infra", ["render", "deploiement", "supabase", "migration"]),
]


def _normalize(text: str) -> str:
    import unicodedata

    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def infer_chantier_theme(existing_sections: list[dict], title: str) -> str:
    """Devine la section d'un chantier créé sans thème explicite --
    Raphaël (2026-09-21) veut que les sections se créent et se trient
    seules, sans lui demander de choisir à chaque fois. Priorité aux
    sections DÉJÀ existantes (son propre découpage passe avant nos
    catégories par défaut, évite de dupliquer une section qu'il a déjà
    faite) ; sinon une famille de mots-clés connue du domaine ; sinon
    "Général" plutôt que de laisser un thème vide (qui retomberait dans
    "À classer" côté CockpitScreen -- l'objectif est justement qu'il n'y
    ait plus rien à classer à la main)."""
    norm_title = _normalize(title)

    for section in existing_sections:
        nom = section.get("nom") or ""
        if not nom:
            continue
        norm_nom = _normalize(nom)
        if norm_nom in norm_title or norm_title in norm_nom:
            return nom

    for theme, keywords in _THEME_KEYWORDS:
        if any(kw in norm_title for kw in keywords):
            return theme

    return "Général"


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
# Questions à choix cliquables sur un chantier (Raphaël, 2026-09-21) --
# remplace la "fiche" Artifact claude.ai, séparée du Cockpit et donc
# perdue d'une session à l'autre. Une question posée ici vit dans la
# même table que le reste du Cockpit : une session Claude et l'appli
# lisent/écrivent la même ligne, répondre d'un côté répond de l'autre.
# ---------------------------------------------------------------

def list_chantier_questions(client: Client, chantier_id: str) -> list[dict]:
    res = (
        _td(client, "chantier_questions")
        .select("*")
        .eq("chantier_id", chantier_id)
        .order("created_at")
        .execute()
    )
    return res.data or []


def add_chantier_question(client: Client, chantier_id: str, question: str, options: list[str]) -> dict:
    res = (
        _td(client, "chantier_questions")
        .insert({"chantier_id": chantier_id, "question": question, "options": options})
        .execute()
    )
    return res.data[0]


def answer_chantier_question(client: Client, question_id: str, answer: str, comment: str | None) -> None:
    from datetime import datetime, timezone

    _td(client, "chantier_questions").update({
        "answer": answer,
        "comment": comment,
        "answered_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", question_id).execute()


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
# Étiquettes libres sur un client (ex: VIP, à recontacter) -- table à
# part, indépendante des colonnes importées (voir migration 0021).
# Partagées par l'organisation entière (pas liées à un compte, contrairement
# aux vues enregistrées ci-dessous) : une étiquette posée par quelqu'un
# doit être visible par tous les membres de cet environnement.
# ---------------------------------------------------------------

@st.cache_data(ttl=30, show_spinner=False)
def list_org_tags(_client: Client, org_id: str) -> list[str]:
    """Étiquettes déjà utilisées dans cet environnement, triées -- sert à
    proposer les étiquettes existantes plutôt que de forcer à retaper un
    nom déjà utilisé ailleurs (évite "VIP" et "vip" en doublon)."""
    res = _td(_client, "record_tags").select("tag").eq("org_id", org_id).execute()
    return sorted({r["tag"] for r in (res.data or [])})


@st.cache_data(ttl=30, show_spinner=False)
def get_record_tags_map(_client: Client, record_ids: tuple[str, ...]) -> dict[str, list[str]]:
    """Étiquettes par client, pour affichage/filtre dans la liste --
    même principe que get_profiles_map (un seul appel réseau pour tout
    le lot affiché, jamais un appel par ligne)."""
    ids = tuple(sorted({i for i in record_ids if i}))
    if not ids:
        return {}
    res = _td(_client, "record_tags").select("record_id, tag").in_("record_id", ids).execute()
    tags_by_record: dict[str, list[str]] = {}
    for r in res.data or []:
        tags_by_record.setdefault(r["record_id"], []).append(r["tag"])
    for tags in tags_by_record.values():
        tags.sort()
    return tags_by_record


def add_record_tag(client: Client, org_id: str, record_id: str, tag: str, user_id: str) -> None:
    """`upsert` sur (record_id, tag) -- reposer une étiquette déjà présente
    ne crée jamais de doublon (contrainte unique, migration 0021)."""
    _td(client, "record_tags").upsert(
        {"org_id": org_id, "record_id": record_id, "tag": tag, "created_by": user_id},
        on_conflict="record_id,tag",
    ).execute()
    list_org_tags.clear()
    get_record_tags_map.clear()


def remove_record_tag(client: Client, record_id: str, tag: str) -> None:
    _td(client, "record_tags").delete().eq("record_id", record_id).eq("tag", tag).execute()
    get_record_tags_map.clear()


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


RECENT_IMPORT_BATCHES_LIMIT = 15


def list_recent_import_batches(client: Client, org_id: str) -> list[dict]:
    """Imports les plus récents de cet environnement -- pour proposer
    d'annuler un import entier (voir cancel_import_batch), pas un
    historique complet illimité."""
    res = (
        _td(client, "import_batches")
        .select("id, source_filename, imported_at, row_count")
        .eq("org_id", org_id)
        .order("imported_at", desc=True)
        .limit(RECENT_IMPORT_BATCHES_LIMIT)
        .execute()
    )
    return res.data or []


def cancel_import_batch(client: Client, batch_id: str) -> None:
    """Annule un import entier : supprime le lot -- les clients importés
    par ce lot (records.batch_id, on delete cascade -- migration 0001)
    partent avec, ainsi que leurs alertes de doublon et étiquettes
    (elles aussi en cascade depuis records). Un seul geste, pas une
    suppression ligne par ligne côté application."""
    _td(client, "import_batches").delete().eq("id", batch_id).execute()


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


def claim_pipeline_session_for_mapping(client: Client, session_id: str) -> bool:
    """Réserve ATOMIQUEMENT une session pour l'application du mapping :
    UPDATE ... WHERE status = 'importing' en un seul aller-retour SQL,
    qui bascule directement sur 'mapped'. True si cette requête a bien
    posé la réservation (statut passé de importing -> mapped), False si
    une autre requête l'a déjà fait avant elle.

    Sans ça, un lire-puis-écrire séparé (lire le statut, décider, écrire
    à la fin) laisse une fenêtre où deux requêtes concurrentes (double
    clic, deux onglets navigateur) peuvent toutes deux lire 'importing',
    passer le garde, puis chacune réécrire/supprimer des lignes de
    l'autre avant que l'une ou l'autre ne marque la session 'mapped' --
    revue Copilot, PR #27. La contrainte `check` de la migration 0010
    reste la seule source de vérité sur les valeurs de statut valides."""
    res = (
        _td(client, "pipeline_sessions")
        .update({"status": "mapped"})
        .eq("id", session_id)
        .eq("status", "importing")
        .execute()
    )
    return bool(res.data)


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


def insert_pipeline_rows_only(client: Client, session_id: str, rows: list[dict], start_index: int = 0) -> int:
    """Même INSERT que `append_pipeline_rows`, mais SANS mettre à jour
    `row_count` -- réservé au chemin rapide de l'import initial
    (POST .../pipeline/sessions), qui insère plusieurs lots EN PARALLÈLE
    (voir api/main.py) et fait un seul `adjust_pipeline_row_count` final
    pour la totalité, au lieu d'un aller-retour RPC par lot. N'appelle
    JAMAIS ça pour un ajout isolé (la session resterait avec un
    row_count incohérent) -- utilise `append_pipeline_rows` dans ce cas."""
    if not rows:
        return 0
    payload = [
        {"session_id": session_id, "row_index": start_index + i, "data": row}
        for i, row in enumerate(rows)
    ]
    _td(client, "pipeline_rows").insert(payload).execute()
    return len(rows)


def adjust_pipeline_row_count(client: Client, session_id: str, delta: int) -> None:
    """Appelle le RPC atomique `adjust_pipeline_row_count` (migration
    0012) directement -- utilisé après `insert_pipeline_rows_only` pour
    régler `row_count` en UN seul appel une fois tous les lots insérés,
    au lieu d'un aller-retour par lot comme le fait `append_pipeline_rows`."""
    if delta == 0:
        return
    client.postgrest.schema("trieur_data").rpc(
        "adjust_pipeline_row_count", {"p_session_id": session_id, "p_delta": delta}
    ).execute()


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


def list_pipeline_rows_for_sheet(client: Client, session_id: str, sheet_key: str, limit: int) -> list[dict]:
    """Comme `list_pipeline_rows`, mais bornée à UN SEUL onglet (`_sheet`,
    filtré côté SQL via l'opérateur jsonb `->>` de PostgREST -- pas un
    filtre Python après coup). Réservée à la suggestion d'auto-assignation
    (dry_run de apply_pipeline_mapping) : un simple LIMIT global, sans
    filtrer par onglet, renvoie les toutes premières lignes de la session
    dans l'ordre du fichier -- si le 1er onglet à lui seul dépasse la
    limite, les onglets suivants n'apparaissent JAMAIS dans l'échantillon,
    et la suggestion les laisse sans aucune colonne assignée (donc exclus
    de la base fusionnée à l'application réelle, silencieusement) -- revue
    Copilot, PR #27."""
    res = (
        _td(client, "pipeline_rows")
        .select("id, row_index, data")
        .eq("session_id", session_id)
        .eq("data->>_sheet", sheet_key)
        .order("row_index")
        .limit(limit)
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


def try_lock_pipeline_dedupe(client: Client, session_id: str, owner: str, ttl_seconds: int = 30) -> bool:
    """Tente de poser un verrou court sur la session (voir migrations
    0013/0014) avant un dédoublonnage : True si obtenu, False si un autre
    dédoublonnage est déjà en cours sur cette session (verrou récent, pas
    encore expiré). Empêche deux appels concurrents de choisir chacun une
    ligne différente à garder dans le même groupe de doublons puis de
    supprimer chacun celle que l'autre voulait garder.

    `owner` doit être un jeton unique par appel (ex. uuid4), pas l'id de
    session : sans propriétaire distinct du verrou lui-même, une requête
    qui dépasse la TTL et perd la propriété du verrou pourrait, dans son
    `finally`, libérer sans le savoir le verrou d'une requête plus
    récente (trouvaille Copilot sur la migration 0013 d'origine)."""
    res = client.postgrest.schema("trieur_data").rpc(
        "try_lock_pipeline_dedupe",
        {"p_session_id": session_id, "p_owner": owner, "p_ttl_seconds": ttl_seconds},
    ).execute()
    return bool(res.data)


def is_pipeline_dedupe_lock_owner(client: Client, session_id: str, owner: str) -> bool:
    """Revérifie, juste avant le DELETE (voir migration 0015), que
    `owner` est TOUJOURS le propriétaire du verrou -- si un dédoublonnage
    a dépassé sa TTL pendant son calcul, un autre appel a pu reprendre le
    verrou entretemps ; continuer sur une analyse devenue périmée
    supprimerait des lignes incohérentes avec le nouvel appel en cours.
    Réduit la fenêtre de course de toute la durée de l'opération à
    l'instant entre cet appel et le DELETE qui le suit immédiatement."""
    res = client.postgrest.schema("trieur_data").rpc(
        "is_pipeline_dedupe_lock_owner", {"p_session_id": session_id, "p_owner": owner}
    ).execute()
    return bool(res.data)


def unlock_pipeline_dedupe(client: Client, session_id: str, owner: str) -> None:
    """Libère le verrou posé par `try_lock_pipeline_dedupe`, à appeler
    dans un `finally` pour ne jamais laisser une session verrouillée par
    erreur au-delà de sa TTL. `owner` doit être le MÊME jeton que celui
    passé au claim correspondant : le RPC ne libère le verrou que s'il
    appartient encore à cet appelant (voir migration 0014), jamais celui
    d'un appelant plus récent."""
    client.postgrest.schema("trieur_data").rpc(
        "unlock_pipeline_dedupe", {"p_session_id": session_id, "p_owner": owner}
    ).execute()


def delete_pipeline_session(client: Client, session_id: str) -> None:
    """Supprime une session de pipeline et toutes ses lignes (cascade,
    voir migration 0010) -- abandon explicite du pipeline en cours par
    l'utilisateur, distinct du nettoyage automatique par TTL
    (`cleanup_expired_pipeline_sessions`, appelé séparément, jamais
    depuis cette fonction)."""
    _td(client, "pipeline_sessions").delete().eq("id", session_id).execute()


# ---------------------------------------------------------------
# Règles de génération des mandats de prélèvement (environnement
# Prélèvement) -- ICS, nature CORE/B2B, délai minimum avant le 1er
# prélèvement. Réglages ajustables sans toucher au code (Raphaël,
# 2026-09-21), une ligne par organisation comme master_columns.
# ---------------------------------------------------------------

def get_prelevement_rules(client: Client, org_id: str) -> dict:
    res = (
        _td(client, "prelevement_rules")
        .select("*")
        .eq("org_id", org_id)
        .limit(1)
        .execute()
    )
    if res.data:
        return res.data[0]
    # Pas encore de réglage enregistré pour cet environnement -- les
    # valeurs par défaut du module trieur.prelevement (ICS vide, CORE,
    # 3 jours, 20€ de frais de dossier par produit), jamais une ligne
    # vide qui forcerait l'appelant à gérer un cas particulier.
    return {
        "org_id": org_id,
        "ics": None,
        "nature": "CORE",
        "delay_days": 3,
        "frais_setup_eur": 20.0,
        "frais_par_produit": {},
        "periodicites": {},
        "colonnes_mandat": None,
    }


def save_prelevement_rules(
    client: Client,
    org_id: str,
    ics: str | None,
    nature: str,
    delay_days: int,
    frais_setup_eur: float,
    frais_par_produit: dict,
    periodicites: dict,
    user_id: str,
    colonnes_mandat: list[dict] | None = None,
) -> dict:
    from datetime import datetime, timezone

    res = (
        _td(client, "prelevement_rules")
        .upsert(
            {
                "org_id": org_id,
                "ics": ics,
                "nature": nature,
                "delay_days": delay_days,
                "frais_setup_eur": frais_setup_eur,
                "frais_par_produit": frais_par_produit,
                "periodicites": periodicites,
                "colonnes_mandat": colonnes_mandat,
                "updated_by": user_id,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="org_id",
        )
        .execute()
    )
    return res.data[0]


# Clés du dict renvoyé par api/main.py:_mandat_dict -> colonnes de
# trieur_data.prelevement_mandats (migration 0023, complétée par la
# migration 0027 pour le nouvel ordre/contenu de colonnes demandé par
# le père de Raphaël le 2026-09-22). Une seule source de vérité pour ce
# mapping -- utilisée par save_prelevement_mandats ci-dessous, jamais
# reconstruite ailleurs.
_MANDAT_DICT_TO_COLUMN = {
    "Nom": "nom",
    "Prenom": "prenom",
    "Email": "email",
    "Telephone": "telephone",
    "Adresse": "adresse",
    "Ville": "ville",
    "Code_postal": "code_postal",
    "Pays": "pays",
    "IBAN": "iban",
    "BIC": "bic",
    "ICS_Crediteur": "ics",
    "RUM": "rum",
    "Type_prelevement": "type_sequence",
    "Montant_EUR": "montant_eur",
    "Devise": "devise",
    "Date_signature_mandat": "date_signature_mandat",
    "Date_premiere_echeance": "date_premiere_echeance",
    "Periodicite": "periodicite",
    "Explication_periodicite": "explication_periodicite",
    "Frequence_mois": "frequence_mois",
    "Jour_prelevement": "jour_prelevement",
    "Prochaine_echeance": "prochaine_echeance",
    "Date_fin": "date_fin",
    "Statut": "statut",
    "Reference_facture": "reference_facture",
    "Libelle": "libelle",
    "Référence client": "reference_client",
    "Motif": "motif",
    "Date d'effet": "date_effet",
}


def save_prelevement_mandats(
    client: Client, org_id: str, mandats: list[dict], user_id: str,
) -> dict:
    """Enregistre un lot de mandats générés (voir _mandat_dict dans
    api/main.py) sous un même batch_id -- demandé par Raphaël (2026-09-22)
    en anticipation, avant que la vue de consultation dédiée existe.
    N'écrase jamais un lot précédent : chaque appel crée un nouveau
    batch_id, donc générer deux fois le même fichier crée deux lots
    distincts (pas de déduplication ici, volontairement -- hors
    périmètre de ce chantier)."""
    import uuid
    from datetime import datetime, timezone

    if not mandats:
        return {"batch_id": None, "n_saved": 0}

    batch_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            "org_id": org_id,
            "batch_id": batch_id,
            "created_by": user_id,
            "created_at": now,
            **{col: m.get(key) for key, col in _MANDAT_DICT_TO_COLUMN.items()},
        }
        for m in mandats
    ]
    _td(client, "prelevement_mandats").insert(rows).execute()
    return {"batch_id": batch_id, "n_saved": len(rows)}


# Colonnes affichables d'un mandat, dans le même ordre que l'aperçu de
# génération (PrelevementScreen) -- réutilise _MANDAT_DICT_TO_COLUMN comme
# unique source de vérité pour les libellés français, jamais dupliqués.
MANDAT_DISPLAY_COLUMNS = list(_MANDAT_DICT_TO_COLUMN.keys())
_MANDAT_COLUMN_TO_LABEL = {v: k for k, v in _MANDAT_DICT_TO_COLUMN.items()}
_MANDAT_DB_COLUMNS = list(_MANDAT_DICT_TO_COLUMN.values())


def _mandat_row_to_display(row: dict) -> dict:
    """Une ligne `trieur_data.prelevement_mandats` (colonnes techniques en
    anglais) -> dict affichable (libellés français, même casse que l'aperçu
    de génération), avec `_id` en tête -- même convention que les clients
    génériques (voir api/main.py:_build_rows, row["_id"])."""
    out: dict = {"_id": row["id"]}
    for col, label in _MANDAT_COLUMN_TO_LABEL.items():
        out[label] = row.get(col)
    out["Enregistré le"] = row.get("created_at")
    return out


def count_prelevement_mandats(client: Client, org_id: str) -> int:
    res = (
        _td(client, "prelevement_mandats")
        .select("id", count="exact")
        .eq("org_id", org_id)
        .limit(1)
        .execute()
    )
    return res.count or 0


def list_prelevement_mandats(
    client: Client, org_id: str, limit: int = LIST_PAGE_SIZE, offset: int = 0,
) -> list[dict]:
    """Mandats enregistrés de cet environnement, du plus récent au plus
    ancien -- même pagination par offset que list_records (limite connue
    identique : recherche/filtres appliqués au lot chargé, pas à tout
    l'historique, voir _render_client_list)."""
    res = (
        _td(client, "prelevement_mandats")
        .select("id, " + ", ".join(_MANDAT_DB_COLUMNS) + ", created_at")
        .eq("org_id", org_id)
        .order("created_at", desc=True)
        .limit(limit)
        .offset(offset)
        .execute()
    )
    return [_mandat_row_to_display(r) for r in (res.data or [])]


def list_all_prelevement_mandats(
    client: Client, org_id: str, page_size: int = LIST_PAGE_SIZE,
) -> list[dict]:
    """Tout l'historique des mandats de cet environnement -- utilisé
    uniquement pour un export complet, même principe que
    list_all_records."""
    total = count_prelevement_mandats(client, org_id)
    all_rows: list[dict] = []
    offset = 0
    while len(all_rows) < total:
        page = list_prelevement_mandats(client, org_id, limit=page_size, offset=offset)
        if not page:
            break
        all_rows.extend(page)
        offset += len(page)
    return all_rows


def get_prelevement_mandat(client: Client, mandat_id: str, org_id: str) -> dict | None:
    res = (
        _td(client, "prelevement_mandats")
        .select("id, " + ", ".join(_MANDAT_DB_COLUMNS) + ", created_at")
        .eq("id", mandat_id)
        .eq("org_id", org_id)
        .limit(1)
        .execute()
    )
    return _mandat_row_to_display(res.data[0]) if res.data else None


def update_prelevement_mandat(client: Client, mandat_id: str, org_id: str, data: dict) -> bool:
    """`data` : dict de libellés français (mêmes clés que
    MANDAT_DISPLAY_COLUMNS) -> nouvelle valeur. Traduit vers les colonnes
    réelles avant l'update -- jamais de colonne technique acceptée
    directement depuis l'appelant (même garde que RecordUpdate côté
    clients génériques, qui remplace tout le jsonb plutôt que d'exposer
    les noms de colonnes SQL)."""
    columns = {
        _MANDAT_DICT_TO_COLUMN[label]: value
        for label, value in data.items()
        if label in _MANDAT_DICT_TO_COLUMN
    }
    if not columns:
        return False
    res = (
        _td(client, "prelevement_mandats")
        .update(columns)
        .eq("id", mandat_id)
        .eq("org_id", org_id)
        .execute()
    )
    return bool(res.data)


def delete_prelevement_mandat(client: Client, mandat_id: str, org_id: str) -> None:
    _td(client, "prelevement_mandats").delete().eq("id", mandat_id).eq("org_id", org_id).execute()


# ---------------------------------------------------------------
# Demandes de modification des règles codées en dur du moteur de
# prélèvement (migration 0025, Raphaël 2026-09-22) : une file d'attente
# structurée, jamais appliquée automatiquement -- une session Claude
# Code la lit sur demande explicite, code/teste/déploie le changement,
# puis met à jour le statut ici même.
# ---------------------------------------------------------------

def list_prelevement_rule_requests(client: Client, org_id: str) -> list[dict]:
    """Inclut les questions posées sur chaque demande (embed PostgREST,
    alias "questions" -- voir migration 0026) : un seul aller-retour
    pour que l'écran affiche, par règle, le statut ET la question en
    attente s'il y en a une, sans requête supplémentaire par demande."""
    res = (
        _td(client, "prelevement_rule_requests")
        .select(
            "*, questions:prelevement_rule_request_questions(*),"
            " events:prelevement_rule_request_events(*)"
        )
        .eq("org_id", org_id)
        .order("created_at", desc=False)
        .execute()
    )
    return res.data or []


def create_prelevement_rule_request(
    client: Client, org_id: str, titre: str, demande: str, user_id: str,
) -> dict:
    res = (
        _td(client, "prelevement_rule_requests")
        .insert({
            "org_id": org_id,
            "titre": titre,
            "demande": demande,
            "statut": "en_attente",
            "created_by": user_id,
            "updated_by": user_id,
        })
        .execute()
    )
    return res.data[0]


def update_prelevement_rule_request(
    client: Client, request_id: str, org_id: str, data: dict, user_id: str,
) -> dict | None:
    """`data` : sous-ensemble de {titre, demande, statut} -- fusion
    partielle, jamais un remplacement de ligne complète (contrairement
    aux réglages Prélèvement) : Raphaël peut éditer le texte d'une
    demande pendant qu'une session Claude Code n'a touché que le statut,
    sans que l'un écrase le travail de l'autre."""
    from datetime import datetime, timezone

    res = (
        _td(client, "prelevement_rule_requests")
        .update({**data, "updated_by": user_id, "updated_at": datetime.now(timezone.utc).isoformat()})
        .eq("id", request_id)
        .eq("org_id", org_id)
        .execute()
    )
    return res.data[0] if res.data else None


def delete_prelevement_rule_request(client: Client, request_id: str, org_id: str) -> None:
    _td(client, "prelevement_rule_requests").delete().eq("id", request_id).eq("org_id", org_id).execute()


# ---------------------------------------------------------------
# Questions à choix cliquables sur une demande de modification de
# règle (migration 0026, Raphaël 2026-09-22) -- même principe que
# chantier_questions côté Cockpit : une session Claude Code pose la
# question ici quand la demande n'est pas claire, plutôt que dans le
# chat ; la réponse vit dans la même table, lue par la session
# suivante.
# ---------------------------------------------------------------

def add_prelevement_rule_request_question(
    client: Client, request_id: str, question: str, options: list[str],
) -> dict:
    res = (
        _td(client, "prelevement_rule_request_questions")
        .insert({"request_id": request_id, "question": question, "options": options})
        .execute()
    )
    return res.data[0]


def answer_prelevement_rule_request_question(
    client: Client, question_id: str, answer: str, comment: str | None,
) -> dict | None:
    from datetime import datetime, timezone

    res = (
        _td(client, "prelevement_rule_request_questions")
        .update({
            "answer": answer,
            "comment": comment,
            "answered_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", question_id)
        .execute()
    )
    return res.data[0] if res.data else None


# ---------------------------------------------------------------
# Journal d'activité en direct sur une demande (migration 0029,
# Raphaël 2026-09-22) -- une session Claude Code y écrit un court
# message à chaque étape clé pendant qu'elle travaille sur la
# demande, pour que ce soit visible sur le site en quasi direct
# plutôt que découvert après coup dans PROJECT_LOG.md.
# ---------------------------------------------------------------

def add_prelevement_rule_request_event(client: Client, request_id: str, message: str) -> dict:
    res = (
        _td(client, "prelevement_rule_request_events")
        .insert({"request_id": request_id, "message": message})
        .execute()
    )
    return res.data[0]


# ---------------------------------------------------------------
# Jeux de colonnes réutilisables pour le fichier de mandats (migration
# 0030, Raphaël 2026-09-22) -- un instantané complet de colonnes_mandat
# (ordre + visibilité), nommé, pour appliquer une disposition déjà
# préparée en un clic plutôt que de tout refaire à la main.
# ---------------------------------------------------------------

def list_prelevement_colonnes_mandat_presets(client: Client, org_id: str) -> list[dict]:
    res = (
        _td(client, "prelevement_colonnes_mandat_presets")
        .select("*")
        .eq("org_id", org_id)
        .order("name", desc=False)
        .execute()
    )
    return res.data or []


def save_prelevement_colonnes_mandat_preset(
    client: Client, org_id: str, name: str, colonnes: list[dict], user_id: str,
) -> dict:
    # upsert sur (org_id, lower(name)) -- enregistrer sous un nom déjà
    # pris REMPLACE le jeu existant plutôt que d'échouer ou d'en créer
    # un second identique visuellement (même règle que colonnes_mandat
    # lui-même : la dernière version enregistrée fait foi).
    existing = list_prelevement_colonnes_mandat_presets(client, org_id)
    match = next((p for p in existing if p["name"].strip().lower() == name.strip().lower()), None)
    if match:
        res = (
            _td(client, "prelevement_colonnes_mandat_presets")
            .update({"colonnes": colonnes, "name": name, "created_by": user_id})
            .eq("id", match["id"])
            .execute()
        )
        return res.data[0]
    res = (
        _td(client, "prelevement_colonnes_mandat_presets")
        .insert({"org_id": org_id, "name": name, "colonnes": colonnes, "created_by": user_id})
        .execute()
    )
    return res.data[0]


def delete_prelevement_colonnes_mandat_preset(client: Client, preset_id: str, org_id: str) -> None:
    (
        _td(client, "prelevement_colonnes_mandat_presets")
        .delete()
        .eq("id", preset_id)
        .eq("org_id", org_id)
        .execute()
    )
