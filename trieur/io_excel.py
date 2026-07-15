"""Lecture des fichiers Excel et Google Sheets (multi-onglets)."""
import io
import re
import urllib.parse
import urllib.request

import pandas as pd
import streamlit as st

from trieur.matching import (
    apply_header_inference_excel,
    infer_column_names,
    looks_like_header,
)


def _collect_sheets(all_sheets_dict):
    """Nettoie un dict {nom: df} : retire les onglets/colonnes vides."""
    sheets = {}
    if all_sheets_dict:
        for sheet_name, df in all_sheets_dict.items():
            if df is not None and len(df) > 0:
                df = df.dropna(axis=1, how="all")
                if len(df.columns) > 0 and len(df) > 0:
                    sheets[sheet_name] = df
    return sheets


def read_excel_all_sheets_from_file(file_obj, filename):
    """
    Lire TOUS les onglets d'un fichier Excel uploadé.
    Retourne un dictionnaire {nom_feuille: dataframe}.

    [PERF v4.1] On essaie d'abord le moteur "calamine" (python-calamine),
    ~3x plus rapide et plus econome en memoire qu'openpyxl sur les gros
    fichiers. S'il n'est pas installe (ou echoue), on retombe sur openpyxl
    puis sur le moteur par defaut : aucune regression.
    """
    # 1) Moteurs rapides : tous les onglets d'un coup
    for engine in ("calamine", "openpyxl"):
        try:
            file_obj.seek(0)
            sheets = _collect_sheets(
                pd.read_excel(file_obj, sheet_name=None, dtype=str, engine=engine)
            )
            if sheets:
                return sheets
        except Exception:
            continue

    # 2) Repli robuste : onglet par onglet (openpyxl puis moteur par defaut),
    #    pour ignorer un onglet corrompu isole.
    for engine in ("openpyxl", None):
        try:
            file_obj.seek(0)
            xls = pd.ExcelFile(file_obj, engine=engine) if engine else pd.ExcelFile(file_obj)
            sheets = {}
            for sheet_name in xls.sheet_names:
                try:
                    df = xls.parse(sheet_name=sheet_name, dtype=str)
                    if df is not None and len(df) > 0:
                        df = df.dropna(axis=1, how="all")
                        if len(df.columns) > 0 and len(df) > 0:
                            sheets[sheet_name] = df
                except Exception:
                    continue
            if sheets:
                return sheets
        except Exception:
            continue

    st.error(f"❌ Impossible de lire {filename}: format non reconnu.")
    return {}

def read_csv_file(file_obj, filename):
    """
    [GROS FICHIERS] Lit un fichier CSV importe (un seul 'onglet').

    Lire un CSV est bien plus rapide et econome en memoire qu'un .xlsx : c'est
    la voie recommandee pour les tres gros volumes (plusieurs millions de
    lignes). On :
      - detecte le separateur ( , ; ou tabulation ) sur la 1re ligne
      - detecte l'encodage (utf-8 puis latin-1, jamais d'echec)
      - lit tout en texte (dtype=str) pour garder les zeros initiaux (CP, tel)
      - deduit les noms de colonnes si la 1re ligne est en fait des donnees

    Retourne (sheets, inferred) : meme forme que la lecture Excel, pour que la
    suite du pipeline (mapping, construction) soit identique.
    """
    sheet_name = re.sub(r"\.csv$", "", filename, flags=re.IGNORECASE) or filename

    # Separateur : deduit d'un echantillon decode en latin-1 (ne plante jamais)
    file_obj.seek(0)
    head = file_obj.read(65536)
    file_obj.seek(0)
    sample = head.decode("latin-1", "replace") if isinstance(head, bytes) else str(head)
    first_line = next((ln for ln in sample.splitlines() if ln.strip()), "")
    counts = {",": first_line.count(","), ";": first_line.count(";"), "\t": first_line.count("\t")}
    sep = max(counts, key=counts.get) if max(counts.values()) > 0 else ","

    def _read(header, encoding):
        file_obj.seek(0)
        return pd.read_csv(
            file_obj, dtype=str, sep=sep, encoding=encoding,
            header=header, on_bad_lines="skip", low_memory=False,
        )

    df = None
    used_enc = "utf-8-sig"
    for enc in ("utf-8-sig", "latin-1"):
        try:
            df = _read("infer", enc)
            used_enc = enc
            break
        except UnicodeDecodeError:
            continue
        except Exception:
            # Dernier recours : laisser pandas sniffer le separateur (plus lent)
            try:
                file_obj.seek(0)
                df = pd.read_csv(file_obj, dtype=str, sep=None, engine="python",
                                 encoding=enc, on_bad_lines="skip")
                used_enc = enc
                break
            except Exception:
                continue

    if df is None:
        st.error(f"❌ Impossible de lire le CSV {filename}.")
        return {}, []

    df = df.dropna(axis=1, how="all")
    if len(df) == 0 or len(df.columns) == 0:
        return {}, []

    inferred = []
    if not looks_like_header(df):
        try:
            raw = _read(None, used_enc).dropna(axis=1, how="all")
            if len(raw) > 0 and len(raw.columns) > 0:
                raw.columns = infer_column_names(raw)
                df = raw
                inferred.append(sheet_name)
        except Exception:
            pass

    return {sheet_name: df}, inferred


def _extract_sheet_id(url):
    """Extrait l'identifiant du classeur depuis une URL Google Sheets."""
    if "/edit" in url:
        url = url.split("/edit")[0]
    if url.endswith("/"):
        url = url[:-1]
    if "/d/" not in url:
        return None
    return url.split("/d/")[1].split("/")[0]


def _name_from_content_disposition(header_value):
    """Extrait le vrai nom du classeur depuis l'en-tete Content-Disposition.
    Ex: 'attachment; filename="AZ.xlsx"; filename*=UTF-8''AZ.xlsx' -> 'AZ'."""
    if not header_value:
        return None
    # filename*=UTF-8''... (RFC 5987) prioritaire car gere l'unicode
    m = re.search(r"filename\*=(?:UTF-8'')?([^;]+)", header_value, re.IGNORECASE)
    if not m:
        m = re.search(r'filename="?([^";]+)"?', header_value, re.IGNORECASE)
    if not m:
        return None
    name = urllib.parse.unquote(m.group(1)).strip().strip('"')
    name = re.sub(r"\.(xlsx|xls|csv)$", "", name, flags=re.IGNORECASE)
    return name or None


def _read_google_via_xlsx(sheet_id):
    """
    [PERF point 4] Telecharge TOUT le classeur en UNE seule requete (export
    xlsx). Recupere tous les onglets par leur vrai nom, quels que soient
    leurs gid (les gid Google ne sont pas sequentiels des qu'un onglet a ete
    supprime/reordonne : l'ancienne boucle 0..50 les ratait).

    Retourne (sheets, inferred, nom_du_classeur) ou None si le telechargement
    echoue / n'est pas un vrai xlsx (feuille non publique -> repli CSV).
    """
    xlsx_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
    try:
        with urllib.request.urlopen(xlsx_url, timeout=20) as resp:
            # Le vrai nom du classeur Google est dans l'en-tete Content-Disposition.
            source_name = _name_from_content_disposition(
                resp.headers.get("Content-Disposition", "")
            )
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
    return sheets, inferred, (source_name or "Google Sheets")


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
    Retourne (onglets, [onglets a en-tete deduite], nom_du_classeur).

    Strategie : 1 seule requete (export xlsx complet) ; repli sur l'ancienne
    methode CSV onglet par onglet si l'export xlsx echoue.
    """
    try:
        sheet_id = _extract_sheet_id(url)
        if not sheet_id:
            return {}, [], "Google Sheets"

        primary = _read_google_via_xlsx(sheet_id)
        if primary is not None and primary[0]:
            return primary  # (sheets, inferred, source_name)

        sheets, inferred = _read_google_via_gid_csv(sheet_id)
        return sheets, inferred, "Google Sheets"
    except Exception as e:
        st.error(f"❌ Erreur Google Sheets: {str(e)}")
        return {}, [], "Google Sheets"


def is_google_sheet_url(text):
    t = str(text).strip().lower()
    return "docs.google.com/spreadsheets" in t
