"""Secours navigateur (localStorage) pour les colonnes maitres.

Le fichier serveur (`user_master_columns.json`) est perdu a chaque
redemarrage du conteneur Streamlit Cloud. Ce module duplique la liste
dans le localStorage du navigateur et la restaure automatiquement si le
serveur revient aux valeurs par defaut -- sans aucune action de la part
de l'utilisateur.

Implemente comme un composant statique (pas de build JS, voir
components/ls_master_columns/index.html) car un composant "one-way"
(components.html) ne peut pas renvoyer de valeur a Python -- et une
navigation JS depuis un iframe de composant est bloquee par le sandbox
Streamlit (pas de flag allow-top-navigation). Le protocole de composant
(setComponentValue) est le seul canal autorise pour faire remonter la
valeur du localStorage vers Python.
"""
import os

import streamlit.components.v1 as components

_COMPONENT_DIR = os.path.join(os.path.dirname(__file__), "..", "components", "ls_master_columns")
_ls_component = components.declare_component("ls_master_columns", path=_COMPONENT_DIR)


def sync_master_columns(current_columns):
    """A appeler a chaque run, apres que st.session_state.master_columns a
    ete determine. Renvoie la liste restauree depuis le localStorage si elle
    differe de `current_columns` (le serveur vient probablement de perdre
    sa version), sinon None."""
    result = _ls_component(current=list(current_columns), key="ls_master_columns_sync", default=None)
    if isinstance(result, list) and result:
        cleaned = [str(c).strip() for c in result if str(c).strip()]
        if cleaned and cleaned != list(current_columns):
            return cleaned
    return None
