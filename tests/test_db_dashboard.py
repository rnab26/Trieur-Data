"""Teste trieur.db.get_last_import_batch() avec un faux client Supabase
(aucun réseau) : alimente le résumé "où j'en suis" en haut de la Base
de données."""
from types import SimpleNamespace

from trieur.db import get_last_import_batch


class _FakeBatchesTable:
    def __init__(self, batches):
        self._batches = batches
        self._org_id = None

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, _field, value):
        self._org_id = value
        return self

    def order(self, _field, desc=False):
        self._desc = desc
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        matched = [b for b in self._batches if b["org_id"] == self._org_id]
        matched.sort(key=lambda b: b["imported_at"], reverse=self._desc)
        return SimpleNamespace(data=matched[: self._limit])


class _FakePostgrest:
    def __init__(self, batches):
        self._batches = batches

    def schema(self, _name):
        return self

    def table(self, _name):
        return _FakeBatchesTable(self._batches)


class _FakeClient:
    def __init__(self, batches):
        self.postgrest = _FakePostgrest(batches)


def test_get_last_import_batch_returns_most_recent():
    client = _FakeClient([
        {"org_id": "org-1", "source_filename": "ancien.csv", "imported_at": "2026-01-01T00:00:00Z"},
        {"org_id": "org-1", "source_filename": "recent.csv", "imported_at": "2026-02-01T00:00:00Z"},
    ])
    result = get_last_import_batch(client, "org-1")
    assert result["source_filename"] == "recent.csv"


def test_get_last_import_batch_none_when_no_import_yet():
    client = _FakeClient([])
    assert get_last_import_batch(client, "org-1") is None


def test_get_last_import_batch_scoped_to_org():
    client = _FakeClient([
        {"org_id": "org-1", "source_filename": "a.csv", "imported_at": "2026-01-01T00:00:00Z"},
        {"org_id": "org-2", "source_filename": "b.csv", "imported_at": "2026-03-01T00:00:00Z"},
    ])
    result = get_last_import_batch(client, "org-1")
    assert result["source_filename"] == "a.csv"
