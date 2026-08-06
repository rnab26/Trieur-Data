import hashlib
import io
import json
from typing import Dict, Iterable, List, Tuple

import pandas as pd
import streamlit as st

from trieur.io_excel import (
    apply_header_inference_excel,
    read_csv_file,
    read_excel_all_sheets_from_file,
    read_google_sheets_all_sheets,
)
from trieur.io_pdf import read_pdf_sepa

SerializedSheet = Tuple[str, str]
SerializedMappingItems = Tuple[Tuple[str, str], ...]
SerializedMapping = Tuple[str, SerializedMappingItems]


class _MemoryUpload(io.BytesIO):
    def __init__(self, data: bytes, name: str):
        super().__init__(data)
        self.name = name
        self.size = len(data)


def normalize_google_url(url: str) -> str:
    return (url or "").strip()


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content or b"").hexdigest()


def local_upload_signature(name: str, size: int, content: bytes) -> Tuple[str, int, str]:
    safe_name = str(name or "")
    safe_size = int(len(content or b""))
    return safe_name, safe_size, sha256_bytes(content or b"")


def input_signature(
    upload_signatures: Iterable[Tuple[str, int, str]],
    google_url: str,
) -> Tuple:
    # Trier par (nom, hash) pour que l'ordre des fichiers n'affecte pas la signature.
    sorted_sigs = tuple(sorted(upload_signatures, key=lambda s: (s[0], s[2])))
    return sorted_sigs + (("__google__", normalize_google_url(google_url)),)


def serialize_sheets_for_build(active_sheets: Dict[str, pd.DataFrame]) -> Tuple[SerializedSheet, ...]:
    out: List[Tuple[str, str]] = []
    for sheet_key in sorted(active_sheets.keys()):
        df = active_sheets[sheet_key]
        out.append((sheet_key, df.to_json(orient="split", date_format="iso")))
    return tuple(out)


def serialize_mappings_for_build(mappings: Dict[str, Dict[str, str]]) -> Tuple[SerializedMapping, ...]:
    out = []
    for sheet_key in sorted(mappings.keys()):
        items = tuple(sorted((str(k), str(v)) for k, v in mappings[sheet_key].items()))
        out.append((sheet_key, items))
    return tuple(out)


def rebuild_key(
    loaded_signature,
    active_sheet_keys: Iterable[str],
    effective_mappings: Dict[str, Dict[str, str]],
    master_columns: Iterable[str],
) -> str:
    payload = {
        "loaded_signature": loaded_signature,
        "active_sheet_keys": sorted([str(x) for x in active_sheet_keys]),
        "mappings": {
            str(k): {str(sk): str(sv) for sk, sv in sorted(v.items())}
            for k, v in sorted(effective_mappings.items())
        },
        "master_columns": [str(c) for c in master_columns],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@st.cache_data(show_spinner=False, max_entries=200, hash_funcs={bytes: lambda _: ""})
def _parse_uploaded_file_by_hash(file_name: str, file_hash: str, file_bytes: bytes) -> Tuple[Dict[str, pd.DataFrame], List[str]]:
    up = _MemoryUpload(file_bytes, file_name)
    lower = str(file_name or "").lower()
    if lower.endswith(".csv"):
        return read_csv_file(up, file_name)
    if lower.endswith(".pdf"):
        return read_pdf_sepa(up, file_name)
    sheets = read_excel_all_sheets_from_file(up, file_name)
    return apply_header_inference_excel(sheets, up)


def parse_uploaded_file_cached(file_name: str, file_bytes: bytes) -> Tuple[Dict[str, pd.DataFrame], List[str]]:
    file_hash = sha256_bytes(file_bytes)
    return _parse_uploaded_file_by_hash(file_name, file_hash, file_bytes)


@st.cache_data(show_spinner=False)
def parse_google_sheets_cached(google_url: str) -> Tuple[Dict[str, pd.DataFrame], List[str], str]:
    return read_google_sheets_all_sheets(google_url)


@st.cache_data(show_spinner=False)
def build_final_df_cached(
    serialized_sheets: Tuple[SerializedSheet, ...],
    serialized_mappings: Tuple[SerializedMapping, ...],
    master_columns: Tuple[str, ...],
) -> pd.DataFrame:
    sheets = {
        sheet_key: pd.read_json(io.StringIO(df_json), orient="split")
        for sheet_key, df_json in serialized_sheets
    }
    mappings = {
        sheet_key: dict(mapping_items)
        for sheet_key, mapping_items in serialized_mappings
    }

    rows = []
    for sheet_key, sheet_df in sheets.items():
        if "__source_file__" in sheet_df.columns and len(sheet_df) > 0:
            source_file = sheet_df["__source_file__"].iloc[0]
        else:
            source_file = sheet_key
        if "__source_sheet__" in sheet_df.columns and len(sheet_df) > 0:
            source_sheet = sheet_df["__source_sheet__"].iloc[0]
        else:
            source_sheet = "Unknown"
        mapping = mappings.get(sheet_key, {})

        assigned_cols = [m for m in mapping.values() if m != "(non assigne)"]
        if not assigned_cols:
            continue

        sub = pd.DataFrame(index=sheet_df.index)
        for master_col in master_columns:
            src_cols_for_master = [s for s, m in mapping.items() if m == master_col and s in sheet_df.columns]
            if master_col == "Source Data":
                sub[master_col] = f"{source_file} ({source_sheet})"
            elif not src_cols_for_master:
                sub[master_col] = None
            elif len(src_cols_for_master) == 1:
                sub[master_col] = sheet_df[src_cols_for_master[0]]
            else:
                combined = sheet_df[src_cols_for_master[0]].copy()
                for extra_col in src_cols_for_master[1:]:
                    is_empty = combined.isna() | (combined.astype(str).str.strip() == "")
                    combined = combined.where(~is_empty, sheet_df[extra_col])
                sub[master_col] = combined
        rows.append(sub)

    if not rows:
        return pd.DataFrame()
    final_df = pd.concat(rows, ignore_index=True)
    return final_df.dropna(how="all")


def dataframe_content_hash(df: pd.DataFrame) -> str:
    payload = df.to_json(orient="split", date_format="iso", force_ascii=False, default_handler=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
