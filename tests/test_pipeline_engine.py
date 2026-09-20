"""Teste api/pipeline_engine.py : le pont entre trieur/filters.py (le
"cœur métier" filtre/dédoublonnage de l'onglet 3, testé indépendamment
dans tests/test_filters.py) et des lignes {id, data} comme les renvoie
le staging Postgres (trieur_data.pipeline_rows). Ces tests vérifient
uniquement le PONT (identifiants -> DataFrame -> identifiants) : les
règles de filtre/dédoublonnage elles-mêmes ne sont jamais réécrites ici."""
from api.pipeline_engine import (
    dedupe_manual,
    dedupe_rule,
    duplicate_groups_for_rows,
    filter_rows,
)


def _rows(*items):
    """items: [(id, {col: val, ...}), ...] -> [{"id":..., "data":...}, ...]"""
    return [{"id": i, "data": d} for i, d in items]


def test_filter_rows_empty_groups_returns_everything():
    rows = _rows(("a", {"VILLE": "Lyon"}), ("b", {"VILLE": "Paris"}))
    assert filter_rows(rows, []) == rows


def test_filter_rows_applies_values_criterion():
    rows = _rows(("a", {"VILLE": "Lyon"}), ("b", {"VILLE": "Paris"}))
    result = filter_rows(rows, [[{"column": "VILLE", "kind": "valeurs", "values": ["Lyon"]}]])
    assert [r["id"] for r in result] == ["a"]


def test_filter_rows_departements_criterion_matches_cp_prefix():
    rows = _rows(("a", {"CP": "33000"}), ("b", {"CP": "75001"}))
    result = filter_rows(rows, [[{"column": "CP", "kind": "departements", "values": ["33"]}]])
    assert [r["id"] for r in result] == ["a"]


def test_filter_rows_or_between_groups_and_between_criteria():
    rows = _rows(
        ("a", {"CP": "34000", "VILLE": "Montpellier"}),
        ("b", {"CP": "71000", "VILLE": "Lyon"}),
        ("c", {"CP": "71000", "VILLE": "Macon"}),
    )
    groups = [
        [{"column": "CP", "kind": "departements", "values": ["34"]}],
        [
            {"column": "CP", "kind": "departements", "values": ["71"]},
            {"column": "VILLE", "kind": "valeurs", "values": ["Lyon"]},
        ],
    ]
    result = filter_rows(rows, groups)
    assert {r["id"] for r in result} == {"a", "b"}


def test_filter_rows_empty_value_never_matches_a_value_criterion():
    """Une case vide sur la colonne filtrée n'est jamais un doublon d'une
    autre case vide -- ici, elle est simplement exclue d'un filtre sur
    une valeur précise (voir trieur/filters.py:apply_single_criterion)."""
    rows = _rows(("a", {"VILLE": "Lyon"}), ("b", {"VILLE": None}))
    result = filter_rows(rows, [[{"column": "VILLE", "kind": "valeurs", "values": ["Lyon"]}]])
    assert [r["id"] for r in result] == ["a"]


def test_duplicate_groups_for_rows_groups_by_value_and_suggests_most_complete():
    rows = _rows(
        ("a", {"EMAIL": "x@y.com", "NOM": "Dupont"}),
        ("b", {"EMAIL": "x@y.com", "NOM": None}),
        ("c", {"EMAIL": "z@y.com", "NOM": "Martin"}),
    )
    groups = duplicate_groups_for_rows(rows, "EMAIL")
    assert len(groups) == 1
    assert groups[0]["value"] == "x@y.com"
    assert set(groups[0]["row_ids"]) == {"a", "b"}
    # "a" a plus de colonnes remplies (NOM non vide) -> suggéré à garder.
    assert groups[0]["suggested_keep_id"] == "a"


def test_duplicate_groups_for_rows_ignores_empty_values():
    rows = _rows(("a", {"EMAIL": ""}), ("b", {"EMAIL": None}), ("c", {"EMAIL": "z@y.com"}))
    assert duplicate_groups_for_rows(rows, "EMAIL") == []


def test_duplicate_groups_for_rows_missing_column_returns_no_group():
    rows = _rows(("a", {"NOM": "Dupont"}))
    assert duplicate_groups_for_rows(rows, "EMAIL") == []


def test_dedupe_rule_first_keeps_earliest_row_per_value():
    rows = _rows(
        ("a", {"TELEPHONE MOBILE": "0600000000"}),
        ("b", {"TELEPHONE MOBILE": "0600000000"}),
        ("c", {"TELEPHONE MOBILE": "0700000000"}),
    )
    kept, removed = dedupe_rule(rows, "TELEPHONE MOBILE", keep="first")
    assert kept == ["a", "c"]
    assert removed == ["b"]


def test_dedupe_rule_complete_keeps_the_row_with_fewest_empty_fields():
    rows = _rows(
        ("a", {"TELEPHONE MOBILE": "0600000000", "NOM": None}),
        ("b", {"TELEPHONE MOBILE": "0600000000", "NOM": "Dupont"}),
    )
    kept, removed = dedupe_rule(rows, "TELEPHONE MOBILE", keep="complete")
    assert kept == ["b"]
    assert removed == ["a"]


def test_dedupe_rule_rows_without_value_are_always_kept():
    rows = _rows(("a", {"TELEPHONE MOBILE": None}), ("b", {"TELEPHONE MOBILE": ""}))
    kept, removed = dedupe_rule(rows, "TELEPHONE MOBILE", keep="first")
    assert set(kept) == {"a", "b"}
    assert removed == []


def test_dedupe_manual_keeps_only_the_chosen_id_per_group():
    rows = _rows(
        ("a", {"EMAIL": "x@y.com"}),
        ("b", {"EMAIL": "x@y.com"}),
        ("c", {"EMAIL": "x@y.com"}),
        ("d", {"EMAIL": "z@y.com"}),
    )
    kept, removed = dedupe_manual(rows, "EMAIL", ["b"])
    assert set(kept) == {"b", "d"}
    assert set(removed) == {"a", "c"}


def test_empty_rows_are_a_noop_everywhere():
    assert filter_rows([], [[{"column": "X", "kind": "valeurs", "values": ["a"]}]]) == []
    assert duplicate_groups_for_rows([], "X") == []
    assert dedupe_rule([], "X") == ([], [])
    assert dedupe_manual([], "X", ["a"]) == ([], [])
