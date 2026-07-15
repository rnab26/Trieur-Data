"""Lecture des fichiers Excel et Google Sheets (multi-onglets)."""
import pandas as pd
import streamlit as st

from trieur.matching import (
    apply_header_inference_excel,
    infer_column_names,
    looks_like_header,
)


def read_excel_all_sheets_from_file(file_obj, filename):
    """
    Lire TOUS les onglets d'un fichier Excel uploadé.
    Retourne un dictionnaire {nom_feuille: dataframe}
    """
    sheets = {}
    try:
        all_sheets_dict = pd.read_excel(file_obj, sheet_name=None, dtype=str, engine="openpyxl")

        if all_sheets_dict:
            for sheet_name, df in all_sheets_dict.items():
                if df is not None and len(df) > 0:
                    df = df.dropna(axis=1, how='all')
                    if len(df.columns) > 0 and len(df) > 0:
                        sheets[sheet_name] = df

        return sheets

    except Exception:
        try:
            file_obj.seek(0)
            xls = pd.ExcelFile(file_obj, engine="openpyxl")

            for sheet_name in xls.sheet_names:
                try:
                    df = xls.parse(sheet_name=sheet_name, dtype=str)
                    if df is not None and len(df) > 0:
                        df = df.dropna(axis=1, how='all')
                        if len(df.columns) > 0 and len(df) > 0:
                            sheets[sheet_name] = df
                except Exception:
                    continue

            return sheets

        except Exception:
            try:
                file_obj.seek(0)
                xls = pd.ExcelFile(file_obj)

                for sheet_name in xls.sheet_names:
                    try:
                        df = xls.parse(sheet_name=sheet_name, dtype=str)
                        if df is not None and len(df) > 0:
                            df = df.dropna(axis=1, how='all')
                            if len(df.columns) > 0 and len(df) > 0:
                                sheets[sheet_name] = df
                    except Exception:
                        continue

                return sheets

            except Exception as e3:
                st.error(f"❌ Impossible de lire {filename}: {str(e3)}")
                return {}

def read_google_sheets_all_sheets(url):
    """
    Lire Google Sheets avec tous les onglets détectés.
    Retourne (onglets, [noms des onglets dont l'en-tete a ete deduite]).
    """
    inferred = []
    try:
        if "/edit" in url:
            url = url.split("/edit")[0]
        if url.endswith("/"):
            url = url[:-1]
        if "/d/" not in url:
            return {}, []

        sheet_id = url.split("/d/")[1].split("/")[0]
        all_sheets = {}

        for gid in range(0, 50):
            try:
                csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
                df = pd.read_csv(csv_url, dtype=str)
                if len(df) > 0 and not df.isnull().all().all():
                    sheet_name = f"Sheet{gid+1}" if gid > 0 else "Sheet1"

                    # [2] En-tete absente : on relit l'onglet sans en-tete pour
                    # ne perdre aucune ligne, puis on nomme d'apres le contenu.
                    if not looks_like_header(df):
                        try:
                            raw = pd.read_csv(csv_url, dtype=str, header=None)
                            raw = raw.dropna(axis=1, how="all")
                            if len(raw) > 0 and len(raw.columns) > 0:
                                raw.columns = infer_column_names(raw)
                                df = raw
                                inferred.append(sheet_name)
                        except Exception:
                            pass

                    all_sheets[sheet_name] = df
            except Exception:
                continue

        return all_sheets, inferred
    except Exception as e:
        st.error(f"❌ Erreur Google Sheets: {str(e)}")
        return {}, []


def is_google_sheet_url(text):
    t = str(text).strip().lower()
    return "docs.google.com/spreadsheets" in t
