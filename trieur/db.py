# =============================================================
# Connexion Supabase (Auth + Postgres via schéma dédié `trieur_data`).
#
# Le projet Supabase est partagé avec l'app Jarvis : toutes les données
# du Trieur de Data vivent dans le schéma `trieur_data`, jamais `public`
# (qui appartient à Jarvis). Voir supabase/migrations/0001_init.sql.
# =============================================================

import streamlit as st
from supabase import create_client, Client


@st.cache_resource(show_spinner=False)
def get_client() -> Client:
    """Client Supabase authentifié avec la session courante (RLS active)."""
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["anon_key"]
    return create_client(url, key)


def _td(client: Client, table: str):
    """Raccourci vers une table du schéma trieur_data."""
    return client.postgrest.schema("trieur_data").table(table)


def get_my_profile(client: Client, user_id: str) -> dict | None:
    res = _td(client, "profiles").select("*").eq("id", user_id).limit(1).execute()
    return res.data[0] if res.data else None


def get_my_memberships(client: Client, user_id: str) -> list[dict]:
    res = (
        _td(client, "memberships")
        .select("org_id, role, organizations(slug, name)")
        .eq("user_id", user_id)
        .execute()
    )
    return res.data or []


def list_organizations(client: Client) -> list[dict]:
    res = _td(client, "organizations").select("*").order("slug").execute()
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


def create_chantier(client: Client, org_id: str, title: str, priority: str, user_id: str) -> dict:
    res = (
        _td(client, "chantiers")
        .insert({
            "org_id": org_id,
            "title": title,
            "priority": priority,
            "created_by": user_id,
        })
        .execute()
    )
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
