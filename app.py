# =============================================================
# Trieur de Fichiers Leads
# VERSION 4.0
#
# Changements de cette version :
#   [7] Menus de mapping ALIGNES au-dessus de chaque colonne + texte toujours
#       lisible en entier : l'assignation est affichee en grille (lots de
#       colonnes), chaque menu ayant directement en dessous l'apercu de SA
#       colonne. Plus de menus ecrases quand il y a beaucoup de colonnes.
#   [10] Design epure facon Apple : CSS global sobre (typographie systeme,
#       coins arrondis, ombres discretes, accent bleu, plus d'air).
#
# Versions precedentes :
#   [5] Filtres PRE-ENREGISTRES (onglet Filtrage) : nommer / appliquer /
#       renommer / supprimer, persistance dans saved_filters.json.
#   [4] Google Sheets ACCELERE : classeur entier en UNE requete (export xlsx),
#       repli CSV si echec. + bouton "Vider le cache" (garde la base).
#
# [REORG] Le code est reparti en modules (aucun changement de comportement) :
#           trieur/matching.py     -> normalisation, detection telephone,
#                                      deduction d'en-tetes, auto-assignation
#           trieur/filters.py      -> code postal / departements
#           trieur/io_excel.py     -> lecture Excel / Google Sheets
#           trieur/export.py       -> export CSV / Excel + nom de fichier
#           trieur/persistence.py  -> colonnes maitres + filtres enregistres
#         app.py ne contient plus que l'interface Streamlit (les 4 onglets).
#         Toutes les fonctions restent accessibles via `app.<fonction>`.
#
# Historique fonctionnel (inchange) :
#   [1] Detection telephone MOBILE / FIXE par le CONTENU (prefixes FR)
#   [2] Deduction des noms de colonnes quand la ligne d'en-tete est ABSENTE
#   [3] Exclusion de fichiers / onglets a l'import
#   [6] Colonnes maitres PERSISTANTES (survivent au rechargement)
#   [8] Limite d'upload portee a 500 Mo (voir .streamlit/config.toml)
#   [9] Nom du fichier final personnalisable avant export (CSV / Excel)
#   [PERF 1.1] Detection telephone echantillonnee (cout constant)
#   [PERF 1.2] Fin des rechargements inutiles (cache par signature)
# =============================================================

import streamlit as st

from trieur.matching import (
    DEFAULT_MASTER_COLUMNS,
    SYNONYMES,
    normalize_text,
    normalize_column_name,
    clean_phone,
    phone_kind,
    detect_phone_column_kind,
    looks_like_header,
    infer_column_names,
    apply_header_inference_excel,
    auto_assign_columns_fast,
    find_best_master_col,
    auto_assign_single_sheet,
)
from trieur.filters import normalize_cp, cp_matches_prefix
from trieur.io_excel import (
    read_excel_all_sheets_from_file,
    read_google_sheets_all_sheets,
    is_google_sheet_url,
)
from trieur.export import export_csv_safe, export_excel_safe, sanitize_filename
from trieur.persistence import (
    MASTER_CONFIG_PATH,
    load_master_columns,
    save_master_columns,
    load_saved_filters,
    save_saved_filters,
)

# Reexports pour compatibilite (import pandas conserve pour la construction
# de la base fusionnee dans l'interface ci-dessous).
import io
import pandas as pd

st.set_page_config(page_title="Trieur de Fichiers Leads", layout="wide")

APP_VERSION = "4.0"

# -------------------------------------------------------------
# [10] DESIGN EPURE FACON APPLE (CSS global, purement cosmetique)
# N'affecte aucun comportement ; se contente d'affiner l'apparence.
# -------------------------------------------------------------
st.markdown(
    """
    <style>
      :root { --accent: #0071e3; }

      html, body, [class*="css"], .stApp {
          font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text",
                       "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
          -webkit-font-smoothing: antialiased;
      }

      /* Titres : plus fins, mieux espaces */
      h1, h2, h3 { letter-spacing: -0.02em; font-weight: 600; }
      .block-container { padding-top: 2.2rem; max-width: 1300px; }

      /* Boutons : coins arrondis, transition douce */
      .stButton > button, .stDownloadButton > button {
          border-radius: 10px;
          border: 1px solid rgba(0,0,0,0.08);
          padding: 0.45rem 1.0rem;
          font-weight: 500;
          transition: all 0.15s ease;
      }
      .stButton > button:hover, .stDownloadButton > button:hover {
          border-color: var(--accent);
          color: var(--accent);
      }
      /* Bouton principal : bleu plein facon Apple */
      .stButton > button[kind="primary"] {
          background: var(--accent);
          border: none;
          box-shadow: 0 1px 3px rgba(0,113,227,0.30);
      }

      /* Champs et menus : coins arrondis */
      .stSelectbox div[data-baseweb="select"] > div,
      .stTextInput input, .stTextArea textarea {
          border-radius: 10px;
      }

      /* Onglets : plus d'air, soulignement accent */
      .stTabs [data-baseweb="tab-list"] { gap: 0.4rem; }
      .stTabs [data-baseweb="tab"] {
          border-radius: 10px 10px 0 0;
          padding: 0.4rem 1rem;
      }

      /* Tableaux et cartes : coins arrondis, ombre discrete */
      [data-testid="stDataFrame"] {
          border-radius: 12px;
          box-shadow: 0 1px 4px rgba(0,0,0,0.06);
      }
      [data-testid="stExpander"] {
          border-radius: 12px;
          border: 1px solid rgba(0,0,0,0.07);
      }

      /* [7] Nom de colonne source : toujours affiche en ENTIER, jamais tronque */
      .src-col-name {
          font-weight: 600;
          font-size: 0.86rem;
          line-height: 1.2;
          white-space: normal;
          overflow-wrap: anywhere;
          word-break: break-word;
          min-height: 2.4em;
          margin-bottom: 0.25rem;
          color: #1d1d1f;
      }
    </style>
    """,
    unsafe_allow_html=True,
)


# -------------------------------------------------------------
# INITIALISATION SESSION
# -------------------------------------------------------------
if "master_columns" not in st.session_state:
    st.session_state.master_columns = load_master_columns()
if "all_sheets" not in st.session_state:
    st.session_state.all_sheets = {}
if "sheet_mappings" not in st.session_state:
    st.session_state.sheet_mappings = {}
if "final_df" not in st.session_state:
    st.session_state.final_df = None
if "filtered_df" not in st.session_state:
    st.session_state.filtered_df = None
if "export_mode" not in st.session_state:
    st.session_state.export_mode = "fusionné"
if "export_name_base" not in st.session_state:
    st.session_state.export_name_base = ""
if "auto_assign_triggered" not in st.session_state:
    st.session_state.auto_assign_triggered = {}
# [3] Onglets exclus par l'utilisateur (cles "fichier :: onglet")
if "excluded_sheets" not in st.session_state:
    st.session_state.excluded_sheets = set()
# [2] Onglets dont l'en-tete a ete deduite (pour prevenir l'utilisateur)
if "inferred_header_sheets" not in st.session_state:
    st.session_state.inferred_header_sheets = []
# [5] Filtres pre-enregistres (charges depuis saved_filters.json)
if "saved_filters" not in st.session_state:
    st.session_state.saved_filters = load_saved_filters()


st.title("Trieur de Fichiers Leads")
st.caption(f"Import Excel ou Google Sheets → mapping colonnes → aperçu → filtrage → export · v{APP_VERSION}")

tab1, tab2, tab3, tab4 = st.tabs(["1. Colonnes maitres", "2. Import et Mapping", "3. Filtrage & Dedup", "4. Export"])

with tab1:
    st.subheader("Gerer vos colonnes maitres")
    st.write("Ajoutez, supprimez ou modifiez vos colonnes maitres ci-dessous, une par ligne. "
             "La liste est **conservee** apres rechargement de la page.")
    cols_text = st.text_area(
        "Colonnes maitres",
        value="\n".join(st.session_state.master_columns),
        height=250,
        key="master_cols_input"
    )

    col_save, col_reset = st.columns([1, 1])
    with col_save:
        if st.button("💾 Enregistrer la liste des colonnes maitres", type="primary"):
            new_list = [c.strip() for c in cols_text.split("\n") if c.strip()]
            # dedoublonnage en gardant l'ordre
            seen = set()
            deduped = []
            for c in new_list:
                key = c.lower()
                if key not in seen:
                    seen.add(key)
                    deduped.append(c)
            if deduped:
                st.session_state.master_columns = deduped
                ok = save_master_columns(deduped)
                if ok:
                    st.success(f"{len(deduped)} colonnes maitres enregistrees et conservees.")
                else:
                    st.warning(f"{len(deduped)} colonnes prises en compte pour la session "
                               "(sauvegarde disque indisponible sur cet hebergement).")
            else:
                st.error("❌ Veuillez entrer au moins une colonne maître.")

    with col_reset:
        if st.button("↩️ Reinitialiser (liste par defaut)"):
            st.session_state.master_columns = DEFAULT_MASTER_COLUMNS.copy()
            save_master_columns(DEFAULT_MASTER_COLUMNS.copy())
            st.success("Liste reinitialisee aux colonnes par defaut.")
            st.rerun()

    st.caption("ℹ️ Astuce : les colonnes **TELEPHONE MOBILE** et **TELEPHONE FIXE** "
               "sont detectees automatiquement d'apres le contenu (prefixes 06/07 = mobile, "
               "01-05/08/09 = fixe), meme si l'en-tete est absente ou trompeuse.")

with tab2:
    st.subheader("Importer vos fichiers Excel ou Google Sheets")
    files = st.file_uploader("Deposez un ou plusieurs fichiers Excel", type=["xlsx", "xls"], accept_multiple_files=True)
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
        for f_idx, f in enumerate(files):
            base_pct = int((f_idx / max(total_files, 1)) * 80)
            update_progress(progress_bar, base_pct, f"Lecture du fichier {f_idx+1}/{total_files} : {f.name}")
            try:
                sheets = read_excel_all_sheets_from_file(f, f.name)
                if not sheets:
                    st.error(f"❌ Aucun onglet lisible dans {f.name}")
                    continue

                # [2] Onglets sans ligne d'en-tete : relecture + noms deduits
                sheets, inferred = apply_header_inference_excel(sheets, f)
                inferred_this_load.extend(f"{f.name} :: {n}" for n in inferred)

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
                        f"Traitement de l'onglet {s_idx+1}/{total_sheet_items} de {f.name}"
                    )

                    if df is None or len(df) == 0:
                        st.warning(f"⚠️ {f.name} :: {sheet_name} est vide, ignoré.")
                        continue

                    key = f.name + " :: " + sheet_name
                    df = df.copy()
                    df["__source_file__"] = f.name
                    df["__source_sheet__"] = sheet_name
                    all_sheets[key] = df

            except Exception as e:
                st.error(f"❌ Erreur lecture {f.name}: {str(e)}")

        update_progress(progress_bar, 80, "Lecture Excel terminée. Finalisation...")

    if need_reload and google_url.strip() and is_google_sheet_url(google_url):
        if progress_bar is None:
            progress_bar = start_progress("Chargement Google Sheets... 0%")

        update_progress(progress_bar, 85 if files else 10, "Récupération des onglets Google Sheets...")
        sheets, inferred = read_google_sheets_all_sheets(google_url)
        inferred_this_load.extend(f"Google Sheets :: {n}" for n in inferred)
        if sheets:
            sheet_items = list(sheets.items())
            total_sheet_items = len(sheet_items)
            for s_idx, (sheet_name, df) in enumerate(sheet_items):
                start_pct = 85 if files else 10
                end_pct = 98
                pct = start_pct + int(((s_idx + 1) / max(total_sheet_items, 1)) * (end_pct - start_pct))
                update_progress(progress_bar, pct, f"Traitement Google Sheet {s_idx+1}/{total_sheet_items}")
                if len(df) > 0:
                    key = "Google Sheets :: " + sheet_name
                    df = df.copy()
                    df["__source_file__"] = "Google Sheets"
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

        for sheet_key, sheet_df in active_sheets.items():
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

            st.write("**Assignez chaque colonne : le menu est directement au-dessus de l'apercu de sa colonne.**")

            preview_df = sheet_df.head(5).copy()

            current_mapping = st.session_state.sheet_mappings[sheet_key]

            updated_mapping = {}

            # [7] Grille par lots : menu + apercu de CHAQUE colonne alignes.
            # On limite a 4 colonnes par rangee pour que le nom de colonne et
            # l'option choisie restent lisibles en entier meme sur des fichiers
            # a beaucoup de colonnes.
            PER_ROW = 4
            for start in range(0, len(real_columns), PER_ROW):
                chunk = real_columns[start:start + PER_ROW]
                cells = st.columns(len(chunk))
                for i, src_col in enumerate(chunk):
                    with cells[i]:
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

                        # Nom de la colonne source, affiche EN ENTIER (CSS anti-troncature)
                        st.markdown(f"<div class='src-col-name'>{src_col}</div>", unsafe_allow_html=True)

                        choice = st.selectbox(
                            src_col,
                            options=available_options,
                            index=idx_val,
                            key=widget_key,
                            label_visibility="collapsed",
                        )
                        updated_mapping[src_col] = choice
                        if choice != "(non assigne)":
                            any_assigned = True

                        # Apercu de CETTE colonne, aligne juste en dessous du menu
                        st.dataframe(
                            preview_df[[src_col]],
                            width="stretch",
                            height=180,
                            hide_index=True,
                        )

            st.session_state.sheet_mappings[sheet_key] = updated_mapping
            st.markdown("---")

        if not any_assigned:
            st.warning("⚠️ Veuillez assigner au moins une colonne maître avant de construire la base.")
        else:
            if st.button("✅ Construire la base de travail fusionnee", type="primary"):
                rows = []
                total_merged = 0

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
                        elif not src_cols_for_master:
                            sub[master_col] = None
                        else:
                            combined = sheet_df[src_cols_for_master[0]].copy()
                            for extra_col in src_cols_for_master[1:]:
                                is_empty = combined.isna() | (combined.astype(str).str.strip() == "")
                                combined = combined.where(~is_empty, sheet_df[extra_col])
                            sub[master_col] = combined
                    rows.append(sub)
                    total_merged += len(sub)

                if not rows:
                    st.error("❌ Aucun onglet avec assignation trouvé.")
                else:
                    final_df = pd.concat(rows, ignore_index=True)
                    final_df = final_df.dropna(how="all")

                    if len(final_df) == 0:
                        st.error("❌ La base fusionnée est vide après nettoyage.")
                    else:
                        st.session_state.final_df = final_df
                        st.success(f"✅ Base construite : {len(final_df)} lignes fusionnées.")
                        st.dataframe(final_df.head(50), width="stretch")
    else:
        st.info("ℹ️ Importe un fichier Excel ou colle une URL Google Sheets pour continuer.")

with tab3:
    st.subheader("Filtrer la base de travail")
    if st.session_state.final_df is None:
        st.info("ℹ️ Importez et mappez des fichiers dans l'onglet precedent avant de filtrer.")
    else:
        df = st.session_state.final_df.copy()
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
            if dep_input.strip():
                prefixes = set(p.strip().zfill(2) for p in dep_input.split(",") if p.strip())
                mask = df["CP"].apply(lambda v: cp_matches_prefix(v, prefixes) if pd.notna(v) else False)
                filtered_df = df[mask]
        elif filter_col != "(aucun filtre)":
            unique_vals = sorted([v for v in df[filter_col].dropna().unique()])
            # Securite : ne garder en memoire que des valeurs qui existent
            # encore pour cette colonne (evite un plantage du multiselect).
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
        remaining_duplicates = filtered_df.duplicated().sum()

        st.write(f"Resultat filtre : **{remaining_lines}** lignes | **{remaining_duplicates}** doublons conserves | **{total_lines}** lignes importees au total")
        st.dataframe(filtered_df.head(50), width="stretch")

        dup_check_col = st.selectbox("Colonne pour detecter les doublons (ex: TELEPHONE MOBILE)", options=["(aucune)"] + st.session_state.master_columns)
        if dup_check_col != "(aucune)":
            dup_count = filtered_df[dup_check_col].duplicated(keep=False).sum()
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
                if st.button("💾 Enregistrer", key="tab3_save_filter", width="stretch"):
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
                    if st.button("Appliquer", key=f"tab3_apply_{i}", width="stretch"):
                        st.session_state["_apply_filter"] = f
                        st.rerun()
                with c3:
                    if st.button("Renommer", key=f"tab3_ren_{i}", width="stretch"):
                        if rn.strip():
                            st.session_state.saved_filters[i]["name"] = rn.strip()
                            save_saved_filters(st.session_state.saved_filters)
                            st.rerun()
                with c4:
                    if st.button("Supprimer", key=f"tab3_del_{i}", width="stretch"):
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

with tab4:
    st.subheader("Exporter le resultat filtre")
    if st.session_state.filtered_df is None:
        st.info("ℹ️ Appliquez un filtre dans l'onglet precedent avant d'exporter.")
    else:
        export_df = st.session_state.filtered_df
        if len(export_df) == 0:
            st.error("❌ Impossible d'exporter : aucune donnée à exporter après filtrage.")
        else:
            st.write(f"{len(export_df)} lignes pretes a l'export.")

            # [9] Nom du fichier personnalisable
            raw_name = st.text_input(
                "Nom du fichier (sans extension)",
                value=st.session_state.export_name_base or "export_leads",
                key="export_name_input"
            )
            st.session_state.export_name_base = raw_name
            clean_name = sanitize_filename(raw_name)
            st.caption(f"Fichiers generes : **{clean_name}.csv** / **{clean_name}.xlsx**")

            col1, col2 = st.columns(2)

            with col1:
                st.markdown("**Export CSV**")
                csv_bytes = export_csv_safe(export_df)
                if csv_bytes:
                    st.download_button(
                        label="💾 Telecharger CSV",
                        data=csv_bytes,
                        file_name=f"{clean_name}.csv",
                        mime="text/csv",
                        key="dl_csv"
                    )

            with col2:
                st.markdown("**Export Excel**")
                buffer = export_excel_safe(export_df)
                if buffer:
                    st.download_button(
                        label="💾 Telecharger Excel",
                        data=buffer,
                        file_name=f"{clean_name}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="dl_xlsx"
                    )

            st.markdown("---")
            st.info("ℹ️ Les fichiers sont encodés en UTF-8.")
