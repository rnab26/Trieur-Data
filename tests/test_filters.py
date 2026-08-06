import pandas as pd

from trieur.filters import (
    apply_filter_groups,
    apply_single_criterion,
    cp_matches_prefix,
    dedupe_dataframe,
    dedupe_dataframe_manual,
    describe_criterion,
    describe_filter_groups,
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


# --- Filtres multi-criteres --------------------------------------------
DF_FILTRES = pd.DataFrame({
    "CP": ["34000", "71000", "71000", "75001"],
    "VILLE": ["Montpellier", "Lyon", "Chalon", "Paris"],
})


def test_apply_single_criterion_departements():
    mask = apply_single_criterion(DF_FILTRES, {"column": "CP", "kind": "departements", "values": ["34"]})
    assert mask.tolist() == [True, False, False, False]


def test_apply_single_criterion_valeurs():
    mask = apply_single_criterion(DF_FILTRES, {"column": "VILLE", "kind": "valeurs", "values": ["Lyon", "Paris"]})
    assert mask.tolist() == [False, True, False, True]


def test_apply_single_criterion_sans_valeurs_ne_matche_rien():
    mask = apply_single_criterion(DF_FILTRES, {"column": "VILLE", "kind": "valeurs", "values": []})
    assert mask.tolist() == [False, False, False, False]


def test_apply_single_criterion_colonne_absente_ne_matche_rien():
    mask = apply_single_criterion(DF_FILTRES, {"column": "INCONNUE", "kind": "valeurs", "values": ["x"]})
    assert mask.tolist() == [False, False, False, False]


def test_apply_filter_groups_un_seul_groupe_et():
    # [CP dept 71] ET [VILLE = Lyon]
    groups = [[
        {"column": "CP", "kind": "departements", "values": ["71"]},
        {"column": "VILLE", "kind": "valeurs", "values": ["Lyon"]},
    ]]
    result = apply_filter_groups(DF_FILTRES, groups)
    assert result["VILLE"].tolist() == ["Lyon"]


def test_apply_filter_groups_ou_entre_groupes():
    # [CP dept 34] OU [CP dept 71 ET VILLE = Lyon]
    groups = [
        [{"column": "CP", "kind": "departements", "values": ["34"]}],
        [
            {"column": "CP", "kind": "departements", "values": ["71"]},
            {"column": "VILLE", "kind": "valeurs", "values": ["Lyon"]},
        ],
    ]
    result = apply_filter_groups(DF_FILTRES, groups)
    assert sorted(result["VILLE"].tolist()) == ["Lyon", "Montpellier"]


def test_apply_filter_groups_ignore_les_groupes_incomplets():
    # un groupe avec des valeurs vides est ignore (pas de filtre a zero)
    groups = [[{"column": "CP", "kind": "departements", "values": []}]]
    result = apply_filter_groups(DF_FILTRES, groups)
    assert len(result) == len(DF_FILTRES)


def test_apply_filter_groups_vide_renvoie_tout():
    assert len(apply_filter_groups(DF_FILTRES, [])) == len(DF_FILTRES)


def test_describe_criterion():
    assert describe_criterion({"column": "CP", "kind": "departements", "values": ["34"]}) == "CP dept 34"
    assert describe_criterion({"column": "VILLE", "kind": "valeurs", "values": ["Lyon"]}) == "VILLE = Lyon"


def test_describe_filter_groups_un_groupe():
    groups = [[{"column": "CP", "kind": "departements", "values": ["34"]}]]
    assert describe_filter_groups(groups) == "CP dept 34"


def test_describe_filter_groups_plusieurs_groupes():
    groups = [
        [{"column": "CP", "kind": "departements", "values": ["34"]}],
        [
            {"column": "CP", "kind": "departements", "values": ["71"]},
            {"column": "VILLE", "kind": "valeurs", "values": ["Lyon"]},
        ],
    ]
    assert describe_filter_groups(groups) == "(CP dept 34) OU (CP dept 71 ET VILLE = Lyon)"


