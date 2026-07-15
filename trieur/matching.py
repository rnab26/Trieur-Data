"""Intelligence des colonnes : normalisation, detection telephone,
deduction des en-tetes absentes, auto-assignation.
Logique pure — aucune dependance Streamlit, donc testable directement."""
import re
import unicodedata
from difflib import SequenceMatcher

import pandas as pd

from trieur.filters import normalize_cp


# --- Colonnes maitres par defaut + synonymes -------------------------
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


# --- Normalisation ---------------------------------------------------
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


# --- Reconnaissance SEMANTIQUE du role telephone ---------------------
# On identifie quelle colonne maitre joue le role "mobile" et laquelle joue
# le role "fixe" d'apres le SENS de son nom (mots-cles), et non d'apres un
# libelle fige. Ainsi, si l'utilisateur renomme "TELEPHONE MOBILE" en
# "phone mobile" (ou "portable", "GSM"...), la detection continue de marcher.
_MOBILE_HINTS = ("mobile", "portable", "gsm", "cell", "cellulaire")
_FIXE_HINTS = ("fixe", "landline", "domicile", "geographique")


def identify_phone_masters(master_columns):
    """Retourne (colonne_maitre_mobile, colonne_maitre_fixe) reperees par le
    SENS de leur nom, ou None si absente. Logique humaine simple : un nom qui
    parle de 'mobile/portable/gsm' est le tel mobile ; 'fixe/landline' le fixe."""
    mobile_master = None
    fixe_master = None
    for master in master_columns:
        n = normalize_column_name(master)
        if mobile_master is None and any(h in n for h in _MOBILE_HINTS):
            mobile_master = master
        elif fixe_master is None and any(h in n for h in _FIXE_HINTS):
            fixe_master = master
    return mobile_master, fixe_master


def _build_normalized_synonyms(master_columns):
    """Construit les synonymes normalisés par colonne maître (inclut le nom maître).

    Les colonnes telephone heritent des synonymes selon leur ROLE (detecte par
    le sens du nom), pas seulement selon leur libelle exact : une colonne maitre
    renommee "phone mobile" recupere quand meme les synonymes du tel mobile."""
    mobile_master, fixe_master = identify_phone_masters(master_columns)
    normalized = {}
    for master in master_columns:
        items = [master] + SYNONYMES.get(master, [])
        if master == mobile_master:
            items += SYNONYMES.get("TELEPHONE MOBILE", [])
        if master == fixe_master:
            items += SYNONYMES.get("TELEPHONE FIXE", [])
        seen = []
        for x in items:
            nx = normalize_column_name(x)
            if nx and nx not in seen:
                seen.append(nx)
        normalized[master] = seen
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

    # Reperage semantique des colonnes telephone (marche meme si renommees).
    mobile_master, fixe_master = identify_phone_masters(master_columns)

    # [1] Detection telephone par contenu (une seule passe).
    # On ne la declenche QUE si une colonne maitre telephone existe,
    # pour ne pas ralentir inutilement les fichiers sans telephone.
    _needs_phone_scan = (mobile_master is not None) or (fixe_master is not None)
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
    has_mobile_master = mobile_master is not None
    has_fixe_master = fixe_master is not None

    # 2bis-a) INVERSION : une colonne sur MOBILE avec contenu fixe ET une colonne
    # sur FIXE avec contenu mobile -> on echange les deux (cas "et inversement").
    if has_mobile_master and has_fixe_master:
        mislabeled_as_mobile = [s for s in real_columns
                                if mapping.get(s) == mobile_master and phone_kinds.get(s) == "fixe"]
        mislabeled_as_fixe = [s for s in real_columns
                              if mapping.get(s) == fixe_master and phone_kinds.get(s) == "mobile"]
        for a, b in zip(mislabeled_as_mobile, mislabeled_as_fixe):
            mapping[a] = fixe_master
            mapping[b] = mobile_master

    if has_mobile_master or has_fixe_master:
        for src in real_columns:
            k = phone_kinds.get(src)
            if not k:
                continue
            cur = mapping.get(src)
            if cur == mobile_master and k == "fixe" and has_fixe_master and fixe_master not in already_used:
                already_used.discard(mobile_master)
                mapping[src] = fixe_master
                already_used.add(fixe_master)
            elif cur == fixe_master and k == "mobile" and has_mobile_master and mobile_master not in already_used:
                already_used.discard(fixe_master)
                mapping[src] = mobile_master
                already_used.add(mobile_master)

    # 2ter) [1] Colonnes telephone NON etiquetees -> route d'apres le contenu.
    # Utile quand l'en-tete est absente/muette (ex: colonne 'Tel1' bourree de 06).
    if has_mobile_master or has_fixe_master:
        for src in real_columns:
            if mapping.get(src) != "(non assigne)":
                continue
            k = phone_kinds.get(src)
            if not k:
                continue
            if k == "mobile" and has_mobile_master and mobile_master not in already_used:
                mapping[src] = mobile_master
                already_used.add(mobile_master)
            elif k == "fixe" and has_fixe_master and fixe_master not in already_used:
                mapping[src] = fixe_master
                already_used.add(fixe_master)
            elif k == "mixte":
                if has_mobile_master and mobile_master not in already_used:
                    mapping[src] = mobile_master
                    already_used.add(mobile_master)
                elif has_fixe_master and fixe_master not in already_used:
                    mapping[src] = fixe_master
                    already_used.add(fixe_master)

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
