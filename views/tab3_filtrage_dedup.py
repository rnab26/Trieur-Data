"""Onglet 3 : filtrage de la base fusionnee (par colonne / departement),
comptage de doublons, et filtres pre-enregistres."""
import traceback

import pandas as pd
import streamlit as st

from trieur.filters import (
    cp_matches_prefix,
    dedupe_dataframe,
    dedupe_dataframe_manual,
    duplicate_groups,
    most_complete_row_index,
)
from trieur.persistence import save_saved_filters

# Au-dela de ce nombre de GROUPES de doublons, la revue manuelle groupe par
# groupe (aperçu + choix de la ligne a garder) devient impraticable -> on
# repasse automatiquement sur une regle globale (premiere/plus complete).
DEDUP_GROUP_THRESHOLD = 50


def render():
    try:
        st.subheader("Filtrer la base de travail")
        if st.session_state.final_df is None:
            st.info("ℹ️ Importez et mappez des fichiers dans l'onglet precedent avant de filtrer.")
        else:
            # [PERF] PAS de .copy() ici : sur des millions de lignes, recopier la
            # base entiere a chaque clic est le principal facteur de lenteur. On
            # lit la base telle quelle ; le filtrage cree une nouvelle vue.
            df = st.session_state.final_df
            total_lines = len(df)
            st.write(f"Base actuelle : **{total_lines}** lignes importees")

            # [5] Application d'un filtre enregistre : on positionne les widgets
            # AVANT de les afficher (le bouton "Appliquer" a declenche un rerun).
            pending = st.session_state.pop("_apply_filter", None)
            if pending is not None:
                col = pending.get("column")
                if col in st.session_state.master_columns and col in df.columns:
                    st.session_state["tab3_filter_col"] = col
                    if pending.get("kind") == "departements":
                        st.session_state["tab3_dep_input"] = ",".join(pending.get("values", []))
                    else:
                        avail = sorted([v for v in df[col].dropna().unique()])
                        st.session_state["tab3_selected_vals"] = [
                            v for v in pending.get("values", []) if v in avail
                        ]
                else:
                    st.warning(f"⚠️ Le filtre vise la colonne '{col}', absente de la base actuelle.")

            filter_col = st.selectbox(
                "Filtrer par colonne",
                options=["(aucun filtre)"] + st.session_state.master_columns,
                key="tab3_filter_col",
            )
            filtered_df = df
            dep_input = ""
            selected_vals = []

            if filter_col == "CP":
                dep_input = st.text_input(
                    "Departements a filtrer (separes par des virgules, ex: 02,33,77)",
                    key="tab3_dep_input",
                )
                if dep_input.strip() and "CP" in df.columns:
                    prefixes = set(p.strip().zfill(2) for p in dep_input.split(",") if p.strip())
                    mask = df["CP"].apply(lambda v: cp_matches_prefix(v, prefixes) if pd.notna(v) else False)
                    filtered_df = df[mask]
            elif filter_col != "(aucun filtre)":
                # [PERF] Une colonne a des milliers de valeurs distinctes (NOM, EMAIL...)
                # -> un menu deroulant deviendrait ingerable et lent. Au-dela d'un
                # seuil, on bascule sur un filtre TEXTE.
                n_unique = int(df[filter_col].nunique(dropna=True))
                if n_unique > 1000:
                    st.caption(f"ℹ️ {n_unique} valeurs distinctes : trop pour une liste. "
                               "Saisis la ou les valeurs exactes a conserver (separees par ;).")
                    txt = st.text_input(
                        f"Valeur(s) exacte(s) pour {filter_col}",
                        key="tab3_text_vals",
                    )
                    if txt.strip():
                        selected_vals = [v.strip() for v in txt.split(";") if v.strip()]
                        filtered_df = df[df[filter_col].isin(selected_vals)]
                else:
                    unique_vals = sorted([v for v in df[filter_col].dropna().unique()])
                    # Securite : ne garder que des valeurs encore presentes (evite un
                    # plantage du multiselect).
                    if "tab3_selected_vals" in st.session_state:
                        st.session_state["tab3_selected_vals"] = [
                            v for v in st.session_state["tab3_selected_vals"] if v in unique_vals
                        ]
                    selected_vals = st.multiselect(
                        "Valeurs a conserver pour " + filter_col,
                        options=unique_vals,
                        key="tab3_selected_vals",
                    )
                    if selected_vals:
                        filtered_df = df[df[filter_col].isin(selected_vals)]

            # [5bis] Suppression de doublons active : elle doit survivre aux
            # reruns suivants (changement de filtre, etc.), sinon l'export
            # redeviendrait dedupe des le prochain clic. On la reapplique
            # donc a chaque passage tant qu'elle n'est pas annulee.
            active_dedup = st.session_state.get("_dedup_active")
            dedup_removed = None
            if active_dedup and active_dedup["column"] in filtered_df.columns:
                before_dedup = len(filtered_df)
                if active_dedup.get("mode") == "manual":
                    filtered_df = dedupe_dataframe_manual(
                        filtered_df, active_dedup["column"], set(active_dedup.get("keep_indices", []))
                    )
                else:
                    filtered_df = dedupe_dataframe(filtered_df, active_dedup["column"], active_dedup.get("keep", "first"))
                dedup_removed = before_dedup - len(filtered_df)

            remaining_lines = len(filtered_df)
            st.write(f"Resultat filtre : **{remaining_lines}** lignes conservees sur **{total_lines}** au total")

            if dedup_removed is not None:
                col_msg, col_undo = st.columns([4, 1])
                with col_msg:
                    st.success(f"✅ Doublons supprimes sur '{active_dedup['column']}' "
                               f"({dedup_removed} ligne(s) retiree(s), {remaining_lines} restantes).")
                with col_undo:
                    if st.button("↩️ Annuler", key="tab3_undo_dedup", use_container_width=True):
                        st.session_state.pop("_dedup_active", None)
                        st.rerun()

            st.dataframe(filtered_df.head(50), use_container_width=True)

            # [PERF] L'analyse des doublons scanne toute la base : on ne le fait
            # QUE sur demande (sinon elle ralentirait chaque interaction).
            dup_check_col = st.selectbox(
                "Colonne pour detecter les doublons (ex: TELEPHONE MOBILE)",
                options=["(aucune)"] + st.session_state.master_columns,
                key="tab3_dup_col",
            )
            if dup_check_col != "(aucune)" and dup_check_col in filtered_df.columns:
                if st.button(f"🔎 Analyser les doublons sur '{dup_check_col}'", key="tab3_analyze_dupes"):
                    st.session_state["_dedup_analysis"] = {
                        "column": dup_check_col,
                        "groups": duplicate_groups(filtered_df, dup_check_col),
                    }
                    for _k in [k for k in list(st.session_state.keys())
                               if isinstance(k, str) and k.startswith("tab3_group_choice_")]:
                        st.session_state.pop(_k, None)

                analysis = st.session_state.get("_dedup_analysis")
                if analysis and analysis["column"] == dup_check_col:
                    groups = analysis["groups"]
                    n_groups = len(groups)

                    if n_groups == 0:
                        st.info(f"ℹ️ Aucun doublon detecte sur '{dup_check_col}'.")
                    elif n_groups <= DEDUP_GROUP_THRESHOLD:
                        dup_rows = sum(len(idx) for _, idx in groups)
                        st.write(f"**{n_groups} groupe(s) de doublons** ({dup_rows} lignes) — "
                                 "la ligne la plus complete est pre-selectionnee ; corrige si besoin.")
                        for gi, (value, idx_list) in enumerate(groups):
                            choice_key = f"tab3_group_choice_{gi}"
                            if choice_key not in st.session_state:
                                st.session_state[choice_key] = most_complete_row_index(filtered_df, idx_list)

                            st.caption(f"**{value}** — {len(idx_list)} lignes")
                            st.dataframe(filtered_df.loc[idx_list], use_container_width=True)

                            def _row_label(i, _df=filtered_df):
                                row = _df.loc[i]
                                preview = " | ".join(str(v) for v in row.dropna().astype(str).head(3))
                                return f"Ligne {i} : {preview}"

                            st.selectbox(
                                "Ligne a conserver",
                                options=idx_list,
                                format_func=_row_label,
                                key=choice_key,
                                label_visibility="collapsed",
                            )

                        if st.button(f"✅ Appliquer la selection ({n_groups} groupe(s))",
                                     key="tab3_apply_manual_dedup", type="primary"):
                            keep_indices = [st.session_state[f"tab3_group_choice_{gi}"] for gi in range(n_groups)]
                            st.session_state["_dedup_active"] = {
                                "column": dup_check_col, "mode": "manual", "keep_indices": keep_indices,
                            }
                            st.session_state.pop("_dedup_analysis", None)
                            st.rerun()
                    else:
                        st.warning(
                            f"⚠️ {n_groups} groupes de doublons detectes : au-dela de la limite de "
                            f"{DEDUP_GROUP_THRESHOLD} groupes pour la revue manuelle. Choisis une regle "
                            "automatique appliquee a tous les groupes :"
                        )
                        keep_label = st.radio(
                            "En cas de doublon, quelle ligne garder ?",
                            options=["La premiere ligne importee", "La ligne la plus complete (le moins de champs vides)"],
                            key="tab3_dedup_keep_rule",
                            horizontal=True,
                        )
                        keep_rule = "complete" if keep_label.startswith("La ligne la plus") else "first"
                        if st.button(f"🗑️ Supprimer les doublons sur '{dup_check_col}'", key="tab3_remove_dupes"):
                            st.session_state["_dedup_active"] = {
                                "column": dup_check_col, "mode": "rule", "keep": keep_rule,
                            }
                            st.session_state.pop("_dedup_analysis", None)
                            st.rerun()

            st.session_state.filtered_df = filtered_df

            # -------------------------------------------------------------
            # [5] FILTRES PRE-ENREGISTRES
            # -------------------------------------------------------------
            st.markdown("---")
            with st.expander("💾 Filtres pre-enregistres", expanded=bool(st.session_state.saved_filters)):
                # Peut-on enregistrer le filtre actuellement affiche ?
                if filter_col == "CP" and dep_input.strip():
                    current_values = [p.strip().zfill(2) for p in dep_input.split(",") if p.strip()]
                    current_kind = "departements"
                elif filter_col not in ("CP", "(aucun filtre)") and selected_vals:
                    current_values = list(selected_vals)
                    current_kind = "valeurs"
                else:
                    current_values = []
                    current_kind = None

                if current_kind:
                    st.caption(f"Filtre actuel : **{filter_col}** = {', '.join(map(str, current_values))}")
                else:
                    st.caption("Choisissez une colonne et des valeurs ci-dessus pour pouvoir enregistrer un filtre.")

                col_name, col_btn = st.columns([3, 1])
                with col_name:
                    new_filter_name = st.text_input(
                        "Nom du filtre", key="tab3_new_filter_name", label_visibility="collapsed",
                        placeholder="Nom du filtre (ex: Sud-Ouest)",
                    )
                with col_btn:
                    if st.button("💾 Enregistrer", key="tab3_save_filter", use_container_width=True):
                        nm = new_filter_name.strip()
                        if not current_kind:
                            st.warning("⚠️ Aucun filtre a enregistrer (choisissez colonne + valeurs).")
                        elif not nm:
                            st.warning("⚠️ Donnez un nom au filtre.")
                        else:
                            new_filter = {
                                "name": nm, "column": filter_col,
                                "kind": current_kind, "values": current_values,
                            }
                            # remplace un filtre du meme nom, sinon ajoute
                            replaced = False
                            for i, f in enumerate(st.session_state.saved_filters):
                                if f["name"].lower() == nm.lower():
                                    st.session_state.saved_filters[i] = new_filter
                                    replaced = True
                                    break
                            if not replaced:
                                st.session_state.saved_filters.append(new_filter)
                            save_saved_filters(st.session_state.saved_filters)
                            st.success(f"Filtre « {nm} » enregistre.")
                            st.rerun()

                if st.session_state.saved_filters:
                    st.markdown("**Filtres enregistres :**")
                for i, f in enumerate(st.session_state.saved_filters):
                    st.caption(f"**{f['name']}** — {f['column']} : {', '.join(map(str, f['values'])) or '(vide)'}")
                    c1, c2, c3, c4 = st.columns([4, 1.2, 1.2, 1.2])
                    with c1:
                        rn = st.text_input(
                            "nom", value=f["name"], key=f"tab3_rn_{i}", label_visibility="collapsed",
                        )
                    with c2:
                        if st.button("Appliquer", key=f"tab3_apply_{i}", use_container_width=True):
                            st.session_state["_apply_filter"] = f
                            st.rerun()
                    with c3:
                        if st.button("Renommer", key=f"tab3_ren_{i}", use_container_width=True):
                            if rn.strip():
                                st.session_state.saved_filters[i]["name"] = rn.strip()
                                save_saved_filters(st.session_state.saved_filters)
                                st.rerun()
                    with c4:
                        if st.button("Supprimer", key=f"tab3_del_{i}", use_container_width=True):
                            st.session_state.saved_filters.pop(i)
                            save_saved_filters(st.session_state.saved_filters)
                            st.rerun()

            # -------------------------------------------------------------
            # [4] NETTOYAGE MEMOIRE (honnete : pas de tache de fond automatique)
            # -------------------------------------------------------------
            with st.expander("🧹 Memoire / cache"):
                st.caption(
                    "Libere les fichiers importes gardes en memoire (utile apres avoir "
                    "construit la base). La base construite et le resultat filtre sont "
                    "CONSERVES. Streamlit n'offre pas de nettoyage automatique en tache "
                    "de fond : ce bouton est le moyen fiable de recuperer de la memoire."
                )
                if st.button("🧹 Vider le cache des fichiers importes", key="tab3_clear_cache"):
                    try:
                        st.cache_data.clear()
                    except Exception:
                        pass
                    for _k in ["all_sheets", "sheet_mappings", "loaded_signature",
                               "excluded_sheets", "inferred_header_sheets"]:
                        st.session_state.pop(_k, None)
                    for _k in [key for key in list(st.session_state.keys())
                               if isinstance(key, str) and (
                                   key.startswith("map_") or key.startswith("inc_sheet_")
                                   or key.startswith("inc_file_"))]:
                        st.session_state.pop(_k, None)
                    st.success("Cache vide. La base construite est conservee.")
                    st.rerun()

    except Exception:
        st.error("\u274c Une erreur est survenue dans cet onglet. Copie-colle le detail ci-dessous pour diagnostic.")
        st.code(traceback.format_exc(), language="text")
