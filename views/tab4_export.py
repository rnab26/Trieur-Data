"""Onglet 4 : ordre/selection des colonnes (glisser-deposer) et export
CSV/Excel de la base filtree."""
import traceback

import streamlit as st
from streamlit_sortables import sort_items

from trieur.export import export_csv_safe, export_excel_safe, sanitize_filename


def render():
    try:
        st.subheader("Exporter le resultat filtre")
        if st.session_state.filtered_df is None:
            st.info("ℹ️ Appliquez un filtre dans l'onglet precedent avant d'exporter.")
        else:
            export_df = st.session_state.filtered_df
            if len(export_df) == 0:
                st.error("❌ Impossible d'exporter : aucune donnée à exporter après filtrage.")
            else:
                st.write(f"{len(export_df)} lignes pretes a l'export.")

                # [10] Ordre et selection des colonnes a l'export, sans toucher
                # au mapping : glisser-deposer pour reordonner, glisser vers
                # "Colonnes exclues" pour retirer une colonne (et inversement
                # pour la remettre).
                current_cols = list(export_df.columns)
                included_key = "export_sort_included"
                excluded_key = "export_sort_excluded"
                if (
                    included_key not in st.session_state
                    or excluded_key not in st.session_state
                    or set(st.session_state[included_key] + st.session_state[excluded_key]) != set(current_cols)
                ):
                    st.session_state[included_key] = current_cols
                    st.session_state[excluded_key] = []

                with st.expander("🔀 Ordre et selection des colonnes a l'export", expanded=False):
                    st.caption(
                        "Glisse une colonne (icone ⠿) pour changer son ordre, ou "
                        "fais-la glisser vers « Colonnes exclues » pour la retirer "
                        "de l'export (et inversement pour la remettre)."
                    )
                    sorted_result = sort_items(
                        [
                            {"header": "Colonnes incluses (ordre d'export)", "items": st.session_state[included_key]},
                            {"header": "Colonnes exclues", "items": st.session_state[excluded_key]},
                        ],
                        multi_containers=True,
                        direction="vertical",
                        custom_style="""
                            .sortable-item::before { content: "⠿  "; opacity: 0.55; }
                        """,
                        key="export_col_sortable",
                    )
                    st.session_state[included_key] = sorted_result[0]["items"]
                    st.session_state[excluded_key] = sorted_result[1]["items"]

                selected_col_order = st.session_state[included_key]
                if selected_col_order:
                    export_df = export_df[selected_col_order]
                else:
                    st.warning("⚠️ Aucune colonne sélectionnée : toutes les colonnes sont incluses par défaut.")

                # [9] Nom du fichier personnalisable
                raw_name = st.text_input(
                    "Nom du fichier (sans extension)",
                    value=st.session_state.export_name_base or "export_leads",
                    key="export_name_input"
                )
                st.session_state.export_name_base = raw_name
                clean_name = sanitize_filename(raw_name)
                st.caption(f"Fichiers generes : **{clean_name}.csv** / **{clean_name}.xlsx**")

                # [PERF] On ne genere PLUS l'export a chaque affichage (l'Excel de
                # plusieurs millions de lignes prend des minutes). On genere
                # UNIQUEMENT au clic, et on garde le resultat en cache tant que la
                # base filtree n'a pas change (signature = nb lignes + colonnes).
                EXCEL_MAX_ROWS = 1_048_576
                n_rows = len(export_df)
                export_sig = (n_rows, tuple(map(str, export_df.columns)))

                col1, col2 = st.columns(2)

                with col1:
                    st.markdown("**Export CSV** — recommandé (rapide, sans limite)")
                    if st.button("⚙️ Préparer le CSV", key="gen_csv", type="primary"):
                        with st.spinner("Génération du CSV..."):
                            st.session_state["_export_csv"] = (export_sig, export_csv_safe(export_df))
                    cached = st.session_state.get("_export_csv")
                    if cached and cached[0] == export_sig and cached[1]:
                        st.download_button(
                            label="💾 Telecharger CSV",
                            data=cached[1],
                            file_name=f"{clean_name}.csv",
                            mime="text/csv",
                            key="dl_csv",
                        )

                with col2:
                    st.markdown("**Export Excel**")
                    if n_rows > EXCEL_MAX_ROWS:
                        st.info(f"ℹ️ {n_rows:,} lignes : au-delà de la limite d'Excel "
                                f"(~{EXCEL_MAX_ROWS:,} par onglet). Utilise l'export CSV.")
                    else:
                        if n_rows > 100_000:
                            st.caption("⚠️ Excel est lent au-delà de ~100 000 lignes "
                                       "(~1 min/million). Le CSV est conseillé.")
                        if st.button("⚙️ Préparer l'Excel", key="gen_xlsx"):
                            with st.spinner("Génération de l'Excel (peut être long)..."):
                                buf = export_excel_safe(export_df)
                                st.session_state["_export_xlsx"] = (
                                    export_sig, buf.getvalue() if buf else None
                                )
                        cachedx = st.session_state.get("_export_xlsx")
                        if cachedx and cachedx[0] == export_sig and cachedx[1]:
                            st.download_button(
                                label="💾 Telecharger Excel",
                                data=cachedx[1],
                                file_name=f"{clean_name}.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                key="dl_xlsx",
                            )

                st.markdown("---")
                st.info("ℹ️ Les fichiers sont encodés en UTF-8. Pour les très gros volumes, préfère le CSV.")
    except Exception:
        st.error("\u274c Une erreur est survenue dans cet onglet. Copie-colle le detail ci-dessous pour diagnostic.")
        st.code(traceback.format_exc(), language="text")
