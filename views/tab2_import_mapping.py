"""Onglet 2 : import des fichiers (Excel/CSV/PDF/Google Sheets), mapping des
colonnes vers les colonnes maitres, et construction de la base fusionnee."""
import gc
import html
import traceback

import pandas as pd
import streamlit as st

from trieur.matching import (
    apply_header_inference_excel,
    auto_assign_single_sheet,
    clean_iban,
    detect_iban_column,
    is_iban_master,
)
from trieur.io_excel import (
    read_excel_all_sheets_from_file,
    read_csv_file,
    read_google_sheets_all_sheets,
    is_google_sheet_url,
)
from trieur.io_pdf import read_pdf_sepa


def render():
    try:
        st.subheader("Importer vos fichiers Excel, CSV ou Google Sheets")
        files = st.file_uploader(
            "Deposez un ou plusieurs fichiers Excel, CSV ou PDF",
            type=["xlsx", "xls", "csv", "pdf"], accept_multiple_files=True,
        )
        st.caption("💡 Pour de tres gros volumes (plusieurs millions de lignes), le "
                   "**CSV** est bien plus rapide et leger que le .xlsx.")
        google_url = st.text_input("Ou collez une URL Google Sheets publique (optionnel)")

        all_sheets = {}

        progress_placeholder = st.empty()
        progress_label = st.empty()
        progress_bar = None

        def start_progress(message):
            bar = progress_placeholder.progress(0)
            progress_label.info(message)
            return bar

        def update_progress(bar, pct, message=None):
            bar.progress(max(0, min(100, int(pct))))
            if message:
                progress_label.info(message)

        def end_progress(bar, message=None):
            bar.progress(100)
            if message:
                progress_label.success(message)
            progress_placeholder.empty()
            progress_label.empty()

        def _files_signature(_files, _gurl):
            """Empreinte de l'ensemble importe (nom+taille des fichiers + URL)."""
            sig = []
            for _f in _files or []:
                try:
                    sig.append((_f.name, int(_f.size)))
                except Exception:
                    sig.append((getattr(_f, "name", "?"), None))
            sig.append(("__google__", _gurl.strip() if _gurl else ""))
            return tuple(sig)

        has_input = bool(files) or bool(google_url.strip() and is_google_sheet_url(google_url))
        current_sig = _files_signature(files, google_url)

        # [PERF] On ne (re)lit les fichiers QUE si l'ensemble importe a change.
        # Sinon on reutilise ce qui est deja en memoire : plus aucun rechargement
        # (ni barre de progression) lors des assignations manuelles.
        need_reload = has_input and (
            st.session_state.get("loaded_signature") != current_sig
            or not st.session_state.get("all_sheets")
        )
        if not need_reload:
            all_sheets = st.session_state.get("all_sheets", {})

        # [2] Onglets dont l'en-tete a du etre deduite pendant CE chargement
        inferred_this_load = []

        if need_reload and files:
            progress_bar = start_progress("Chargement des fichiers Excel... 0%")
            total_files = len(files)
            # [FIX doublons de nom] Deux fichiers deposes ensemble peuvent porter
            # EXACTEMENT le meme nom (ex: "export.csv" telecharge deux fois a des
            # dates differentes). Streamlit les distingue tres bien (2 entrees
            # dans l'uploader), mais notre cle interne all_sheets etait basee sur
            # f.name : le 2e fichier ecrasait silencieusement le 1er. On rend le
            # nom utilise pour la cle unique au sein de cet import (export.csv,
            # export (2).csv...) sans toucher au fichier lu ni a son nom affiche
            # dans le widget. On verifie l'unicite contre TOUS les noms deja
            # attribues (pas juste le compteur de f.name) pour ne jamais retomber
            # sur un nom deja pris par un vrai fichier "... (2).ext" du batch.
            used_display_names = set()
            for f_idx, f in enumerate(files):
                base_pct = int((f_idx / max(total_files, 1)) * 80)
                update_progress(progress_bar, base_pct, f"Lecture du fichier {f_idx+1}/{total_files} : {f.name}")

                stem, dot, ext = f.name.rpartition(".")
                display_name = f.name
                suffix_n = 2
                while display_name in used_display_names:
                    display_name = f"{stem} ({suffix_n}).{ext}" if dot else f"{f.name} ({suffix_n})"
                    suffix_n += 1
                used_display_names.add(display_name)

                try:
                    # [GROS FICHIERS] CSV lu directement (rapide/leger) ; sinon Excel.
                    if f.name.lower().endswith(".csv"):
                        sheets, inferred = read_csv_file(f, display_name)
                    elif f.name.lower().endswith(".pdf"):
                        # [PDF] Prélèvements SEPA -> une ligne par prélèvement
                        sheets, inferred = read_pdf_sepa(f, display_name)
                    else:
                        sheets = read_excel_all_sheets_from_file(f, display_name)
                        # [2] Onglets sans ligne d'en-tete : relecture + noms deduits
                        sheets, inferred = apply_header_inference_excel(sheets, f)

                    if not sheets:
                        st.error(f"❌ Aucun onglet lisible dans {display_name}")
                        continue

                    inferred_this_load.extend(f"{display_name} :: {n}" for n in inferred)

                    sheet_items = list(sheets.items())
                    total_sheet_items = len(sheet_items)

                    for s_idx, (sheet_name, df) in enumerate(sheet_items):
                        if total_sheet_items > 0:
                            step_within_file = int(((s_idx + 1) / total_sheet_items) * (80 / max(total_files, 1)))
                        else:
                            step_within_file = 0
                        update_progress(
                            progress_bar,
                            base_pct + step_within_file,
                            f"Traitement de l'onglet {s_idx+1}/{total_sheet_items} de {display_name}"
                        )

                        if df is None or len(df) == 0:
                            st.warning(f"⚠️ {display_name} :: {sheet_name} est vide, ignoré.")
                            continue

                        key = display_name + " :: " + sheet_name
                        # [MEM] pas de .copy() : le DataFrame vient d'etre lu et
                        # nous appartient, on le complete en place (evite de
                        # doubler la memoire sur les gros fichiers).
                        df["__source_file__"] = display_name
                        df["__source_sheet__"] = sheet_name
                        all_sheets[key] = df

                except Exception as e:
                    st.error(f"❌ Erreur lecture {display_name}: {str(e)}")

            update_progress(progress_bar, 80, "Lecture Excel terminée. Finalisation...")

        if need_reload and google_url.strip() and is_google_sheet_url(google_url):
            if progress_bar is None:
                progress_bar = start_progress("Chargement Google Sheets... 0%")

            update_progress(progress_bar, 85 if files else 10, "Récupération des onglets Google Sheets...")
            # read_google_sheets_all_sheets renvoie aussi le VRAI nom du classeur
            # Google (lu dans l'en-tete du telechargement) -> la colonne source
            # affiche le vrai nom du fichier, pas "Google Sheets".
            sheets, inferred, gs_name = read_google_sheets_all_sheets(google_url)
            inferred_this_load.extend(f"{gs_name} :: {n}" for n in inferred)
            if sheets:
                sheet_items = list(sheets.items())
                total_sheet_items = len(sheet_items)
                for s_idx, (sheet_name, df) in enumerate(sheet_items):
                    start_pct = 85 if files else 10
                    end_pct = 98
                    pct = start_pct + int(((s_idx + 1) / max(total_sheet_items, 1)) * (end_pct - start_pct))
                    update_progress(progress_bar, pct, f"Traitement Google Sheet {s_idx+1}/{total_sheet_items}")
                    if len(df) > 0:
                        key = gs_name + " :: " + sheet_name
                        # [MEM] pas de .copy() (voir import Excel ci-dessus)
                        df["__source_file__"] = gs_name
                        df["__source_sheet__"] = sheet_name
                        all_sheets[key] = df
                st.success(f"✅ Google Sheets importé avec {len(sheets)} onglet(s) détecté(s).")
            else:
                st.warning("⚠️ Impossible de lire le Google Sheets.")

        if progress_bar is not None:
            end_progress(progress_bar, "Chargement terminé à 100%")

        if need_reload:
            # Memoriser le resultat pour ne plus reparser aux prochains reruns
            st.session_state.all_sheets = all_sheets
            st.session_state.loaded_signature = current_sig

            # [2] Garder la liste des onglets corriges pour l'afficher a chaque rerun
            st.session_state.inferred_header_sheets = inferred_this_load

            # [3] Nouvel import = on repart avec tous les onglets inclus
            st.session_state.excluded_sheets = set()

            # Repartir sur des mappings propres pour ce nouvel ensemble
            st.session_state.sheet_mappings = {}
            for _k in list(st.session_state.keys()):
                if isinstance(_k, str) and (
                    _k.startswith("map_") or _k.startswith("inc_sheet_") or _k.startswith("inc_file_")
                ):
                    del st.session_state[_k]

            # [FIX 3 onglets] Auto-assignation de TOUS les onglets des l'import,
            # pour qu'aucun onglet ne reste vide et sans avoir a cliquer.
            for _sk, _sdf in all_sheets.items():
                _new_map, _, _ = auto_assign_single_sheet(_sk, _sdf, st.session_state.master_columns)
                st.session_state.sheet_mappings[_sk] = _new_map
                for _src, _master in _new_map.items():
                    st.session_state[f"map_{_sk}_{_src}"] = _master

        if all_sheets:
            # [2] Prevenir que des en-tetes ont ete deduites (persiste entre les reruns)
            if st.session_state.inferred_header_sheets:
                st.warning(
                    "⚠️ En-tetes absentes detectees et deduites pour : "
                    + ", ".join(f"**{n}**" for n in st.session_state.inferred_header_sheets)
                    + ". Les colonnes ont ete nommees d'apres leur contenu et aucune ligne "
                      "n'a ete perdue. Verifiez l'assignation ci-dessous."
                )

            # [3] Selection des fichiers / onglets a inclure
            with st.expander("🗂️ Choisir les fichiers et onglets a inclure", expanded=False):
                st.caption("Decochez ce que vous ne voulez pas traiter. "
                           "Aucun fichier n'est relu : le changement est immediat.")

                sheets_by_file = {}
                for k in all_sheets.keys():
                    fname = k.split(" :: ")[0]
                    sheets_by_file.setdefault(fname, []).append(k)

                for fname, keys in sheets_by_file.items():
                    file_included = all(k not in st.session_state.excluded_sheets for k in keys)
                    file_key = f"inc_file_{fname}"
                    prev_key = f"inc_file_prev_{fname}"

                    inc_file = st.checkbox(f"**{fname}** ({len(keys)} onglet(s))",
                                           value=file_included, key=file_key)

                    # Bascule au niveau FICHIER : on propage a tous ses onglets.
                    # On ne le fait qu'au moment ou l'utilisateur change la case,
                    # sinon on ecraserait ses choix onglet par onglet.
                    prev = st.session_state.get(prev_key)
                    if prev is not None and prev != inc_file:
                        for k in keys:
                            if inc_file:
                                st.session_state.excluded_sheets.discard(k)
                            else:
                                st.session_state.excluded_sheets.add(k)
                            st.session_state[f"inc_sheet_{k}"] = inc_file
                        st.session_state[prev_key] = inc_file
                        st.rerun()
                    st.session_state[prev_key] = inc_file

                    for k in keys:
                        sheet_name = k.split(" :: ", 1)[1] if " :: " in k else k
                        n_rows = len(all_sheets[k])
                        inc_sheet = st.checkbox(
                            f"　└ {sheet_name} — {n_rows} lignes",
                            value=(k not in st.session_state.excluded_sheets),
                            key=f"inc_sheet_{k}"
                        )
                        if inc_sheet:
                            st.session_state.excluded_sheets.discard(k)
                        else:
                            st.session_state.excluded_sheets.add(k)

            # Seuls les onglets coches sont mappes puis fusionnes
            active_sheets = {k: v for k, v in all_sheets.items()
                             if k not in st.session_state.excluded_sheets}

            total_files = len(set([k.split(" :: ")[0] for k in active_sheets.keys()]))
            total_sheets = len(all_sheets)
            n_active = len(active_sheets)
            n_excluded = total_sheets - n_active

            if n_excluded:
                st.success(f"✅ {total_sheets} onglet(s) détecté(s) — **{n_active} inclus**, "
                           f"{n_excluded} exclu(s) · {total_files} fichier(s) traité(s).")
            else:
                st.success(f"✅ {total_files} fichier(s) importés, {total_sheets} onglet(s) détecté(s) au total.")

            # [ALERTE] Prevenir seulement pour un volume vraiment eleve. Le compte
            # dispose de 2,7 Go de RAM ; mesure reelle : ~540 Mo pour 257 000
            # lignes. Le seuil est donc place haut (600 000 lignes) pour ne pas
            # alerter inutilement.
            total_rows_all = sum(len(v) for v in active_sheets.values())
            if total_rows_all > 600000:
                st.warning(
                    f"⚠️ Volume important : **{total_rows_all:,} lignes** au total. "
                    "Ton hébergement dispose de 2,7 Go de RAM ; à ce niveau le "
                    "traitement peut devenir lent ou instable. En cas de souci : "
                    "importe moins de fichiers/onglets à la fois, exclus les onglets "
                    "inutiles ci-dessous, ou découpe le fichier."
                )

            with st.expander("📋 Detail des onglets importes"):
                for k, df in all_sheets.items():
                    parts = k.split(" :: ")
                    filename = parts[0]
                    sheetname = parts[1] if len(parts) > 1 else "Unknown"
                    num_rows = len(df)
                    real_cols = [c for c in df.columns if c not in ["__source_file__", "__source_sheet__"]]
                    num_cols = len(real_cols)
                    num_dup = df.duplicated().sum()
                    flag = "" if k in active_sheets else " · ⛔ exclu"

                    st.write(f"**{filename}** → **{sheetname}** : {num_rows} lignes, {num_cols} colonnes, {num_dup} doublons{flag}")

            if not active_sheets:
                st.warning("⚠️ Tous les onglets sont exclus. Cochez-en au moins un pour continuer.")

            st.markdown("---")
            st.subheader("Assignation des colonnes")

            col_global_auto, col_space = st.columns([1, 3])
            with col_global_auto:
                if st.button("🚀 Auto-assigner TOUS les onglets", key="auto_all_sheets", type="primary"):
                    total_sheets_count = len(active_sheets)
                    for sheet_key, sheet_df in active_sheets.items():
                        new_mapping, matched_count, total_cols = auto_assign_single_sheet(
                            sheet_key, sheet_df, st.session_state.master_columns
                        )
                        st.session_state.sheet_mappings[sheet_key] = new_mapping
                        for src_col, master_col in new_mapping.items():
                            widget_key = f"map_{sheet_key}_{src_col}"
                            st.session_state[widget_key] = master_col

                    st.success(f"✅ Auto-assignation terminée pour {total_sheets_count} onglet(s).")
                    st.rerun()

            st.markdown("---")

            any_assigned = False

            for sheet_idx, (sheet_key, sheet_df) in enumerate(active_sheets.items()):
                st.markdown(f"### 📄 {sheet_key}")

                real_columns = [c for c in sheet_df.columns if c not in ["__source_file__", "__source_sheet__"]]
                num_rows = len(sheet_df)
                num_cols = len(real_columns)
                num_duplicates = sheet_df.duplicated().sum()

                st.write(f"**Résumé :** {num_rows} lignes | {num_cols} colonnes | {num_duplicates} doublons")

                if sheet_key not in st.session_state.sheet_mappings:
                    st.session_state.sheet_mappings[sheet_key] = {}

                col_auto, col_space = st.columns([1, 3])
                with col_auto:
                    if st.button(f"🚀 Auto", key=f"auto_{sheet_key}"):
                        new_mapping, matched_count, total_cols = auto_assign_single_sheet(
                            sheet_key, sheet_df, st.session_state.master_columns
                        )
                        st.session_state.sheet_mappings[sheet_key] = new_mapping
                        for src_col, master_col in new_mapping.items():
                            widget_key = f"map_{sheet_key}_{src_col}"
                            st.session_state[widget_key] = master_col
                        st.success(f"✅ {matched_count}/{total_cols} colonnes assignées")
                        st.rerun()

                st.write("**Colonne maître (menu) et aperçu des données forment un même tableau : chaque menu est aligné, à la même largeur, au-dessus de sa colonne.**")

                preview_df = sheet_df.head(6).copy()

                current_mapping = st.session_state.sheet_mappings[sheet_key]

                updated_mapping = {}

                # [7 - tableau aligne] Menus (ligne du haut) + apercu des donnees
                # rendus dans la MEME grille st.columns(n) -> memes largeurs, parfait
                # alignement vertical, comme des cellules empilees d'un seul tableau.
                # Le conteneur porte une cle pour cibler le CSS (fond accentue sur la
                # ligne des menus, cellules compactes en dessous).
                with st.container(key=f"maptbl-{sheet_idx}"):
                    # Ligne 1 : les menus des colonnes maitres (visuellement distincts)
                    menu_cols = st.columns(len(real_columns))
                    for idx, src_col in enumerate(real_columns):
                        with menu_cols[idx]:
                            current = current_mapping.get(src_col, "(non assigne)")
                            widget_key = f"map_{sheet_key}_{src_col}"

                            if widget_key in st.session_state:
                                current = st.session_state[widget_key]
                            else:
                                st.session_state[widget_key] = current

                            already_used_in_current = [updated_mapping.get(c, "") for c in real_columns if c != src_col and updated_mapping.get(c) != "(non assigne)"]
                            available_options = ["(non assigne)"] + [m for m in st.session_state.master_columns if m not in already_used_in_current]

                            if current not in available_options:
                                current = "(non assigne)"
                                st.session_state[widget_key] = current

                            try:
                                idx_val = available_options.index(current)
                            except ValueError:
                                idx_val = 0

                            choice = st.selectbox(
                                str(src_col),  # str() : evite le crash Cloud si l'en-tete est un nombre
                                options=available_options,
                                index=idx_val,
                                key=widget_key,
                                label_visibility="visible",
                            )
                            updated_mapping[src_col] = choice
                            if choice != "(non assigne)":
                                any_assigned = True

                    # Lignes suivantes : apercu des donnees, memes colonnes -> aligne
                    for _, prow in preview_df.iterrows():
                        data_cols = st.columns(len(real_columns))
                        for idx, src_col in enumerate(real_columns):
                            with data_cols[idx]:
                                v = prow[src_col]
                                txt = "" if pd.isna(v) else html.escape(str(v))
                                st.markdown(f"<div class='mapcell'>{txt}</div>", unsafe_allow_html=True)

                st.session_state.sheet_mappings[sheet_key] = updated_mapping
                st.markdown("---")

            if not any_assigned:
                st.warning("⚠️ Veuillez assigner au moins une colonne maître avant de construire la base.")
            else:
                if st.button("✅ Construire la base de travail fusionnee", type="primary"):
                    rows = []
                    total_merged = 0
                    # [4] Colonnes maitres reellement mappees sur AU MOINS un
                    # fichier fusionne : les autres (jamais assignees, donc
                    # vides sur toute la base) seront retirees de l'export final.
                    used_master_cols = set()

                    # [3] on ne fusionne QUE les onglets coches
                    for sheet_key, sheet_df in active_sheets.items():
                        source_file = sheet_df["__source_file__"].iloc[0] if len(sheet_df) > 0 else sheet_key
                        source_sheet = sheet_df["__source_sheet__"].iloc[0] if len(sheet_df) > 0 else "Unknown"
                        mapping = st.session_state.sheet_mappings.get(sheet_key, {})

                        assigned_cols = [m for m in mapping.values() if m != "(non assigne)"]
                        if not assigned_cols:
                            st.warning(f"⚠️ {sheet_key}: Aucune colonne assignée, ignoré.")
                            continue

                        sub = pd.DataFrame(index=sheet_df.index)
                        for master_col in st.session_state.master_columns:
                            src_cols_for_master = [s for s, m in mapping.items() if m == master_col and s in sheet_df.columns]
                            if master_col == "Source Data":
                                sub[master_col] = f"{source_file} ({source_sheet})"
                                used_master_cols.add(master_col)
                            elif not src_cols_for_master:
                                sub[master_col] = None
                            elif len(src_cols_for_master) == 1:
                                # [MEM] source unique : pas de .copy() (concat copiera)
                                sub[master_col] = sheet_df[src_cols_for_master[0]]
                                used_master_cols.add(master_col)
                            else:
                                combined = sheet_df[src_cols_for_master[0]].copy()
                                for extra_col in src_cols_for_master[1:]:
                                    is_empty = combined.isna() | (combined.astype(str).str.strip() == "")
                                    combined = combined.where(~is_empty, sheet_df[extra_col])
                                sub[master_col] = combined
                                used_master_cols.add(master_col)

                            # [1] IBAN / reference bancaire : plus d'espaces internes,
                            # quel que soit le fichier source (PDF, Excel, CSV...).
                            # Detection par le nom ET par le contenu (forme d'un IBAN) :
                            # le nom seul rate les colonnes maitres renommees ("Référence"
                            # au lieu de "Référence bancaire", "Compte"...).
                            if is_iban_master(master_col) or detect_iban_column(sub[master_col]):
                                sub[master_col] = sub[master_col].map(clean_iban)
                        rows.append(sub)
                        total_merged += len(sub)

                    if not rows:
                        st.error("❌ Aucun onglet avec assignation trouvé.")
                    else:
                        final_df = pd.concat(rows, ignore_index=True)
                        final_df = final_df.dropna(how="all")
                        # [4] Retire les colonnes maitres jamais assignees sur
                        # aucun fichier fusionne (colonnes "en brut" 100% vides).
                        final_df = final_df[[c for c in final_df.columns if c in used_master_cols]]
                        # [MEM] liberer les DataFrames intermediaires : sur un gros
                        # import ils doublent la memoire une fois la base construite.
                        del rows
                        gc.collect()

                        # [MEM] colonnes a faible cardinalite -> "category" : enorme
                        # economie sur des millions de lignes (ex: Source Data, qui
                        # repete le meme libelle, passe de ~29 Mo a ~1 Mo/million).
                        for _c in ("Source Data", "GENRE/CIVILITE", "VILLE"):
                            if _c in final_df.columns:
                                try:
                                    final_df[_c] = final_df[_c].astype("category")
                                except Exception:
                                    pass

                        if len(final_df) == 0:
                            st.error("❌ La base fusionnée est vide après nettoyage.")
                        else:
                            st.session_state.final_df = final_df
                            # invalider un eventuel export mis en cache (base changee)
                            for _k in ("_export_csv", "_export_xlsx"):
                                st.session_state.pop(_k, None)
                            st.success(f"✅ Base construite : {len(final_df)} lignes fusionnées.")
                            st.dataframe(final_df.head(50), use_container_width=True)
        else:
            st.info("ℹ️ Importe un fichier Excel ou colle une URL Google Sheets pour continuer.")

    except Exception:
        st.error("\u274c Une erreur est survenue dans cet onglet. Copie-colle le detail ci-dessous pour diagnostic.")
        st.code(traceback.format_exc(), language="text")
