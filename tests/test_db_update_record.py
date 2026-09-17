"""Teste trieur.db.update_record()/get_record()/get_profiles_map() avec
un faux client Supabase (aucun réseau)."""
from types import SimpleNamespace

from trieur.db import get_profiles_map, get_record, update_record


class _FakeTable:
    def __init__(self, store, name):
        self._store = store
        self._name = name
        self._payload = None
        self._filters = {}

    def update(self, payload):
        self._payload = dict(payload)
        return self

    def eq(self, field, value):
        self._filters[field] = value
        return self

    def select(self, *_args, **_kwargs):
        return self

    def limit(self, _n):
        return self

    def in_(self, field, values):
        self._filters[f"{field}__in"] = set(values)
        return self

    def execute(self):
        matched = [
            rec for rec in self._store[self._name]
            if all(
                (rec["id"] in v if k.endswith("__in") else rec.get(k) == v)
                for k, v in self._filters.items()
            )
        ]
        if self._payload is not None:
            # update() : le vrai client Supabase renvoie par defaut les
            # lignes affectees (returning=representation) -- verifie sur
            # le code installe (postgrest/_sync/request_builder.py),
            # jamais suppose.
            for rec in matched:
                rec.update(self._payload)
            return SimpleNamespace(data=matched)
        return SimpleNamespace(data=matched)


class _FakePostgrest:
    def __init__(self, store):
        self._store = store

    def schema(self, _name):
        return self

    def table(self, name):
        return _FakeTable(self._store, name)


class _FakeClient:
    def __init__(self, records=None, profiles=None):
        self.store = {"records": records or [], "profiles": profiles or []}
        self.postgrest = _FakePostgrest(self.store)


def test_update_record_replaces_data_and_stamps_who_when():
    client = _FakeClient(records=[{"id": "r1", "data": {"NOM": "Dupont"}, "updated_at": None, "updated_by": None}])

    update_record(client, "r1", {"NOM": "Dupont-Martin"}, "user-42")

    rec = client.store["records"][0]
    assert rec["data"] == {"NOM": "Dupont-Martin"}
    assert rec["updated_by"] == "user-42"
    assert rec["updated_at"] is not None


def test_update_record_only_touches_the_targeted_record():
    client = _FakeClient(records=[
        {"id": "r1", "data": {"NOM": "A"}, "updated_at": None, "updated_by": None},
        {"id": "r2", "data": {"NOM": "B"}, "updated_at": None, "updated_by": None},
    ])

    update_record(client, "r1", {"NOM": "A-modifié"}, "user-1")

    assert client.store["records"][0]["data"] == {"NOM": "A-modifié"}
    assert client.store["records"][1]["data"] == {"NOM": "B"}  # inchangé


def test_update_record_returns_true_on_match():
    client = _FakeClient(records=[{"id": "r1", "data": {}, "updated_at": None, "updated_by": None}])
    assert update_record(client, "r1", {"NOM": "X"}, "user-1") is True


def test_update_record_returns_false_when_record_no_longer_exists():
    """Le client visait un client supprime entre-temps par quelqu'un
    d'autre -- le caller (vue) doit pouvoir le detecter au lieu
    d'annoncer un succes qui n'a pas eu lieu."""
    client = _FakeClient(records=[])
    assert update_record(client, "does-not-exist", {"NOM": "X"}, "user-1") is False


def test_get_record_returns_current_data():
    client = _FakeClient(records=[{"id": "r1", "data": {"NOM": "Dupont"}}])
    assert get_record(client, "r1") == {"id": "r1", "data": {"NOM": "Dupont"}}


def test_get_record_returns_none_when_missing():
    client = _FakeClient(records=[])
    assert get_record(client, "does-not-exist") is None


def test_get_profiles_map_returns_known_ids_only():
    client = _FakeClient(profiles=[
        {"id": "u1", "full_name": "Alice"},
        {"id": "u2", "full_name": "Bob"},
    ])

    result = get_profiles_map(client, ("u1", "u3", None, ""))

    assert result == {"u1": {"id": "u1", "full_name": "Alice"}}


def test_get_profiles_map_empty_input_returns_empty_without_network_call():
    client = _FakeClient(profiles=[{"id": "u1", "full_name": "Alice"}])
    assert get_profiles_map(client, ()) == {}
    assert get_profiles_map(client, (None, "")) == {}
