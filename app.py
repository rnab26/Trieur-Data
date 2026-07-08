import streamlit as st
import pandas as pd
import numpy as np
import io
from difflib import SequenceMatcher
from functools import lru_cache

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

def read_excel_any(file_obj):
    try:
        return pd.read_excel(file_obj, sheet_name=None, dtype=str, engine="openpyxl")
    except Exception:
        return pd.read_excel(file_obj, sheet_name=None, dtype=str)

def export_excel_bytes(df):
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

@st.cache_data
def auto_assign_columns(real_columns_tuple, master_columns_tuple):
    real_columns = list(real_columns_tuple)
    master_columns = list(master_columns_tuple)
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
st.caption("Import Excel ou Google Sheets -> mapping colonnes -> aperçu -> filtrage -> export")

tab1, tab2, tab3, tab4 = st.tabs(["1. Colonnes maitres", "2. Import et Mapping", "3. Filtrage", "4. Export"])

with tab1:
    st.subheader("Gerer vos colonnes maitres")
    st.write("Ajoutez, supprimez ou modifiez vos colonnes maitres ci-dessous, une par ligne.")
    cols_text = st.text_area("Colonnes maitres", value="\n".join(st.session_state.master_columns), height=250)
    if st.button("Enregistrer la liste des colonnes maitres"):
        new_list = [c.strip() for c in cols_text.split("\n") if c.strip()]
        st.session_state.master_columns = new_list
        st.success(str(len(new_list)) + " colonnes maitres enregistrees.")

with tab2:
    st.subheader("Importer vos fichiers Excel ou Google Sheets")
    files = st.file_uploader("Deposez un ou plusieurs fichiers Excel", type=["xlsx", "xls"], accept_multiple_files=True)
    google_url = st.text_input("Ou collez une URL Google Sheets publique (optionnel)")

    all_sheets = {}
    if files:
        for f in files:
            try:
                sheets = read_excel_any(f)
                for sheet_name, df in sheets.items():
                    key = f.name + " :: " + sheet_name
                    df = df.copy()
                    df["__source_file__"] = f.name
                    all_sheets[key] = df
            except Exception as e:
                st.error("Erreur lecture " + f.name + ": " + str(e))

    if google_url.strip() and is_google_sheet_url(google_url):
        csv_url = google_sheet_to_csv_url(google_url)
        if csv_url:
            try:
                gdf = pd.read_csv(csv_url, dtype=str)
                gdf["__source_file__"] = "Google Sheets"
                all_sheets["Google Sheets :: Sheet1"] = gdf
            except Exception as e:
                st.error("Erreur lecture Google Sheets: " + str(e))
        else:
            st.warning("URL Google Sheets non reconnue.")

    if all_sheets:
        st.session_state.all_sheets = all_sheets
        st.success(str(len(files)) + " fichier(s) importes, " + str(len(all_sheets)) + " onglet(s) detecte(s) au total.")

        with st.expander("📋 Detail des onglets importes"):
            for k, df in all_sheets.items():
                st.write(f"**{k}** : {len(df)} lignes, {len(df.columns)} colonnes")

        st.markdown("---")
        st.subheader("Mapping par fichier/onglet")

        for sheet_key, sheet_df in all_sheets.items():
            st.markdown(f"### 📄 {sheet_key}")
            
            real_columns = [c for c in sheet_df.columns if c != "__source_file__"]
            st.write(f"**Colonnes detectees ({len(real_columns)}) :** `{' | '.join(real_columns)}`")
            
            if sheet_key not in st.session_state.sheet_mappings:
                st.session_state.sheet_mappings[sheet_key] = {}
            
            current_mapping = st.session_state.sheet_mappings[sheet_key]
            
            col_auto, col_space = st.columns([1, 3])
            with col_auto:
                if st.button(f"🚀 Auto", key=f"auto_{sheet_key}"):
                    new_mapping = auto_assign_columns(tuple(real_columns), tuple(st.session_state.master_columns))
                    st.session_state.sheet_mappings[sheet_key] = new_mapping
                    st.rerun()
            
            st.write("**Aperçu des 7 premieres lignes :**")
            st.dataframe(sheet_df.head(7), use_container_width=True)
            
            st.write("**Mapping des colonnes (affichage horizontal compact) :**")
            mapping_options = ["(non assigne)"] + st.session_state.master_columns
            updated_mapping = {}
            
            cols_per_row = 4
            for i in range(0, len(real_columns), cols_per_row):
                cols = st.columns(cols_per_row)
                batch = real_columns[i:i+cols_per_row]
                
                for idx, src_col in enumerate(batch):
                    with cols[idx]:
                        current = current_mapping.get(src_col, "(non assigne)")
                        if current not in mapping_options:
                            current = "(non assigne)"
                        try:
                            idx_val = mapping_options.index(current)
                        except ValueError:
                            idx_val = 0
                        choice = st.selectbox(
                            src_col,
                            options=mapping_options,
                            index=idx_val,
                            key=f"map_{sheet_key}_{src_col}",
                            label_visibility="collapsed"
                        )
                        updated_mapping[src_col] = choice
            
            st.session_state.sheet_mappings[sheet_key] = updated_mapping
            st.markdown("---")

        if st.button("✅ Construire la base de travail fusionnee", type="primary"):
            rows = []
            for sheet_key, sheet_df in all_sheets.items():
                source_file = sheet_df["__source_file__"].iloc[0] if len(sheet_df) > 0 else sheet_key
                mapping = st.session_state.sheet_mappings.get(sheet_key, {})
                
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
            
            final_df = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=st.session_state.master_columns)
            final_df = final_df.dropna(how="all")
            st.session_state.final_df = final_df
            st.success(f"✅ Base de travail construite : {len(final_df)} lignes.")
            st.dataframe(final_df.head(50), use_container_width=True)
    else:
        st.info("Importe un fichier Excel ou colle une URL Google Sheets pour continuer.")

with tab3:
    st.subheader("Filtrer la base de travail")
    if st.session_state.final_df is None:
        st.info("Importez et mappez des fichiers dans l'onglet precedent avant de filtrer.")
    else:
        df = st.session_state.final_df.copy()
        st.write(f"Base actuelle : {len(df)} lignes")
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
        st.write(f"Resultat filtre : {len(filtered_df)} lignes")
        st.dataframe(filtered_df.head(50), use_container_width=True)
        dup_check_col = st.selectbox("Colonne pour detecter les doublons (ex: TELEPHONE MOBILE)", options=["(aucune)"] + st.session_state.master_columns)
        if dup_check_col != "(aucune)":
            dup_count = filtered_df[dup_check_col].duplicated(keep=False).sum()
            st.warning(f"{dup_count} lignes en doublon detectees sur la colonne '{dup_check_col}' (non supprimees automatiquement).")
        st.session_state.filtered_df = filtered_df

with tab4:
    st.subheader("Exporter le resultat filtre")
    if st.session_state.filtered_df is None:
        st.info("Appliquez un filtre dans l'onglet precedent avant d'exporter.")
    else:
        export_df = st.session_state.filtered_df
        st.write(f"{len(export_df)} lignes pretes a l'export.")
        chunks = np.array_split(export_df, max(1, -(-len(export_df) // 1000000))) if len(export_df) > 0 else [export_df]
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Export CSV**")
            for i, chunk in enumerate(chunks):
                csv_bytes = chunk.to_csv(index=False, sep=",").encode("utf-8-sig")
                fname = "export_leads.csv" if len(chunks) == 1 else f"export_leads_partie{i+1}.csv"
                st.download_button(f"Telecharger CSV" + ("" if len(chunks)==1 else f" (partie {i+1})"), data=csv_bytes, file_name=fname, mime="text/csv", key="csv_"+str(i))
        with col2:
            st.markdown("**Export Excel**")
            for i, chunk in enumerate(chunks):
                buffer = export_excel_bytes(chunk)
                fname = "export_leads.xlsx" if len(chunks) == 1 else f"export_leads_partie{i+1}.xlsx"
                st.download_button(f"Telecharger Excel" + ("" if len(chunks)==1 else f" (partie {i+1})"), data=buffer, file_name=fname, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="xlsx_"+str(i))
