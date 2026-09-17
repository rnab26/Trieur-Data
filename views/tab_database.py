# =============================================================
# Base de données : mémoire persistante du Trieur de Data, par
# organisation (Leads / Prélèvement) -- liste des clients importés
# (avec recherche), import avec vérification de doublon IBAN contre
# tout l'historique en base, file d'alertes à résoudre à la main.
# Les réglages (colonnes maîtres de l'environnement) sont dans un
# tiroir séparé, discret -- ce n'est pas le contenu principal de cet
# onglet.
#
# Accessible à tout membre connecté de l'organisation (pas réservé aux
# administrateurs -- contrairement au Cockpit, qui lui ne concerne que
# le développement du logiciel).
#
# Vue provisoire : le format définitif (colonnes affichées, filtres)
# sera revu une fois un exemple réel (Excel Prélèvement) reçu -- voir
# le chantier Cockpit correspondant.
# =============================================================

import pandas as pd
import streamlit as st

from trieur.db import (
    count_records,
    delete_record,
    get_org_master_columns,
    import_dataframe,
    list_dedup_alerts,
    list_records,
    resolve_dedup_alert,
    save_org_master_columns,
)
from views._auth import accessible_organizations, require_login
from views._ui import clear_stale_widgets, confirm_delete_button


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
    is_admin = ctx["profile"].get("is_super_admin")

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

    _render_alerts(client, org_id, user)
    _render_client_list(client, org_id)
    _render_import(client, org_id, user)
    _render_settings(client, org_id, is_admin)


def _render_alerts(client, org_id, user):
    alerts = list_dedup_alerts(client, org_id, status="pending")
    if not alerts:
        return

    st.warning(f"⚠️ {len(alerts)} alerte(s) de doublon IBAN en attente")
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
    st.divider()


_LIST_PAGE_SIZE = 300


def _render_client_list(client, org_id):
    total = count_records(client, org_id)
    st.markdown(f"##### Clients importés ({total})")

    if total == 0:
        st.caption("Aucun client importé pour l'instant dans cet environnement.")
        st.divider()
        return

    limit_key = f"db_list_limit_{org_id}"
    limit = st.session_state.get(limit_key, _LIST_PAGE_SIZE)

    search = st.text_input("🔎 Rechercher (nom, IBAN, email...)", key=f"search_{org_id}")
    records = list_records(client, org_id, limit=limit)
    master_cols = get_org_master_columns(client, org_id)

    rows = []
    for r in records:
        data = r["data"] or {}
        if search:
            haystack = " ".join(str(v) for v in data.values()).lower()
            if search.lower() not in haystack:
                continue
        batch = r.get("import_batches") or {}
        # Colonnes de l'organisation d'abord, dans l'ordre defini dans les
        # reglages -- puis toute colonne presente dans la ligne mais pas
        # (encore) declaree, pour ne jamais masquer de donnee.
        row = {"_id": r["id"]}
        for col in master_cols:
            row[col] = data.get(col)
        for key, value in data.items():
            if key not in master_cols:
                row[key] = value
        row["Fichier source"] = batch.get("source_filename")
        row["Importé le"] = batch.get("imported_at")
        rows.append(row)

    if not rows:
        st.caption("Aucun résultat pour cette recherche.")
        st.divider()
        return

    # Colonnes connues sur ce lot charge (pas seulement apres recherche/
    # filtre, pour que la liste de colonnes ne varie pas silencieusement
    # quand on tape dans la recherche).
    all_cols = []
    for row in rows:
        for c in row.keys():
            if c != "_id" and c not in all_cols:
                all_cols.append(c)

    with st.expander("🔎 Filtres par colonne"):
        st.caption("Chaque filtre garde les lignes qui CONTIENNENT le texte tapé (insensible à la casse). Combinés entre eux.")
        col_filters = {}
        filt_cols = st.columns(2)
        for i, col in enumerate(all_cols):
            with filt_cols[i % 2]:
                val = st.text_input(col, key=f"colfilter_{org_id}_{col}", placeholder="contient...")
                if val.strip():
                    col_filters[col] = val.strip().lower()

    if col_filters:
        rows = [
            r for r in rows
            if all(col_filters[c] in str(r.get(c) or "").lower() for c in col_filters)
        ]

    if not rows:
        st.caption("Aucun résultat pour ces filtres.")
        st.divider()
        return

    # Colonnes affichees : preference de session (pas encore persistee entre
    # connexions -- voir "vues enregistrees", chantier suivant). Sanitize
    # d'abord une selection perimee (colonne qui n'existe plus dans ce lot)
    # pour ne jamais faire planter le multiselect.
    visible_key = f"db_visible_cols_{org_id}"
    if visible_key in st.session_state:
        st.session_state[visible_key] = [c for c in st.session_state[visible_key] if c in all_cols]
    visible_cols = st.multiselect(
        "Colonnes affichées",
        options=all_cols,
        default=all_cols,
        key=visible_key,
    )
    if not visible_cols:
        st.warning("⚠️ Aucune colonne sélectionnée : toutes affichées par défaut.")
        visible_cols = all_cols

    df = pd.DataFrame(rows)
    row_ids = list(df["_id"])
    st.caption(
        f"{len(rows)} résultat(s) affiché(s) sur {len(records)} chargé(s) "
        f"({total} au total dans l'environnement). Clique un en-tête de "
        "colonne pour trier ; coche des lignes pour les supprimer ensemble."
    )
    selection_key = f"db_table_select_{org_id}"
    event = st.dataframe(
        df[visible_cols],
        use_container_width=True,
        height=300,
        hide_index=True,
        key=selection_key,
        on_select="rerun",
        selection_mode="multi-row",
    )
    selected_rows = (getattr(event, "selection", None) or {}).get("rows", [])

    if selected_rows:
        selected_ids = [row_ids[i] for i in selected_rows]
        st.write(f"**{len(selected_ids)} ligne(s) sélectionnée(s).**")
        if confirm_delete_button(f"🗑️ Supprimer la sélection ({len(selected_ids)})", key=f"bulk_delete_{org_id}"):
            for rid in selected_ids:
                delete_record(client, rid)
            st.success(f"{len(selected_ids)} client(s) supprimé(s).")
            clear_stale_widgets(f"_confirm_pending_bulk_delete_{org_id}")
            st.rerun()

    if len(records) == limit and len(records) < total:
        remaining = total - len(records)
        if st.button(f"⬇️ Charger {min(_LIST_PAGE_SIZE, remaining)} client(s) de plus (sur {remaining} restants)", key=f"loadmore_{org_id}"):
            st.session_state[limit_key] = limit + _LIST_PAGE_SIZE
            st.rerun()

    st.divider()


def _render_import(client, org_id, user):
    st.markdown("##### Importer un fichier dans la base (avec vérification IBAN)")
    st.caption(
        "Chaque ligne est comparée à TOUT l'historique déjà en base pour cet "
        "environnement (pas juste ce fichier) — un même IBAN déjà vu, même "
        "sous un autre nom, déclenche une alerte au lieu d'être importé en "
        "double silencieusement."
    )

    uploaded = st.file_uploader("Fichier CSV ou Excel", type=["csv", "xlsx"], key=f"upload_{org_id}")
    if uploaded is None:
        return

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
        progress = st.progress(0.0)
        n_imported, n_alerts = import_dataframe(
            client, org_id, uploaded.name, user.id, df,
            iban_col=iban_col if iban_col != "(aucune)" else None,
            on_progress=lambda done, total: progress.progress(done / max(total, 1)),
        )
        st.success(f"{n_imported} lignes importées, {n_alerts} alerte(s) de doublon IBAN créée(s).")
        st.rerun()


def _render_settings(client, org_id, is_admin):
    with st.expander("⚙️ Réglages de l'environnement (colonnes)"):
        cols = list(get_org_master_columns(client, org_id))

        if not is_admin:
            st.caption("Colonnes de cet environnement, modifiables par un administrateur uniquement.")
            for c in cols:
                st.write(f"• {c}")
            return

        st.caption(
            "Crée, renomme, réordonne ou supprime les colonnes de cet "
            "environnement. Les clients déjà importés ne sont pas modifiés — "
            "seuls l'affichage et le prochain import s'adaptent."
        )

        for i, col_name in enumerate(cols):
            c_name, c_up, c_down, c_del = st.columns([6, 1, 1, 1])
            with c_name:
                new_name = st.text_input(
                    "Nom", value=col_name, key=f"colname_{org_id}_{i}", label_visibility="collapsed"
                )
                if new_name.strip() and new_name.strip() != col_name:
                    cols[i] = new_name.strip()
                    save_org_master_columns(client, org_id, cols)
                    st.rerun()
            with c_up:
                if i > 0 and st.button("⬆️", key=f"up_{org_id}_{i}"):
                    cols[i - 1], cols[i] = cols[i], cols[i - 1]
                    save_org_master_columns(client, org_id, cols)
                    clear_stale_widgets(f"colname_{org_id}_")
                    st.rerun()
            with c_down:
                if i < len(cols) - 1 and st.button("⬇️", key=f"down_{org_id}_{i}"):
                    cols[i + 1], cols[i] = cols[i], cols[i + 1]
                    save_org_master_columns(client, org_id, cols)
                    clear_stale_widgets(f"colname_{org_id}_")
                    st.rerun()
            with c_del:
                if st.button("🗑️", key=f"del_{org_id}_{i}"):
                    cols.pop(i)
                    save_org_master_columns(client, org_id, cols)
                    clear_stale_widgets(f"colname_{org_id}_")
                    st.rerun()

        st.divider()
        new_col = st.text_input("Nouvelle colonne", key=f"newcol_{org_id}")
        if st.button("➕ Ajouter une colonne", key=f"addcol_{org_id}"):
            name = new_col.strip()
            if not name:
                st.error("Donne un nom à la nouvelle colonne.")
            elif name in cols:
                st.error("Cette colonne existe déjà.")
            else:
                cols.append(name)
                save_org_master_columns(client, org_id, cols)
                st.rerun()
