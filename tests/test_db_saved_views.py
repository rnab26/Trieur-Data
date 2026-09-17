"""Teste trieur.db.list_saved_views()/save_saved_view()/delete_saved_view()
avec un faux client Supabase (aucun réseau)."""
from types import SimpleNamespace

from trieur.db import delete_saved_view, list_saved_views, save_saved_view


class _FakeViewsTable:
    def __init__(self, store):
        self._store = store
        self._filters = {}
        self._upsert_payload = None
        self._delete = False

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, field, value):
        self._filters[field] = value
        return self

    def order(self, *_args, **_kwargs):
        return self

    def upsert(self, payload, on_conflict=None):
        self._upsert_payload = dict(payload)
        self._on_conflict_fields = (on_conflict or "").split(",")
        return self

    def delete(self):
        self._delete = True
        return self

    def execute(self):
        if self._upsert_payload is not None:
            key_fields = self._on_conflict_fields
            existing = next(
                (r for r in self._store if all(r.get(f) == self._upsert_payload.get(f) for f in key_fields)),
                None,
            )
            if existing is not None:
                existing.update(self._upsert_payload)
                row = existing
            else:
                row = dict(self._upsert_payload)
                row["id"] = f"view-{len(self._store)}"
                self._store.append(row)
            return SimpleNamespace(data=[row])
        if self._delete:
            matched = [r for r in self._store if all(r.get(k) == v for k, v in self._filters.items())]
            for r in matched:
                self._store.remove(r)
            return SimpleNamespace(data=matched)
        matched = [r for r in self._store if all(r.get(k) == v for k, v in self._filters.items())]
        return SimpleNamespace(data=sorted(matched, key=lambda r: r.get("name", "")))


class _FakePostgrest:
    def __init__(self, store):
        self._store = store

    def schema(self, _name):
        return self

    def table(self, _name):
        return _FakeViewsTable(self._store)


class _FakeClient:
    def __init__(self):
        self.store = []
        self.postgrest = _FakePostgrest(self.store)


def test_save_then_list_saved_view():
    client = _FakeClient()
    save_saved_view(client, "user-1", "org-1", "Prélèvements actifs", "dupont", {"VILLE": "paris"}, ["NOM", "VILLE"])

    views = list_saved_views(client, "user-1", "org-1")

    assert len(views) == 1
    assert views[0]["name"] == "Prélèvements actifs"
    assert views[0]["search"] == "dupont"
    assert views[0]["col_filters"] == {"VILLE": "paris"}
    assert views[0]["visible_cols"] == ["NOM", "VILLE"]


def test_save_same_name_replaces_instead_of_duplicating():
    client = _FakeClient()
    save_saved_view(client, "user-1", "org-1", "Vue A", "old", {}, [])
    save_saved_view(client, "user-1", "org-1", "Vue A", "new", {}, [])

    views = list_saved_views(client, "user-1", "org-1")

    assert len(views) == 1
    assert views[0]["search"] == "new"


def test_list_saved_views_scoped_to_user_and_org():
    client = _FakeClient()
    save_saved_view(client, "user-1", "org-1", "Vue A", "", {}, [])
    save_saved_view(client, "user-2", "org-1", "Vue B", "", {}, [])
    save_saved_view(client, "user-1", "org-2", "Vue C", "", {}, [])

    views = list_saved_views(client, "user-1", "org-1")

    assert [v["name"] for v in views] == ["Vue A"]


def test_delete_saved_view():
    client = _FakeClient()
    saved = save_saved_view(client, "user-1", "org-1", "Vue A", "", {}, [])

    delete_saved_view(client, saved["id"])

    assert list_saved_views(client, "user-1", "org-1") == []
