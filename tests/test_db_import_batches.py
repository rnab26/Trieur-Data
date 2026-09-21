"""Teste trieur.db.list_recent_import_batches()/cancel_import_batch()
avec un faux client Supabase (aucun réseau) -- même esprit que
tests/test_db_saved_views.py. Le cascade réel (records/dedup_alerts/
record_tags supprimés avec leur lot) est garanti par la contrainte SQL
(migration 0001) -- ici on vérifie juste que la fonction cible bien le
bon lot, dans la bonne table."""
from types import SimpleNamespace

from trieur.db import RECENT_IMPORT_BATCHES_LIMIT, cancel_import_batch, list_recent_import_batches


class _FakeBatchesTable:
    def __init__(self, store):
        self._store = store
        self._filters = {}
        self._order = None
        self._limit = None
        self._delete = False

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, field, value):
        self._filters[field] = value
        return self

    def order(self, field, desc=False):
        self._order = (field, desc)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def delete(self):
        self._delete = True
        return self

    def _matches(self, row):
        return all(row.get(k) == v for k, v in self._filters.items())

    def execute(self):
        matched = [r for r in self._store if self._matches(r)]
        if self._delete:
            for r in matched:
                self._store.remove(r)
            return SimpleNamespace(data=matched)
        if self._order:
            field, desc = self._order
            matched = sorted(matched, key=lambda r: r[field], reverse=desc)
        if self._limit is not None:
            matched = matched[: self._limit]
        return SimpleNamespace(data=matched)


class _FakePostgrest:
    def __init__(self, store):
        self._store = store

    def schema(self, _name):
        return self

    def table(self, _name):
        return _FakeBatchesTable(self._store)


class _FakeClient:
    def __init__(self, batches):
        self.store = batches
        self.postgrest = _FakePostgrest(self.store)


def _batch(i, org_id="org-1"):
    return {
        "id": f"batch-{i}",
        "org_id": org_id,
        "source_filename": f"fichier{i}.csv",
        "imported_at": f"2026-01-{i:02d}T00:00:00Z",
        "row_count": i * 10,
    }


def test_list_recent_import_batches_most_recent_first():
    client = _FakeClient([_batch(1), _batch(3), _batch(2)])

    batches = list_recent_import_batches(client, "org-1")

    assert [b["id"] for b in batches] == ["batch-3", "batch-2", "batch-1"]


def test_list_recent_import_batches_scoped_to_org():
    client = _FakeClient([_batch(1, org_id="org-1"), _batch(2, org_id="org-2")])

    batches = list_recent_import_batches(client, "org-1")

    assert [b["id"] for b in batches] == ["batch-1"]


def test_list_recent_import_batches_capped_to_limit():
    client = _FakeClient([_batch(i) for i in range(1, RECENT_IMPORT_BATCHES_LIMIT + 5)])

    batches = list_recent_import_batches(client, "org-1")

    assert len(batches) == RECENT_IMPORT_BATCHES_LIMIT


def test_cancel_import_batch_removes_only_that_batch():
    client = _FakeClient([_batch(1), _batch(2)])

    cancel_import_batch(client, "batch-1")

    remaining = list_recent_import_batches(client, "org-1")
    assert [b["id"] for b in remaining] == ["batch-2"]
