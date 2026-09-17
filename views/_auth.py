# =============================================================
# Connexion Supabase (Auth) : UN SEUL bouton, dans la barre de menu en
# haut de l'app (voir app.py), partagé par toutes les sections -- pas de
# formulaire de connexion dupliqué dans chaque onglet.
# =============================================================

import streamlit as st

from trieur.db import get_client, get_my_memberships, get_my_profile, list_organizations
from views._ls_auth_sync import clear_stored_session, read_stored_session, store_session


def try_restore_session():
    """À appeler une fois, tôt, avant d'afficher le bouton de connexion.

    Streamlit efface `st.session_state` à chaque reconnexion WebSocket
    (mobile qui met l'onglet en veille, réseau qui coupe un instant...) --
    ce qui déconnectait silencieusement l'utilisateur en permanence, même
    si son jeton Supabase restait valable plusieurs semaines. Restaure la
    session depuis le secours localStorage (voir views/_ls_auth_sync.py)
    si le serveur vient de la perdre."""
    if "auth_session" in st.session_state:
        return

    stored = read_stored_session()
    if not stored:
        return

    client = get_client()
    try:
        auth_res = client.auth.set_session(stored["access_token"], stored["refresh_token"])
    except Exception:
        # Jeton invalide/expiré (ex: mot de passe changé ailleurs) : on
        # nettoie le secours plutôt que de retenter en boucle.
        clear_stored_session()
        return

    if not auth_res.session:
        clear_stored_session()
        return

    st.session_state["auth_session"] = auth_res.session
    # set_session peut avoir fait tourner le refresh_token (single-use) :
    # on réenregistre la paire la plus fraîche.
    store_session(auth_res.session.access_token, auth_res.session.refresh_token)
    st.rerun()


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
                clear_stored_session()
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
            store_session(auth_res.session.access_token, auth_res.session.refresh_token)
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


def optional_login_ctx() -> dict | None:
    """Comme `require_login()`, mais ne bloque JAMAIS le rendu (pas de
    `st.stop()`) : renvoie `None` si Supabase n'est pas configuré, si
    personne n'est connecté, ou si le compte connecté n'a pas de profil.
    Pour les sections ADDITIVES d'un onglet qui reste 100% utilisable
    sans compte (colonnes maîtres liées au compte dans l'onglet 1,
    bouton "Enregistrer dans la base de données" dans l'onglet Export)."""
    try:
        configured = "supabase" in st.secrets
    except Exception:
        configured = False
    if not configured or "auth_session" not in st.session_state:
        return None

    client = get_client()
    session = st.session_state["auth_session"]
    client.auth.set_session(session.access_token, session.refresh_token)
    user = session.user

    profile = get_my_profile(client, user.id)
    if not profile:
        return None

    memberships = get_my_memberships(client, user.id)
    return {"client": client, "user": user, "profile": profile, "memberships": memberships}


def accessible_organizations(ctx: dict) -> list[dict]:
    """Organisations que l'utilisateur connecté peut voir : toutes pour un
    super-admin, seulement celles où il est membre sinon."""
    if ctx["profile"].get("is_super_admin"):
        return list_organizations(ctx["client"])
    return [m["organizations"] | {"id": m["org_id"]} for m in ctx["memberships"]]
