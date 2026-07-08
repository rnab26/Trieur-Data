import streamlit as st
import pandas as pd
import numpy as np
import io
import unicodedata
import re
from difflib import SequenceMatcher

st.set_page_config(page_title="Trieur de Fichiers Leads", layout="wide")

DEFAULT_MASTER_COLUMNS = [
    "NOM", "PRENOM", "GENRE/CIVILITE", "VILLE", "CP", "ADRESSE",
    "TELEPHONE MOBILE", "TELEPHONE FIXE", "EMAIL", "DATE DE NAISSANCE", "Source Data"
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
    "Source Data": ["source", "fichier", "file", "origin"]
}

if "master_columns" not in st.session_state:
    st.session_state.master_columns = DEFAULT_MASTER_COLUMNS.copy()
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

def normalize_text(text):
    """Normaliser un texte : minuscules, accents, espaces, caractères spéciaux"""
    text = str(text).lower().strip()
    text = unicodedata.normalize('NFKD', text)
    text = ''.join([c for c in text if not unicodedata.combining(c)])
    text = re.sub(r'[\s\-_/.]', '', text)
    text = re.sub(r'[^a-z0-9]', '', text)
    return text

def find_best_master_col(src_col, master_cols, already_used=None):
    """Trouver la meilleure colonne maître pour une colonne source"""
    if already_used is None:
        already_used = []
    
    src_norm = normalize_text(src_col)
    
    if not src_norm or src_norm == "(nonassigne)":
        return None
    
    # 1. Correspondance exacte normalisée
    for master in master_cols:
        if master not in already_used and normalize_text(master) == src_norm:
            return master
    
    # 2. Correspondance via synonymes (priorité haute)
    for master in master_cols:
        if master not in already_used:
            synonyms = SYNONYMES.get(master, [])
            for syn in synonyms:
                if normalize_text(syn) == src_norm:
                    return master
    
    # 3. Fuzzy matching avec seuil strict
    best_master = None
    best_score = 0.72
    for master in master_cols:
        if master not in already_used:
            score = SequenceMatcher(None, src_norm, normalize_text(master)).ratio()
            if score > best_score:
                best_score = score
                best_master = master
    
    return best_master

def read_excel_all_sheets(file_obj):
    """Lire TOUS les onglets d'un fichier Excel"""
    try:
        xls = pd.ExcelFile(file_obj, engine="openpyxl")
        sheets = {}
        for sheet_name in xls.sheet_names:
            df = xls.parse(sheet_name=sheet_name, dtype=str)
            if len(df) > 0:
                sheets[sheet_name] = df
        return sheets
    except Exception:
        try:
            xls = pd.ExcelFile(file_obj)
            sheets = {}
            for sheet_name in xls.sheet_names:
                df = xls.parse(sheet_name=sheet_name, dtype=str)
                if len(df) > 0:
                    sheets[sheet_name] = df
            return sheets
        except Exception as e:
            st.error(f"❌ Erreur lecture Excel: {str(e)}")
            return {}

def read_google_sheets_all_sheets(url):
    """Lire Google Sheets avec tous les onglets détectés"""
    try:
        if "/edit" in url:
            url = url.split("/edit")[0]
        if url.endswith("/"):
            url = url[:-1]
        if "/d/" not in url:
            return {}
        
        sheet_id = url.split("/d/")[1].split("/")[0]
        all_sheets = {}
        
        for gid in range(0, 50):
            try:
                csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
                df = pd.read_csv(csv_url, dtype=str, timeout=10)
                if len(df) > 0 and not df.isnull().all().all():
                    sheet_name = f"Sheet{gid+1}" if gid > 0 else "Sheet1"
                    all_sheets[sheet_name] = df
            except Exception:
                continue
        
        return all_sheets if all_sheets else {}
    except Exception as e:
        st.error(f"❌ Erreur Google Sheets: {str(e)}")
        return {}

def export_csv_safe(df):
    """Export CSV sécurisé"""
    try:
        df_clean = df.copy()
        for col in df_clean.columns:
            df_clean[col] = df_clean[col].astype(str)
        csv_bytes = df_clean.to_csv(index=False, sep=",").encode("utf-8-sig")
        return csv_bytes
    except Exception as e:
        st.error(f"❌ Erreur CSV: {str(e)}")
        return None

def export_excel_safe(df):
    """Export Excel sécurisé avec fallback"""
    try:
        buffer = io.BytesIO()
        try:
            with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
                df.to_excel(writer, index=False, sheet_name="Leads")
                workbook = writer.book
                worksheet = writer.sheets["Leads"]
                if "CP" in df.columns:
                    text_format = workbook.add_format({"num_format": "@"})
                    cp_idx = df.columns.get_loc("CP")
                    worksheet.set_column(cp_idx, cp_idx, 12, text_format)
        except Exception:
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                df.to_excel(writer, index=False, sheet_name="Leads")
        buffer.seek(0)
        return buffer
    except Exception as e:
        st.error(f"❌ Erreur Excel: {str(e)}")
        return None

def is_google_sheet_url(text):
    t = str(text).strip().lower()
    return "docs.google.com/spreadsheets" in t

def normalize_cp(value):
    s = str(value).strip()
    s = s.split(".")[0]
    if not s.isdigit():
        return None
    if len(s) == 4:
        s = "0" + s
    if len(s) != 5:
        return None
    return s

def cp_matches_prefix(cp_value, prefixes):
    cp5 = normalize_cp(cp_value)
    if cp5 is None:
        return False
    return cp5[:2] in prefixes

st.title("Trieur de Fichiers Leads")
st.caption("Import Excel ou Google Sheets → mapping colonnes → aperçu → filtrage → export")

tab1, tab2, tab3, tab4 = st.tabs(["1. Colonnes maitres", "2. Import et Mapping", "3. Filtrage & Dedup", "4. Export"])

with tab1:
    st.subheader("Gerer vos colonnes maitres")
    st.write("Ajoutez, supprimez ou modifiez vos colonnes maitres ci-dessous, une par ligne.")
    cols_text = st.text_area("Colonnes maitres", value="\n".join(st.session_state.master_columns), height=250, key="master_cols_input")
    if st.button("Enregistrer la liste des colonnes maitres"):
        new_list = [c.strip() for c in cols_text.split("\n") if c.strip()]
        if new_list:
            st.session_state.master_columns = new_list
            st.success(str(len(new_list)) + " colonnes maitres enregistrees.")
        else:
            st.error("❌ Veuillez entrer au moins une colonne maître.")

with tab2:
    st.subheader("Importer vos fichiers Excel ou Google Sheets")
    files = st.file_uploader("Deposez un ou plusieurs fichiers Excel", type=["xlsx", "xls"], accept_multiple_files=True)
    google_url = st.text_input("Ou collez une URL Google Sheets publique (optionnel)")

    all_sheets = {}
    
    if files:
        for f in files:
            try:
                sheets = read_excel_all_sheets(f)
                if not sheets:
                    st.error(f"❌ Aucun onglet lisible dans {f.name}")
                    continue
                for sheet_name, df in sheets.items():
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

    if google_url.strip() and is_google_sheet_url(google_url):
        with st.spinner("🔄 Récupération des onglets Google Sheets..."):
            sheets = read_google_sheets_all_sheets(google_url)
            if sheets:
                for sheet_name, df in sheets.items():
                    if len(df) > 0:
                        key = "Google Sheets :: " + sheet_name
                        df = df.copy()
                        df["__source_file__"] = "Google Sheets"
                        df["__source_sheet__"] = sheet_name
                        all_sheets[key] = df
                st.success(f"✅ Google Sheets importé avec {len(sheets)} onglet(s) détecté(s).")
            else:
                st.warning("⚠️ Impossible de lire le Google Sheets.")

    if all_sheets:
        st.session_state.all_sheets = all_sheets
        total_files = len(set([k.split(" :: ")[0] for k in all_sheets.keys()]))
        st.success(str(total_files) + " fichier(s) importes, " + str(len(all_sheets)) + " onglet(s) detecte(s) au total.")

        with st.expander("📋 Detail des onglets importes"):
            for k, df in all_sheets.items():
                num_dup = df.duplicated().sum()
                real_cols = [c for c in df.columns if c not in ["__source_file__", "__source_sheet__"]]
                st.write(f"**{k}** : {len(df)} lignes, {len(real_cols)} colonnes, {num_dup} doublons")

        st.markdown("---")
        st.subheader("Assignation des colonnes")

        any_assigned = False

        for sheet_key, sheet_df in all_sheets.items():
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
                    st.session_state.auto_assign_triggered[sheet_key] = True
            
            # Appliquer l'auto-assignation SI le bouton a été cliqué
            if st.session_state.auto_assign_triggered.get(sheet_key, False):
                new_mapping = {}
                already_used = []
                matched_count = 0
                
                # Parcourir chaque colonne source et trouver la meilleure colonne maître
                for src_col in real_columns:
                    best_master = find_best_master_col(src_col, st.session_state.master_columns, already_used)
                    if best_master:
                        new_mapping[src_col] = best_master
                        already_used.append(best_master)
                        matched_count += 1
                    else:
                        new_mapping[src_col] = "(non assigne)"
                
                st.session_state.sheet_mappings[sheet_key] = new_mapping
                st.success(f"✅ {matched_count}/{len(real_columns)} colonnes assignées automatiquement")
                st.session_state.auto_assign_triggered[sheet_key] = False
            
            st.write("**Aperçu des 7 premières lignes avec assignation au-dessus :**")
            
            preview_df = sheet_df.head(7).copy()
            
            st.write("**Sélectionnez les colonnes maîtres correspondantes :**")
            
            current_mapping = st.session_state.sheet_mappings[sheet_key]
            mapping_options = ["(non assigne)"] + st.session_state.master_columns
            
            updated_mapping = {}
            
            cols_display = st.columns(len(real_columns))
            
            # Afficher un selectbox pour chaque colonne source
            for idx, src_col in enumerate(real_columns):
                with cols_display[idx]:
                    current = current_mapping.get(src_col, "(non assigne)")
                    
                    # Les options disponibles sont les colonnes maîtres non encore utilisées dans ce mapping
                    already_used_in_current = [updated_mapping.get(c, "") for c in real_columns if c != src_col and updated_mapping.get(c) != "(non assigne)"]
                    available_options = ["(non assigne)"] + [m for m in st.session_state.master_columns if m not in already_used_in_current]
                    
                    if current not in available_options:
                        current = "(non assigne)"
                    
                    try:
                        idx_val = available_options.index(current)
                    except ValueError:
                        idx_val = 0
                    
                    choice = st.selectbox(
                        src_col,
                        options=available_options,
                        index=idx_val,
                        key=f"map_{sheet_key}_{src_col}",
                        label_visibility="visible"
                    )
                    updated_mapping[src_col] = choice
                    if choice != "(non assigne)":
                        any_assigned = True
            
            st.session_state.sheet_mappings[sheet_key] = updated_mapping
            st.dataframe(preview_df, use_container_width=True)
            st.markdown("---")

        if not any_assigned:
            st.warning("⚠️ Veuillez assigner au moins une colonne maître avant de construire la base.")
        else:
            if st.button("✅ Construire la base de travail fusionnee", type="primary"):
                rows = []
                total_merged = 0
                
                for sheet_key, sheet_df in all_sheets.items():
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
                        st.dataframe(final_df.head(50), use_container_width=True)
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
        
        filter_col = st.selectbox("Filtrer par colonne", options=["(aucun filtre)"] + st.session_state.master_columns)
        filtered_df = df
        
        if filter_col == "CP":
            dep_input = st.text_input("Departements a filtrer (separes par des virgules, ex: 02,33,77)")
            if dep_input.strip():
                prefixes = set(p.strip().zfill(2) for p in dep_input.split(",") if p.strip())
                mask = df["CP"].apply(lambda v: cp_matches_prefix(v, prefixes) if pd.notna(v) else False)
                filtered_df = df[mask]
        elif filter_col != "(aucun filtre)":
            unique_vals = sorted([v for v in df[filter_col].dropna().unique()])
            selected_vals = st.multiselect("Valeurs a conserver pour " + filter_col, options=unique_vals)
            if selected_vals:
                filtered_df = df[df[filter_col].isin(selected_vals)]
        
        remaining_lines = len(filtered_df)
        remaining_duplicates = filtered_df.duplicated().sum()
        
        st.write(f"Resultat filtre : **{remaining_lines}** lignes | **{remaining_duplicates}** doublons conserves | **{total_lines}** lignes importees au total")
        st.dataframe(filtered_df.head(50), use_container_width=True)
        
        dup_check_col = st.selectbox("Colonne pour detecter les doublons (ex: TELEPHONE MOBILE)", options=["(aucune)"] + st.session_state.master_columns)
        if dup_check_col != "(aucune)":
            dup_count = filtered_df[dup_check_col].duplicated(keep=False).sum()
            st.warning(f"{dup_count} lignes en doublon detectees sur la colonne '{dup_check_col}' (non supprimees automatiquement).")
        
        st.session_state.filtered_df = filtered_df

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
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("**Export CSV**")
                if st.button("Telecharger CSV", key="btn_csv"):
                    csv_bytes = export_csv_safe(export_df)
                    if csv_bytes:
                        st.download_button(
                            label="💾 Telecharger CSV",
                            data=csv_bytes,
                            file_name="export_leads.csv",
                            mime="text/csv"
                        )
            
            with col2:
                st.markdown("**Export Excel**")
                if st.button("Telecharger Excel", key="btn_xlsx"):
                    buffer = export_excel_safe(export_df)
                    if buffer:
                        st.download_button(
                            label="💾 Telecharger Excel",
                            data=buffer,
                            file_name="export_leads.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )
            
            st.markdown("---")
            st.info("ℹ️ Les fichiers sont encodés en UTF-8.")
