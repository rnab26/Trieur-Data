import pandas as pd

from trieur.filters import (
    cp_matches_prefix,
    dedupe_dataframe,
    dedupe_dataframe_manual,
    duplicate_groups,
    most_complete_row_index,
    normalize_cp,
)


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


def test_dedupe_dataframe_ne_traite_pas_les_cases_vides_comme_doublons():
    # Deux lignes SANS telephone ne sont pas des doublons l'une de l'autre.
    df = pd.DataFrame({
        "TELEPHONE": ["0601020304", None, None, "0601020304"],
        "NOM": ["Alice", "Bob", "Carla", "Alice bis"],
    })
    result = dedupe_dataframe(df, "TELEPHONE", keep="first")
    assert len(result) == 3
    assert set(result["NOM"]) == {"Alice", "Bob", "Carla"}


def test_duplicate_groups_ignore_les_cases_vides():
    df = pd.DataFrame({"TELEPHONE": ["0601020304", "0601020304", None, None, "0611111111"]})
    groups = duplicate_groups(df, "TELEPHONE")
    assert len(groups) == 1
    value, idx = groups[0]
    assert value == "0601020304"
    assert set(idx) == {0, 1}


def test_duplicate_groups_colonne_absente():
    df = pd.DataFrame({"NOM": ["Alice"]})
    assert duplicate_groups(df, "TELEPHONE") == []


def test_most_complete_row_index_choisit_le_moins_de_vides():
    df = pd.DataFrame({
        "TELEPHONE": ["0601020304", "0601020304"],
        "EMAIL": [None, "alice@example.com"],
        "NOM": ["Alice", "Alice"],
    })
    assert most_complete_row_index(df, [0, 1]) == 1


def test_dedupe_dataframe_manual_respecte_le_choix_par_groupe():
    df = pd.DataFrame({
        "TELEPHONE": ["0601020304", "0601020304", "0611111111", None],
        "NOM": ["Alice A", "Alice B", "Bob", "Sans tel"],
    })
    # on choisit explicitement de garder la ligne 1 (Alice B) du groupe de doublons
    result = dedupe_dataframe_manual(df, "TELEPHONE", keep_indices=[1])
    assert set(result["NOM"]) == {"Alice B", "Bob", "Sans tel"}


def test_dedupe_dataframe_manual_colonne_absente():
    df = pd.DataFrame({"NOM": ["Alice", "Alice"]})
    result = dedupe_dataframe_manual(df, "TELEPHONE", keep_indices=[])
    assert len(result) == 2


