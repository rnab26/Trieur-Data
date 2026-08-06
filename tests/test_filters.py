import pandas as pd

from trieur.filters import cp_matches_prefix, dedupe_dataframe, normalize_cp


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


def test_dedupe_dataframe_garde_la_premiere_occurrence():
    df = pd.DataFrame({
        "TELEPHONE": ["0601020304", "0601020304", "0611111111"],
        "NOM": ["Alice", "Alice bis", "Bob"],
    })
    result = dedupe_dataframe(df, "TELEPHONE", keep="first")
    assert len(result) == 2
    assert result["NOM"].tolist() == ["Alice", "Bob"]


def test_dedupe_dataframe_garde_la_ligne_la_plus_complete():
    df = pd.DataFrame({
        "TELEPHONE": ["0601020304", "0601020304", "0611111111"],
        "NOM": ["Alice", "Alice", "Bob"],
        "EMAIL": [None, "alice@example.com", "bob@example.com"],
    })
    result = dedupe_dataframe(df, "TELEPHONE", keep="complete")
    assert len(result) == 2
    kept = result[result["TELEPHONE"] == "0601020304"].iloc[0]
    assert kept["EMAIL"] == "alice@example.com"


def test_dedupe_dataframe_sans_doublon_ne_change_rien():
    df = pd.DataFrame({"TELEPHONE": ["0601020304", "0611111111"]})
    result = dedupe_dataframe(df, "TELEPHONE")
    assert len(result) == 2


def test_dedupe_dataframe_colonne_absente_renvoie_le_df_inchange():
    df = pd.DataFrame({"NOM": ["Alice", "Alice"]})
    result = dedupe_dataframe(df, "TELEPHONE")
    assert len(result) == 2


