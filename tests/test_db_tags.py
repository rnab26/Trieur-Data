"""Teste trieur.db.list_org_tags()/get_record_tags_map()/add_record_tag()/
remove_record_tag() avec un faux client Supabase (aucun réseau) -- même
esprit que tests/test_db_saved_views.py."""
from types import SimpleNamespace

import pytest

from trieur.db import (
    add_record_tag,
    get_record_tags_map,
    list_org_tags,
    remove_record_tag,
)


class _FakeTagsTable:
    def __init__(self, store):
        self._store = store
        self._filters = {}
        self._in_filters = {}
        self._upsert_payload = None
        self._on_conflict_fields = None
        self._delete = False

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, field, value):
        self._filters[field] = value
        return self

    def in_(self, field, values):
        self._in_filters[field] = set(values)
        return self

    def upsert(self, payload, on_conflict=None):
        self._upsert_payload = dict(payload)
        self._on_conflict_fields = (on_conflict or "").split(",")
        return self

    def delete(self):
        self._delete = True
        return self

    def _matches(self, row):
        for field, value in self._filters.items():
            if row.get(field) != value:
                return False
        for field, values in self._in_filters.items():
            if row.get(field) not in values:
                return False
        return True

    def execute(self):
        if self._upsert_payload is not None:
            keys = self._on_conflict_fields
            existing = next(
                (r for r in self._store if all(r.get(k) == self._upsert_payload.get(k) for k in keys)),
                None,
            )
            if existing is not None:
                existing.update(self._upsert_payload)
                row = existing
            else:
                row = dict(self._upsert_payload)
                row["id"] = f"tag-{len(self._store)}"
                self._store.append(row)
            return SimpleNamespace(data=[row])
        if self._delete:
            matched = [r for r in self._store if self._matches(r)]
            for r in matched:
                self._store.remove(r)
            return SimpleNamespace(data=matched)
        matched = [r for r in self._store if self._matches(r)]
        return SimpleNamespace(data=matched)


class _FakePostgrest:
    def __init__(self, store):
        self._store = store

    def schema(self, _name):
        return self

    def table(self, _name):
        return _FakeTagsTable(self._store)


class _FakeClient:
    def __init__(self):
        self.store = []
        self.postgrest = _FakePostgrest(self.store)


@pytest.fixture(autouse=True)
def _clear_caches():
    list_org_tags.clear()
    get_record_tags_map.clear()
    yield
    list_org_tags.clear()
    get_record_tags_map.clear()


def test_add_then_list_org_tags_sorted_and_deduped():
    client = _FakeClient()
    add_record_tag(client, "org-1", "rec-1", "VIP", "user-1")
    add_record_tag(client, "org-1", "rec-2", "à recontacter", "user-1")
    add_record_tag(client, "org-1", "rec-2", "VIP", "user-1")

    assert list_org_tags(client, "org-1") == ["VIP", "à recontacter"]


def test_add_same_tag_twice_does_not_duplicate():
    client = _FakeClient()
    add_record_tag(client, "org-1", "rec-1", "VIP", "user-1")
    add_record_tag(client, "org-1", "rec-1", "VIP", "user-1")

    tags = get_record_tags_map(client, ("rec-1",))
    assert tags["rec-1"] == ["VIP"]


def test_get_record_tags_map_scoped_per_record():
    client = _FakeClient()
    add_record_tag(client, "org-1", "rec-1", "VIP", "user-1")
    add_record_tag(client, "org-1", "rec-2", "litige", "user-1")

    tags = get_record_tags_map(client, ("rec-1", "rec-2"))
    assert tags == {"rec-1": ["VIP"], "rec-2": ["litige"]}


def test_get_record_tags_map_empty_ids_is_noop():
    client = _FakeClient()
    assert get_record_tags_map(client, ()) == {}


def test_remove_record_tag_drops_only_that_tag():
    client = _FakeClient()
    add_record_tag(client, "org-1", "rec-1", "VIP", "user-1")
    add_record_tag(client, "org-1", "rec-1", "litige", "user-1")

    remove_record_tag(client, "rec-1", "VIP")

    tags = get_record_tags_map(client, ("rec-1",))
    assert tags["rec-1"] == ["litige"]
