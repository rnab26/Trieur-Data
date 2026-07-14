# =============================================================
# Trieur de Fichiers Leads
# VERSION 2.0
# Changements par rapport a la version precedente :
#   [2] Deduction des noms de colonnes quand la ligne d'en-tete est ABSENTE :
#       - looks_like_header() repere une "en-tete" qui est en fait une ligne
#         de donnees (emails, telephones, CP, nombres purs, motif "Unnamed:")
#       - dans ce cas l'onglet est relu SANS en-tete (aucune ligne perdue) et
#         les colonnes sont nommees d'apres leur CONTENU (EMAIL, TELEPHONE
#         MOBILE/FIXE, CP, DATE DE NAISSANCE, sinon COLONNE_1, COLONNE_2...)
#       - les noms deduits reprennent ceux des colonnes maitres, donc
#         l'auto-assignation les reconnait directement
#       - un avertissement liste les onglets concernes
#       - un fichier AVEC en-tete n'est pas touche (relecture uniquement si
#         l'en-tete est jugee absente)
#   [3] Exclusion de fichiers / onglets a l'import :
#       - cases "Inclure" par onglet, + une case par fichier qui bascule
#         tous ses onglets
#       - les onglets decoches sont retires du mapping ET de la base finale
#       - cocher/decocher ne relit AUCUN fichier (choix gardes en session)
#
# Rappel des versions precedentes :
#   [1] Detection telephone MOBILE / FIXE par le CONTENU (prefixes FR)
#   [6] Colonnes maitres PERSISTANTES (survivent au rechargement)
#   [8] Limite d'upload portee a 500 Mo (voir .streamlit/config.toml)
#   [9] Nom du fichier final personnalisable avant export (CSV / Excel)
#   [PERF 1.1] Correction de la lenteur d'auto-assignation :
#       - la detection telephone echantillonne AVANT traitement
#         (cout constant meme sur des colonnes de 1M lignes)
#       - le scan telephone ne se declenche que si une colonne maitre
#         telephone existe
#   [PERF 1.2] Fin des rechargements inutiles :
#       - les fichiers ne sont lus/parses qu'UNE fois (mise en cache par
#         signature nom+taille). Les assignations manuelles ne relancent
#         plus aucun chargement ni barre de progression.
#       - auto-assignation automatique de TOUS les onglets des l'import
#         (corrige le cas ou seul l'onglet 1 etait assigne).
# Aucune logique existante n'a ete supprimee.
# =============================================================

import streamlit as st
import pandas as pd
import numpy as np
import io
import os
import json
import unicodedata
import re
from difflib import SequenceMatcher

st.set_page_config(page_title="Trieur de Fichiers Leads", layout="wide")

APP_VERSION = "2.0"

DEFAULT_MASTER_COLUMNS = [
    "NOM", "PRENOM", "GENRE/CIVILITE", "VILLE", "CP", "ADRESSE",
    "TELEPHONE MOBILE", "TELEPHONE FIXE", "EMAIL", "DATE DE NAISSANCE", "Source Data"
]

SYNONYMES = {
    "NOM": ["nom", "lastname", "surname", "last_name", "family_name", "patronyme", "name", "nomclient", "clientname"],
    "PRENOM": ["prenom", "prénom", "firstname", "first_name", "given_name", "givenname", "prenomclient"],
    "GENRE/CIVILITE": ["genre", "civilite", "civilité", "sexe", "sex", "title", "salutation", "gender", "civ", "civil"],
    "VILLE": ["ville", "city", "commune", "locality", "town"],
    "CP": ["cp", "codepostal", "code_postal", "postalcode", "zipcode", "zip", "postal", "code", "postcode"],
    "ADRESSE": ["adresse", "address", "rue", "street", "location", "libellevoie", "voie", "numvoie", "numerovoie"],
    "TELEPHONE MOBILE": ["telephoneportable", "portable", "mobile", "gsm", "cell", "cellphone", "phone_mobile", "tel_mobile", "mobilephone", "phonenumbermobile"],
    "TELEPHONE FIXE": ["telephonefixe", "fixe", "phone", "homephone", "landline", "phone_fixe", "telephone", "telephonedomicile", "tel"],
    "EMAIL": ["email", "e-mail", "mail", "courriel", "e_mail", "mailcontact"],
    "DATE DE NAISSANCE": ["datedenaissance", "date_naissance", "naissance", "dob", "birthdate", "birthday", "datenaissance"],
    "Source Data": ["source", "fichier", "file", "origin", "sourcedata"]
}

# -------------------------------------------------------------
# [6] PERSISTANCE DES COLONNES MAITRES
# On sauvegarde la liste dans un petit fichier JSON a cote de l'app.
# -> survit au rechargement de la page (F5) tant que l'instance tourne.
# Note : sur Streamlit Cloud, le fichier est reinitialise lors d'un
# redeploiement/reboot. Pour un defaut PERMANENT, modifier
# DEFAULT_MASTER_COLUMNS ci-dessus.
# -------------------------------------------------------------
MASTER_CONFIG_PATH = "user_master_columns.json"

def load_master_columns():
    try:
        if os.path.exists(MASTER_CONFIG_PATH):
            with open(MASTER_CONFIG_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            cols = data.get("master_columns")
            if isinstance(cols, list) and cols:
                cleaned = [str(c).strip() for c in cols if str(c).strip()]
                if cleaned:
                    return cleaned
    except Exception:
        pass
    return DEFAULT_MASTER_COLUMNS.copy()

def save_master_columns(cols):
    try:
        with open(MASTER_CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump({"master_columns": cols}, fh, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


# -------------------------------------------------------------
# INITIALISATION SESSION
# -------------------------------------------------------------
if "master_columns" not in st.session_state:
    st.session_state.master_columns = load_master_columns()
if "all_sheets" not in st.session_state:
    st.session_state.all_sheets = {}
if "sheet_mappings" not in st.session_state:
    st.session_state.sheet_mappings = {}
if "final_df" not in st.session_state:
    st.session_state.final_df = None
if "filtered_df" not in st.session_state:
    st.session_state.filtered_df = None
if "export_mode" not in st.session_state:
    st.session_state.export_mode = "fusionné"
if "export_name_base" not in st.session_state:
    st.session_state.export_name_base = ""
if "auto_assign_triggered" not in st.session_state:
    st.session_state.auto_assign_triggered = {}
# [3] Onglets exclus par l'utilisateur (cles "fichier :: onglet")
if "excluded_sheets" not in st.session_state:
    st.session_state.excluded_sheets = set()
# [2] Onglets dont l'en-tete a ete deduite (pour prevenir l'utilisateur)
if "inferred_header_sheets" not in st.session_state:
    st.session_state.inferred_header_sheets = []


def normalize_text(text):
    """Normaliser un texte : minuscules, accents, espaces, caractères spéciaux"""
    text = str(text).lower().strip()
    text = unicodedata.normalize('NFKD', text)
    text = ''.join([c for c in text if not unicodedata.combining(c)])
    text = re.sub(r'[\s\-_/.]', '', text)
    text = re.sub(r'[^a-z0-9]', '', text)
    return text

def normalize_column_name(text):
    """Normalisation stricte des noms de colonnes pour le matching robuste."""
    return normalize_text(text)


# =============================================================
# [1] DETECTION TELEPHONE MOBILE / FIXE PAR LE CONTENU
# =============================================================
def clean_phone(value):
    """
    Nettoie un numero et le ramene, si possible, a 10 chiffres commencant par 0.
    Gere : separateurs (espaces, points, tirets), +33 / 0033 / 33,
    numeros importes comme des floats ('612345678.0'), et le 0 initial perdu.
    Retourne une chaine de chiffres, ou "" si vide.
    """
    if value is None:
        return ""
    s = str(value).strip()
    if s == "" or s.lower() in ("nan", "none", "null"):
        return ""

    # Cas float exporte type "612345678.0"
    if re.fullmatch(r"\+?\d+\.0+", s):
        s = s.split(".")[0]

    # Garder chiffres et +
    digits = re.sub(r"[^\d+]", "", s)

    # Prefixes internationaux France -> 0
    if digits.startswith("+33"):
        digits = "0" + digits[3:]
    elif digits.startswith("0033"):
        digits = "0" + digits[4:]
    elif digits.startswith("33") and len(digits) == 11:
        digits = "0" + digits[2:]

    # Enlever un eventuel + restant
    digits = re.sub(r"\D", "", digits)

    # 0 initial perdu (Excel numerique) : 9 chiffres commencant par 1-9
    if len(digits) == 9 and digits[0] in "123456789":
        digits = "0" + digits

    return digits

def phone_kind(value):
    """
    Retourne 'mobile', 'fixe' ou None pour un numero francais.
      06 / 07  -> mobile
      01-05    -> fixe (geographique)
      08 / 09  -> fixe / non-geographique (regroupe avec fixe)
    """
    d = clean_phone(value)
    if len(d) != 10 or not d.isdigit() or d[0] != "0":
        return None
    second = d[1]
    if second in ("6", "7"):
        return "mobile"
    if second in ("1", "2", "3", "4", "5", "8", "9"):
        return "fixe"
    return None

def detect_phone_column_kind(series, sample=200):
    """
    Analyse un ECHANTILLON d'une colonne et renvoie :
      'mobile', 'fixe', 'mixte'  si la colonne ressemble a des telephones,
       None sinon.

    IMPORTANT PERFORMANCE : on decoupe d'abord les premieres lignes
    (series.head), PUIS on nettoie. Ainsi le cout reste constant meme
    sur une colonne de plusieurs centaines de milliers de lignes.
    """
    try:
        # On prend une marge (x5) pour compenser les cases vides, mais on
        # ne touche jamais toute la colonne.
        head = series.head(sample * 5)
        vals = head.dropna().astype(str)
    except Exception:
        return None
    vals = vals[vals.str.strip() != ""]
    if len(vals) == 0:
        return None
    vals = vals.head(sample)

    kinds = [phone_kind(v) for v in vals]
    valid = [k for k in kinds if k is not None]

    # Il faut qu'au moins la moitie de l'echantillon ressemble a des tel FR
    if len(valid) < max(3, int(0.5 * len(vals))):
        return None

    total = len(valid)
    n_mobile = valid.count("mobile")
    n_fixe = valid.count("fixe")

    if total > 0 and n_mobile / total >= 0.8:
        return "mobile"
    if total > 0 and n_fixe / total >= 0.8:
        return "fixe"
    return "mixte"

def _phone_kinds_for_sheet(real_columns, sheet_df):
    """Retourne {colonne_source: 'mobile'|'fixe'|'mixte'|None}."""
    result = {}
    if sheet_df is None:
        return result
    for src in real_columns:
        if src in sheet_df.columns:
            result[src] = detect_phone_column_kind(sheet_df[src])
        else:
            result[src] = None
    return result


# =============================================================
# [2] DEDUCTION DES NOMS DE COLONNES QUAND L'EN-TETE EST ABSENTE
#
# Probleme : si un fichier n'a pas de ligne d'en-tete, pandas prend la
# PREMIERE LIGNE DE DONNEES comme nom de colonnes (ou met "Unnamed: 0").
# Resultat : le mapping ne reconnait rien, et un lead est perdu.
#
# Solution : reperer ce cas (looks_like_header), puis relire l'onglet SANS
# en-tete et nommer les colonnes d'apres leur CONTENU (infer_column_names).
# =============================================================
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
DATE_RE = re.compile(r"^\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}")
UNNAMED_RE = re.compile(r"^unnamed:\s*\d+$", re.IGNORECASE)
NUMERIC_ONLY_RE = re.compile(r"^[\d\s.,\-/+]+$")


def _sample_values(series, sample=200):
    """
    Renvoie un ECHANTILLON de valeurs non vides d'une colonne.
    Meme precaution memoire que detect_phone_column_kind : on decoupe les
    premieres lignes AVANT toute conversion, jamais la colonne entiere.
    """
    try:
        head = series.head(sample * 5)
        vals = head.dropna().astype(str)
    except Exception:
        return []
    vals = vals[vals.str.strip() != ""]
    return [v for v in vals.head(sample)]


def _ratio(values, predicate):
    if not values:
        return 0.0
    return sum(1 for v in values if predicate(v)) / len(values)


def _is_email_value(v):
    return bool(EMAIL_RE.search(str(v).strip()))


def _is_cp_value(v):
    return normalize_cp(v) is not None


def _is_date_value(v):
    return bool(DATE_RE.match(str(v).strip()))


def _is_numeric_value(v):
    s = str(v).strip()
    return bool(s) and bool(NUMERIC_ONLY_RE.fullmatch(s))


def looks_like_header(df):
    """
    True si les noms de colonnes ressemblent a une VRAIE en-tete.

    Une vraie en-tete = surtout du texte court non numerique.
    A l'inverse, un nom de colonne qui est un email, un telephone, un code
    postal, un nombre pur, une date, un "Unnamed: N" ou un texte tres long
    est en realite une DONNEE : le fichier n'a pas d'en-tete.

    On decide a la majorite : si la moitie ou plus des noms ressemblent a des
    donnees, on considere l'en-tete absente. Un fichier normal (NOM, PRENOM,
    EMAIL, CP...) obtient 0 signal de donnee et reste donc intact.

    Cout : O(nombre de colonnes). Ne lit aucune donnee.
    """
    cols = list(df.columns)
    if not cols:
        return True

    data_like = 0
    for c in cols:
        s = str(c).strip()
        if not s or s.lower() in ("nan", "none"):
            data_like += 1
        elif UNNAMED_RE.match(s):
            data_like += 1
        elif _is_email_value(s):
            data_like += 1
        elif phone_kind(s) is not None:
            data_like += 1
        elif _is_date_value(s):
            data_like += 1
        elif _is_numeric_value(s):
            # couvre aussi les codes postaux et les nombres purs
            data_like += 1
        elif len(s) > 40:
            # une en-tete est courte ; un texte long est une donnee (adresse...)
            data_like += 1

    return data_like < max(1, (len(cols) + 1) // 2)


def _guess_column_name(series):
    """
    Devine le nom d'une colonne d'apres son CONTENU (sur un echantillon).
    Renvoie un nom de colonne maitre connu, ou None si indetermine.
    """
    kind = detect_phone_column_kind(series)
    if kind == "mobile":
        return "TELEPHONE MOBILE"
    if kind == "fixe":
        return "TELEPHONE FIXE"
    if kind == "mixte":
        return "TELEPHONE MOBILE"

    vals = _sample_values(series)
    if not vals:
        return None

    if _ratio(vals, _is_email_value) >= 0.5:
        return "EMAIL"
    if _ratio(vals, _is_cp_value) >= 0.6:
        return "CP"
    if _ratio(vals, _is_date_value) >= 0.6:
        return "DATE DE NAISSANCE"

    return None


def infer_column_names(df):
    """
    Renvoie la liste des noms de colonnes deduits du contenu.
    Les noms reprennent ceux des colonnes maitres (EMAIL, TELEPHONE MOBILE,
    CP, DATE DE NAISSANCE) pour que l'auto-assignation les reconnaisse ;
    les colonnes indeterminees deviennent COLONNE_1, COLONNE_2...
    Les noms sont garantis uniques.
    """
    names = []
    used = set()
    for idx, col in enumerate(df.columns):
        guess = _guess_column_name(df[col])
        if not guess:
            guess = f"COLONNE_{idx + 1}"

        base = guess
        suffix = 2
        while guess in used:
            guess = f"{base}_{suffix}"
            suffix += 1

        used.add(guess)
        names.append(guess)
    return names


def _reread_sheet_without_header(file_obj, sheet_name):
    """Relit un onglet Excel en considerant qu'il n'a PAS d'en-tete."""
    for engine in ("openpyxl", None):
        try:
            file_obj.seek(0)
            if engine:
                df = pd.read_excel(file_obj, sheet_name=sheet_name, dtype=str,
                                   header=None, engine=engine)
            else:
                df = pd.read_excel(file_obj, sheet_name=sheet_name, dtype=str,
                                   header=None)
            if df is not None and len(df) > 0:
                return df
        except Exception:
            continue
    return None


def apply_header_inference_excel(sheets, file_obj):
    """
    Corrige les onglets dont l'en-tete est absente.
    Ne relit QUE les onglets suspects (les fichiers normaux ne coutent rien).
    Retourne (sheets, [noms des onglets corriges]).
    """
    suspects = [name for name, df in sheets.items() if not looks_like_header(df)]
    if not suspects:
        return sheets, []

    inferred = []
    for name in suspects:
        raw = _reread_sheet_without_header(file_obj, name)
        if raw is None:
            continue
        raw = raw.dropna(axis=1, how="all")
        if len(raw.columns) == 0 or len(raw) == 0:
            continue
        raw.columns = infer_column_names(raw)
        sheets[name] = raw
        inferred.append(name)

    return sheets, inferred


def _build_normalized_synonyms(master_columns):
    """Construit les synonymes normalisés par colonne maître (inclut le nom maître)."""
    normalized = {}
    for master in master_columns:
        items = [master] + SYNONYMES.get(master, [])
        normalized[master] = [normalize_column_name(x) for x in items if normalize_column_name(x)]
    return normalized

def auto_assign_columns_fast(real_columns, master_columns, sheet_df=None):
    """
    Auto-assignation robuste des colonnes avec priorités:
    1) correspondance exacte normalisée
    2) inclusion d'un synonyme dans la colonne source
    3) [NOUVEAU] routage telephone MOBILE/FIXE d'apres le CONTENU
    4) fuzzy matching en dernier recours

    Respecte l'unicité des colonnes maîtres dans l'onglet.
    Retourne: mapping {src_col: master_col | '(non assigne)'}
    """
    mapping = {}
    already_used = set()

    normalized_masters = {m: normalize_column_name(m) for m in master_columns}
    normalized_synonyms = _build_normalized_synonyms(master_columns)

    # Pré-normalisation des colonnes source
    src_norm_map = {src: normalize_column_name(src) for src in real_columns}

    # [1] Detection telephone par contenu (une seule passe).
    # On ne la declenche QUE si une colonne maitre telephone existe,
    # pour ne pas ralentir inutilement les fichiers sans telephone.
    _needs_phone_scan = ("TELEPHONE MOBILE" in master_columns) or ("TELEPHONE FIXE" in master_columns)
    if sheet_df is not None and _needs_phone_scan:
        phone_kinds = _phone_kinds_for_sheet(real_columns, sheet_df)
    else:
        phone_kinds = {}

    # 1) Exact match normalisé (master ou synonyme exactement égal)
    for src in real_columns:
        src_norm = src_norm_map.get(src, "")
        if not src_norm:
            mapping[src] = "(non assigne)"
            continue

        assigned = None
        for master in master_columns:
            if master in already_used:
                continue
            if src_norm == normalized_masters.get(master, ""):
                assigned = master
                break
            if src_norm in normalized_synonyms.get(master, []):
                assigned = master
                break

        if assigned:
            mapping[src] = assigned
            already_used.add(assigned)
        else:
            mapping[src] = "(non assigne)"

    # 2) Inclusion de synonymes dans le nom de colonne source
    for src in real_columns:
        if mapping.get(src) != "(non assigne)":
            continue
        src_norm = src_norm_map.get(src, "")
        if not src_norm:
            continue

        best_master = None
        best_len = 0
        for master in master_columns:
            if master in already_used:
                continue
            for syn in normalized_synonyms.get(master, []):
                if not syn:
                    continue
                if syn in src_norm:
                    if len(syn) > best_len:
                        best_len = len(syn)
                        best_master = master

        if best_master:
            mapping[src] = best_master
            already_used.add(best_master)

    # 2bis) [1] CORRECTION des telephones mal etiquetes par leur en-tete.
    # Si une colonne a ete mappee sur MOBILE mais son contenu est clairement
    # du fixe (et inversement), on corrige quand la cible est libre.
    has_mobile_master = "TELEPHONE MOBILE" in master_columns
    has_fixe_master = "TELEPHONE FIXE" in master_columns

    # 2bis-a) INVERSION : une colonne sur MOBILE avec contenu fixe ET une colonne
    # sur FIXE avec contenu mobile -> on echange les deux (cas "et inversement").
    if has_mobile_master and has_fixe_master:
        mislabeled_as_mobile = [s for s in real_columns
                                if mapping.get(s) == "TELEPHONE MOBILE" and phone_kinds.get(s) == "fixe"]
        mislabeled_as_fixe = [s for s in real_columns
                              if mapping.get(s) == "TELEPHONE FIXE" and phone_kinds.get(s) == "mobile"]
        for a, b in zip(mislabeled_as_mobile, mislabeled_as_fixe):
            mapping[a] = "TELEPHONE FIXE"
            mapping[b] = "TELEPHONE MOBILE"

    if has_mobile_master or has_fixe_master:
        for src in real_columns:
            k = phone_kinds.get(src)
            if not k:
                continue
            cur = mapping.get(src)
            if cur == "TELEPHONE MOBILE" and k == "fixe" and has_fixe_master and "TELEPHONE FIXE" not in already_used:
                already_used.discard("TELEPHONE MOBILE")
                mapping[src] = "TELEPHONE FIXE"
                already_used.add("TELEPHONE FIXE")
            elif cur == "TELEPHONE FIXE" and k == "mobile" and has_mobile_master and "TELEPHONE MOBILE" not in already_used:
                already_used.discard("TELEPHONE FIXE")
                mapping[src] = "TELEPHONE MOBILE"
                already_used.add("TELEPHONE MOBILE")

    # 2ter) [1] Colonnes telephone NON etiquetees -> route d'apres le contenu.
    # Utile quand l'en-tete est absente/muette (ex: colonne 'Tel1' bourree de 06).
    if has_mobile_master or has_fixe_master:
        for src in real_columns:
            if mapping.get(src) != "(non assigne)":
                continue
            k = phone_kinds.get(src)
            if not k:
                continue
            if k == "mobile" and has_mobile_master and "TELEPHONE MOBILE" not in already_used:
                mapping[src] = "TELEPHONE MOBILE"
                already_used.add("TELEPHONE MOBILE")
            elif k == "fixe" and has_fixe_master and "TELEPHONE FIXE" not in already_used:
                mapping[src] = "TELEPHONE FIXE"
                already_used.add("TELEPHONE FIXE")
            elif k == "mixte":
                if has_mobile_master and "TELEPHONE MOBILE" not in already_used:
                    mapping[src] = "TELEPHONE MOBILE"
                    already_used.add("TELEPHONE MOBILE")
                elif has_fixe_master and "TELEPHONE FIXE" not in already_used:
                    mapping[src] = "TELEPHONE FIXE"
                    already_used.add("TELEPHONE FIXE")

    # 3) Fuzzy matching en dernier recours
    fuzzy_threshold = 0.72
    for src in real_columns:
        if mapping.get(src) != "(non assigne)":
            continue

        src_norm = src_norm_map.get(src, "")
        if not src_norm:
            continue

        best_master = None
        best_score = fuzzy_threshold

        for master in master_columns:
            if master in already_used:
                continue

            score_master = SequenceMatcher(None, src_norm, normalized_masters.get(master, "")).ratio()
            if score_master > best_score:
                best_score = score_master
                best_master = master

            for syn in normalized_synonyms.get(master, []):
                score_syn = SequenceMatcher(None, src_norm, syn).ratio()
                if score_syn > best_score:
                    best_score = score_syn
                    best_master = master

        if best_master:
            mapping[src] = best_master
            already_used.add(best_master)

    return mapping

def find_best_master_col(src_col, master_cols, already_used=None):
    """Trouver la meilleure colonne maître pour une colonne source"""
    if already_used is None:
        already_used = []

    src_norm = normalize_text(src_col)

    if not src_norm or src_norm == "(nonassigne)":
        return None

    # 1. Correspondance EXACTE normalisée - PRIORITÉ ABSOLUE
    for master in master_cols:
        if master not in already_used:
            master_norm = normalize_text(master)
            if master_norm == src_norm:
                return master

    # 2. Correspondance via synonymes (priorité haute)
    for master in master_cols:
        if master not in already_used:
            synonyms = SYNONYMES.get(master, [])
            for syn in synonyms:
                if normalize_text(syn) == src_norm:
                    return master

    # 3. Fuzzy matching avec seuil modéré
    best_master = None
    best_score = 0.65
    for master in master_cols:
        if master not in already_used:
            master_norm = normalize_text(master)
            score = SequenceMatcher(None, src_norm, master_norm).ratio()
            if score > best_score:
                best_score = score
                best_master = master

    if best_master:
        return best_master

    return None

def auto_assign_single_sheet(sheet_key, sheet_df, master_columns):
    """
    Auto-assigner une seule feuille.
    Retourne un dictionnaire {src_col: master_col} et le nombre de colonnes assignées.
    """
    real_columns = [c for c in sheet_df.columns if c not in ["__source_file__", "__source_sheet__"]]
    # [1] on passe le dataframe pour permettre la detection tel par contenu
    new_mapping = auto_assign_columns_fast(real_columns, master_columns, sheet_df=sheet_df)
    matched_count = sum(1 for v in new_mapping.values() if v != "(non assigne)")

    return new_mapping, matched_count, len(real_columns)

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

def is_google_sheet_url(text):
    t = str(text).strip().lower()
    return "docs.google.com/spreadsheets" in t

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


st.title("Trieur de Fichiers Leads")
st.caption(f"Import Excel ou Google Sheets → mapping colonnes → aperçu → filtrage → export · v{APP_VERSION}")

tab1, tab2, tab3, tab4 = st.tabs(["1. Colonnes maitres", "2. Import et Mapping", "3. Filtrage & Dedup", "4. Export"])

with tab1:
    st.subheader("Gerer vos colonnes maitres")
    st.write("Ajoutez, supprimez ou modifiez vos colonnes maitres ci-dessous, une par ligne. "
             "La liste est **conservee** apres rechargement de la page.")
    cols_text = st.text_area(
        "Colonnes maitres",
        value="\n".join(st.session_state.master_columns),
        height=250,
        key="master_cols_input"
    )

    col_save, col_reset = st.columns([1, 1])
    with col_save:
        if st.button("💾 Enregistrer la liste des colonnes maitres", type="primary"):
            new_list = [c.strip() for c in cols_text.split("\n") if c.strip()]
            # dedoublonnage en gardant l'ordre
            seen = set()
            deduped = []
            for c in new_list:
                key = c.lower()
                if key not in seen:
                    seen.add(key)
                    deduped.append(c)
            if deduped:
                st.session_state.master_columns = deduped
                ok = save_master_columns(deduped)
                if ok:
                    st.success(f"{len(deduped)} colonnes maitres enregistrees et conservees.")
                else:
                    st.warning(f"{len(deduped)} colonnes prises en compte pour la session "
                               "(sauvegarde disque indisponible sur cet hebergement).")
            else:
                st.error("❌ Veuillez entrer au moins une colonne maître.")

    with col_reset:
        if st.button("↩️ Reinitialiser (liste par defaut)"):
            st.session_state.master_columns = DEFAULT_MASTER_COLUMNS.copy()
            save_master_columns(DEFAULT_MASTER_COLUMNS.copy())
            st.success("Liste reinitialisee aux colonnes par defaut.")
            st.rerun()

    st.caption("ℹ️ Astuce : les colonnes **TELEPHONE MOBILE** et **TELEPHONE FIXE** "
               "sont detectees automatiquement d'apres le contenu (prefixes 06/07 = mobile, "
               "01-05/08/09 = fixe), meme si l'en-tete est absente ou trompeuse.")

with tab2:
    st.subheader("Importer vos fichiers Excel ou Google Sheets")
    files = st.file_uploader("Deposez un ou plusieurs fichiers Excel", type=["xlsx", "xls"], accept_multiple_files=True)
    google_url = st.text_input("Ou collez une URL Google Sheets publique (optionnel)")

    all_sheets = {}

    progress_placeholder = st.empty()
    progress_label = st.empty()
    progress_bar = None

    def start_progress(message):
        bar = progress_placeholder.progress(0)
        progress_label.info(message)
        return bar

    def update_progress(bar, pct, message=None):
        bar.progress(max(0, min(100, int(pct))))
        if message:
            progress_label.info(message)

    def end_progress(bar, message=None):
        bar.progress(100)
        if message:
            progress_label.success(message)
        progress_placeholder.empty()
        progress_label.empty()

    def _files_signature(_files, _gurl):
        """Empreinte de l'ensemble importe (nom+taille des fichiers + URL)."""
        sig = []
        for _f in _files or []:
            try:
                sig.append((_f.name, int(_f.size)))
            except Exception:
                sig.append((getattr(_f, "name", "?"), None))
        sig.append(("__google__", _gurl.strip() if _gurl else ""))
        return tuple(sig)

    has_input = bool(files) or bool(google_url.strip() and is_google_sheet_url(google_url))
    current_sig = _files_signature(files, google_url)

    # [PERF] On ne (re)lit les fichiers QUE si l'ensemble importe a change.
    # Sinon on reutilise ce qui est deja en memoire : plus aucun rechargement
    # (ni barre de progression) lors des assignations manuelles.
    need_reload = has_input and (
        st.session_state.get("loaded_signature") != current_sig
        or not st.session_state.get("all_sheets")
    )
    if not need_reload:
        all_sheets = st.session_state.get("all_sheets", {})

    # [2] Onglets dont l'en-tete a du etre deduite pendant CE chargement
    inferred_this_load = []

    if need_reload and files:
        progress_bar = start_progress("Chargement des fichiers Excel... 0%")
        total_files = len(files)
        for f_idx, f in enumerate(files):
            base_pct = int((f_idx / max(total_files, 1)) * 80)
            update_progress(progress_bar, base_pct, f"Lecture du fichier {f_idx+1}/{total_files} : {f.name}")
            try:
                sheets = read_excel_all_sheets_from_file(f, f.name)
                if not sheets:
                    st.error(f"❌ Aucun onglet lisible dans {f.name}")
                    continue

                # [2] Onglets sans ligne d'en-tete : relecture + noms deduits
                sheets, inferred = apply_header_inference_excel(sheets, f)
                inferred_this_load.extend(f"{f.name} :: {n}" for n in inferred)

                sheet_items = list(sheets.items())
                total_sheet_items = len(sheet_items)

                for s_idx, (sheet_name, df) in enumerate(sheet_items):
                    if total_sheet_items > 0:
                        step_within_file = int(((s_idx + 1) / total_sheet_items) * (80 / max(total_files, 1)))
                    else:
                        step_within_file = 0
                    update_progress(
                        progress_bar,
                        base_pct + step_within_file,
                        f"Traitement de l'onglet {s_idx+1}/{total_sheet_items} de {f.name}"
                    )

                    if df is None or len(df) == 0:
                        st.warning(f"⚠️ {f.name} :: {sheet_name} est vide, ignoré.")
                        continue

                    key = f.name + " :: " + sheet_name
                    df = df.copy()
                    df["__source_file__"] = f.name
                    df["__source_sheet__"] = sheet_name
                    all_sheets[key] = df

            except Exception as e:
                st.error(f"❌ Erreur lecture {f.name}: {str(e)}")

        update_progress(progress_bar, 80, "Lecture Excel terminée. Finalisation...")

    if need_reload and google_url.strip() and is_google_sheet_url(google_url):
        if progress_bar is None:
            progress_bar = start_progress("Chargement Google Sheets... 0%")

        update_progress(progress_bar, 85 if files else 10, "Récupération des onglets Google Sheets...")
        sheets, inferred = read_google_sheets_all_sheets(google_url)
        inferred_this_load.extend(f"Google Sheets :: {n}" for n in inferred)
        if sheets:
            sheet_items = list(sheets.items())
            total_sheet_items = len(sheet_items)
            for s_idx, (sheet_name, df) in enumerate(sheet_items):
                start_pct = 85 if files else 10
                end_pct = 98
                pct = start_pct + int(((s_idx + 1) / max(total_sheet_items, 1)) * (end_pct - start_pct))
                update_progress(progress_bar, pct, f"Traitement Google Sheet {s_idx+1}/{total_sheet_items}")
                if len(df) > 0:
                    key = "Google Sheets :: " + sheet_name
                    df = df.copy()
                    df["__source_file__"] = "Google Sheets"
                    df["__source_sheet__"] = sheet_name
                    all_sheets[key] = df
            st.success(f"✅ Google Sheets importé avec {len(sheets)} onglet(s) détecté(s).")
        else:
            st.warning("⚠️ Impossible de lire le Google Sheets.")

    if progress_bar is not None:
        end_progress(progress_bar, "Chargement terminé à 100%")

    if need_reload:
        # Memoriser le resultat pour ne plus reparser aux prochains reruns
        st.session_state.all_sheets = all_sheets
        st.session_state.loaded_signature = current_sig

        # [2] Garder la liste des onglets corriges pour l'afficher a chaque rerun
        st.session_state.inferred_header_sheets = inferred_this_load

        # [3] Nouvel import = on repart avec tous les onglets inclus
        st.session_state.excluded_sheets = set()

        # Repartir sur des mappings propres pour ce nouvel ensemble
        st.session_state.sheet_mappings = {}
        for _k in list(st.session_state.keys()):
            if isinstance(_k, str) and (
                _k.startswith("map_") or _k.startswith("inc_sheet_") or _k.startswith("inc_file_")
            ):
                del st.session_state[_k]

        # [FIX 3 onglets] Auto-assignation de TOUS les onglets des l'import,
        # pour qu'aucun onglet ne reste vide et sans avoir a cliquer.
        for _sk, _sdf in all_sheets.items():
            _new_map, _, _ = auto_assign_single_sheet(_sk, _sdf, st.session_state.master_columns)
            st.session_state.sheet_mappings[_sk] = _new_map
            for _src, _master in _new_map.items():
                st.session_state[f"map_{_sk}_{_src}"] = _master

    if all_sheets:
        # [2] Prevenir que des en-tetes ont ete deduites (persiste entre les reruns)
        if st.session_state.inferred_header_sheets:
            st.warning(
                "⚠️ En-tetes absentes detectees et deduites pour : "
                + ", ".join(f"**{n}**" for n in st.session_state.inferred_header_sheets)
                + ". Les colonnes ont ete nommees d'apres leur contenu et aucune ligne "
                  "n'a ete perdue. Verifiez l'assignation ci-dessous."
            )

        # [3] Selection des fichiers / onglets a inclure
        with st.expander("🗂️ Choisir les fichiers et onglets a inclure", expanded=False):
            st.caption("Decochez ce que vous ne voulez pas traiter. "
                       "Aucun fichier n'est relu : le changement est immediat.")

            sheets_by_file = {}
            for k in all_sheets.keys():
                fname = k.split(" :: ")[0]
                sheets_by_file.setdefault(fname, []).append(k)

            for fname, keys in sheets_by_file.items():
                file_included = all(k not in st.session_state.excluded_sheets for k in keys)
                file_key = f"inc_file_{fname}"
                prev_key = f"inc_file_prev_{fname}"

                inc_file = st.checkbox(f"**{fname}** ({len(keys)} onglet(s))",
                                       value=file_included, key=file_key)

                # Bascule au niveau FICHIER : on propage a tous ses onglets.
                # On ne le fait qu'au moment ou l'utilisateur change la case,
                # sinon on ecraserait ses choix onglet par onglet.
                prev = st.session_state.get(prev_key)
                if prev is not None and prev != inc_file:
                    for k in keys:
                        if inc_file:
                            st.session_state.excluded_sheets.discard(k)
                        else:
                            st.session_state.excluded_sheets.add(k)
                        st.session_state[f"inc_sheet_{k}"] = inc_file
                    st.session_state[prev_key] = inc_file
                    st.rerun()
                st.session_state[prev_key] = inc_file

                for k in keys:
                    sheet_name = k.split(" :: ", 1)[1] if " :: " in k else k
                    n_rows = len(all_sheets[k])
                    inc_sheet = st.checkbox(
                        f"　└ {sheet_name} — {n_rows} lignes",
                        value=(k not in st.session_state.excluded_sheets),
                        key=f"inc_sheet_{k}"
                    )
                    if inc_sheet:
                        st.session_state.excluded_sheets.discard(k)
                    else:
                        st.session_state.excluded_sheets.add(k)

        # Seuls les onglets coches sont mappes puis fusionnes
        active_sheets = {k: v for k, v in all_sheets.items()
                         if k not in st.session_state.excluded_sheets}

        total_files = len(set([k.split(" :: ")[0] for k in active_sheets.keys()]))
        total_sheets = len(all_sheets)
        n_active = len(active_sheets)
        n_excluded = total_sheets - n_active

        if n_excluded:
            st.success(f"✅ {total_sheets} onglet(s) détecté(s) — **{n_active} inclus**, "
                       f"{n_excluded} exclu(s) · {total_files} fichier(s) traité(s).")
        else:
            st.success(f"✅ {total_files} fichier(s) importés, {total_sheets} onglet(s) détecté(s) au total.")

        with st.expander("📋 Detail des onglets importes"):
            for k, df in all_sheets.items():
                parts = k.split(" :: ")
                filename = parts[0]
                sheetname = parts[1] if len(parts) > 1 else "Unknown"
                num_rows = len(df)
                real_cols = [c for c in df.columns if c not in ["__source_file__", "__source_sheet__"]]
                num_cols = len(real_cols)
                num_dup = df.duplicated().sum()
                flag = "" if k in active_sheets else " · ⛔ exclu"

                st.write(f"**{filename}** → **{sheetname}** : {num_rows} lignes, {num_cols} colonnes, {num_dup} doublons{flag}")

        if not active_sheets:
            st.warning("⚠️ Tous les onglets sont exclus. Cochez-en au moins un pour continuer.")

        st.markdown("---")
        st.subheader("Assignation des colonnes")

        col_global_auto, col_space = st.columns([1, 3])
        with col_global_auto:
            if st.button("🚀 Auto-assigner TOUS les onglets", key="auto_all_sheets", type="primary"):
                total_sheets_count = len(active_sheets)
                for sheet_key, sheet_df in active_sheets.items():
                    new_mapping, matched_count, total_cols = auto_assign_single_sheet(
                        sheet_key, sheet_df, st.session_state.master_columns
                    )
                    st.session_state.sheet_mappings[sheet_key] = new_mapping
                    for src_col, master_col in new_mapping.items():
                        widget_key = f"map_{sheet_key}_{src_col}"
                        st.session_state[widget_key] = master_col

                st.success(f"✅ Auto-assignation terminée pour {total_sheets_count} onglet(s).")
                st.rerun()

        st.markdown("---")

        any_assigned = False

        for sheet_key, sheet_df in active_sheets.items():
            st.markdown(f"### 📄 {sheet_key}")

            real_columns = [c for c in sheet_df.columns if c not in ["__source_file__", "__source_sheet__"]]
            num_rows = len(sheet_df)
            num_cols = len(real_columns)
            num_duplicates = sheet_df.duplicated().sum()

            st.write(f"**Résumé :** {num_rows} lignes | {num_cols} colonnes | {num_duplicates} doublons")

            if sheet_key not in st.session_state.sheet_mappings:
                st.session_state.sheet_mappings[sheet_key] = {}

            col_auto, col_space = st.columns([1, 3])
            with col_auto:
                if st.button(f"🚀 Auto", key=f"auto_{sheet_key}"):
                    new_mapping, matched_count, total_cols = auto_assign_single_sheet(
                        sheet_key, sheet_df, st.session_state.master_columns
                    )
                    st.session_state.sheet_mappings[sheet_key] = new_mapping
                    for src_col, master_col in new_mapping.items():
                        widget_key = f"map_{sheet_key}_{src_col}"
                        st.session_state[widget_key] = master_col
                    st.success(f"✅ {matched_count}/{total_cols} colonnes assignées")
                    st.rerun()

            st.write("**Aperçu des 7 premières lignes avec assignation au-dessus :**")

            preview_df = sheet_df.head(7).copy()

            st.write("**Sélectionnez les colonnes maîtres correspondantes :**")

            current_mapping = st.session_state.sheet_mappings[sheet_key]
            mapping_options = ["(non assigne)"] + st.session_state.master_columns

            updated_mapping = {}

            cols_display = st.columns(len(real_columns))

            for idx, src_col in enumerate(real_columns):
                with cols_display[idx]:
                    current = current_mapping.get(src_col, "(non assigne)")
                    widget_key = f"map_{sheet_key}_{src_col}"

                    if widget_key in st.session_state:
                        current = st.session_state[widget_key]
                    else:
                        st.session_state[widget_key] = current

                    already_used_in_current = [updated_mapping.get(c, "") for c in real_columns if c != src_col and updated_mapping.get(c) != "(non assigne)"]
                    available_options = ["(non assigne)"] + [m for m in st.session_state.master_columns if m not in already_used_in_current]

                    if current not in available_options:
                        current = "(non assigne)"
                        st.session_state[widget_key] = current

                    try:
                        idx_val = available_options.index(current)
                    except ValueError:
                        idx_val = 0

                    choice = st.selectbox(
                        src_col,
                        options=available_options,
                        index=idx_val,
                        key=widget_key,
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

                # [3] on ne fusionne QUE les onglets coches
                for sheet_key, sheet_df in active_sheets.items():
                    source_file = sheet_df["__source_file__"].iloc[0] if len(sheet_df) > 0 else sheet_key
                    source_sheet = sheet_df["__source_sheet__"].iloc[0] if len(sheet_df) > 0 else "Unknown"
                    mapping = st.session_state.sheet_mappings.get(sheet_key, {})

                    assigned_cols = [m for m in mapping.values() if m != "(non assigne)"]
                    if not assigned_cols:
                        st.warning(f"⚠️ {sheet_key}: Aucune colonne assignée, ignoré.")
                        continue

                    sub = pd.DataFrame(index=sheet_df.index)
                    for master_col in st.session_state.master_columns:
                        src_cols_for_master = [s for s, m in mapping.items() if m == master_col and s in sheet_df.columns]
                        if master_col == "Source Data":
                            sub[master_col] = f"{source_file} ({source_sheet})"
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
                    st.error("❌ Aucun onglet avec assignation trouvé.")
                else:
                    final_df = pd.concat(rows, ignore_index=True)
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
    st.subheader("Filtrer la base de travail")
    if st.session_state.final_df is None:
        st.info("ℹ️ Importez et mappez des fichiers dans l'onglet precedent avant de filtrer.")
    else:
        df = st.session_state.final_df.copy()
        total_lines = len(df)
        st.write(f"Base actuelle : **{total_lines}** lignes importees")

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

        remaining_lines = len(filtered_df)
        remaining_duplicates = filtered_df.duplicated().sum()

        st.write(f"Resultat filtre : **{remaining_lines}** lignes | **{remaining_duplicates}** doublons conserves | **{total_lines}** lignes importees au total")
        st.dataframe(filtered_df.head(50), use_container_width=True)

        dup_check_col = st.selectbox("Colonne pour detecter les doublons (ex: TELEPHONE MOBILE)", options=["(aucune)"] + st.session_state.master_columns)
        if dup_check_col != "(aucune)":
            dup_count = filtered_df[dup_check_col].duplicated(keep=False).sum()
            st.warning(f"{dup_count} lignes en doublon detectees sur la colonne '{dup_check_col}' (non supprimees automatiquement).")

        st.session_state.filtered_df = filtered_df

with tab4:
    st.subheader("Exporter le resultat filtre")
    if st.session_state.filtered_df is None:
        st.info("ℹ️ Appliquez un filtre dans l'onglet precedent avant d'exporter.")
    else:
        export_df = st.session_state.filtered_df
        if len(export_df) == 0:
            st.error("❌ Impossible d'exporter : aucune donnée à exporter après filtrage.")
        else:
            st.write(f"{len(export_df)} lignes pretes a l'export.")

            # [9] Nom du fichier personnalisable
            raw_name = st.text_input(
                "Nom du fichier (sans extension)",
                value=st.session_state.export_name_base or "export_leads",
                key="export_name_input"
            )
            st.session_state.export_name_base = raw_name
            clean_name = sanitize_filename(raw_name)
            st.caption(f"Fichiers generes : **{clean_name}.csv** / **{clean_name}.xlsx**")

            col1, col2 = st.columns(2)

            with col1:
                st.markdown("**Export CSV**")
                csv_bytes = export_csv_safe(export_df)
                if csv_bytes:
                    st.download_button(
                        label="💾 Telecharger CSV",
                        data=csv_bytes,
                        file_name=f"{clean_name}.csv",
                        mime="text/csv",
                        key="dl_csv"
                    )

            with col2:
                st.markdown("**Export Excel**")
                buffer = export_excel_safe(export_df)
                if buffer:
                    st.download_button(
                        label="💾 Telecharger Excel",
                        data=buffer,
                        file_name=f"{clean_name}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="dl_xlsx"
                    )

            st.markdown("---")
            st.info("ℹ️ Les fichiers sont encodés en UTF-8.")
