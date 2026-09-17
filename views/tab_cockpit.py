# =============================================================
# Cockpit : réservé aux administrateurs. Sert UNIQUEMENT au
# développement du logiciel (chantiers, demandes, fil de discussion
# avec Claude) -- rien à voir avec les données clients / l'historique
# d'import, qui vivent dans l'onglet "Base de données".
#
# Structure calquée sur le CLAUDE.md global de l'utilisateur (section
# "Mémoire et continuité entre sessions") : les chantiers en attente
# d'une réponse de l'utilisateur ressortent en premier, les terminés
# sont archivés (jamais supprimés) et repliés par défaut, et chaque
# chantier porte des points cochables ("coche ce qui est fait plutôt
# que de le supprimer, note les points restés ouverts") en plus du fil
# de discussion libre.
# =============================================================

import streamlit as st

from trieur.db import (
    add_chantier_message,
    add_chantier_todo,
    create_chantier,
    list_chantier_messages,
    list_chantier_todos,
    list_chantiers,
    set_chantier_todo_done,
    update_chantier_status,
)
from views._auth import accessible_organizations, require_login

STATUT_LABELS = {
    "a_faire": "📋 À faire",
    "en_cours": "🔧 En cours",
    "attente_retour": "⏳ Attente de ta réponse",
    "termine": "✅ Terminé",
    "abandonne": "⛔ Abandonné",
}

# Ordre d'affichage : ce qui a besoin de toi d'abord, ce qui est clos en dernier.
STATUT_ORDER = ["attente_retour", "en_cours", "a_faire", "termine", "abandonne"]
STATUT_ACTIFS = ["attente_retour", "en_cours", "a_faire"]
STATUT_ARCHIVES = ["termine", "abandonne"]


def render():
    try:
        configured = "supabase" in st.secrets
    except Exception:
        configured = False

    if not configured:
        st.info(
            "Le Cockpit n'est pas encore configuré (clés Supabase manquantes "
            "dans les Secrets Streamlit Cloud). Le reste de l'app fonctionne "
            "normalement."
        )
        return

    ctx = require_login()

    if not ctx["profile"].get("is_super_admin"):
        st.warning("Le Cockpit est réservé aux administrateurs.")
        return

    client = ctx["client"]
    user = ctx["user"]

    all_orgs = accessible_organizations(ctx)
    if not all_orgs:
        st.info("Aucun espace accessible.")
        return

    org_labels = {o["id"]: o["name"] for o in all_orgs}
    org_id = st.selectbox(
        "Environnement du chantier",
        options=list(org_labels.keys()),
        format_func=lambda oid: org_labels[oid],
        key="cockpit_org_select",
    )

    with st.expander("➕ Nouveau chantier"):
        with st.form("new_chantier_form", clear_on_submit=True):
            title = st.text_input("Titre du chantier / de la demande")
            priority = st.select_slider("Priorité", options=["basse", "normale", "haute"], value="normale")
            submit_new = st.form_submit_button("Créer", type="primary")
        if submit_new and title.strip():
            create_chantier(client, org_id, title.strip(), priority, user.id)
            st.rerun()

    chantiers = list_chantiers(client, org_id)
    if not chantiers:
        st.caption("Aucun chantier pour cet environnement pour l'instant.")
        return

    by_status = {s: [] for s in STATUT_ORDER}
    for ch in chantiers:
        by_status.setdefault(ch["status"], []).append(ch)

    n_actifs = sum(len(by_status[s]) for s in STATUT_ACTIFS)
    if n_actifs == 0:
        st.caption("Aucun chantier actif — tout est terminé ou abandonné.")

    for status in STATUT_ACTIFS:
        for ch in by_status.get(status, []):
            _render_chantier(client, ch, user)

    archives = [ch for s in STATUT_ARCHIVES for ch in by_status.get(s, [])]
    if archives:
        with st.expander(f"📦 Chantiers clos ({len(archives)})"):
            for ch in archives:
                _render_chantier(client, ch, user, compact=True)


def _render_chantier(client, ch, user, compact=False):
    with st.container(border=True):
        col_title, col_status = st.columns([3, 1])
        with col_title:
            st.markdown(f"**{ch['title']}**")
            st.caption(f"Priorité {ch['priority']} · mis à jour {ch['updated_at']}")
        with col_status:
            new_status = st.selectbox(
                "Statut",
                options=STATUT_ORDER,
                index=STATUT_ORDER.index(ch["status"]),
                format_func=lambda s: STATUT_LABELS[s],
                key=f"status_{ch['id']}",
                label_visibility="collapsed",
            )
            if new_status != ch["status"]:
                update_chantier_status(client, ch["id"], new_status)
                st.rerun()

        _render_todos(client, ch["id"])

        with st.expander("Fil de discussion", expanded=not compact and ch["status"] == "attente_retour"):
            messages = list_chantier_messages(client, ch["id"])
            for msg in messages:
                author = "🧑 Toi" if msg["author_type"] == "user" else "🤖 Claude"
                st.markdown(f"**{author}** · {msg['created_at']}")
                st.write(msg["body"])
                st.divider()

            reply = st.text_area("Ajouter un message", key=f"reply_{ch['id']}")
            if st.button("Envoyer", key=f"send_{ch['id']}"):
                if reply.strip():
                    add_chantier_message(client, ch["id"], reply.strip(), user.id)
                    st.rerun()


def _render_todos(client, chantier_id):
    """Points cochables : jamais supprimés une fois faits, juste cochés
    (voir CLAUDE.md -- "coche ce qui est fait plutôt que de le supprimer")."""
    todos = list_chantier_todos(client, chantier_id)
    if todos:
        for todo in todos:
            checked = st.checkbox(
                todo["body"], value=todo["done"], key=f"todo_{todo['id']}"
            )
            if checked != todo["done"]:
                set_chantier_todo_done(client, todo["id"], checked)
                st.rerun()

    new_todo = st.text_input(
        "Ajouter un point à suivre", key=f"newtodo_{chantier_id}", label_visibility="collapsed",
        placeholder="Ajouter un point à suivre pour ce chantier...",
    )
    if st.button("➕", key=f"addtodo_{chantier_id}"):
        if new_todo.strip():
            add_chantier_todo(client, chantier_id, new_todo.strip())
            st.rerun()
