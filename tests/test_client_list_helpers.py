"""Teste les fonctions pures extraites de views/tab_database.py
(_build_rows, _filter_by_search, _filter_by_columns) : partagées entre
l'affichage paginé de la liste clients et l'export complet -- un bug ici
casse les deux en même temps."""
from views.tab_database import _build_rows, _filter_by_columns, _filter_by_search


def test_build_rows_master_columns_first_then_extras():
    records = [
        {
            "id": "r1",
            "data": {"NOM": "Dupont", "EXTRA": "z"},
            "import_batches": {"source_filename": "a.csv", "imported_at": "2026-01-01"},
        },
    ]
    rows = _build_rows(records, master_cols=["NOM", "IBAN"])

    assert rows == [{
        "_id": "r1",
        "NOM": "Dupont",
        "IBAN": None,
        "EXTRA": "z",
        "Fichier source": "a.csv",
        "Importé le": "2026-01-01",
    }]


def test_build_rows_missing_data_or_batch_does_not_crash():
    records = [{"id": "r1", "data": None, "import_batches": None}]
    rows = _build_rows(records, master_cols=["NOM"])
    assert rows == [{"_id": "r1", "NOM": None, "Fichier source": None, "Importé le": None}]


def test_filter_by_search_is_case_insensitive_and_ignores_id():
    rows = [
        {"_id": "r1", "NOM": "Dupont"},
        {"_id": "r2", "NOM": "Martin"},
    ]
    assert [r["_id"] for r in _filter_by_search(rows, "DUPONT")] == ["r1"]
    assert [r["_id"] for r in _filter_by_search(rows, "")] == ["r1", "r2"]


def test_filter_by_search_never_matches_the_id_field_itself():
    rows = [{"_id": "unique-secret-id", "NOM": "Dupont"}]
    assert _filter_by_search(rows, "unique-secret-id") == []


def test_filter_by_columns_combines_with_and():
    rows = [
        {"_id": "r1", "NOM": "Dupont", "VILLE": "Paris"},
        {"_id": "r2", "NOM": "Dupont", "VILLE": "Lyon"},
        {"_id": "r3", "NOM": "Martin", "VILLE": "Paris"},
    ]
    result = _filter_by_columns(rows, {"NOM": "dupont", "VILLE": "paris"})
    assert [r["_id"] for r in result] == ["r1"]


def test_filter_by_columns_empty_filters_is_noop():
    rows = [{"_id": "r1", "NOM": "Dupont"}]
    assert _filter_by_columns(rows, {}) == rows


def test_filter_by_columns_missing_value_does_not_crash():
    rows = [{"_id": "r1", "NOM": None}]
    assert _filter_by_columns(rows, {"NOM": "x"}) == []
