# =============================================================
# Connexion Supabase (Auth) : UN SEUL bouton, dans la barre de menu en
# haut de l'app (voir app.py), partagé par toutes les sections -- pas de
# formulaire de connexion dupliqué dans chaque onglet.
# =============================================================

import streamlit as st

from trieur.db import get_client, get_my_memberships, get_my_profile, list_organizations


def render_top_auth_widget():
    """Bouton de connexion/déconnexion unique, à afficher une fois en haut
    de l'app quelle que soit la section active. Ne bloque jamais le rendu :
    c'est `require_login()` (appelé dans Cockpit/Base de données) qui
    s'en charge, seulement pour les sections qui en ont besoin."""
    if "auth_session" in st.session_state:
        email = st.session_state["auth_session"].user.email
        with st.popover(f"🟢 {email}"):
            if st.button("Se déconnecter", key="top_logout"):
                get_client().auth.sign_out()
                del st.session_state["auth_session"]
                st.rerun()
        return

    with st.popover("🔒 Se connecter"):
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
    """À appeler au début d'une section qui a besoin d'un compte (Cockpit,
    Base de données). Affiche un message renvoyant vers le bouton du haut
    (pas un formulaire dupliqué) tant que personne n'est connecté."""
    if "auth_session" not in st.session_state:
        st.info("Connecte-toi via le bouton **🔒 Se connecter** en haut de la page.")
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

    return {"client": client, "user": user, "profile": profile, "memberships": memberships}


def accessible_organizations(ctx: dict) -> list[dict]:
    """Organisations que l'utilisateur connecté peut voir : toutes pour un
    super-admin, seulement celles où il est membre sinon."""
    if ctx["profile"].get("is_super_admin"):
        return list_organizations(ctx["client"])
    return [m["organizations"] | {"id": m["org_id"]} for m in ctx["memberships"]]
