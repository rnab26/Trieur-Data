"""Lecture des fichiers Excel et Google Sheets (multi-onglets)."""
import io
import urllib.request

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

def _extract_sheet_id(url):
    """Extrait l'identifiant du classeur depuis une URL Google Sheets."""
    if "/edit" in url:
        url = url.split("/edit")[0]
    if url.endswith("/"):
        url = url[:-1]
    if "/d/" not in url:
        return None
    return url.split("/d/")[1].split("/")[0]


def _read_google_via_xlsx(sheet_id):
    """
    [PERF point 4] Telecharge TOUT le classeur en UNE seule requete (export
    xlsx). Recupere tous les onglets par leur vrai nom, quels que soient
    leurs gid (les gid Google ne sont pas sequentiels des qu'un onglet a ete
    supprime/reordonne : l'ancienne boucle 0..50 les ratait).

    Retourne (sheets, inferred) ou None si le telechargement echoue / n'est
    pas un vrai xlsx (feuille non publique -> on retombe sur la methode CSV).
    """
    xlsx_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
    try:
        with urllib.request.urlopen(xlsx_url, timeout=20) as resp:
            content = resp.read()
    except Exception:
        return None

    # Un vrai .xlsx est une archive ZIP -> commence par 'PK'. Si Google renvoie
    # une page d'erreur HTML (acces refuse), on echoue proprement sans afficher
    # d'erreur (le repli CSV prendra le relais).
    if not content[:2] == b"PK":
        return None

    bio = io.BytesIO(content)
    sheets = read_excel_all_sheets_from_file(bio, "Google Sheets")
    if not sheets:
        return None
    sheets, inferred = apply_header_inference_excel(sheets, bio)
    return sheets, inferred


def _read_google_via_gid_csv(sheet_id):
    """
    Repli : ancienne methode CSV onglet par onglet (gid 0..49).
    Conservee telle quelle pour garantir zero regression si l'export xlsx
    n'est pas disponible.
    """
    inferred = []
    all_sheets = {}
    for gid in range(0, 50):
        try:
            csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
            df = pd.read_csv(csv_url, dtype=str)
            if len(df) > 0 and not df.isnull().all().all():
                sheet_name = f"Sheet{gid+1}" if gid > 0 else "Sheet1"

                # [2] En-tete absente : relecture sans en-tete + noms deduits.
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


def read_google_sheets_all_sheets(url):
    """
    Lire Google Sheets avec tous les onglets détectés.
    Retourne (onglets, [noms des onglets dont l'en-tete a ete deduite]).

    Strategie : 1 seule requete (export xlsx complet) ; repli sur l'ancienne
    methode CSV onglet par onglet si l'export xlsx echoue.
    """
    try:
        sheet_id = _extract_sheet_id(url)
        if not sheet_id:
            return {}, []

        primary = _read_google_via_xlsx(sheet_id)
        if primary is not None and primary[0]:
            return primary

        return _read_google_via_gid_csv(sheet_id)
    except Exception as e:
        st.error(f"❌ Erreur Google Sheets: {str(e)}")
        return {}, []


def is_google_sheet_url(text):
    t = str(text).strip().lower()
    return "docs.google.com/spreadsheets" in t
