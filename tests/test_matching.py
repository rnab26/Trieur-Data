import pandas as pd

from trieur.matching import (
    DEFAULT_MASTER_COLUMNS,
    apply_remembered_mapping,
    auto_assign_columns_fast,
    auto_assign_with_memory,
    clean_iban,
    clean_phone,
    column_fingerprint,
    detect_iban_column,
    detect_phone_column_kind,
    iban_is_valid,
    infer_column_names,
    is_iban_master,
    looks_like_header,
    looks_like_iban,
    mapping_to_remembered,
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


# --- IBAN --------------------------------------------------------------
def test_is_iban_master_reconnait_le_sens_du_nom():
    assert is_iban_master("Référence bancaire") is True
    assert is_iban_master("IBAN") is True
    assert is_iban_master("NOM") is False


def test_clean_iban_retire_les_espaces_internes():
    assert clean_iban("FR76 3000 6000 0112 3456 7890 189") == "FR7630006000011234567890189"
    assert clean_iban(None) is None or pd.isna(clean_iban(None))


def test_looks_like_iban_detecte_la_forme():
    assert looks_like_iban("FR7630006000011234567890189") is True
    assert looks_like_iban("bonjour") is False
    assert looks_like_iban(None) is False


def test_detect_iban_column_sur_petit_echantillon():
    s = pd.Series(["FR7630006000011234567890189", "DE89370400440532013000"])
    assert detect_iban_column(s) is True
    assert detect_iban_column(pd.Series(["Alice", "Bob"])) is False


def test_iban_is_valid_accepte_des_iban_connus_valides():
    # IBAN d'exemple officiels (registre IBAN / Wikipedia)
    assert iban_is_valid("FR7630006000011234567890189") is True
    assert iban_is_valid("DE89370400440532013000") is True
    assert iban_is_valid("GB29NWBK60161331926819") is True
    # tolere les espaces
    assert iban_is_valid("FR76 3000 6000 0112 3456 7890 189") is True


def test_iban_is_valid_rejette_un_checksum_casse():
    assert iban_is_valid("FR7630006000011234567890180") is False


def test_iban_is_valid_none_si_non_applicable():
    assert iban_is_valid(None) is None
    assert iban_is_valid("") is None
    assert iban_is_valid("bonjour") is None


# --- Memoire du mapping par forme de fichier --------------------------
def test_column_fingerprint_ignore_ordre_et_casse():
    fp1 = column_fingerprint(["NOM", "Email", "CP"])
    fp2 = column_fingerprint(["cp", "nom", "EMAIL"])
    assert fp1 == fp2


def test_column_fingerprint_differe_si_colonnes_differentes():
    assert column_fingerprint(["NOM", "EMAIL"]) != column_fingerprint(["NOM", "TELEPHONE"])


def test_mapping_to_remembered_ignore_les_non_assignes():
    remembered = mapping_to_remembered({"Ref Client": "NOM", "Autre": "(non assigne)"})
    assert remembered == {"refclient": "NOM"}


def test_apply_remembered_mapping_rejoue_sur_une_casse_differente():
    remembered = {"refclient": "NOM"}
    mapping = apply_remembered_mapping(["REF CLIENT", "AUTRE"], remembered)
    assert mapping["REF CLIENT"] == "NOM"
    assert mapping["AUTRE"] == "(non assigne)"


def test_apply_remembered_mapping_respecte_lunicite():
    remembered = {"a": "NOM", "b": "NOM"}
    mapping = apply_remembered_mapping(["a", "b"], remembered)
    assignes = [v for v in mapping.values() if v != "(non assigne)"]
    assert assignes == ["NOM"]


def test_auto_assign_with_memory_priorise_le_mapping_memorise():
    # "NUM DOSSIER" n'est reconnu par AUCUNE heuristique -> reste non assigne
    # sans memoire, mais le mapping memorise doit le recuperer.
    df = pd.DataFrame({"NUM DOSSIER": ["A", "B"], "EMAIL": ["a@x.fr", "b@x.fr"]})
    sans_memoire = auto_assign_columns_fast(list(df.columns), M, sheet_df=df)
    assert sans_memoire["NUM DOSSIER"] == "(non assigne)"

    remembered = {"numdossier": "NOM"}
    avec_memoire = auto_assign_with_memory(list(df.columns), M, sheet_df=df, remembered_for_shape=remembered)
    assert avec_memoire["NUM DOSSIER"] == "NOM"
    assert avec_memoire["EMAIL"] == "EMAIL"
