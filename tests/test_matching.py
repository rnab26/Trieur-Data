import pandas as pd

from trieur.matching import (
    DEFAULT_MASTER_COLUMNS,
    auto_assign_columns_fast,
    clean_phone,
    detect_phone_column_kind,
    infer_column_names,
    looks_like_header,
    normalize_text,
    phone_kind,
)

M = DEFAULT_MASTER_COLUMNS


# --- Normalisation ---------------------------------------------------
def test_normalize_text_retire_accents_casse_ponctuation():
    assert normalize_text("Prénom-Client") == "prenomclient"
    assert normalize_text("  Téléphone Mobile ") == "telephonemobile"


# --- Detection telephone (non-regression v1.1) -----------------------
def test_phone_kind_prefixes():
    assert phone_kind("06 12 34 56 78") == "mobile"
    assert phone_kind("+33 7 55 44 33 22") == "mobile"
    assert phone_kind("01.42.33.44.55") == "fixe"


def test_clean_phone_gere_float_et_zero_perdu():
    assert clean_phone("612345678.0") == "0612345678"
    assert phone_kind("142334455") == "fixe"


def test_phone_kind_invalide():
    assert phone_kind("bonjour") is None


def test_detect_phone_column_kind_sur_serie():
    s = pd.Series(["0612345678", "0698765432", "0655443322"])
    assert detect_phone_column_kind(s) == "mobile"


# --- Auto-assignation ------------------------------------------------
def test_auto_assign_exact_et_synonyme():
    m = auto_assign_columns_fast(["NOM", "mail", "cp"], M)
    assert m["NOM"] == "NOM"
    assert m["mail"] == "EMAIL"
    assert m["cp"] == "CP"


def test_auto_assign_non_assigne_si_inconnu():
    m = auto_assign_columns_fast(["colonne_xyz_inconnue"], M)
    assert m["colonne_xyz_inconnue"] == "(non assigne)"


def test_auto_assign_inversion_mobile_fixe():
    df = pd.DataFrame({
        "TELEPHONE MOBILE": ["0142334455", "0388776655", "0499887766"],  # en fait FIXE
        "TELEPHONE FIXE": ["0612345678", "0698765432", "0655443322"],    # en fait MOBILE
    })
    m = auto_assign_columns_fast(list(df.columns), M, sheet_df=df)
    assert m["TELEPHONE MOBILE"] == "TELEPHONE FIXE"
    assert m["TELEPHONE FIXE"] == "TELEPHONE MOBILE"


def test_auto_assign_colonne_tel_non_etiquetee():
    df = pd.DataFrame({"Tel1": ["0612345678", "0698765432", "0655443322"], "NOM": ["a", "b", "c"]})
    m = auto_assign_columns_fast(list(df.columns), M, sheet_df=df)
    assert m["Tel1"] == "TELEPHONE MOBILE"


def test_auto_assign_unicite_des_colonnes_maitres():
    df = pd.DataFrame({"Tel1": ["0612345678"] * 3, "Tel2": ["0698765432"] * 3})
    m = auto_assign_columns_fast(list(df.columns), M, sheet_df=df)
    assignes = [v for v in m.values() if v != "(non assigne)"]
    assert len(assignes) == len(set(assignes))


# --- Deduction d'en-tetes (point 2) ----------------------------------
def test_looks_like_header_vraie_entete():
    df = pd.DataFrame({"NOM": ["a"], "EMAIL": ["j@x.fr"], "CP": ["75001"]})
    assert looks_like_header(df) is True


def test_looks_like_header_entete_absente():
    df = pd.DataFrame({"Dupont": ["Martin"], "j@mail.fr": ["p@mail.fr"], "0612345678": ["0698765432"]})
    assert looks_like_header(df) is False


def test_looks_like_header_unnamed():
    df = pd.DataFrame({"Unnamed: 0": ["a"], "Unnamed: 1": ["b"], "Unnamed: 2": ["c"]})
    assert looks_like_header(df) is False


def test_infer_column_names_par_contenu():
    raw = pd.DataFrame({
        0: ["Dupont", "Martin", "Durand", "Petit"],
        1: ["j@mail.fr", "p@mail.fr", "a@mail.fr", "s@mail.fr"],
        2: ["0612345678", "0698765432", "0655443322", "0677889900"],
        3: ["0142334455", "0388776655", "0499887766", "0155443322"],
        4: ["75001", "33000", "02100", "59000"],
    })
    n = infer_column_names(raw)
    assert n[1] == "EMAIL"
    assert n[2] == "TELEPHONE MOBILE"
    assert n[3] == "TELEPHONE FIXE"
    assert n[4] == "CP"
    assert n[0].startswith("COLONNE_")
    assert len(set(n)) == len(n)
