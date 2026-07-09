@'
import streamlit as st
import pandas as pd
import io
import unicodedata
import re
import time
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

# =========================================================
# CONFIG
# =========================================================
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

NON_ASSIGNE = "(non assigne)"
MAX_PREVIEW_ROWS = 50
MAX_FILTER_OPTIONS = 500
AUTO_MAP_TIMEOUT_MS = 350  # auto-mapping opportuniste: ne doit pas bloquer


# =========================================================
# SESSION STATE
# =========================================================
def init_state():
    defaults = {
        "master_columns": DEFAULT_MASTER_COLUMNS.copy(),
        "all_sheets": {},              # {sheet_key: DataFrame}
        "sheet_mappings": {},          # {sheet_key: {src_col: master_col}}
        "final_df": None,
        "filtered_df": None,
        "import_errors": [],
        "build_errors": [],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# =========================================================
# NORMALISATION / HYGIENE
# =========================================================
@st.cache_data(show_spinner=False)
def normalize_text(text: object) -> str:
    """Normalisation robuste pour comparaison texte."""
    if text is None:
        return ""
    t = str(text).strip().lower()
    t = unicodedata.normalize("NFKD", t)
    t = ''.join([c for c in t if not unicodedata.combining(c)])
    t = re.sub(r"[\s\-_/.]", "", t)
    t = re.sub(r"[^a-z0-9]", "", t)
    return t


@st.cache_data(show_spinner=False)
def normalized_synonyms(master_cols: Tuple[str, ...]) -> Dict[str, List[str]]:
    out = {}
    for m in master_cols:
        out[m] = [normalize_text(x) for x in SYNONYMES.get(m, [])]
    return out


def normalize_cp(value: object) -> Optional[str]:
    s = str(value).strip().split(".")[0]
    if not s.isdigit():
        return None
    if len(s) == 4:
        s = "0" + s
    if len(s) != 5:
        return None
    return s


def cp_matches_prefix(cp_value: object, prefixes: set) -> bool:
    cp5 = normalize_cp(cp_value)
    return bool(cp5 and cp5[:2] in prefixes)


def is_google_sheet_url(text: str) -> bool:
    t = str(text).strip().lower()
    return ("docs.google.com/spreadsheets" in t) and ("/d/" in t)


# =========================================================
# MATCHING COLONNES (opportuniste)
# =========================================================
def find_best_master_col(
    src_col: str,
    master_cols: List[str],
    syn_map: Dict[str, List[str]],
) -> Optional[str]:
    src_norm = normalize_text(src_col)

    # Niveau 1: exact normalisé
    for master in master_cols:
        if normalize_text(master) == src_norm:
            return master

    # Niveau 2: synonymes normalisés
    for master in master_cols:
        if src_norm in syn_map.get(master, []):
            return master

    # Niveau 3: fuzzy limité
    best_master = None
    best_score = 0.74  # plus strict => moins d'erreurs
    for master in master_cols:
        score = SequenceMatcher(None, src_norm, normalize_text(master)).ratio()
        if score > best_score:
            best_score = score
            best_master = master
    return best_master


def auto_map_sheet_opportuniste(sheet_df: pd.DataFrame, master_cols: List[str]) -> Dict[str, str]:
    """
    Auto-mapping opportuniste:
    - Rapide d'abord
    - Timeout dur => fallback NON_ASSIGNE
    """
    start = time.perf_counter()
    real_columns = [c for c in sheet_df.columns if c not in ["__source_file__", "__source_sheet__"]]
    syn_map = normalized_synonyms(tuple(master_cols))
    mapping = {}

    for src_col in real_columns:
        elapsed_ms = (time.perf_counter() - start) * 1000
        if elapsed_ms > AUTO_MAP_TIMEOUT_MS:
            # fallback immédiat pour rester fluide
            mapping[src_col] = NON_ASSIGNE
            continue
        best = find_best_master_col(src_col, master_cols, syn_map)
        mapping[src_col] = best if best else NON_ASSIGNE

    return mapping


# =========================================================
# I/O (CACHE)
# =========================================================
@st.cache_data(show_spinner=False)
def read_excel_all_sheets_cached(file_bytes: bytes, file_name: str) -> Dict[str, pd.DataFrame]:
    """
    Lecture Excel cachee.
    - Evite reread complet à chaque rerun
    - Ignore les feuilles vides/corrompues
    """
    out = {}
    bio = io.BytesIO(file_bytes)

    # 1) openpyxl
    try:
        xls = pd.ExcelFile(bio, engine="openpyxl")
        for sh in xls.sheet_names:
            try:
                df = xls.parse(sheet_name=sh, dtype=str)
                if df is not None and not df.empty and not df.isnull().all().all():
                    out[sh] = df
            except Exception:
                continue
        return out
    except Exception:
        pass

    # 2) fallback engine auto
    try:
        bio.seek(0)
        xls = pd.ExcelFile(bio)
        for sh in xls.sheet_names:
            try:
                df = xls.parse(sheet_name=sh, dtype=str)
                if df is not None and not df.empty and not df.isnull().all().all():
                    out[sh] = df
            except Exception:
                continue
        return out
    except Exception:
        return {}


@st.cache_data(show_spinner=False)
def read_google_sheet_fast_cached(url: str) -> Dict[str, pd.DataFrame]:
    """
    Lecture Google Sheet rapide (sheet principale gid=0).
    On évite la boucle 0..49 qui bloque souvent.
    """
    try:
        u = url.strip()
        if "/edit" in u:
            u = u.split("/edit")[0]
        if u.endswith("/"):
            u = u[:-1]
        if "/d/" not in u:
            return {}

        sheet_id = u.split("/d/")[1].split("/")[0]
        csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid=0"
        df = pd.read_csv(csv_url, dtype=str)
        if df is None or df.empty or df.isnull().all().all():
            return {}
        return {"Sheet1": df}
    except Exception:
        return {}


# =========================================================
# BUILD DATASET
# =========================================================
def build_sheet_mapping_if_missing(sheet_key: str, sheet_df: pd.DataFrame):
    if sheet_key in st.session_state.sheet_mappings:
        return
    real_columns = [c for c in sheet_df.columns if c not in ["__source_file__", "__source_sheet__"]]
    st.session_state.sheet_mappings[sheet_key] = {c: NON_ASSIGNE for c in real_columns}


def merge_all_sheets(
    all_sheets: Dict[str, pd.DataFrame],
    sheet_mappings: Dict[str, Dict[str, str]],
    master_cols: List[str],
) -> Tuple[pd.DataFrame, List[str]]:
    rows = []
    errors = []

    for sheet_key, sheet_df in all_sheets.items():
        if sheet_df is None or sheet_df.empty:
            continue

        mapping = sheet_mappings.get(sheet_key, {})
        assigned_cols = [m for m in mapping.values() if m != NON_ASSIGNE]
        if not assigned_cols:
            continue

        source_file = (
            sheet_df["__source_file__"].iloc[0]
            if "__source_file__" in sheet_df.columns and len(sheet_df) > 0
            else sheet_key
        )
        source_sheet = (
            sheet_df["__source_sheet__"].iloc[0]
            if "__source_sheet__" in sheet_df.columns and len(sheet_df) > 0
            else "Unknown"
        )

        sub = pd.DataFrame(index=sheet_df.index)

        for master_col in master_cols:
            try:
                src_cols = [s for s, m in mapping.items() if m == master_col and s in sheet_df.columns]
                if master_col == "Source Data":
                    sub[master_col] = f"{source_file} ({source_sheet})"
                elif not src_cols:
                    sub[master_col] = None
                else:
                    combined = sheet_df[src_cols[0]]
                    for extra_col in src_cols[1:]:
                        is_empty = combined.isna() | (combined.astype(str).str.strip() == "")
                        combined = combined.where(~is_empty, sheet_df[extra_col])
                    sub[master_col] = combined
            except Exception as e:
                errors.append(f"{sheet_key} / {master_col}: {e}")
                sub[master_col] = None

        rows.append(sub)

    if not rows:
        return pd.DataFrame(columns=master_cols), errors

    final_df = pd.concat(rows, ignore_index=True, copy=False)
    final_df = final_df.dropna(how="all")

    # Nettoyage minimal défensif
    final_df.columns = [str(c).strip() for c in final_df.columns]
    final_df = final_df.loc[:, ~final_df.columns.duplicated()]

    return final_df, errors


# =========================================================
# EXPORT (CACHE)
# =========================================================
@st.cache_data(show_spinner=False)
def export_csv_bytes(df: pd.DataFrame) -> bytes:
    try:
        return df.astype(str).to_csv(index=False, sep=",").encode("utf-8-sig")
    except Exception:
        return b""


@st.cache_data(show_spinner=False)
def export_excel_bytes(df: pd.DataFrame) -> bytes:
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
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Leads")
    buffer.seek(0)
    return buffer.getvalue()


# =========================================================
# APP UI
# =========================================================
init_state()

st.title("Trieur de Fichiers Leads")
st.caption("Rapide d'abord: import robuste, mapping opportuniste, filtrage fluide, export simple")

tab1, tab2, tab3, tab4 = st.tabs(
    ["1. Colonnes maîtres", "2. Import et Mapping", "3. Filtrage & Dedup", "4. Export"]
)

# -------------------------
# TAB 1
# -------------------------
with tab1:
    st.subheader("Gérer les colonnes maîtres")
    cols_text = st.text_area(
        "Colonnes maîtres (une par ligne)",
        value="\n".join(st.session_state.master_columns),
        height=220,
    )
    if st.button("Enregistrer la liste"):
        new_list = [c.strip() for c in cols_text.split("\n") if c.strip()]
        if not new_list:
            st.error("❌ Veuillez entrer au moins une colonne maître.")
        else:
            st.session_state.master_columns = new_list
            st.success(f"✅ {len(new_list)} colonnes enregistrées.")

# -------------------------
# TAB 2
# -------------------------
with tab2:
    st.subheader("Import des sources")
    files = st.file_uploader(
        "Déposez un ou plusieurs fichiers Excel",
        type=["xlsx", "xls"],
        accept_multiple_files=True,
    )
    google_url = st.text_input("URL Google Sheets publique (optionnel)")
    col_a, col_b = st.columns([1, 1])
    with col_a:
        import_clicked = st.button("Charger les sources", type="primary")
    with col_b:
        clear_clicked = st.button("Réinitialiser import")

    if clear_clicked:
        st.session_state.all_sheets = {}
        st.session_state.sheet_mappings = {}
        st.session_state.final_df = None
        st.session_state.filtered_df = None
        st.session_state.import_errors = []
        st.session_state.build_errors = []
        st.success("✅ Import réinitialisé.")

    if import_clicked:
        all_sheets = {}
        import_errors = []

        # Excel
        for f in files or []:
            try:
                sheets = read_excel_all_sheets_cached(f.getvalue(), f.name)
                if not sheets:
                    import_errors.append(f"Aucun onglet lisible: {f.name}")
                    continue
                for sheet_name, df in sheets.items():
                    if df is None or df.empty:
                        continue
                    key = f"{f.name} :: {sheet_name}"
                    df = df.copy()
                    df["__source_file__"] = f.name
                    df["__source_sheet__"] = sheet_name
                    all_sheets[key] = df
            except Exception as e:
                import_errors.append(f"Erreur lecture {f.name}: {e}")

        # Google Sheets (rapide)
        if google_url.strip():
            if is_google_sheet_url(google_url):
                try:
                    gsheets = read_google_sheet_fast_cached(google_url)
                    if not gsheets:
                        import_errors.append("Google Sheets vide/inaccessible.")
                    for sheet_name, df in gsheets.items():
                        key = f"Google Sheets :: {sheet_name}"
                        df = df.copy()
                        df["__source_file__"] = "Google Sheets"
                        df["__source_sheet__"] = sheet_name
                        all_sheets[key] = df
                except Exception as e:
                    import_errors.append(f"Erreur Google Sheets: {e}")
            else:
                import_errors.append("URL Google Sheets invalide.")

        st.session_state.all_sheets = all_sheets
        st.session_state.sheet_mappings = {}
        st.session_state.final_df = None
        st.session_state.filtered_df = None
        st.session_state.import_errors = import_errors
        st.session_state.build_errors = []

        if all_sheets:
            total_files = len(set(k.split(" :: ")[0] for k in all_sheets.keys()))
            st.success(f"✅ {total_files} fichier(s) / {len(all_sheets)} onglet(s) importés.")
        else:
            st.info("ℹ️ Aucune source importée.")

    # Affichage erreurs import
    if st.session_state.import_errors:
        for err in st.session_state.import_errors:
            st.warning(f"⚠️ {err}")

    all_sheets = st.session_state.all_sheets
    if all_sheets:
        with st.expander("📋 Détail des onglets importés", expanded=False):
            for k, df in all_sheets.items():
                real_cols = [c for c in df.columns if c not in ["__source_file__", "__source_sheet__"]]
                dup = int(df.duplicated().sum()) if df is not None and not df.empty else 0
                st.write(f"**{k}** : {len(df)} lignes, {len(real_cols)} colonnes, {dup} doublons")

        st.markdown("---")
        st.subheader("Assignation des colonnes")

        any_assigned = False
        for sheet_key, sheet_df in all_sheets.items():
            st.markdown(f"### 📄 {sheet_key}")

            if sheet_df is None or sheet_df.empty:
                st.warning("⚠️ Feuille vide ignorée.")
                continue

            build_sheet_mapping_if_missing(sheet_key, sheet_df)

            real_columns = [c for c in sheet_df.columns if c not in ["__source_file__", "__source_sheet__"]]
            st.caption(f"{len(sheet_df)} lignes | {len(real_columns)} colonnes")

            c1, c2 = st.columns([1, 3])
            with c1:
                if st.button("🚀 Auto", key=f"auto_{sheet_key}"):
                    st.session_state.sheet_mappings[sheet_key] = auto_map_sheet_opportuniste(
                        sheet_df, st.session_state.master_columns
                    )
                    st.rerun()
            with c2:
                st.caption("Auto = opportuniste rapide. Si ambigu/lent: non assigné (fallback manuel).")

            current_mapping = st.session_state.sheet_mappings.get(sheet_key, {})
            options = [NON_ASSIGNE] + st.session_state.master_columns

            # UI légère: une ligne par colonne source
            for src_col in real_columns:
                left, right = st.columns([2, 3])
                with left:
                    st.write(src_col)
                with right:
                    cur = current_mapping.get(src_col, NON_ASSIGNE)
                    if cur not in options:
                        cur = NON_ASSIGNE
                    choice = st.selectbox(
                        f"Mapping {sheet_key}::{src_col}",
                        options=options,
                        index=options.index(cur),
                        key=f"map_{sheet_key}_{src_col}",
                        label_visibility="collapsed",
                    )
                    current_mapping[src_col] = choice
                    if choice != NON_ASSIGNE:
                        any_assigned = True

            st.session_state.sheet_mappings[sheet_key] = current_mapping
            st.dataframe(sheet_df.head(7), use_container_width=True)
            st.markdown("---")

        if not any_assigned:
            st.warning("⚠️ Assigne au moins une colonne maître pour construire la base.")
        else:
            if st.button("✅ Construire la base fusionnée", type="primary"):
                final_df, build_errors = merge_all_sheets(
                    st.session_state.all_sheets,
                    st.session_state.sheet_mappings,
                    st.session_state.master_columns
                )
                st.session_state.build_errors = build_errors

                if final_df is None or final_df.empty:
                    st.error("❌ Base fusionnée vide après traitement.")
                    st.session_state.final_df = None
                    st.session_state.filtered_df = None
                else:
                    st.session_state.final_df = final_df
                    st.session_state.filtered_df = final_df
                    st.success(f"✅ Base construite: {len(final_df)} lignes.")
                    st.dataframe(final_df.head(MAX_PREVIEW_ROWS), use_container_width=True)

    if st.session_state.build_errors:
        with st.expander("⚠️ Détails erreurs de construction", expanded=False):
            for e in st.session_state.build_errors[:100]:
                st.write(f"- {e}")

# -------------------------
# TAB 3
# -------------------------
with tab3:
    st.subheader("Filtrage & dédup")
    if st.session_state.final_df is None or st.session_state.final_df.empty:
        st.info("ℹ️ Construis la base dans l'onglet 2 d'abord.")
    else:
        df = st.session_state.final_df
        st.write(f"Base actuelle: **{len(df)}** lignes")

        filter_col = st.selectbox("Filtrer par colonne", options=["(aucun filtre)"] + st.session_state.master_columns)
        filtered_df = df

        if filter_col == "CP":
            if "CP" in df.columns:
                dep_input = st.text_input("Départements (ex: 02,33,77)")
                if dep_input.strip():
                    prefixes = set(p.strip().zfill(2) for p in dep_input.split(",") if p.strip())
                    mask = df["CP"].apply(lambda v: cp_matches_prefix(v, prefixes) if pd.notna(v) else False)
                    filtered_df = df[mask]
            else:
                st.warning("⚠️ Colonne CP absente.")

        elif filter_col != "(aucun filtre)":
            if filter_col not in df.columns:
                st.warning(f"⚠️ Colonne '{filter_col}' absente.")
            else:
                uniq = df[filter_col].dropna().astype(str).unique()
                if len(uniq) > MAX_FILTER_OPTIONS:
                    q = st.text_input(f"Recherche texte dans {filter_col} (liste trop grande)")
                    if q.strip():
                        filtered_df = df[df[filter_col].astype(str).str.contains(q, case=False, na=False)]
                else:
                    vals = sorted(uniq.tolist())
                    selected = st.multiselect(f"Valeurs à conserver ({filter_col})", options=vals)
                    if selected:
                        filtered_df = df[df[filter_col].astype(str).isin(selected)]

        remaining_lines = len(filtered_df)
        remaining_dup = int(filtered_df.duplicated().sum())
        st.write(f"Résultat: **{remaining_lines}** lignes | **{remaining_dup}** doublons")

        dup_col = st.selectbox("Détecter doublons sur", options=["(aucune)"] + st.session_state.master_columns)
        if dup_col != "(aucune)":
            if dup_col in filtered_df.columns:
                dup_count = int(filtered_df[dup_col].duplicated(keep=False).sum())
                st.warning(f"{dup_count} lignes en doublon sur '{dup_col}' (non supprimées automatiquement).")
            else:
                st.warning(f"⚠️ Colonne '{dup_col}' absente.")

        st.session_state.filtered_df = filtered_df
        st.dataframe(filtered_df.head(MAX_PREVIEW_ROWS), use_container_width=True)

# -------------------------
# TAB 4
# -------------------------
with tab4:
    st.subheader("Export")
    export_df = st.session_state.filtered_df

    if export_df is None:
        st.info("ℹ️ Aucune donnée à exporter.")
    elif export_df.empty:
        st.error("❌ Données filtrées vides.")
    else:
        st.write(f"{len(export_df)} lignes prêtes à exporter.")

        csv_bytes = export_csv_bytes(export_df)
        xlsx_bytes = export_excel_bytes(export_df)

        c1, c2 = st.columns(2)
        with c1:
            st.download_button(
                label="💾 Télécharger CSV",
                data=csv_bytes,
                file_name="export_leads.csv",
                mime="text/csv",
            )
        with c2:
            st.download_button(
                label="💾 Télécharger Excel",
                data=xlsx_bytes,
                file_name="export_leads.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        st.info("ℹ️ CSV en UTF-8-SIG, Excel en XLSX.")
'@ | Set-Content -LiteralPath ".\app (1).py" -Encoding UTF8

Write-Host "OK: fichier '.\app (1).py' remplacé."
