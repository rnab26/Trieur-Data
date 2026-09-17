# =============================================================
# Base de données : mémoire persistante du Trieur de Data, par
# organisation (Leads / Prélèvement) -- colonnes maîtres propres à
# l'environnement, import avec vérification de doublon IBAN contre
# tout l'historique en base, file d'alertes à résoudre à la main.
#
# Accessible à tout membre connecté de l'organisation (pas réservé aux
# administrateurs -- contrairement au Cockpit, qui lui ne concerne que
# le développement du logiciel).
# =============================================================

import pandas as pd
import streamlit as st

from trieur.db import (
    create_dedup_alert,
    create_import_batch,
    find_iban_matches,
    get_org_master_columns,
    insert_record,
    list_dedup_alerts,
    resolve_dedup_alert,
    save_org_master_columns,
)
from views._auth import accessible_organizations, require_login


def render():
    try:
        configured = "supabase" in st.secrets
    except Exception:
        configured = False

    if not configured:
        st.info(
            "La Base de données n'est pas encore configurée (clés Supabase "
            "manquantes dans les Secrets Streamlit Cloud). Le Trieur de Data "
            "fonctionne normalement en mode local (onglets Import/Filtrage/Export)."
        )
        return

    ctx = require_login()
    client = ctx["client"]
    user = ctx["user"]

    all_orgs = accessible_organizations(ctx)
    if not all_orgs:
        st.info("Aucun espace accessible. Contacte l'administrateur.")
        return

    org_labels = {o["id"]: o["name"] for o in all_orgs}
    org_id = st.selectbox(
        "Environnement",
        options=list(org_labels.keys()),
        format_func=lambda oid: org_labels[oid],
        key="db_org_select",
    )

    st.markdown("##### Colonnes maîtres de cet environnement")
    current_cols = get_org_master_columns(client, org_id)
    is_admin = ctx["profile"].get("is_super_admin")
    cols_text = st.text_area(
        "Une colonne par ligne",
        value="\n".join(current_cols),
        key=f"org_cols_{org_id}",
        height=150,
        disabled=not is_admin,
    )
    if is_admin:
        if st.button("Enregistrer les colonnes maîtres", key=f"save_cols_{org_id}"):
            new_cols = [c.strip() for c in cols_text.splitlines() if c.strip()]
            save_org_master_columns(client, org_id, new_cols)
            st.success("Colonnes maîtres enregistrées.")
            st.rerun()
    else:
        st.caption("Réglage de l'organisation, modifiable par un administrateur uniquement.")

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
