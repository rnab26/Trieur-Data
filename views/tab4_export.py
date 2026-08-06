"""Onglet 4 : ordre/selection des colonnes (glisser-deposer) et export
CSV/Excel de la base filtree."""
import traceback

import streamlit as st
from streamlit_sortables import sort_items

from trieur.export import export_csv_safe, export_excel_safe, sanitize_filename
from trieur.persistence import save_export_presets


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

                # [11] Application d'un preset d'export : positionner AVANT le
                # widget sort_items (meme logique que le "pending filter" de
                # l'onglet Filtrage). Les colonnes du preset absentes de la base
                # actuelle sont ignorees ; les colonnes nouvelles (pas prevues par
                # le preset) sont ajoutees en fin de liste incluse, pour ne
                # jamais faire disparaitre une colonne silencieusement.
                pending_preset = st.session_state.pop("_apply_export_preset", None)
                if pending_preset is not None:
                    preset_included = [c for c in pending_preset.get("included", []) if c in current_cols]
                    preset_excluded = [c for c in pending_preset.get("excluded", []) if c in current_cols]
                    known = set(preset_included) | set(preset_excluded)
                    new_cols = [c for c in current_cols if c not in known]
                    missing = [c for c in pending_preset.get("included", []) + pending_preset.get("excluded", [])
                               if c not in current_cols]
                    st.session_state[included_key] = preset_included + new_cols
                    st.session_state[excluded_key] = preset_excluded
                    if missing:
                        st.warning(f"⚠️ Le preset « {pending_preset.get('name', '')} » référençait des "
                                   f"colonnes absentes de la base actuelle : {', '.join(missing)} (ignorées).")
                    if new_cols:
                        st.info("ℹ️ Colonnes non prévues par le preset, ajoutées en fin de liste incluse : "
                                + ", ".join(new_cols))

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

                # [11] Presets d'export : enregistrer/reappliquer l'ordre et la
                # selection de colonnes ci-dessus sous un nom, pour ne pas avoir
                # a refaire le glisser-deposer a chaque export similaire.
                with st.expander("💾 Presets d'export (ordre + colonnes)", expanded=False):
                    st.caption("Enregistre l'ordre et la selection de colonnes definis ci-dessus "
                               "sous un nom, pour les reappliquer en un clic la prochaine fois.")
                    col_pname, col_psave = st.columns([3, 1])
                    with col_pname:
                        new_preset_name = st.text_input(
                            "Nom du preset", key="tab4_new_preset_name", label_visibility="collapsed",
                            placeholder="Nom du preset (ex: Rapport banque)",
                        )
                    with col_psave:
                        if st.button("💾 Enregistrer", key="tab4_save_preset", use_container_width=True):
                            nm = new_preset_name.strip()
                            if not nm:
                                st.warning("⚠️ Donnez un nom au preset.")
                            else:
                                new_preset = {
                                    "name": nm,
                                    "included": list(st.session_state[included_key]),
                                    "excluded": list(st.session_state[excluded_key]),
                                }
                                replaced = False
                                for i, p in enumerate(st.session_state.export_presets):
                                    if p["name"].lower() == nm.lower():
                                        st.session_state.export_presets[i] = new_preset
                                        replaced = True
                                        break
                                if not replaced:
                                    st.session_state.export_presets.append(new_preset)
                                save_export_presets(st.session_state.export_presets)
                                st.success(f"Preset « {nm} » enregistré.")
                                st.rerun()

                    if st.session_state.export_presets:
                        st.markdown("**Presets enregistrés :**")
                    for i, p in enumerate(st.session_state.export_presets):
                        st.caption(f"**{p['name']}** — {len(p['included'])} colonne(s) incluse(s), "
                                   f"{len(p['excluded'])} exclue(s)")
                        pc1, pc2, pc3, pc4 = st.columns([4, 1.2, 1.2, 1.2])
                        with pc1:
                            rn = st.text_input(
                                "nom", value=p["name"], key=f"tab4_rn_{i}", label_visibility="collapsed",
                            )
                        with pc2:
                            if st.button("Appliquer", key=f"tab4_apply_{i}", use_container_width=True):
                                st.session_state["_apply_export_preset"] = p
                                st.rerun()
                        with pc3:
                            if st.button("Renommer", key=f"tab4_ren_{i}", use_container_width=True):
                                if rn.strip():
                                    st.session_state.export_presets[i]["name"] = rn.strip()
                                    save_export_presets(st.session_state.export_presets)
                                    st.rerun()
                        with pc4:
                            if st.button("Supprimer", key=f"tab4_del_{i}", use_container_width=True):
                                st.session_state.export_presets.pop(i)
                                save_export_presets(st.session_state.export_presets)
                                st.rerun()

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
