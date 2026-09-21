"""Teste les fonctions pures extraites de views/tab_database.py
(_build_rows, _filter_by_search, _filter_by_columns, _resolve_modifier_names)
: partagées entre l'affichage paginé de la liste clients et l'export
complet -- un bug ici casse les deux en même temps."""
from views.tab_database import (
    _apply_tags,
    _build_rows,
    _filter_by_columns,
    _filter_by_search,
    _resolve_modifier_names,
)


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
        "Modifié le": None,
        "_modifie_par_id": None,
    }]


def test_build_rows_missing_data_or_batch_does_not_crash():
    records = [{"id": "r1", "data": None, "import_batches": None}]
    rows = _build_rows(records, master_cols=["NOM"])
    assert rows == [{
        "_id": "r1", "NOM": None, "Fichier source": None, "Importé le": None,
        "Modifié le": None, "_modifie_par_id": None,
    }]


def test_build_rows_surfaces_raw_update_fields():
    records = [{
        "id": "r1", "data": {}, "import_batches": {},
        "updated_at": "2026-02-01T10:00:00Z", "updated_by": "user-1",
    }]
    rows = _build_rows(records, master_cols=[])
    assert rows[0]["Modifié le"] == "2026-02-01T10:00:00Z"
    assert rows[0]["_modifie_par_id"] == "user-1"


class _FakeClientForNames:
    """Faux client minimal pour _resolve_modifier_names : seul
    get_profiles_map (trieur.db) l'utilise, via .postgrest.schema(...)
    .table("profiles").select(...).in_(...).execute()."""

    class _Table:
        def __init__(self, profiles):
            self._profiles = profiles
            self._ids = None

        def select(self, *_a, **_k):
            return self

        def in_(self, _field, ids):
            self._ids = set(ids)
            return self

        def execute(self):
            from types import SimpleNamespace
            return SimpleNamespace(data=[p for p in self._profiles if p["id"] in self._ids])

    class _Postgrest:
        def __init__(self, profiles):
            self._profiles = profiles

        def schema(self, _name):
            return self

        def table(self, _name):
            return _FakeClientForNames._Table(self._profiles)

    def __init__(self, profiles):
        self.postgrest = self._Postgrest(profiles)


def test_resolve_modifier_names_replaces_id_with_full_name():
    client = _FakeClientForNames(profiles=[{"id": "user-1", "full_name": "Alice"}])
    rows = [{"_id": "r1", "_modifie_par_id": "user-1"}]

    result = _resolve_modifier_names(client, rows)

    assert result[0]["Modifié par"] == "Alice"
    assert "_modifie_par_id" not in result[0]


def test_resolve_modifier_names_unresolvable_id_becomes_quelquun():
    client = _FakeClientForNames(profiles=[])
    rows = [{"_id": "r1", "_modifie_par_id": "user-unknown"}]

    result = _resolve_modifier_names(client, rows)

    assert result[0]["Modifié par"] == "quelqu'un"


def test_resolve_modifier_names_never_modified_stays_none():
    client = _FakeClientForNames(profiles=[])
    rows = [{"_id": "r1", "_modifie_par_id": None}]

    result = _resolve_modifier_names(client, rows)

    assert result[0]["Modifié par"] is None


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
    result = _filter_by_columns(rows, {
        "NOM": {"op": "contient", "value": "dupont"},
        "VILLE": {"op": "contient", "value": "paris"},
    })
    assert [r["_id"] for r in result] == ["r1"]


def test_filter_by_columns_empty_filters_is_noop():
    rows = [{"_id": "r1", "NOM": "Dupont"}]
    assert _filter_by_columns(rows, {}) == rows


def test_filter_by_columns_missing_value_does_not_crash():
    rows = [{"_id": "r1", "NOM": None}]
    assert _filter_by_columns(rows, {"NOM": {"op": "contient", "value": "x"}}) == []


def test_filter_by_columns_operator_egal_a():
    rows = [{"_id": "r1", "VILLE": "Paris"}, {"_id": "r2", "VILLE": "Paris 15"}]
    result = _filter_by_columns(rows, {"VILLE": {"op": "égal à", "value": "paris"}})
    assert [r["_id"] for r in result] == ["r1"]


def test_filter_by_columns_operator_ne_contient_pas():
    rows = [{"_id": "r1", "VILLE": "Paris"}, {"_id": "r2", "VILLE": "Lyon"}]
    result = _filter_by_columns(rows, {"VILLE": {"op": "ne contient pas", "value": "paris"}})
    assert [r["_id"] for r in result] == ["r2"]


def test_filter_by_columns_operator_vide_et_non_vide():
    rows = [{"_id": "r1", "EMAIL": ""}, {"_id": "r2", "EMAIL": "a@b.com"}, {"_id": "r3", "EMAIL": None}]
    vides = _filter_by_columns(rows, {"EMAIL": {"op": "vide", "value": ""}})
    assert sorted(r["_id"] for r in vides) == ["r1", "r3"]
    non_vides = _filter_by_columns(rows, {"EMAIL": {"op": "non vide", "value": ""}})
    assert [r["_id"] for r in non_vides] == ["r2"]


def test_diff_rows_flags_differing_fields():
    from views.tab_database import diff_rows

    rows = diff_rows({"NOM": "Dupont", "VILLE": "Paris"}, {"NOM": "Dupont", "VILLE": "Lyon"})
    by_field = {r["Champ"]: r for r in rows}
    assert by_field["NOM"]["Différent"] == ""
    assert by_field["VILLE"]["Différent"] == "⚠️"


def test_diff_rows_includes_fields_only_on_one_side():
    from views.tab_database import diff_rows

    rows = diff_rows({"NOM": "Dupont"}, {"NOM": "Dupont", "IBAN": "FR76"})
    fields = {r["Champ"] for r in rows}
    assert fields == {"NOM", "IBAN"}


def test_diff_rows_handles_none_inputs():
    from views.tab_database import diff_rows
    assert diff_rows(None, None) == []


def test_filter_by_columns_vide_does_not_treat_zero_as_empty():
    rows = [{"_id": "r1", "MONTANT": 0}, {"_id": "r2", "MONTANT": None}]
    vides = _filter_by_columns(rows, {"MONTANT": {"op": "vide", "value": ""}})
    assert [r["_id"] for r in vides] == ["r2"]
    non_vides = _filter_by_columns(rows, {"MONTANT": {"op": "non vide", "value": ""}})
    assert [r["_id"] for r in non_vides] == ["r1"]


def test_diff_rows_does_not_treat_zero_as_equal_to_empty():
    from views.tab_database import diff_rows
    rows = diff_rows({"MONTANT": 0}, {"MONTANT": None})
    assert rows[0]["Différent"] == "⚠️"


class _FakeClientForTags:
    """Faux client minimal pour _apply_tags : seul get_record_tags_map
    (trieur.db) l'utilise, via .postgrest.schema(...).table("record_tags")
    .select(...).in_(...).execute(). Ids de test dédiés ("tags-testX")
    pour ne jamais entrer en collision avec le cache partagé d'un autre
    fichier de test (même piège déjà rencontré avec get_profiles_map)."""

    class _Table:
        def __init__(self, rows):
            self._rows = rows
            self._ids = None

        def select(self, *_a, **_k):
            return self

        def in_(self, _field, ids):
            self._ids = set(ids)
            return self

        def execute(self):
            from types import SimpleNamespace
            return SimpleNamespace(data=[r for r in self._rows if r["record_id"] in self._ids])

    class _Postgrest:
        def __init__(self, rows):
            self._rows = rows

        def schema(self, _name):
            return self

        def table(self, _name):
            return _FakeClientForTags._Table(self._rows)

    def __init__(self, rows):
        self.postgrest = self._Postgrest(rows)


def test_apply_tags_joins_sorted_comma_separated():
    from trieur.db import get_record_tags_map

    get_record_tags_map.clear()
    client = _FakeClientForTags([
        {"record_id": "tags-test-r1", "tag": "VIP"},
        {"record_id": "tags-test-r1", "tag": "à recontacter"},
    ])
    rows = [{"_id": "tags-test-r1"}]

    result = _apply_tags(client, rows)

    assert result[0]["Étiquettes"] == "VIP, à recontacter"
    get_record_tags_map.clear()


def test_apply_tags_no_tags_is_empty_string():
    from trieur.db import get_record_tags_map

    get_record_tags_map.clear()
    client = _FakeClientForTags([])
    rows = [{"_id": "tags-test-r2"}]

    result = _apply_tags(client, rows)

    assert result[0]["Étiquettes"] == ""
    get_record_tags_map.clear()
