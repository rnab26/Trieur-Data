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
if "mapping" not in st.session_state:
    st.session_state.mapping = {}
if "raw_data" not in st.session_state:
    st.session_state.raw_data = None
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
    dep = cp5[:2]
    return dep in prefixes

st.title("Trieur de Fichiers Leads")
st.caption("Import multi-fichiers / multi-onglets -> mapping colonnes -> filtrage -> export CSV/Excel")

tab1, tab2, tab3, tab4 = st.tabs(["1. Colonnes maitres", "2. Import et Mapping", "3. Filtrage", "4. Export"])

with tab1:
    st.subheader("Gerer vos colonnes maitres")
    st.write("Ajoutez, supprimez ou modifiez vos colonnes maitres ci-dessous, une par ligne.")
    cols_text = st.text_area(
        "Colonnes maitres",
        value="\n".join(st.session_state.master_columns),
        height=250
    )
    if st.button("Enregistrer la liste des colonnes maitres"):
        new_list = [c.strip() for c in cols_text.split("\n") if c.strip()]
        st.session_state.master_columns = new_list
        st.success(str(len(new_list)) + " colonnes maitres enregistrees.")

with tab2:
    st.subheader("Importer vos fichiers Excel")
    files = st.file_uploader("Deposez un ou plusieurs fichiers Excel", type=["xlsx", "xls"], accept_multiple_files=True)

    if files:
        all_sheets = {}
        for f in files:
            try:
                sheets = pd.read_excel(f, sheet_name=None, dtype=str)
                for sheet_name, df in sheets.items():
                    key = f.name + " :: " + sheet_name
                    df = df.copy()
                    df["__source_file__"] = f.name
                    all_sheets[key] = df
            except Exception as e:
                st.error("Erreur lecture " + f.name + ": " + str(e))

        st.session_state.raw_data = all_sheets
        st.success(str(len(files)) + " fichier(s) importes, " + str(len(all_sheets)) + " onglet(s) detecte(s) au total.")

        with st.expander("Voir le detail des onglets detectes"):
            for k, df in all_sheets.items():
                st.write(k + " -- " + str(len(df)) + " lignes, " + str(len(df.columns)) + " colonnes")

        all_source_columns = set()
        for df in all_sheets.values():
            for c in df.columns:
                if c != "__source_file__":
                    all_source_columns.add(c)
        all_source_columns = sorted(all_source_columns)

        st.markdown("---")
        st.subheader("Mapping des colonnes")

        if st.button("Assignation automatique"):
            threshold_auto = 0.75
            new_mapping = {}
            for src_col in all_source_columns:
                best_master = None
                best_score = 0
                for master_col in st.session_state.master_columns:
                    score = similarity(src_col, master_col)
                    if score > best_score:
                        best_score = score
                        best_master = master_col
                if best_score >= threshold_auto:
                    new_mapping[src_col] = best_master
                else:
                    new_mapping[src_col] = "(non assigne)"
            st.session_state.mapping = new_mapping
            st.success("Assignation automatique terminee. Verifiez et corrigez ci-dessous si besoin.")

        st.write("Corrigez manuellement les assignations si necessaire :")
        mapping_options = ["(non assigne)"] + st.session_state.master_columns
        updated_mapping = {}
        for src_col in all_source_columns:
            current = st.session_state.mapping.get(src_col, "(non assigne)")
            if current not in mapping_options:
                current = "(non assigne)"
            choice = st.selectbox(
                "Colonne source: " + src_col,
                options=mapping_options,
                index=mapping_options.index(current),
                key="map_" + src_col
            )
            updated_mapping[src_col] = choice
        st.session_state.mapping = updated_mapping

        if st.button("Construire la base de travail fusionnee"):
            rows = []
            for key, df in all_sheets.items():
                source_file = df["__source_file__"].iloc[0] if len(df) > 0 else key
                sub = pd.DataFrame(index=df.index)
                for master_col in st.session_state.master_columns:
                    src_cols_for_master = [s for s, m in st.session_state.mapping.items() if m == master_col and s in df.columns]
                    if master_col == "Source Data":
                        sub[master_col] = source_file
                        continue
                    if not src_cols_for_master:
                        sub[master_col] = None
                        continue
                    combined = df[src_cols_for_master[0]].copy()
                    for extra_col in src_cols_for_master[1:]:
                        is_empty = combined.isna() | (combined.astype(str).str.strip() == "")
                        combined = combined.where(~is_empty, df[extra_col])
                    sub[master_col] = combined
                rows.append(sub)

            final_df = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=st.session_state.master_columns)
            final_df = final_df.dropna(how="all")
            st.session_state.final_df = final_df
            st.success("Base de travail construite : " + str(len(final_df)) + " lignes.")
            st.dataframe(final_df.head(50))

with tab3:
    st.subheader("Filtrer la base de travail")
    if st.session_state.final_df is None:
        st.info("Importez et mappez des fichiers dans l'onglet precedent avant de filtrer.")
    else:
        df = st.session_state.final_df.copy()
        st.write("Base actuelle : " + str(len(df)) + " lignes")

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

        st.write("Resultat filtre : " + str(len(filtered_df)) + " lignes")
        st.dataframe(filtered_df.head(50))

        dup_check_col = st.selectbox("Colonne pour detecter les doublons (ex: TELEPHONE MOBILE)", options=["(aucune)"] + st.session_state.master_columns)
        if dup_check_col != "(aucune)":
            dup_count = filtered_df[dup_check_col].duplicated(keep=False).sum()
            st.warning(str(dup_count) + " lignes en doublon detectees sur la colonne '" + dup_check_col + "' (non supprimees automatiquement).")

        st.session_state.filtered_df = filtered_df

with tab4:
    st.subheader("Exporter le resultat filtre")
    if st.session_state.filtered_df is None:
        st.info("Appliquez un filtre dans l'onglet precedent avant d'exporter.")
    else:
        export_df = st.session_state.filtered_df
        st.write(str(len(export_df)) + " lignes pretes a l'export.")

        max_rows_per_file = 1000000
        n_chunks = max(1, -(-len(export_df) // max_rows_per_file))

        if n_chunks > 1:
            st.warning("Le volume depasse " + str(max_rows_per_file) + " lignes : l'export sera scinde en " + str(n_chunks) + " fichiers.")

        chunks = np.array_split(export_df, n_chunks) if len(export_df) > 0 else [export_df]

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Export CSV**")
            for i, chunk in enumerate(chunks):
                csv_bytes = chunk.to_csv(index=False, sep=",").encode("utf-8-sig")
                fname = "export_leads.csv" if n_chunks == 1 else "export_leads_partie" + str(i+1) + ".csv"
                st.download_button("Telecharger CSV" + ("" if n_chunks==1 else " (partie " + str(i+1) + ")"), data=csv_bytes, file_name=fname, mime="text/csv", key="csv_"+str(i))

        with col2:
            st.markdown("**Export Excel**")
            for i, chunk in enumerate(chunks):
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
                    chunk.to_excel(writer, index=False, sheet_name="Leads")
                    workbook = writer.book
                    worksheet = writer.sheets["Leads"]
                    if "CP" in chunk.columns:
                        text_format = workbook.add_format({"num_format": "@"})
                        cp_idx = chunk.columns.get_loc("CP")
                        worksheet.set_column(cp_idx, cp_idx, 12, text_format)
                buffer.seek(0)
                fname = "export_leads.xlsx" if n_chunks == 1 else "export_leads_partie" + str(i+1) + ".xlsx"
                st.download_button("Telecharger Excel" + ("" if n_chunks==1 else " (partie " + str(i+1) + ")"), data=buffer, file_name=fname, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="xlsx_"+str(i))
