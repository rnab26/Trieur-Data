import io, re, time, unicodedata
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Trieur de Fichiers Leads", layout="wide")

DEFAULT_MASTER_COLUMNS = [
    "NOM","PRENOM","GENRE/CIVILITE","VILLE","CP","ADRESSE",
    "TELEPHONE MOBILE","TELEPHONE FIXE","EMAIL","DATE DE NAISSANCE","Source Data",
]
SYNONYMES = {
    "NOM":["nom","lastname","surname","last_name","family_name","patronyme"],
    "PRENOM":["prenom","prénom","firstname","first_name","given_name"],
    "GENRE/CIVILITE":["genre","civilite","civilité","sexe","sex","title","salutation"],
    "VILLE":["ville","city","commune","locality"],
    "CP":["cp","codepostal","code_postal","postalcode","zipcode","zip","postal"],
    "ADRESSE":["adresse","address","rue","street","location"],
    "TELEPHONE MOBILE":["telephoneportable","portable","mobile","gsm","cell","cellphone","phone_mobile"],
    "TELEPHONE FIXE":["telephonefixe","fixe","phone","homephone","landline","phone_fixe"],
    "EMAIL":["email","e-mail","mail","courriel","e_mail"],
    "DATE DE NAISSANCE":["datedenaissance","date_naissance","naissance","dob","birthdate","birthday","birth_date"],
    "Source Data":["source","fichier","file","origin"],
}
PREVIEW_ROWS, DISPLAY_ROWS, FUZZY_THRESHOLD, MAX_AUTO_COLUMNS_PER_SHEET = 7, 50, 0.65, 300

def _init_state():
    d = {
        "master_columns": DEFAULT_MASTER_COLUMNS.copy(),
        "all_sheets": {}, "sheet_mappings": {},
        "final_df": None, "filtered_df": None,
        "invalid_rows_count": 0, "last_build_ms": 0
    }
    for k,v in d.items():
        if k not in st.session_state: st.session_state[k] = v
_init_state()

def normalize_text(text: object) -> str:
    if text is None or (isinstance(text,float) and np.isnan(text)): return ""
    t = str(text).lower().strip()
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[\s\-_/.]", "", t)
    t = re.sub(r"[^a-z0-9]", "", t)
    return t

def _safe_str_series(s: pd.Series) -> pd.Series:
    return s.astype("string").fillna("").str.strip()

def find_best_master_col(src_col: str, master_cols: List[str]) -> Optional[str]:
    src = normalize_text(src_col)
    if not src: return None
    for m in master_cols:
        if normalize_text(m) == src: return m
    for m in master_cols:
        if any(normalize_text(s) == src for s in SYNONYMES.get(m, [])): return m
    best, score = None, FUZZY_THRESHOLD
    for m in master_cols:
        sc = SequenceMatcher(None, src, normalize_text(m)).ratio()
        if sc > score: best, score = m, sc
    return best

def is_google_sheet_url(text: object) -> bool:
    return "docs.google.com/spreadsheets" in str(text).strip().lower()

def normalize_cp(v: object) -> Optional[str]:
    s = str(v).strip().split(".")[0]
    if not s.isdigit(): return None
    if len(s) == 4: s = "0"+s
    return s if len(s)==5 else None

def cp_matches_prefix(cp_value: object, prefixes: set) -> bool:
    cp5 = normalize_cp(cp_value)
    return bool(cp5 and cp5[:2] in prefixes)

def _empty_df() -> pd.DataFrame: return pd.DataFrame()

def _safe_unique_values(df: pd.DataFrame, col: str, max_items=2000) -> List[str]:
    if col not in df.columns: return []
    vals = df[col].dropna().astype(str).str.strip()
    vals = vals[vals!=""].unique().tolist()
    vals = sorted(vals)
    return vals[:max_items]

@st.cache_data(show_spinner=False, ttl=1800)
def _excel_sheet_names(file_bytes: bytes, filename: str) -> List[str]:
    xls = pd.ExcelFile(io.BytesIO(file_bytes), engine="openpyxl")
    return xls.sheet_names

@st.cache_data(show_spinner=False, ttl=1800)
def _read_excel_sheet(file_bytes: bytes, filename: str, sheet_name: str) -> pd.DataFrame:
    bio = io.BytesIO(file_bytes)
    try: df = pd.read_excel(bio, sheet_name=sheet_name, dtype=str, engine="openpyxl")
    except Exception:
        bio.seek(0); df = pd.read_excel(bio, sheet_name=sheet_name, dtype=str)
    if df is None or len(df)==0: return _empty_df()
    df = df.dropna(how="all")
    if len(df)==0: return _empty_df()
    df.columns = [str(c).strip() for c in df.columns]
    return df

@st.cache_data(show_spinner=False, ttl=900)
def _read_google_sheet_gid(sheet_id: str, gid: int) -> pd.DataFrame:
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
    try: df = pd.read_csv(url, dtype=str)
    except Exception: return _empty_df()
    if df is None or len(df)==0 or df.isnull().all().all(): return _empty_df()
    df = df.dropna(how="all")
    if len(df)==0: return _empty_df()
    df.columns = [str(c).strip() for c in df.columns]
    return df

def _extract_google_sheet_id(url: str) -> Optional[str]:
    u = str(url).strip()
    if "/edit" in u: u = u.split("/edit")[0]
    if u.endswith("/"): u = u[:-1]
    if "/d/" not in u: return None
    try: return u.split("/d/")[1].split("/")[0]
    except Exception: return None

def export_csv_safe(df: pd.DataFrame) -> Optional[bytes]:
    try:
        d = df.copy()
        for c in d.columns: d[c] = d[c].astype(str)
        return d.to_csv(index=False, sep=",").encode("utf-8-sig")
    except Exception as e:
        st.error(f"❌ Erreur CSV: {e}"); return None

def export_excel_safe(df: pd.DataFrame) -> Optional[io.BytesIO]:
    try:
        buf = io.BytesIO()
        try:
            with pd.ExcelWriter(buf, engine="xlsxwriter") as w:
                df.to_excel(w, index=False, sheet_name="Leads")
                if "CP" in df.columns:
                    fmt = w.book.add_format({"num_format":"@"})
                    i = df.columns.get_loc("CP")
                    w.sheets["Leads"].set_column(i, i, 12, fmt)
        except Exception:
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as w:
                df.to_excel(w, index=False, sheet_name="Leads")
        buf.seek(0); return buf
    except Exception as e:
        st.error(f"❌ Erreur Excel: {e}"); return None

@st.cache_data(show_spinner=False, ttl=1800)
def auto_map_columns(real_columns: Tuple[str,...], master_columns: Tuple[str,...]) -> Dict[str,str]:
    m = {}
    cols = list(real_columns)[:MAX_AUTO_COLUMNS_PER_SHEET]
    for c in cols:
        b = find_best_master_col(c, list(master_columns))
        m[c] = b if b else "(non assigne)"
    for c in list(real_columns)[MAX_AUTO_COLUMNS_PER_SHEET:]:
        m[c] = "(non assigne)"
    return m

def _sanitize_mapping(mapping: Dict[str,str], master_cols: List[str]) -> Dict[str,str]:
    valid = set(["(non assigne)"] + master_cols)
    return {k: (v if v in valid else "(non assigne)") for k,v in mapping.items()}

@st.cache_data(show_spinner=True, ttl=1800)
def build_final_df_cached(
    sheet_keys: Tuple[str,...],
    sheet_payloads: Tuple[Tuple[str,bytes,str],...],
    mappings_payload: Tuple[Tuple[str,Tuple[Tuple[str,str],...]],...],
    master_cols: Tuple[str,...],
) -> Tuple[pd.DataFrame,int]:
    mapping_dict = {k: dict(v) for k,v in mappings_payload}
    master, rows, invalid_rows = list(master_cols), [], 0

    for sheet_key, file_bytes, sheet_ref in sheet_payloads:
        if sheet_key.startswith("Google Sheets("):
            try:
                gid = int(sheet_ref)
                m = re.search(r"Google Sheets\((.*?)\) ::", sheet_key)
                if not m: 
                    continue
                sid = m.group(1)
                df = _read_google_sheet_gid(sid, gid)
                source_file, source_sheet = "Google Sheets", (f"Sheet{gid+1}" if gid>0 else "Sheet1")
            except Exception:
                continue
        else:
            filename = sheet_key.split(" :: ")[0]
            df = _read_excel_sheet(file_bytes, filename, sheet_ref)
            source_file, source_sheet = filename, sheet_ref

        if df is None or len(df)==0: continue
        before = len(df); df = df.dropna(how="all")
        invalid_rows += max(0, before-len(df))
        if len(df)==0: continue

        mapping = mapping_dict.get(sheet_key, {})
        if not [x for x in mapping.values() if x!="(non assigne)"]: continue

        sub = pd.DataFrame(index=df.index)
        for mc in master:
            srcs = [s for s,m in mapping.items() if m==mc and s in df.columns]
            if mc=="Source Data":
                sub[mc] = f"{source_file} ({source_sheet})"
            elif not srcs:
                sub[mc] = None
            else:
                comb = _safe_str_series(df[srcs[0]])
                for ex in srcs[1:]:
                    add = _safe_str_series(df[ex]); comb = comb.where(comb!="", add)
                sub[mc] = comb
        rows.append(sub)

    if not rows: return _empty_df(), invalid_rows
    out = pd.concat(rows, ignore_index=True).dropna(how="all")
    for c in out.columns: out[c] = out[c].astype("string").fillna("").str.strip()
    return out, invalid_rows

st.title("Trieur de Fichiers Leads")
st.caption("Import Excel/Google Sheets → mapping colonnes → aperçu → filtrage → export")

tab1, tab2, tab3, tab4 = st.tabs(["1. Colonnes maîtres","2. Import et Mapping","3. Filtrage & Dedup","4. Export"])

with tab1:
    st.subheader("Gérer vos colonnes maîtres")
    cols_text = st.text_area("Colonnes maîtres", value="\n".join(st.session_state.master_columns), height=250)
    if st.button("Enregistrer la liste des colonnes maîtres"):
        new_list = [c.strip() for c in cols_text.split("\n") if c.strip()]
        if new_list:
            st.session_state.master_columns = new_list
            st.success(f"{len(new_list)} colonnes maîtres enregistrées.")
        else:
            st.error("❌ Veuillez entrer au moins une colonne maître.")

with tab2:
    st.subheader("Importer vos fichiers Excel ou Google Sheets")
    files = st.file_uploader("Déposez un ou plusieurs fichiers Excel", type=["xlsx","xls"], accept_multiple_files=True)
    google_url = st.text_input("Ou collez une URL Google Sheets publique (optionnel)")

    if st.button("Charger les sources", type="primary"):
        all_sheets, rows_total = {}, 0

        if files:
            for f in files:
                try:
                    b = f.getvalue()
                    sheet_names = _excel_sheet_names(b, f.name)
                except Exception as e:
                    st.error(f"❌ Erreur lecture {f.name}: {e}"); continue
                for sn in sheet_names:
                    df = _read_excel_sheet(b, f.name, sn)
                    if df is None or len(df)==0: continue
                    d = df.copy()
                    d["__source_file__"], d["__source_sheet__"] = f.name, sn
                    d["__file_bytes__"], d["__sheet_ref__"] = b, sn
                    all_sheets[f"{f.name} :: {sn}"] = d
                    rows_total += len(d)

        if google_url.strip() and is_google_sheet_url(google_url):
            sid = _extract_google_sheet_id(google_url)
            if not sid: st.warning("⚠️ URL Google Sheets invalide.")
            else:
                found = 0
                for gid in range(0, 50):
                    df = _read_google_sheet_gid(sid, gid)
                    if df is None or len(df)==0: continue
                    sheet = f"Sheet{gid+1}" if gid>0 else "Sheet1"
                    d = df.copy()
                    d["__source_file__"], d["__source_sheet__"] = "Google Sheets", sheet
                    d["__file_bytes__"], d["__sheet_ref__"] = b"", str(gid)
                    all_sheets[f"Google Sheets({sid}) :: {sheet}"] = d
                    rows_total += len(d); found += 1
                if found: st.success(f"✅ Google Sheets importé ({found} onglet(s)).")
                else: st.warning("⚠️ Impossible de lire le Google Sheets.")

        if all_sheets:
            st.session_state.all_sheets = all_sheets
            st.session_state.sheet_mappings = {
                k: _sanitize_mapping(v, st.session_state.master_columns)
                for k, v in st.session_state.sheet_mappings.items()
            }
            st.success(f"{len(set(k.split(' :: ')[0] for k in all_sheets))} fichier(s), {len(all_sheets)} onglet(s), {rows_total} lignes.")
        else:
            st.info("ℹ️ Aucune source valide chargée.")

    all_sheets = st.session_state.all_sheets
    if all_sheets:
        for sheet_key, sheet_df in all_sheets.items():
            st.markdown(f"### 📄 {sheet_key}")
            real_cols = [c for c in sheet_df.columns if not c.startswith("__")]
            st.write(f"**Résumé :** {len(sheet_df)} lignes | {len(real_cols)} colonnes | {sheet_df[real_cols].duplicated().sum() if real_cols else 0} doublons")

            if sheet_key not in st.session_state.sheet_mappings:
                st.session_state.sheet_mappings[sheet_key] = {}
            st.session_state.sheet_mappings[sheet_key] = _sanitize_mapping(
                st.session_state.sheet_mappings[sheet_key], st.session_state.master_columns
            )

            if st.button("🚀 Auto", key=f"auto_{sheet_key}"):
                st.session_state.sheet_mappings[sheet_key] = auto_map_columns(tuple(real_cols), tuple(st.session_state.master_columns))
                st.rerun()

            updated = {}
            if real_cols:
                cols = st.columns(min(len(real_cols), 8))
                for i, src in enumerate(real_cols):
                    with cols[i % len(cols)]:
                        cur = st.session_state.sheet_mappings[sheet_key].get(src, "(non assigne)")
                        used = {updated.get(c,"") for c in real_cols if c!=src and updated.get(c,"")}
                        opts = ["(non assigne)"] + [m for m in st.session_state.master_columns if m not in used]
                        if cur not in opts: cur = "(non assigne)"
                        idx = opts.index(cur) if cur in opts else 0
                        updated[src] = st.selectbox(src, opts, index=idx, key=f"map_{sheet_key}_{src}")
            st.session_state.sheet_mappings[sheet_key] = updated
            st.dataframe(sheet_df[real_cols].head(PREVIEW_ROWS), use_container_width=True)
            st.markdown("---")

        any_assigned = any(
            any(v != "(non assigne)" for v in m.values())
            for m in st.session_state.sheet_mappings.values()
        )

        if not any_assigned:
            st.warning("⚠️ Assigne au moins une colonne maître.")
        elif st.button("✅ Construire la base de travail fusionnée", type="primary"):
            t0 = time.perf_counter()
            sheet_payloads, mappings_payload = [], []
            for k, d in all_sheets.items():
                b = d["__file_bytes__"].iloc[0] if "__file_bytes__" in d.columns and len(d)>0 else b""
                r = str(d["__sheet_ref__"].iloc[0]) if "__sheet_ref__" in d.columns and len(d)>0 else ""
                sheet_payloads.append((k,b,r))
            for k,m in st.session_state.sheet_mappings.items():
                mappings_payload.append((k, tuple(sorted(m.items()))))

            out, bad = build_final_df_cached(
                sheet_keys=tuple(all_sheets.keys()),
                sheet_payloads=tuple(sheet_payloads),
                mappings_payload=tuple(mappings_payload),
                master_cols=tuple(st.session_state.master_columns),
            )
            st.session_state.final_df = out if len(out)>0 else None
            st.session_state.invalid_rows_count = bad
            st.session_state.last_build_ms = int((time.perf_counter()-t0)*1000)

            if st.session_state.final_df is None:
                st.error("❌ Base vide après nettoyage.")
            else:
                st.success(f"✅ Base construite : {len(out)} lignes | invalides ignorées: {bad} | {st.session_state.last_build_ms} ms")
                st.dataframe(out.head(DISPLAY_ROWS), use_container_width=True)
    else:
        st.info("ℹ️ Importe un fichier pour continuer.")

with tab3:
    st.subheader("Filtrage")
    if st.session_state.final_df is None:
        st.info("ℹ️ Construis la base dans l’onglet 2.")
    else:
        df = st.session_state.final_df.copy()
        st.write(f"Base actuelle : **{len(df)}** lignes")
        opts = ["(aucun filtre)"] + [c for c in st.session_state.master_columns if c in df.columns]
        col = st.selectbox("Filtrer par colonne", opts, index=0)
        filt = df

        if col == "CP" and "CP" in df.columns:
            dep = st.text_input("Départements (ex: 02,33,77)")
            if dep.strip():
                prefixes = set(p.strip().zfill(2) for p in dep.split(",") if p.strip())
                filt = df[df["CP"].apply(lambda v: cp_matches_prefix(v, prefixes))]
        elif col != "(aucun filtre)" and col in df.columns:
            vals = _safe_unique_values(df, col)
            sel = st.multiselect(f"Valeurs à conserver pour {col}", vals)
            if sel: filt = df[df[col].isin(sel)]

        st.write(f"Résultat : **{len(filt)}** lignes | **{filt.duplicated().sum()}** doublons")
        st.dataframe(filt.head(DISPLAY_ROWS), use_container_width=True)

        dup_opts = ["(aucune)"] + [c for c in st.session_state.master_columns if c in filt.columns]
        dup_col = st.selectbox("Colonne de détection doublons", dup_opts, index=0)
        if dup_col != "(aucune)" and dup_col in filt.columns:
            s = filt[dup_col].astype("string").fillna("")
            d = s[s!=""].duplicated(keep=False).sum()
            st.warning(f"{int(d)} lignes en doublon détectées sur '{dup_col}'.")

        st.session_state.filtered_df = filt

with tab4:
    st.subheader("Export")
    if st.session_state.filtered_df is None:
        st.info("ℹ️ Applique un filtre d’abord.")
    else:
        d = st.session_state.filtered_df
        if len(d)==0:
            st.error("❌ Aucune donnée à exporter.")
        else:
            st.write(f"{len(d)} lignes prêtes.")
            c1, c2 = st.columns(2)
            with c1:
                b = export_csv_safe(d)
                if b is not None:
                    st.download_button("💾 Télécharger CSV", data=b, file_name="export_leads.csv", mime="text/csv")
            with c2:
                x = export_excel_safe(d)
                if x is not None:
                    st.download_button("💾 Télécharger Excel", data=x, file_name="export_leads.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            st.info("ℹ️ Encodage UTF-8.")
