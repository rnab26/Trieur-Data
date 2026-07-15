"""Export CSV / Excel et nettoyage du nom de fichier."""
import io
import re

import pandas as pd
import streamlit as st


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


def sanitize_filename(name, default="export_leads"):
    """Nettoie un nom de fichier saisi par l'utilisateur (sans extension)."""
    name = str(name).strip()
    if not name:
        return default
    # retirer une extension eventuelle
    name = re.sub(r"\.(csv|xlsx|xls)$", "", name, flags=re.IGNORECASE)
    # remplacer les caracteres interdits
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = name.strip().strip(".")
    return name if name else default
