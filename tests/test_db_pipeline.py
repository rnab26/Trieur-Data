"""Teste les fonctions de staging du pipeline "Trieur de Data"
(trieur/db.py, voir supabase/migrations/0010_pipeline_staging.sql) avec un
faux client Supabase (aucun réseau) -- même pattern que
tests/test_db_import.py et tests/test_db_saved_views.py."""
from types import SimpleNamespace

from datetime import datetime, timedelta, timezone

from trieur.db import (
    append_pipeline_rows,
    create_pipeline_session,
    delete_expired_pipeline_sessions_for_org,
    delete_pipeline_rows,
    delete_pipeline_session,
    get_pipeline_session,
    list_pipeline_rows,
    update_pipeline_session_status,
)


class _FakeTable:
    """Reproduit juste assez de l'API supabase-py (postgrest-py) pour ces
    fonctions : insert (dict ou liste de dicts), select/eq/order/limit/
    offset, update, delete -- un seul store par table, partagé entre
    toutes les instances via le dict passé au constructeur.

    `_DEFAULTS` reproduit les valeurs par défaut posées côté SQL
    (migration 0010) sur les colonnes qu'un insert ne fournit pas
    explicitement (ex: `row_count`, `status`) -- sans ça, un insert sur
    ce faux client renverrait une ligne incomplète par rapport à ce que
    Postgres renvoie réellement."""

    _DEFAULTS = {
        "pipeline_sessions": {"status": "importing", "row_count": 0},
    }

    def __init__(self, store, name):
        self._store = store
        self._name = name
        self._filters = {}
        self._lt_filters = {}
        self._insert_payload = None
        self._update_payload = None
        self._delete = False
        self._order_field = None
        self._limit = None
        self._offset = 0

    def insert(self, payload):
        self._insert_payload = payload
        return self

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, field, value):
        self._filters[field] = value
        return self

    def in_(self, field, values):
        self._filters[field] = ("in", set(values))
        return self

    def lt(self, field, value):
        self._lt_filters[field] = value
        return self

    def order(self, field, desc=False):
        self._order_field = (field, desc)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def offset(self, n):
        self._offset = n
        return self

    def update(self, payload):
        self._update_payload = dict(payload)
        return self

    def delete(self):
        self._delete = True
        return self

    def _matched(self):
        def _match_one(r, k, v):
            if isinstance(v, tuple) and v[0] == "in":
                return r.get(k) in v[1]
            return r.get(k) == v

        return [
            r
            for r in self._store[self._name]
            if all(_match_one(r, k, v) for k, v in self._filters.items())
            and all(r.get(k) is not None and r.get(k) < v for k, v in self._lt_filters.items())
        ]

    def execute(self):
        if self._insert_payload is not None:
            rows = self._insert_payload if isinstance(self._insert_payload, list) else [self._insert_payload]
            inserted = []
            for row in rows:
                rec = {**self._DEFAULTS.get(self._name, {}), **row}
                rec.setdefault("id", f"{self._name}-{len(self._store[self._name])}")
                self._store[self._name].append(rec)
                inserted.append(rec)
            return SimpleNamespace(data=inserted)
        if self._update_payload is not None:
            matched = self._matched()
            for r in matched:
                r.update(self._update_payload)
            return SimpleNamespace(data=matched)
        if self._delete:
            matched = self._matched()
            for r in matched:
                self._store[self._name].remove(r)
            return SimpleNamespace(data=matched)
        matched = self._matched()
        if self._order_field:
            field, desc = self._order_field
            matched = sorted(matched, key=lambda r: r.get(field), reverse=desc)
        matched = matched[self._offset:]
        if self._limit is not None:
            matched = matched[: self._limit]
        return SimpleNamespace(data=matched)


class _FakePostgrest:
    def __init__(self, store):
        self._store = store

    def schema(self, _name):
        return self

    def table(self, name):
        return _FakeTable(self._store, name)


class _FakeClient:
    def __init__(self):
        self.store = {"pipeline_sessions": [], "pipeline_rows": []}
        self.postgrest = _FakePostgrest(self.store)


def test_create_then_get_pipeline_session():
    client = _FakeClient()
    session = create_pipeline_session(client, "org-1", "user-1", source_filename="clients.csv")

    assert session["org_id"] == "org-1"
    assert session["created_by"] == "user-1"
    assert session["source_filename"] == "clients.csv"

    fetched = get_pipeline_session(client, session["id"])
    assert fetched["id"] == session["id"]


def test_get_pipeline_session_returns_none_when_missing():
    """Session supprimée par le nettoyage TTL ou jamais créée : `None`,
    jamais une erreur -- l'appelant doit pouvoir dire "session expirée"."""
    client = _FakeClient()

    assert get_pipeline_session(client, "does-not-exist") is None


def test_append_pipeline_rows_sets_row_index_and_updates_row_count():
    client = _FakeClient()
    session = create_pipeline_session(client, "org-1", "user-1")

    n = append_pipeline_rows(client, session["id"], [{"NOM": "Dupont"}, {"NOM": "Martin"}])

    assert n == 2
    rows = list_pipeline_rows(client, session["id"])
    assert [r["row_index"] for r in rows] == [0, 1]
    assert [r["data"]["NOM"] for r in rows] == ["Dupont", "Martin"]
    assert get_pipeline_session(client, session["id"])["row_count"] == 2


def test_append_pipeline_rows_in_two_batches_continues_row_index():
    """Import par lots (fichier volumineux) : le deuxième appel reprend à
    `start_index`, jamais recalculé depuis le nombre de lignes déjà en
    base par la fonction elle-même -- c'est l'appelant qui connaît sa
    position dans le fichier source."""
    client = _FakeClient()
    session = create_pipeline_session(client, "org-1", "user-1")

    append_pipeline_rows(client, session["id"], [{"NOM": "A"}, {"NOM": "B"}], start_index=0)
    append_pipeline_rows(client, session["id"], [{"NOM": "C"}], start_index=2)

    rows = list_pipeline_rows(client, session["id"])
    assert [r["row_index"] for r in rows] == [0, 1, 2]
    assert get_pipeline_session(client, session["id"])["row_count"] == 3


def test_append_pipeline_rows_empty_list_is_a_noop():
    client = _FakeClient()
    session = create_pipeline_session(client, "org-1", "user-1")

    n = append_pipeline_rows(client, session["id"], [])

    assert n == 0
    assert get_pipeline_session(client, session["id"])["row_count"] == 0


def test_list_pipeline_rows_ordered_by_row_index_not_insertion_order():
    client = _FakeClient()
    session = create_pipeline_session(client, "org-1", "user-1")
    # Insertion volontairement dans le désordre.
    append_pipeline_rows(client, session["id"], [{"NOM": "C"}], start_index=2)
    append_pipeline_rows(client, session["id"], [{"NOM": "A"}], start_index=0)
    append_pipeline_rows(client, session["id"], [{"NOM": "B"}], start_index=1)

    rows = list_pipeline_rows(client, session["id"])

    assert [r["data"]["NOM"] for r in rows] == ["A", "B", "C"]


def test_delete_pipeline_rows_removes_only_listed_ids_and_updates_row_count():
    """Utilisé par la suppression de doublons (onglet 3, api/pipeline_engine.py) :
    seules les lignes listées disparaissent, `row_count` reflète le
    nouveau total -- une seule source de vérité pour ce compteur."""
    client = _FakeClient()
    session = create_pipeline_session(client, "org-1", "user-1")
    append_pipeline_rows(client, session["id"], [{"NOM": "A"}, {"NOM": "B"}, {"NOM": "C"}])
    rows = list_pipeline_rows(client, session["id"])
    to_remove = [rows[0]["id"], rows[2]["id"]]

    n = delete_pipeline_rows(client, session["id"], to_remove)

    assert n == 2
    remaining = list_pipeline_rows(client, session["id"])
    assert [r["data"]["NOM"] for r in remaining] == ["B"]
    assert get_pipeline_session(client, session["id"])["row_count"] == 1


def test_delete_pipeline_rows_empty_list_is_a_noop():
    client = _FakeClient()
    session = create_pipeline_session(client, "org-1", "user-1")
    append_pipeline_rows(client, session["id"], [{"NOM": "A"}])

    n = delete_pipeline_rows(client, session["id"], [])

    assert n == 0
    assert get_pipeline_session(client, session["id"])["row_count"] == 1


def test_delete_pipeline_rows_scoped_to_session_ignores_ids_of_other_sessions():
    client = _FakeClient()
    s1 = create_pipeline_session(client, "org-1", "user-1")
    s2 = create_pipeline_session(client, "org-1", "user-1")
    append_pipeline_rows(client, s1["id"], [{"NOM": "A"}])
    append_pipeline_rows(client, s2["id"], [{"NOM": "B"}])
    other_row_id = list_pipeline_rows(client, s2["id"])[0]["id"]

    n = delete_pipeline_rows(client, s1["id"], [other_row_id])

    assert n == 0
    assert len(list_pipeline_rows(client, s2["id"])) == 1


def test_list_pipeline_rows_paginates_with_limit_and_offset():
    client = _FakeClient()
    session = create_pipeline_session(client, "org-1", "user-1")
    append_pipeline_rows(client, session["id"], [{"NOM": f"row{i}"} for i in range(5)])

    page = list_pipeline_rows(client, session["id"], limit=2, offset=2)

    assert [r["row_index"] for r in page] == [2, 3]


def test_update_pipeline_session_status():
    client = _FakeClient()
    session = create_pipeline_session(client, "org-1", "user-1")

    update_pipeline_session_status(client, session["id"], "mapped")

    assert get_pipeline_session(client, session["id"])["status"] == "mapped"


def test_delete_expired_pipeline_sessions_for_org_removes_only_expired_ones():
    """Revue PR #24, point #8 : nettoyage opportuniste scopé à l'org de
    l'appelant (pas le RPC cross-org, réservé à service_role depuis la
    migration 0011) -- ne touche que les sessions de CET org, et
    seulement celles déjà expirées."""
    client = _FakeClient()
    expired = create_pipeline_session(client, "org-1", "user-1")
    fresh = create_pipeline_session(client, "org-1", "user-1")
    other_org_expired = create_pipeline_session(client, "org-2", "user-1")

    now = datetime.now(timezone.utc)
    client.store["pipeline_sessions"][0]["expires_at"] = (now - timedelta(hours=1)).isoformat()
    client.store["pipeline_sessions"][1]["expires_at"] = (now + timedelta(hours=23)).isoformat()
    client.store["pipeline_sessions"][2]["expires_at"] = (now - timedelta(hours=1)).isoformat()

    n_deleted = delete_expired_pipeline_sessions_for_org(client, "org-1")

    assert n_deleted == 1
    assert get_pipeline_session(client, expired["id"]) is None
    assert get_pipeline_session(client, fresh["id"]) is not None
    # Un org différent, même expiré, n'est pas touché par cet appel --
    # scopé à org-1 uniquement.
    assert get_pipeline_session(client, other_org_expired["id"]) is not None


def test_delete_pipeline_session_removes_its_rows_too():
    """Le cascade réel est garanti par la contrainte SQL (migration
    0010) -- ici on vérifie juste que la fonction Python cible bien la
    session et n'oublie pas d'appeler la bonne table."""
    client = _FakeClient()
    session = create_pipeline_session(client, "org-1", "user-1")
    append_pipeline_rows(client, session["id"], [{"NOM": "Dupont"}])

    delete_pipeline_session(client, session["id"])

    assert get_pipeline_session(client, session["id"]) is None
