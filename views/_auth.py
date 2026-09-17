# =============================================================
# Écran de connexion (Supabase Auth) + résolution du profil/organisations
# de l'utilisateur connecté. Bloque l'accès au reste de l'app tant que
# la personne n'est pas authentifiée.
# =============================================================

import streamlit as st

from trieur.db import get_client, get_my_memberships, get_my_profile, list_organizations


def _login_form():
    st.title("Trieur de Data")
    st.caption("Connexion requise")

    with st.form("login_form"):
        email = st.text_input("Email")
        password = st.text_input("Mot de passe", type="password")
        submitted = st.form_submit_button("Se connecter", type="primary")

    if submitted:
        client = get_client()
        try:
            auth_res = client.auth.sign_in_with_password({"email": email, "password": password})
        except Exception as exc:
            st.error(f"Connexion refusée : {exc}")
            return
        st.session_state["auth_session"] = auth_res.session
        st.rerun()

    st.caption("Pas encore de compte ? Demande une invitation à l'administrateur.")


def require_login() -> dict:
    """Bloque le rendu tant que l'utilisateur n'est pas connecté et n'a
    pas d'organisation. Retourne un contexte {user, profile, memberships}."""
    if "auth_session" not in st.session_state:
        _login_form()
        st.stop()

    client = get_client()
    session = st.session_state["auth_session"]
    client.auth.set_session(session.access_token, session.refresh_token)
    user = session.user

    profile = get_my_profile(client, user.id)
    memberships = get_my_memberships(client, user.id)

    if not profile:
        st.error("Compte connecté mais aucun profil Trieur de Data associé. Contacte l'administrateur.")
        st.stop()

    if not memberships and not profile.get("is_super_admin"):
        st.warning("Ton compte n'a accès à aucun espace pour l'instant. Contacte l'administrateur.")
        st.stop()

    with st.sidebar:
        st.caption(f"Connecté : {user.email}")
        if st.button("Se déconnecter"):
            client.auth.sign_out()
            del st.session_state["auth_session"]
            st.rerun()

    return {"client": client, "user": user, "profile": profile, "memberships": memberships}


def accessible_organizations(ctx: dict) -> list[dict]:
    """Organisations que l'utilisateur connecté peut voir : toutes pour un
    super-admin, seulement celles où il est membre sinon."""
    if ctx["profile"].get("is_super_admin"):
        return list_organizations(ctx["client"])
    return [m["organizations"] | {"id": m["org_id"]} for m in ctx["memberships"]]
