from trieur.filters import cp_matches_prefix, normalize_cp


def test_normalize_cp_complete_les_codes_a_4_chiffres():
    assert normalize_cp("2000") == "02000"


def test_normalize_cp_garde_les_codes_valides():
    assert normalize_cp("75001") == "75001"


def test_normalize_cp_retire_le_suffixe_decimal_excel():
    assert normalize_cp("75001.0") == "75001"


def test_normalize_cp_rejette_le_non_numerique():
    assert normalize_cp("abcde") is None
    assert normalize_cp("") is None


def test_normalize_cp_rejette_une_longueur_invalide():
    assert normalize_cp("123") is None
    assert normalize_cp("123456") is None


def test_cp_matches_prefix_vrai_quand_departement_present():
    assert cp_matches_prefix("33000", {"33", "77"}) is True


def test_cp_matches_prefix_faux_quand_absent():
    assert cp_matches_prefix("75001", {"33", "77"}) is False


def test_cp_matches_prefix_faux_pour_cp_invalide():
    assert cp_matches_prefix("invalide", {"33"}) is False


