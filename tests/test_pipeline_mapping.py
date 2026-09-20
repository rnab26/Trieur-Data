"""Teste api/pipeline_mapping.py : applique un mapping colonnes source
-> colonnes maîtres à UNE ligne, avec les mêmes règles que le bouton
"Construire la base de travail fusionnée" de
views/tab2_import_mapping.py (voir commit 635fcde)."""
from api.pipeline_mapping import _is_empty, detect_iban_master_columns, merge_mapped_row


def test_is_empty_none_nan_and_blank_string():
    assert _is_empty(None) is True
    assert _is_empty(float("nan")) is True
    assert _is_empty("   ") is True
    assert _is_empty("") is True
    assert _is_empty("x") is False
    assert _is_empty(0) is False
    assert _is_empty(False) is False


def test_merge_mapped_row_simple_one_to_one_mapping():
    src = {"nom_client": "Dupont", "iban_ref": "FR7630006000011234567890189"}
    mapping = {"nom_client": "NOM", "iban_ref": "IBAN"}
    result = merge_mapped_row(src, mapping, ["NOM", "IBAN"], None, set())
    assert result == {"NOM": "Dupont", "IBAN": "FR7630006000011234567890189"}


def test_merge_mapped_row_first_non_empty_value_wins_on_collision():
    """Deux colonnes source pointent vers la même colonne maître : la
    PREMIÈRE valeur non vide gagne, la deuxième ne comble que si la
    première est vide -- jamais "la dernière écrase" (règle exacte de
    views/tab2_import_mapping.py)."""
    src = {"tel1": "0601020304", "tel2": "0708091011"}
    mapping = {"tel1": "TELEPHONE MOBILE", "tel2": "TELEPHONE MOBILE"}
    result = merge_mapped_row(src, mapping, ["TELEPHONE MOBILE"], None, set())
    assert result == {"TELEPHONE MOBILE": "0601020304"}


def test_merge_mapped_row_second_column_fills_when_first_is_empty():
    src = {"tel1": "", "tel2": "0708091011"}
    mapping = {"tel1": "TELEPHONE MOBILE", "tel2": "TELEPHONE MOBILE"}
    result = merge_mapped_row(src, mapping, ["TELEPHONE MOBILE"], None, set())
    assert result == {"TELEPHONE MOBILE": "0708091011"}


def test_merge_mapped_row_unassigned_columns_are_dropped():
    src = {"nom_client": "Dupont", "colonne_inconnue": "x"}
    mapping = {"nom_client": "NOM", "colonne_inconnue": "(non assigne)"}
    result = merge_mapped_row(src, mapping, ["NOM"], None, set())
    assert result == {"NOM": "Dupont"}


def test_merge_mapped_row_sets_source_data_automatically_never_from_mapping():
    src = {"nom_client": "Dupont", "source": "devrait etre ignore"}
    mapping = {"nom_client": "NOM", "source": "Source Data"}
    result = merge_mapped_row(src, mapping, ["NOM", "Source Data"], "clients.csv (Feuille1)", set())
    assert result == {"NOM": "Dupont", "Source Data": "clients.csv (Feuille1)"}


def test_merge_mapped_row_omits_source_data_when_not_a_master_column():
    src = {"nom_client": "Dupont"}
    mapping = {"nom_client": "NOM"}
    result = merge_mapped_row(src, mapping, ["NOM"], "clients.csv (Feuille1)", set())
    assert "Source Data" not in result


def test_merge_mapped_row_cleans_internal_spaces_on_iban_columns():
    src = {"iban_ref": "FR76 3000 6000 0112 3456 7890 189"}
    mapping = {"iban_ref": "IBAN"}
    result = merge_mapped_row(src, mapping, ["IBAN"], None, {"IBAN"})
    assert result == {"IBAN": "FR7630006000011234567890189"}


def test_detect_iban_master_columns_by_name():
    assert detect_iban_master_columns([], ["NOM", "IBAN", "Référence bancaire"]) == {
        "IBAN", "Référence bancaire",
    }


def test_detect_iban_master_columns_by_content_when_name_is_generic():
    sample = [{"Compte": "FR76 3000 6000 0112 3456 7890 189"} for _ in range(3)]
    result = detect_iban_master_columns(sample, ["NOM", "Compte"])
    assert result == {"Compte"}


def test_detect_iban_master_columns_ignores_non_iban_content():
    sample = [{"NOM": "Dupont"}, {"NOM": "Martin"}]
    assert detect_iban_master_columns(sample, ["NOM"]) == set()
