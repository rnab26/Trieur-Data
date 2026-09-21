"""Teste trieur.db.list_org_memberships()/update_membership_role()/
remove_membership() et can_write_org() avec un faux client Supabase
(aucun réseau) -- même esprit que tests/test_db_saved_views.py."""
from types import SimpleNamespace

import pytest

from trieur.db import (
    can_write_org,
    get_my_memberships,
    get_profiles_map,
    list_org_memberships,
    remove_membership,
    update_membership_role,
)


@pytest.fixture(autouse=True)
def _clear_caches():
    """get_profiles_map (utilisé par list_org_memberships) est en
    @st.cache_data, clé sur les user_ids SANS le client (voir
    trieur/db.py) -- sans ce nettoyage avant ET après chaque test, un
    résultat mis en cache pour un id réutilisé (ex: "user-1") fuit vers
    un autre test de ce fichier, ou vers un autre fichier de test lancé
    dans le même processus pytest (déjà vu : tests/test_client_list_helpers.py
    récupérait un cache vide laissé par ce fichier)."""
    get_my_memberships.clear()
    get_profiles_map.clear()
    yield
    get_my_memberships.clear()
    get_profiles_map.clear()


class _FakeTable:
    def __init__(self, rows, name):
        self._rows = rows
        self._name = name
        self._filters = {}
        self._order = None
        self._payload = None
        self._op = None

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, field, value):
        self._filters[field] = value
        return self

    def in_(self, field, values):
        self._filters[field] = ("in", set(values))
        return self

    def order(self, field, *_args, **_kwargs):
        self._order = field
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def delete(self):
        self._op = "delete"
        return self

    def _matches(self, row):
        for field, value in self._filters.items():
            if isinstance(value, tuple) and value[0] == "in":
                if row.get(field) not in value[1]:
                    return False
            elif row.get(field) != value:
                return False
        return True

    def execute(self):
        matched = [r for r in self._rows if self._matches(r)]
        if self._op == "update":
            for r in matched:
                r.update(self._payload)
            return SimpleNamespace(data=matched)
        if self._op == "delete":
            for r in matched:
                self._rows.remove(r)
            return SimpleNamespace(data=matched)
        if self._order:
            matched = sorted(matched, key=lambda r: r.get(self._order) or "")
        return SimpleNamespace(data=matched)


class _FakePostgrest:
    def __init__(self, tables):
        self._tables = tables

    def schema(self, _name):
        return self

    def table(self, name):
        return _FakeTable(self._tables[name], name)


class _FakeClient:
    def __init__(self, memberships=None, profiles=None):
        self.postgrest = _FakePostgrest({
            "memberships": memberships or [],
            "profiles": profiles or [],
        })


def test_list_org_memberships_resolves_names():
    client = _FakeClient(
        memberships=[
            {"user_id": "user-1", "org_id": "org-1", "role": "member", "created_at": "2026-01-01"},
            {"user_id": "user-2", "org_id": "org-1", "role": "lecture_seule", "created_at": "2026-01-02"},
            {"user_id": "user-3", "org_id": "org-2", "role": "member", "created_at": "2026-01-01"},
        ],
        profiles=[
            {"id": "user-1", "full_name": "Alice"},
            {"id": "user-2", "full_name": "Bob"},
        ],
    )

    members = list_org_memberships(client, "org-1")

    assert [m["user_id"] for m in members] == ["user-1", "user-2"]
    assert members[0]["full_name"] == "Alice"
    assert members[1]["role"] == "lecture_seule"


def test_list_org_memberships_unresolvable_profile_is_none():
    client = _FakeClient(
        memberships=[{"user_id": "user-9", "org_id": "org-1", "role": "member", "created_at": "2026-01-01"}],
        profiles=[],
    )

    members = list_org_memberships(client, "org-1")

    assert members[0]["full_name"] is None


def test_update_membership_role_changes_only_target_row():
    client = _FakeClient(
        memberships=[
            {"user_id": "user-1", "org_id": "org-1", "role": "member", "created_at": "2026-01-01"},
            {"user_id": "user-2", "org_id": "org-1", "role": "member", "created_at": "2026-01-01"},
        ],
    )

    update_membership_role(client, "user-1", "org-1", "lecture_seule")

    members = {m["user_id"]: m["role"] for m in list_org_memberships(client, "org-1")}
    assert members == {"user-1": "lecture_seule", "user-2": "member"}


def test_remove_membership_drops_only_that_row():
    client = _FakeClient(
        memberships=[
            {"user_id": "user-1", "org_id": "org-1", "role": "member", "created_at": "2026-01-01"},
            {"user_id": "user-1", "org_id": "org-2", "role": "member", "created_at": "2026-01-01"},
        ],
    )

    remove_membership(client, "user-1", "org-1")

    assert list_org_memberships(client, "org-1") == []
    assert len(list_org_memberships(client, "org-2")) == 1


def test_can_write_org_blocks_lecture_seule_only():
    assert can_write_org("member", is_super_admin=False) is True
    assert can_write_org("org_admin", is_super_admin=False) is True
    assert can_write_org("lecture_seule", is_super_admin=False) is False
    assert can_write_org("lecture_seule", is_super_admin=True) is True
    assert can_write_org(None, is_super_admin=False) is True
