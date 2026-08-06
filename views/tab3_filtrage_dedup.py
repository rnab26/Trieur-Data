"""Onglet 3 : filtrage de la base fusionnee (par colonne / departement),
comptage de doublons, et filtres pre-enregistres."""
import traceback

import pandas as pd
import streamlit as st

from trieur.filters import cp_matches_prefix
from trieur.persistence import save_saved_filters


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

            remaining_lines = len(filtered_df)
            st.write(f"Resultat filtre : **{remaining_lines}** lignes conservees sur **{total_lines}** au total")
            st.dataframe(filtered_df.head(50), use_container_width=True)

            # [PERF] Le comptage des doublons scanne toute la base : on ne le fait
            # QUE sur demande (sinon il ralentirait chaque interaction).
            dup_check_col = st.selectbox("Colonne pour detecter les doublons (ex: TELEPHONE MOBILE)", options=["(aucune)"] + st.session_state.master_columns)
            if dup_check_col != "(aucune)" and dup_check_col in filtered_df.columns:
                if st.button(f"🔎 Compter les doublons sur '{dup_check_col}'", key="tab3_count_dupes"):
                    dup_count = int(filtered_df[dup_check_col].duplicated(keep=False).sum())
                    st.warning(f"{dup_count} lignes en doublon detectees sur la colonne '{dup_check_col}' (non supprimees automatiquement).")

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
