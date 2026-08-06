"""Onglet 3 : filtrage multi-criteres de la base fusionnee, revue des
doublons groupe par groupe, et filtres pre-enregistres."""
import traceback
import uuid

import streamlit as st

from trieur.filters import (
    apply_filter_groups,
    dedupe_dataframe,
    dedupe_dataframe_manual,
    describe_filter_groups,
    duplicate_groups,
    most_complete_row_index,
)
from trieur.persistence import save_saved_filters

# Au-dela de ce nombre de GROUPES de doublons, la revue manuelle groupe par
# groupe (aperçu + choix de la ligne a garder) devient impraticable -> on
# repasse automatiquement sur une regle globale (premiere/plus complete).
DEDUP_GROUP_THRESHOLD = 50


def _render_value_picker(df, column, key_prefix):
    """Widget de choix de valeurs adapte a `column` (departements pour CP,
    texte libre au-dela de 1000 valeurs distinctes, multiselect sinon).
    Renvoie (kind, values) pour CE critere."""
    if column == "CP":
        dep_input = st.text_input(
            "Departements (ex: 02,33,77)",
            key=f"{key_prefix}_dep",
            label_visibility="collapsed",
            placeholder="Departements, ex: 02,33,77",
        )
        values = [p.strip().zfill(2) for p in dep_input.split(",") if p.strip()]
        return "departements", values

    n_unique = int(df[column].nunique(dropna=True)) if column in df.columns else 0
    if n_unique > 1000:
        # [PERF] Une colonne a des milliers de valeurs distinctes (NOM, EMAIL...)
        # -> un menu deroulant deviendrait ingerable et lent. Au-dela d'un
        # seuil, on bascule sur un filtre TEXTE.
        txt = st.text_input(
            f"Valeur(s) exacte(s) pour {column} (separees par ;)",
            key=f"{key_prefix}_txt",
            label_visibility="collapsed",
            placeholder=f"Valeur(s) pour {column}, separees par ;",
        )
        values = [v.strip() for v in txt.split(";") if v.strip()]
        return "valeurs", values

    unique_vals = sorted([v for v in df[column].dropna().unique()]) if column in df.columns else []
    vals_key = f"{key_prefix}_vals"
    # Securite : ne garder que des valeurs encore presentes (evite un
    # plantage du multiselect si la base a change entre-temps).
    if vals_key in st.session_state:
        st.session_state[vals_key] = [v for v in st.session_state[vals_key] if v in unique_vals]
    values = st.multiselect(
        f"Valeurs pour {column}",
        options=unique_vals,
        key=vals_key,
        label_visibility="collapsed",
        placeholder=f"Valeurs pour {column}",
    )
    return "valeurs", values


def _render_criterion(df, cid):
    """Affiche UNE ligne de critere (colonne + valeurs + suppression).
    Renvoie (criterion_dict, remove_clicked)."""
    col1, col2, col3 = st.columns([2, 4, 0.6])
    with col1:
        column = st.selectbox(
            "Colonne", options=st.session_state.master_columns,
            key=f"fc_col_{cid}", label_visibility="collapsed",
        )
    with col2:
        kind, values = _render_value_picker(df, column, key_prefix=f"fc_{cid}")
    with col3:
        remove = st.button("🗑️", key=f"fc_rm_{cid}", help="Retirer ce critere")
    return {"column": column, "kind": kind, "values": values}, remove


def _forget_criterion(cid):
    for suffix in ("_dep", "_txt", "_vals"):
        st.session_state.pop(f"fc_{cid}{suffix}", None)
    st.session_state.pop(f"fc_col_{cid}", None)


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

            # -------------------------------------------------------------
            # [13] FILTRE MULTI-CRITERES : plusieurs GROUPES combines en OU,
            # chaque groupe pouvant contenir plusieurs criteres combines en ET.
            # Ex : [CP dept 34] OU [CP dept 71 ET VILLE = Lyon].
            # -------------------------------------------------------------
            if "_filter_group_ids" not in st.session_state:
                st.session_state["_filter_group_ids"] = [[str(uuid.uuid4())]]

            # Application d'un filtre enregistre : on genere de nouveaux ids et on
            # pre-positionne les widgets AVANT de les afficher (meme logique que
            # les autres "pending" de ce projet), le bouton "Appliquer" ayant
            # declenche un rerun.
            pending_groups = st.session_state.pop("_apply_filter_groups", None)
            if pending_groups is not None:
                new_group_ids = []
                for group in pending_groups:
                    ids_for_group = []
                    for crit in group:
                        cid = str(uuid.uuid4())
                        ids_for_group.append(cid)
                        column = crit.get("column")
                        st.session_state[f"fc_col_{cid}"] = (
                            column if column in st.session_state.master_columns
                            else st.session_state.master_columns[0]
                        )
                        values = crit.get("values") or []
                        if crit.get("kind") == "departements":
                            st.session_state[f"fc_{cid}_dep"] = ",".join(values)
                        else:
                            # on pre-seed les deux widgets possibles (texte ou
                            # multiselect) ; seul celui reellement affiche compte.
                            st.session_state[f"fc_{cid}_txt"] = ";".join(map(str, values))
                            st.session_state[f"fc_{cid}_vals"] = list(values)
                    if ids_for_group:
                        new_group_ids.append(ids_for_group)
                st.session_state["_filter_group_ids"] = new_group_ids or [[str(uuid.uuid4())]]

            st.markdown("**Filtrer par un ou plusieurs criteres**")
            st.caption("Plusieurs groupes = **OU** entre eux ; plusieurs criteres dans un "
                       "groupe = **ET**. Ex : tout le 34, plus le 71 seulement pour Lyon.")

            group_ids = st.session_state["_filter_group_ids"]
            all_groups = []
            for gi, crit_ids in enumerate(group_ids):
                if gi > 0:
                    st.markdown("<div style='text-align:center; font-weight:600; "
                               "color:#888; margin:4px 0;'>OU</div>", unsafe_allow_html=True)
                with st.container(border=True):
                    group_criteria = []
                    crit_ids_to_remove = []
                    for cid in crit_ids:
                        crit, remove = _render_criterion(df, cid)
                        group_criteria.append(crit)
                        if remove:
                            crit_ids_to_remove.append(cid)

                    add_col, _sp = st.columns([1, 3])
                    with add_col:
                        if st.button("➕ Critere (ET)", key=f"fc_addcrit_{gi}"):
                            crit_ids.append(str(uuid.uuid4()))
                            st.rerun()

                    if crit_ids_to_remove:
                        # [FIX] st.rerun() arrete l'execution IMMEDIATEMENT : le nettoyage
                        # d'un groupe devenu vide doit se faire ICI, pas apres la boucle
                        # (ce code-la ne serait jamais atteint -> le groupe vide restait
                        # visible indefiniment, meme apres suppression de son dernier critere).
                        for cid in crit_ids_to_remove:
                            crit_ids.remove(cid)
                            _forget_criterion(cid)
                        if not crit_ids and len(group_ids) > 1:
                            group_ids.pop(gi)
                        st.rerun()

                    all_groups.append(group_criteria)

            if st.button("➕ Ajouter un groupe (OU)"):
                group_ids.append([str(uuid.uuid4())])
                st.rerun()

            filtered_df = apply_filter_groups(df, all_groups)
            complete_groups = [g for g in all_groups if g and all(c.get("values") for c in g)]

            # -------------------------------------------------------------
            # [5] FILTRES PRE-ENREGISTRES -- juste sous le filtre, pour etre
            # visible immediatement (pas besoin de scroller).
            # -------------------------------------------------------------
            with st.expander("💾 Filtres pre-enregistres", expanded=bool(st.session_state.saved_filters)):
                if complete_groups:
                    st.caption(f"Filtre actuel : **{describe_filter_groups(complete_groups)}**")
                else:
                    st.caption("Choisis au moins une colonne et des valeurs ci-dessus pour "
                               "pouvoir enregistrer un filtre.")

                col_name, col_btn = st.columns([3, 1])
                with col_name:
                    new_filter_name = st.text_input(
                        "Nom du filtre", key="tab3_new_filter_name", label_visibility="collapsed",
                        placeholder="Nom du filtre (ex: Sud-Ouest)",
                    )
                with col_btn:
                    if st.button("💾 Enregistrer", key="tab3_save_filter", use_container_width=True):
                        nm = new_filter_name.strip()
                        if not complete_groups:
                            st.warning("⚠️ Aucun critere complet a enregistrer (choisis colonne + valeurs).")
                        elif not nm:
                            st.warning("⚠️ Donnez un nom au filtre.")
                        else:
                            new_filter = {"name": nm, "groups": complete_groups}
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
                    st.caption(f"**{f['name']}** — {describe_filter_groups(f['groups'])}")
                    c1, c2, c3, c4 = st.columns([4, 1.2, 1.2, 1.2])
                    with c1:
                        rn = st.text_input(
                            "nom", value=f["name"], key=f"tab3_rn_{i}", label_visibility="collapsed",
                        )
                    with c2:
                        if st.button("Appliquer", key=f"tab3_apply_{i}", use_container_width=True):
                            st.session_state["_apply_filter_groups"] = f["groups"]
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

            st.markdown("---")

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
        st.error("❌ Une erreur est survenue dans cet onglet. Copie-colle le detail ci-dessous pour diagnostic.")
        st.code(traceback.format_exc(), language="text")
