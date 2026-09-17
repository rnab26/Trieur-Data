"""Secours navigateur (localStorage) pour la session de connexion.

Streamlit efface `st.session_state` à chaque reconnexion WebSocket (mobile
qui met l'onglet en veille, réseau qui coupe un instant...) -- ce qui
déconnectait silencieusement l'utilisateur en permanence, alors que le
jeton Supabase (access_token/refresh_token) restait valable plusieurs
semaines. Même principe que le secours des colonnes maîtres
(views/_ls_sync.py) : le tuple de jetons est dupliqué dans le localStorage
du navigateur et restauré automatiquement à chaque nouvelle session
serveur, sans action de la part de l'utilisateur.
"""
import os

import streamlit.components.v1 as components

_COMPONENT_DIR = os.path.join(os.path.dirname(__file__), "..", "components", "ls_auth_session")
_ls_component = components.declare_component("ls_auth_session", path=_COMPONENT_DIR)


def read_stored_session():
    """Renvoie {"access_token", "refresh_token"} depuis le localStorage, ou
    None (rien de stocké, ou pas encore reçu la réponse JS -- comportement
    normal des composants Streamlit à double sens, voir _ls_sync.py)."""
    result = _ls_component(current=None, clear=False, key="ls_auth_session_read", default=None)
    if isinstance(result, dict) and result.get("access_token") and result.get("refresh_token"):
        return result
    return None


def store_session(access_token: str, refresh_token: str):
    _ls_component(
        current={"access_token": access_token, "refresh_token": refresh_token},
        clear=False,
        key="ls_auth_session_write",
    )


def clear_stored_session():
    _ls_component(current=None, clear=True, key="ls_auth_session_clear")
