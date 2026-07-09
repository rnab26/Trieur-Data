import streamlit as st
import pandas as pd
import io
import hashlib
import unicodedata
import re
from difflib import SequenceMatcher

st.set_page_config(page_title="Trieur de Fichiers Leads", layout="wide")

DEFAULT_MASTER_COLUMNS = [
    "NOM",
    "PRENOM",
    "GENRE/CIVILITE",
    "VILLE",
    "CP",
    "ADRESSE",
    "TELEPHONE MOBILE",
    "TELEPHONE FIXE",
    "EMAIL",
    "DATE DE NAISSANCE",
    "Source Data",
]

SYNONYMES = {
    "NOM": ["nom", "lastname", "surname", "last_name", "family_name", "patronyme"],
    "PRENOM": ["prenom", "prénom", "firstname", "first_name", "given_name"],
    "GENRE/CIVILITE": ["genre", "civilite", "civilité", "sexe", "sex", "title", "salutation"],
    "VILLE": ["ville", "city", "commune", "locality"],
    "CP": ["cp", "codepostal", "code_postal", "postalcode", "zipcode", "zip", "postal"],
    "ADRESSE": ["adresse", "address", "rue", "street", "location"],
    "TELEPHONE MOBILE": ["telephoneportable", "portable", "mobile", "gsm", "cell", "cellphone", "phone_mobile"],
    "TELEPHONE FIXE": ["telephonefixe", "fixe", "phone", "homephone", "landline", "phone_fixe"],
    "EMAIL": ["email", "e-mail", "mail", "courriel", "e_mail"],
    "DATE DE NAISSANCE": ["datedenaissance", "date_naissance", "naissance", "dob", "birthdate", "birthday", "birth_date"],
    "Source Data": ["source", "fichier", "file", "origin"],
}

NON_ASSIGNE = "(non assigne)"
META_COLS = ["__source_file__", "__source_sheet__"]

for key, default in {
    "master_columns": DEFAULT_MASTER_COLUMNS.copy(),
    "all_sheets": {},
    "sheet_mappings": {},
    "final_df": None,
    "filtered_df": None,
    "auto_assign_done": False,
    "last_import_signature": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


def normalize_text(text):
    text = str(text).lower().strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[\s\-_/.]", "", text)
    text = re.sub(r"[^a-z0-9]", "", text)
    return text


def clean_df(df):
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    df = df.loc[:, ~df.columns.duplicated()]
    df = df.dropna(how="all")
    for col in df.columns:
        df[col] = df[col].astype(str).replace({"nan": None, "None": None, "": None})
    return df


def find_best_master_col(src_col, master_cols):
    src_norm = normalize_text(src_col)
    if not src_norm:
        return None

    for master in master_cols:
        if normalize_text(master) == src_norm:
            return master

    for master in master_cols:
        for syn in SYNONYMES.get(master, []):
            if normalize_text(syn) == src_norm:
                return master

    best_master = None
    best_score = 0.72
    for master in master_cols:
        score = SequenceMatcher(None, src_norm, normalize_text(master)).ratio()
        if score > best_score:
            best_score = score
            best_master = master
    return best_master


def build_import_signature(files, google_url):
    parts = []
    for f in files or []:
        payload = f.getvalue()
        parts.append(f"{f.name}:{len(payload)}:{hashlib.md5(payload).hexdigest()}")
    parts.append((google_url or "").strip())
    return "|".join(parts)


def parse_excel_file(file_bytes):
    xls = pd.ExcelFile(io.BytesIO(file_bytes), engine="openpyxl")
    result = {}
    for sheet_name in xls.sheet_names:
        try:
            preview = xls.parse(sheet_name=sheet_name, dtype=str)
            preview = clean_df(preview)
            if len(preview) > 0 and len(preview.columns) > 0:
                result[sheet_name] = preview
        except Exception:
            continue
    return result


def parse_google_sheets(url):
    try:
        if "/edit" in url:
            url = url.split("/edit")[0]
        if url.endswith("/"):
            url = url[:-1]
        if "/d/" not in url:
            return {}
        sheet_id = url.split("/d/")[1].split("/")[0]
        result = {}
        for gid in range(50):
            try:
                csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
                df = pd.read_csv(csv_url, dtype=str)
                df = clean_df(df)
                if len(df) > 0 and len(df.columns) > 0:
                    result[f"Sheet{gid + 1}" if gid > 0 else "Sheet1"] = df
            except Exception:
                continue
        return result
    except Exception:
        return {}


def import_all_sources(files, google_url, status_box, progress_bar):
    all_sheets = {}
    tasks = []
    for f in files or []:
        tasks.append(("excel", f.name, f.getvalue()))
    if google_url.strip():
        tasks.append(("gsheet", "Google Sheets", google_url.strip()))

    total = max(len(tasks), 1)
    for idx, task in enumerate(tasks, start=1):
        pct = int(((idx - 1) / total) * 100)
        progress_bar.progress(pct)

        if task[0] == "excel":
            _, filename, file_bytes = task
            status_box.info(f"Import en cours : {filename}")
            sheets = parse_excel_file(file_bytes)
            for sheet_name, df in sheets.items():
                key = f"{filename} :: {sheet_name}"
                tmp = df.copy()
                tmp["__source_file__"] = filename
                tmp["__source_sheet__"] = sheet_name
                all_sheets[key] = tmp
        else:
            _, _, url = task
            status_box.info("Import du Google Sheets en cours...")
            sheets = parse_google_sheets(url)
            for sheet_name, df in sheets.items():
                key = f"Google Sheets :: {sheet_name}"
                tmp = df.copy()
                tmp["__source_file__"] = "Google Sheets"
                tmp["__source_sheet__"] = sheet_name
                all_sheets[key] = tmp

        progress_bar.progress(int((idx / total) * 100))

    return all_sheets


def auto_assign_all_sheets(all_sheets, master_columns, status_box, progress_bar):
    new_mappings = {}
    total_sheets = max(len(all_sheets), 1)

    for idx, (sheet_key, sheet_df) in enumerate(all_sheets.items(), start=1):
        status_box.info(f"Auto assignation : {sheet_key}")
        real_columns = [c for c in sheet_df.columns if c not in META_COLS]
        mapping = {}
        for src_col in real_columns:
            best_master = find_best_master_col(src_col, master_columns)
            mapping[src_col] = best_master if best_master else NON_ASSIGNE
        new_mappings[sheet_key] = mapping
        progress_bar.progress(int((idx / total_sheets) * 100))

    return new_mappings


def merge_all_sheets(all_sheets, sheet_mappings, master_columns, status_box, progress_bar):
    rows = []
    total = max(len(all_sheets), 1)

    for idx, (sheet_key, sheet_df) in enumerate(all_sheets.items(), start=1):
        status_box.info(f"Fusion : {sheet_key}")
        mapping = sheet_mappings.get(sheet_key, {})
        assigned_cols = [m for m in mapping.values() if m != NON_ASSIGNE]
        if not assigned_cols:
            progress_bar.progress(int((idx / total) * 100))
            continue

        source_file = sheet_df["__source_file__"].iloc[0] if len(sheet_df) > 0 else sheet_key
        source_sheet = sheet_df["__source_sheet__"].iloc[0] if len(sheet_df) > 0 else "Unknown"
        sub = pd.DataFrame(index=sheet_df.index)

        for master_col in master_columns:
            src_cols = [s for s, m in mapping.items() if m == master_col and s in sheet_df.columns]
            if master_col == "Source Data":
                sub[master_col] = f"{source_file} ({source_sheet})"
            elif not src_cols:
                sub[master_col] = None
            else:
                combined = sheet_df[src_cols[0]].copy()
                for extra_col in src_cols[1:]:
                    is_empty = combined.isna() | (combined.astype(str).str.strip() == "")
                    combined = combined.where(~is_empty, sheet_df[extra_col])
                sub[master_col] = combined

        rows.append(sub)
        progress_bar.progress(int((idx / total) * 100))

    if not rows:
        return None

    final_df = pd.concat(rows, ignore_index=True)
    final_df = final_df.dropna(how="all")
    return final_df if len(final_df) > 0 else None


def export_csv_safe(df, progress_bar=None):
    try:
        if progress_bar is not None:
            progress_bar.progress(20)
        df_clean = df.copy()
        for col in df_clean.columns:
            df_clean[col] = df_clean[col].astype(str)
        if progress_bar is not None:
            progress_bar.progress(70)
        csv_bytes = df_clean.to_csv(index=False, sep=",").encode("utf-8-sig")
        if progress_bar is not None:
            progress_bar.progress(100)
        return csv_bytes
    except Exception as e:
        st.error(f"❌ Erreur CSV: {str(e)}")
        return None


def export_excel_safe(df, progress_bar=None):
    try:
        if progress_bar is not None:
            progress_bar.progress(15)
        buffer = io.BytesIO()
        try:
            with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
                df.to_excel(writer, index=False, sheet_name="Leads")
        except Exception:
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                df.to_excel(writer, index=False, sheet_name="Leads")
        if progress_bar is not None:
            progress_bar.progress(100)
        buffer.seek(0)
        return buffer
    except Exception as e:
        st.error(f"❌ Erreur Excel: {str(e)}")
        return None


def normalize_cp(value):
    s = str(value).strip().split(".")[0]
    if not s.isdigit():
        return None
    if len(s) == 4:
        s = "0" + s
    if len(s) != 5:
        return None
    return s


def cp_matches_prefix(cp_value, prefixes):
    cp5 = normalize_cp(cp_value)
    return cp5 is not None and cp5[:2] in prefixes


def is_google_sheet_url(text):
    return "docs.google.com/spreadsheets" in str(text).strip().lower()


st.title("Trieur de Fichiers Leads")
st.caption("Version optimisée : import manuel, auto assign global, progression visuelle, base finale et export")

status_box = st.empty()
progress_box = st.empty()

st.header("1. Import des fichiers")
files = st.file_uploader(
    "Déposez un ou plusieurs fichiers Excel",
    type=["xlsx", "xls"],
    accept_multiple_files=True,
)
google_url = st.text_input("Ou collez une URL Google Sheets publique (optionnel)")

col_imp1, col_imp2 = st.columns([2, 5])
with col_imp1:
    if st.button("📥 Lancer l'import", type="primary"):
        if not files and not (google_url.strip() and is_google_sheet_url(google_url)):
            st.warning("Ajoutez au moins un fichier Excel ou une URL Google Sheets.")
        else:
            signature = build_import_signature(files, google_url)
            progress = progress_box.progress(0)
            imported = import_all_sources(files, google_url, status_box, progress)
            progress.empty()
            if imported:
                st.session_state.all_sheets = imported
                st.session_state.sheet_mappings = {}
                st.session_state.final_df = None
                st.session_state.filtered_df = None
                st.session_state.auto_assign_done = False
                st.session_state.last_import_signature = signature
                status_box.success(f"Import terminé : {len(imported)} onglet(s) chargé(s).")
            else:
                status_box.error("Aucun onglet valide n'a pu être importé.")
with col_imp2:
    st.caption("Le chargement est maintenant déclenché par bouton pour éviter les reruns inutiles à chaque interaction.")

all_sheets = st.session_state.all_sheets

if all_sheets:
    with st.expander("📋 Détail des onglets importés", expanded=False):
        for k, df in all_sheets.items():
            real_cols = [c for c in df.columns if c not in META_COLS]
            st.write(f"**{k}** : {len(df)} lignes, {len(real_cols)} colonnes, {df.duplicated().sum()} doublons")

st.header("2. Colonnes maîtres")
cols_text = st.text_area(
    "Colonnes maîtres",
    value="\n".join(st.session_state.master_columns),
    height=220,
)
if st.button("💾 Enregistrer la liste des colonnes maîtres"):
    new_list = [c.strip() for c in cols_text.split("\n") if c.strip()]
    if new_list:
        st.session_state.master_columns = new_list
        status_box.success(f"{len(new_list)} colonnes maîtres enregistrées.")
    else:
        status_box.error("Veuillez entrer au moins une colonne maître.")

st.header("3. Assignation automatique")
if all_sheets:
    col_a, col_b = st.columns([2, 1])
    with col_a:
        if st.button("🚀 Auto assign all sheets", type="primary"):
            progress = progress_box.progress(0)
            mappings = auto_assign_all_sheets(
                all_sheets,
                st.session_state.master_columns,
                status_box,
                progress,
            )
            progress.empty()
            st.session_state.sheet_mappings = mappings
            st.session_state.auto_assign_done = True
            status_box.success("Assignation automatique terminée pour tous les onglets.")
    with col_b:
        if st.button("♻️ Reset mappings"):
            st.session_state.sheet_mappings = {}
            st.session_state.auto_assign_done = False
            st.session_state.final_df = None
            st.session_state.filtered_df = None
            status_box.success("Mappings réinitialisés.")
else:
    st.info("Importez d'abord vos fichiers.")

st.header("4. Mapping manuel par onglet")
if all_sheets:
    any_assigned = False
    for sheet_key, sheet_df in all_sheets.items():
        with st.expander(f"📄 {sheet_key}", expanded=False):
            real_columns = [c for c in sheet_df.columns if c not in META_COLS]
            st.write(f"Résumé : {len(sheet_df)} lignes | {len(real_columns)} colonnes | {sheet_df.duplicated().sum()} doublons")

            if sheet_key not in st.session_state.sheet_mappings:
                st.session_state.sheet_mappings[sheet_key] = {}

            current_mapping = st.session_state.sheet_mappings[sheet_key]
            updated_mapping = {}

            for src_col in real_columns:
                current = current_mapping.get(src_col, NON_ASSIGNE)
                options = [NON_ASSIGNE] + st.session_state.master_columns
                if current not in options:
                    current = NON_ASSIGNE
                choice = st.selectbox(
                    src_col,
                    options=options,
                    index=options.index(current),
                    key=f"map_{sheet_key}_{src_col}",
                )
                updated_mapping[src_col] = choice
                if choice != NON_ASSIGNE:
                    any_assigned = True

            st.session_state.sheet_mappings[sheet_key] = updated_mapping
            st.dataframe(sheet_df.head(7), use_container_width=True)
else:
    st.info("Aucun onglet importé.")

st.header("5. Construction de la base finale")
if all_sheets:
    if st.button("✅ Construire la base finale", type="primary"):
        progress = progress_box.progress(0)
        final_df = merge_all_sheets(
            all_sheets,
            st.session_state.sheet_mappings,
            st.session_state.master_columns,
            status_box,
            progress,
        )
        progress.empty()
        if final_df is None or len(final_df) == 0:
            status_box.error("La base fusionnée est vide ou aucune assignation exploitable n'a été trouvée.")
        else:
            st.session_state.final_df = final_df
            st.session_state.filtered_df = final_df.copy()
            status_box.success(f"Base construite : {len(final_df)} lignes fusionnées.")
            st.dataframe(final_df.head(50), use_container_width=True)
else:
    st.info("Importez et mappez vos fichiers pour construire la base.")

st.header("6. Filtrage & Dedup")
if st.session_state.final_df is None:
    st.info("Construisez d'abord la base finale.")
else:
    df = st.session_state.final_df.copy()
    st.write(f"Base actuelle : **{len(df)}** lignes importées")

    filter_col = st.selectbox("Filtrer par colonne", options=["(aucun filtre)"] + st.session_state.master_columns)
    filtered_df = df

    if filter_col == "CP" and "CP" in df.columns:
        dep_input = st.text_input("Départements à filtrer (séparés par des virgules, ex: 02,33,77)")
        if dep_input.strip():
            prefixes = {p.strip().zfill(2) for p in dep_input.split(",") if p.strip()}
            mask = df["CP"].apply(lambda v: cp_matches_prefix(v, prefixes) if pd.notna(v) else False)
            filtered_df = df[mask]
    elif filter_col != "(aucun filtre)" and filter_col in df.columns:
        unique_vals = sorted([v for v in df[filter_col].dropna().unique() if str(v).strip()])
        selected_vals = st.multiselect(f"Valeurs à conserver pour {filter_col}", options=unique_vals)
        if selected_vals:
            filtered_df = df[df[filter_col].isin(selected_vals)]

    st.write(f"Résultat filtré : **{len(filtered_df)}** lignes | **{filtered_df.duplicated().sum()}** doublons conservés")
    st.dataframe(filtered_df.head(50), use_container_width=True)

    dup_check_col = st.selectbox("Colonne pour détecter les doublons", options=["(aucune)"] + st.session_state.master_columns)
    if dup_check_col != "(aucune)" and dup_check_col in filtered_df.columns:
        dup_count = filtered_df[dup_check_col].duplicated(keep=False).sum()
        st.warning(f"{dup_count} lignes en doublon détectées sur la colonne '{dup_check_col}'.")

    st.session_state.filtered_df = filtered_df

st.header("7. Export")
if st.session_state.filtered_df is None:
    st.info("Aucune donnée à exporter pour le moment.")
else:
    export_df = st.session_state.filtered_df
    if len(export_df) == 0:
        st.error("Aucune donnée à exporter.")
    else:
        st.write(f"{len(export_df)} lignes prêtes à l'export.")
        col1, col2 = st.columns(2)

        with col1:
            if st.button("Préparer CSV"):
                progress = progress_box.progress(0)
                status_box.info("Préparation du CSV...")
                csv_bytes = export_csv_safe(export_df, progress)
                progress.empty()
                if csv_bytes:
                    status_box.success("CSV prêt.")
                    st.download_button(
                        label="💾 Télécharger CSV",
                        data=csv_bytes,
                        file_name="export_leads.csv",
                        mime="text/csv",
                        key="download_csv",
                    )

        with col2:
            if st.button("Préparer Excel"):
                progress = progress_box.progress(0)
                status_box.info("Préparation du fichier Excel...")
                buffer = export_excel_safe(export_df, progress)
                progress.empty()
                if buffer:
                    status_box.success("Fichier Excel prêt.")
                    st.download_button(
                        label="💾 Télécharger Excel",
                        data=buffer,
                        file_name="export_leads.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="download_xlsx",
                    )
