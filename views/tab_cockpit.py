# =============================================================
# Cockpit : chantiers par organisation (Leads / Prélèvement / Global),
# avec fil de discussion utilisateur <-> Claude sur chaque chantier +
# réglages et import propres à chaque environnement (colonnes maîtres,
# vérification de doublon IBAN contre tout l'historique en base).
# =============================================================

import pandas as pd
import streamlit as st

from trieur.db import (
    add_chantier_message,
    create_chantier,
    create_dedup_alert,
    create_import_batch,
    find_iban_matches,
    get_org_master_columns,
    insert_record,
    list_chantier_messages,
    list_chantiers,
    list_dedup_alerts,
    list_organizations,
    resolve_dedup_alert,
    save_org_master_columns,
)
from views._auth import require_login

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
    client = ctx["client"]
    user = ctx["user"]
    profile = ctx["profile"]
    memberships = ctx["memberships"]

    if profile.get("is_super_admin"):
        all_orgs = list_organizations(client)
    else:
        all_orgs = [m["organizations"] | {"id": m["org_id"]} for m in memberships]

    if not all_orgs:
        st.info("Aucun espace accessible.")
        return

    org_labels = {o["id"]: o["name"] for o in all_orgs}
    org_id = st.selectbox(
        "Environnement",
        options=list(org_labels.keys()),
        format_func=lambda oid: org_labels[oid],
        key="cockpit_org_select",
    )

    sub_chantiers, sub_import = st.tabs(["Chantiers", "Import & Dédup base"])

    with sub_chantiers:
        _render_chantiers(client, org_id, user)

    with sub_import:
        _render_import_dedup(client, org_id, user)


def _render_chantiers(client, org_id, user):
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


def _render_import_dedup(client, org_id, user):
    st.markdown("##### Colonnes maîtres de cet environnement")
    current_cols = get_org_master_columns(client, org_id)
    cols_text = st.text_area(
        "Une colonne par ligne",
        value="\n".join(current_cols),
        key=f"org_cols_{org_id}",
        height=150,
    )
    if st.button("Enregistrer les colonnes maîtres", key=f"save_cols_{org_id}"):
        new_cols = [c.strip() for c in cols_text.splitlines() if c.strip()]
        save_org_master_columns(client, org_id, new_cols)
        st.success("Colonnes maîtres enregistrées.")
        st.rerun()

    st.divider()
    st.markdown("##### Importer un fichier dans la base (avec vérification IBAN)")
    st.caption(
        "Chaque ligne est comparée à TOUT l'historique déjà en base pour cet "
        "environnement (pas juste ce fichier) — un même IBAN déjà vu, même "
        "sous un autre nom, déclenche une alerte au lieu d'être importé en "
        "double silencieusement."
    )

    uploaded = st.file_uploader("Fichier CSV ou Excel", type=["csv", "xlsx"], key=f"upload_{org_id}")
    if uploaded is not None:
        try:
            df = pd.read_csv(uploaded) if uploaded.name.endswith(".csv") else pd.read_excel(uploaded)
        except Exception as exc:
            st.error(f"Impossible de lire le fichier : {exc}")
            return

        st.dataframe(df.head(10), use_container_width=True)
        iban_col = st.selectbox(
            "Quelle colonne contient l'IBAN ?",
            options=["(aucune)"] + list(df.columns),
            key=f"iban_col_{org_id}",
        )

        if st.button("Vérifier et importer", type="primary", key=f"import_{org_id}"):
            batch = create_import_batch(client, org_id, uploaded.name, user.id, len(df))
            n_imported, n_alerts = 0, 0
            progress = st.progress(0.0)
            for i, row in enumerate(df.to_dict(orient="records")):
                record = insert_record(client, org_id, batch["id"], row)
                n_imported += 1
                if iban_col != "(aucune)" and row.get(iban_col):
                    matches = find_iban_matches(client, org_id, str(row[iban_col]))
                    matches = [m for m in matches if m["record_id"] != record["id"]]
                    if matches:
                        for m in matches:
                            create_dedup_alert(
                                client, org_id, record["id"], m["record_id"],
                                note=f"IBAN déjà vu dans {m['source_filename']} ({m['imported_at']})",
                            )
                        n_alerts += 1
                progress.progress((i + 1) / max(len(df), 1))
            st.success(f"{n_imported} lignes importées, {n_alerts} alerte(s) de doublon IBAN créée(s).")
            st.rerun()

    st.divider()
    st.markdown("##### Alertes de doublon en attente")
    alerts = list_dedup_alerts(client, org_id, status="pending")
    if not alerts:
        st.caption("Aucune alerte en attente.")
        return

    for alert in alerts:
        with st.container(border=True):
            st.write("**Nouvelle ligne :**", alert["record"]["data"])
            st.write("**Déjà en base :**", alert["matched"]["data"])
            st.caption(alert.get("note") or "")
            col_dup, col_ok = st.columns(2)
            with col_dup:
                if st.button("C'est un doublon", key=f"dup_{alert['id']}"):
                    resolve_dedup_alert(client, alert["id"], "confirmed_duplicate", user.id)
                    st.rerun()
            with col_ok:
                if st.button("Ce sont 2 personnes différentes", key=f"ok_{alert['id']}"):
                    resolve_dedup_alert(client, alert["id"], "confirmed_different", user.id)
                    st.rerun()
