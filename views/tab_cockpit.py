# =============================================================
# Cockpit : réservé aux administrateurs. Sert UNIQUEMENT au
# développement du logiciel (chantiers, demandes, fil de discussion
# avec Claude) -- rien à voir avec les données clients / l'historique
# d'import, qui vivent dans l'onglet "Base de données".
# =============================================================

import streamlit as st

from trieur.db import add_chantier_message, create_chantier, list_chantier_messages, list_chantiers
from views._auth import accessible_organizations, require_login

STATUT_LABELS = {
    "a_faire": "À faire",
    "en_cours": "En cours",
    "attente_retour": "En attente de retour",
    "termine": "Terminé",
    "abandonne": "Abandonné",
}


def render():
    try:
        configured = "supabase" in st.secrets
    except Exception:
        # Aucun fichier de secrets du tout (dev local, CI, tests) : le Cockpit
        # est juste indisponible, le reste de l'app continue de fonctionner.
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

    for ch in chantiers:
        with st.container(border=True):
            col_title, col_status = st.columns([3, 1])
            with col_title:
                st.markdown(f"**{ch['title']}**")
                st.caption(f"Priorité {ch['priority']} · mis à jour {ch['updated_at']}")
            with col_status:
                st.markdown(f"`{STATUT_LABELS.get(ch['status'], ch['status'])}`")

            with st.expander("Fil de discussion"):
                messages = list_chantier_messages(client, ch["id"])
                for msg in messages:
                    author = "🧑 Toi" if msg["author_type"] == "user" else "🤖 Claude"
                    st.markdown(f"**{author}** · {msg['created_at']}")
                    st.write(msg["body"])
                    st.divider()

                reply_key = f"reply_{ch['id']}"
                reply = st.text_area("Ajouter un message", key=reply_key)
                if st.button("Envoyer", key=f"send_{ch['id']}"):
                    if reply.strip():
                        add_chantier_message(client, ch["id"], reply.strip(), user.id)
                        st.rerun()
