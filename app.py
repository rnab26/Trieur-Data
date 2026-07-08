import streamlit as st
import pandas as pd
import numpy as np
import io
from difflib import SequenceMatcher

st.set_page_config(page_title="Trieur de Fichiers Leads", layout="wide")

DEFAULT_MASTER_COLUMNS = [
    "NOM", "PRENOM", "GENRE/CIVILITE", "VILLE", "CP", "ADRESSE",
    "TELEPHONE MOBILE", "TELEPHONE FIXE", "EMAIL", "DATE DE NAISSANCE", "Source Data"
]

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

def similarity(a, b):
    return SequenceMatcher(None, str(a).lower().strip(), str(b).lower().strip()).ratio()

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

@st.cache_data
def read_excel_any(file_obj):
    try:
        return pd.read_excel(file_obj, sheet_name=None, dtype=str, engine="openpyxl")
    except Exception:
        try:
            return pd.read_excel(file_obj, sheet_name=None, dtype=str)
        except Exception as e:
            st.error(f"Impossible de lire le fichier: {str(e)}")
            return {}

def export_csv_safe(df):
    """Export CSV sécurisé avec gestion d'erreurs"""
    try:
        df_clean = df.copy()
        for col in df_clean.columns:
            if df_clean[col].dtype == 'object':
                df_clean[col] = df_clean[col].astype(str)
        csv_bytes = df_clean.to_csv(index=False, sep=",").encode("utf-8-sig")
        return csv_bytes
    except Exception as e:
        st.error(f"Erreur lors de la génération CSV: {str(e)}")
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
            try:
                with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                    df.to_excel(writer, index=False, sheet_name="Leads")
            except Exception as e:
                st.error(f"Erreur lors de la génération Excel: {str(e)}")
                return None
        buffer.seek(0)
        return buffer
    except Exception as e:
        st.error(f"Erreur critique Excel: {str(e)}")
        return None

def auto_assign_columns_fast(real_columns, master_columns):
    """Assignation automatique rapide"""
    threshold_auto = 0.75
    new_mapping = {}
    for src_col in real_columns:
        best_master = None
        best_score = 0
        for master_col in master_columns:
            score = similarity(src_col, master_col)
            if score > best_score:
                best_score = score
                best_master = master_col
        new_mapping[src_col] = best_master if best_score >= threshold_auto else "(non assigne)"
    return new_mapping

def is_google_sheet_url(text):
    t = str(text).strip().lower()
    return "docs.google.com/spreadsheets" in t

def google_sheet_to_csv_url(url):
    try:
        if "/edit" in url:
            url = url.split("/edit")[0]
        if url.endswith("/"):
            url = url[:-1]
        if "/d/" not in url:
            return None
        sheet_id = url.split("/d/")[1].split("/")[0]
        return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    except Exception:
        return None

st.title("Trieur de Fichiers Leads")
st.caption("Import Excel ou Google Sheets → mapping colonnes → aperçu → filtrage → export")

tab1, tab2, tab3, tab4 = st.tabs(["1. Colonnes maitres", "2. Import et Mapping", "3. Filtrage & Dedup", "4. Export"])

with tab1:
    st.subheader("Gerer vos colonnes maitres")
    st.write("Ajoutez, supprimez ou modifiez vos colonnes maitres ci-dessous, une par ligne.")
    cols_text = st.text_area("Colonnes maitres", value="\n".join(st.session_state.master_columns), height=250, key="master_cols_input")
    if st.button("✅ Enregistrer la liste des colonnes maitres"):
        new_list = [c.strip() for c in cols_text.split("\n") if c.strip()]
        if new_list:
            st.session_state.master_columns = new_list
            st.success(f"✅ {len(new_list)} colonnes maitres enregistrees.")
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
                sheets = read_excel_any(f)
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
                    all_sheets[key] = df
            except Exception as e:
                st.error(f"❌ Erreur lecture {f.name}: {str(e)}")

    if google_url.strip() and is_google_sheet_url(google_url):
        csv_url = google_sheet_to_csv_url(google_url)
        if csv_url:
            try:
                gdf = pd.read_csv(csv_url, dtype=str)
                if len(gdf) == 0:
                    st.warning("⚠️ Google Sheets est vide.")
                else:
                    gdf["__source_file__"] = "Google Sheets"
                    all_sheets["Google Sheets :: Sheet1"] = gdf
            except Exception as e:
                st.error(f"❌ Erreur lecture Google Sheets: {str(e)}")
        else:
            st.warning("⚠️ URL Google Sheets non reconnue.")

    if all_sheets:
        st.session_state.all_sheets = all_sheets
        total_files = len(set([k.split(" :: ")[0] for k in all_sheets.keys()]))
        st.success(f"✅ {total_files} fichier(s) importes, {len(all_sheets)} onglet(s) detecte(s) au total.")

        with st.expander("📋 Detail des onglets importes"):
            for k, df in all_sheets.items():
                num_dup = df.duplicated().sum()
                st.write(f"**{k}** → {len(df)} lignes | {len(df.columns)} colonnes | {num_dup} doublons")

        st.markdown("---")
        st.subheader("Assignation des colonnes")

        any_assigned = False

        for sheet_key, sheet_df in all_sheets.items():
            st.markdown(f"### 📄 {sheet_key}")
            
            real_columns = [c for c in sheet_df.columns if c != "__source_file__"]
            num_rows = len(sheet_df)
            num_cols = len(real_columns)
            num_duplicates = sheet_df.duplicated().sum()
            
            st.write(f"📊 **Résumé :** {num_rows} lignes | {num_cols} colonnes | {num_duplicates} doublons")
            
            if sheet_key not in st.session_state.sheet_mappings:
                st.session_state.sheet_mappings[sheet_key] = {}
            
            col_auto, col_space = st.columns([1, 3])
            with col_auto:
                if st.button(f"🚀 Auto-assign", key=f"auto_{sheet_key}"):
                    new_mapping = auto_assign_columns_fast(real_columns, st.session_state.master_columns)
                    st.session_state.sheet_mappings[sheet_key] = new_mapping
                    st.rerun()
            
            st.write("**Sélectionnez les colonnes maîtres correspondantes :**")
            
            preview_df = sheet_df.head(7).copy()
            
            current_mapping = st.session_state.sheet_mappings[sheet_key]
            
            updated_mapping = {}
            cols_display = st.columns(len(real_columns))
            
            for idx, src_col in enumerate(real_columns):
                with cols_display[idx]:
                    current = current_mapping.get(src_col, "(non assigne)")
                    
                    available_options = ["(non assigne)"] + [m for m in st.session_state.master_columns 
                                                               if m not in [updated_mapping.get(c, "") for c in real_columns if c != src_col]]
                    
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
                    mapping = st.session_state.sheet_mappings.get(sheet_key, {})
                    
                    assigned_cols = [m for m in mapping.values() if m != "(non assigne)"]
                    if not assigned_cols:
                        st.warning(f"⚠️ {sheet_key}: Aucune colonne assignée, ignoré.")
                        continue
                    
                    sub = pd.DataFrame(index=sheet_df.index)
                    for master_col in st.session_state.master_columns:
                        src_cols_for_master = [s for s, m in mapping.items() if m == master_col and s in sheet_df.columns]
                        if master_col == "Source Data":
                            sub[master_col] = source_file
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
                    st.error("❌ Aucun onglet avec assignation trouvé. Veuillez assigner des colonnes.")
                else:
                    final_df = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=st.session_state.master_columns)
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
    st.subheader("Filtrer et Deduplicater")
    
    if st.session_state.final_df is None:
        st.info("ℹ️ Importez et mappez des fichiers dans l'onglet precedent avant de filtrer.")
    else:
        df = st.session_state.final_df.copy()
        total_lines = len(df)
        
        st.write(f"📊 **Base de travail :** {total_lines} lignes importees")
        
        col_filter, col_dedup = st.columns(2)
        
        with col_filter:
            st.markdown("#### 🔍 Filtrage")
            filter_col = st.selectbox("Filtrer par colonne", options=["(aucun filtre)"] + st.session_state.master_columns)
            filtered_df = df.copy()
            
            if filter_col == "CP":
                dep_input = st.text_input("Départements (ex: 02,33,77)")
                if dep_input.strip():
                    prefixes = set(p.strip().zfill(2) for p in dep_input.split(",") if p.strip())
                    mask = df["CP"].apply(lambda v: cp_matches_prefix(v, prefixes) if pd.notna(v) else False)
                    filtered_df = df[mask]
            elif filter_col != "(aucun filtre)":
                unique_vals = sorted([str(v) for v in df[filter_col].dropna().unique()])
                selected_vals = st.multiselect(f"Valeurs pour {filter_col}", options=unique_vals)
                if selected_vals:
                    filtered_df = df[df[filter_col].isin(selected_vals)]
        
        with col_dedup:
            st.markdown("#### 🔄 Déduplication")
            dup_col = st.selectbox("Colonne de déduplication", options=["(aucune)"] + st.session_state.master_columns, key="dedup_col")
            
            if dup_col != "(aucune)":
                dup_before = filtered_df[dup_col].duplicated(keep=False).sum()
                if dup_before > 0:
                    st.warning(f"⚠️ {dup_before} lignes en doublon detectees sur '{dup_col}'")
                    if st.checkbox(f"Supprimer les doublons sur '{dup_col}'", key=f"dup_checkbox_{dup_col}"):
                        filtered_df = filtered_df.drop_duplicates(subset=[dup_col], keep='first')
                        dup_after = dup_before - len([x for x in filtered_df[dup_col].duplicated(keep=False)])
                        st.success(f"✅ {dup_before - dup_after} doublons supprimés.")
                else:
                    st.info(f"ℹ️ Aucun doublon sur '{dup_col}'")
        
        remaining_lines = len(filtered_df)
        remaining_duplicates = filtered_df.duplicated().sum()
        
        st.markdown("---")
        st.write(f"📊 **Résumé filtre :** {remaining_lines} lignes restantes | {remaining_duplicates} doublons globaux | {total_lines} au total")
        st.dataframe(filtered_df.head(50), use_container_width=True)
        
        st.session_state.filtered_df = filtered_df

with tab4:
    st.subheader("Exporter le resultat")
    
    if st.session_state.filtered_df is None:
        st.info("ℹ️ Filtrez et préparez vos données dans l'onglet precedent avant d'exporter.")
    else:
        export_df = st.session_state.filtered_df.copy()
        
        if len(export_df) == 0:
            st.error("❌ Impossible d'exporter : aucune donnée à exporter après filtrage.")
        else:
            st.write(f"📊 **Pret a exporter :** {len(export_df)} lignes en {export_df.shape[1]} colonnes")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("#### 📥 CSV")
                if st.button("Telecharger CSV", key="btn_csv"):
                    csv_bytes = export_csv_safe(export_df)
                    if csv_bytes:
                        st.download_button(
                            label="💾 Telecharger CSV",
                            data=csv_bytes,
                            file_name="export_leads.csv",
                            mime="text/csv"
                        )
                    else:
                        st.error("❌ Export CSV échoué.")
            
            with col2:
                st.markdown("#### 📥 Excel")
                if st.button("Telecharger Excel", key="btn_xlsx"):
                    buffer = export_excel_safe(export_df)
                    if buffer:
                        st.download_button(
                            label="💾 Telecharger Excel",
                            data=buffer,
                            file_name="export_leads.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )
                    else:
                        st.error("❌ Export Excel échoué.")
            
            st.markdown("---")
            st.info("ℹ️ Les fichiers sont encodés en UTF-8. Les doublons ne sont PAS supprimés automatiquement : utilisez l'onglet Filtrage pour déduplicater si besoin.")
