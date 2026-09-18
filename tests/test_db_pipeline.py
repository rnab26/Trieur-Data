"""Teste les fonctions de staging du pipeline "Trieur de Data"
(trieur/db.py, voir supabase/migrations/0010_pipeline_staging.sql) avec un
faux client Supabase (aucun réseau) -- même pattern que
tests/test_db_import.py et tests/test_db_saved_views.py."""
from types import SimpleNamespace

from datetime import datetime, timedelta, timezone

from trieur.db import (
    append_pipeline_rows,
    append_pipeline_rows_bulk,
    create_pipeline_session,
    delete_expired_pipeline_sessions_for_org,
    delete_pipeline_export_preset,
    delete_pipeline_session,
    get_pipeline_session,
    get_remembered_mapping_for_shape,
    list_pipeline_export_presets,
    list_pipeline_rows,
    save_pipeline_export_preset,
    save_remembered_mapping_for_shape,
    update_pipeline_session_dedup,
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
        self._upsert_payload = None
        self._on_conflict = None

    def insert(self, payload):
        self._insert_payload = payload
        return self

    def upsert(self, payload, on_conflict=None):
        self._upsert_payload = payload
        self._on_conflict = on_conflict
        return self

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, field, value):
        self._filters[field] = value
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
        return [
            r
            for r in self._store[self._name]
            if all(r.get(k) == v for k, v in self._filters.items())
            and all(r.get(k) is not None and r.get(k) < v for k, v in self._lt_filters.items())
        ]

    def execute(self):
        if self._upsert_payload is not None:
            keys = (self._on_conflict or "").split(",")
            existing = next(
                (
                    r for r in self._store[self._name]
                    if all(r.get(k) == self._upsert_payload.get(k) for k in keys)
                ),
                None,
            )
            if existing is not None:
                existing.update(self._upsert_payload)
                row = existing
            else:
                row = {**self._DEFAULTS.get(self._name, {}), **self._upsert_payload}
                row.setdefault("id", f"{self._name}-{len(self._store[self._name])}")
                self._store[self._name].append(row)
            return SimpleNamespace(data=[row])
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
        self.store = {
            "pipeline_sessions": [],
            "pipeline_rows": [],
            "pipeline_remembered_mappings": [],
            "pipeline_export_presets": [],
        }
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


# ---------------------------------------------------------------
# [PERF] append_pipeline_rows_bulk -- correctif du goulot d'étranglement
# mesuré (SELECT+UPDATE par lot de append_pipeline_rows) : une seule
# lecture de row_count, une seule écriture, quel que soit le nombre de
# lots INSERT.
# ---------------------------------------------------------------

def test_append_pipeline_rows_bulk_inserts_all_rows_in_chunks():
    client = _FakeClient()
    session = create_pipeline_session(client, "org-1", "user-1")
    rows = [{"NOM": f"row{i}"} for i in range(10)]

    n = append_pipeline_rows_bulk(client, session["id"], rows, batch_size=3)

    assert n == 10
    stored = list_pipeline_rows(client, session["id"], limit=100)
    assert [r["row_index"] for r in stored] == list(range(10))
    assert get_pipeline_session(client, session["id"])["row_count"] == 10


def test_append_pipeline_rows_bulk_only_updates_row_count_once():
    """La cause racine du ralentissement mesuré : un SELECT+UPDATE par lot
    au lieu d'une seule lecture/écriture pour tout l'import -- ce test
    vérifie que la fonction "bulk" ne fait qu'UNE seule requête UPDATE
    sur pipeline_sessions, quel que soit le nombre de lots INSERT."""
    client = _FakeClient()
    session = create_pipeline_session(client, "org-1", "user-1")
    rows = [{"NOM": f"row{i}"} for i in range(9)]

    original_update = _FakeTable.update
    calls = []

    def _tracked_update(self, payload):
        if self._name == "pipeline_sessions":
            calls.append(payload)
        return original_update(self, payload)

    _FakeTable.update = _tracked_update
    try:
        append_pipeline_rows_bulk(client, session["id"], rows, batch_size=2)
    finally:
        _FakeTable.update = original_update

    assert len(calls) == 1
    assert calls[0] == {"row_count": 9}


def test_append_pipeline_rows_bulk_continues_row_index_from_start_index():
    client = _FakeClient()
    session = create_pipeline_session(client, "org-1", "user-1")
    append_pipeline_rows_bulk(client, session["id"], [{"NOM": "A"}, {"NOM": "B"}], start_index=0)

    append_pipeline_rows_bulk(client, session["id"], [{"NOM": "C"}], start_index=2)

    rows = list_pipeline_rows(client, session["id"], limit=100)
    assert [r["row_index"] for r in rows] == [0, 1, 2]
    assert get_pipeline_session(client, session["id"])["row_count"] == 3


def test_append_pipeline_rows_bulk_empty_list_is_a_noop():
    client = _FakeClient()
    session = create_pipeline_session(client, "org-1", "user-1")

    n = append_pipeline_rows_bulk(client, session["id"], [])

    assert n == 0
    assert get_pipeline_session(client, session["id"])["row_count"] == 0


# ---------------------------------------------------------------
# Dédoublonnage actif sur une session (persiste jusqu'à annulation).
# ---------------------------------------------------------------

def test_update_pipeline_session_dedup_sets_and_clears_config():
    client = _FakeClient()
    session = create_pipeline_session(client, "org-1", "user-1")

    update_pipeline_session_dedup(client, session["id"], {"column": "IBAN", "keep": "first"})
    assert get_pipeline_session(client, session["id"])["dedup_config"] == {"column": "IBAN", "keep": "first"}

    update_pipeline_session_dedup(client, session["id"], None)
    assert get_pipeline_session(client, session["id"])["dedup_config"] is None


# ---------------------------------------------------------------
# Mémoire du mapping par forme de fichier (remplace remembered_mappings.json).
# ---------------------------------------------------------------

def test_remembered_mapping_round_trip_and_default_empty():
    client = _FakeClient()

    assert get_remembered_mapping_for_shape(client, "org-1", "fp-1") == {}

    save_remembered_mapping_for_shape(client, "org-1", "fp-1", {"nom": "NOM"})

    assert get_remembered_mapping_for_shape(client, "org-1", "fp-1") == {"nom": "NOM"}


def test_remembered_mapping_same_fingerprint_replaces_not_duplicates():
    client = _FakeClient()
    save_remembered_mapping_for_shape(client, "org-1", "fp-1", {"nom": "NOM"})

    save_remembered_mapping_for_shape(client, "org-1", "fp-1", {"nom": "NOM", "iban_ref": "IBAN"})

    assert get_remembered_mapping_for_shape(client, "org-1", "fp-1") == {"nom": "NOM", "iban_ref": "IBAN"}
    assert len(client.store["pipeline_remembered_mappings"]) == 1


def test_remembered_mapping_scoped_by_org():
    client = _FakeClient()
    save_remembered_mapping_for_shape(client, "org-1", "fp-1", {"nom": "NOM"})

    assert get_remembered_mapping_for_shape(client, "org-2", "fp-1") == {}


# ---------------------------------------------------------------
# Presets d'export nommés (remplace export_presets.json).
# ---------------------------------------------------------------

def test_save_and_list_pipeline_export_presets():
    client = _FakeClient()

    save_pipeline_export_preset(client, "user-1", "org-1", "Export standard", ["NOM", "EMAIL"], ["CP"])

    presets = list_pipeline_export_presets(client, "user-1", "org-1")
    assert len(presets) == 1
    assert presets[0]["name"] == "Export standard"
    assert presets[0]["included"] == ["NOM", "EMAIL"]
    assert presets[0]["excluded"] == ["CP"]


def test_save_pipeline_export_preset_same_name_replaces():
    client = _FakeClient()
    save_pipeline_export_preset(client, "user-1", "org-1", "Standard", ["NOM"], [])

    save_pipeline_export_preset(client, "user-1", "org-1", "Standard", ["NOM", "EMAIL"], ["CP"])

    presets = list_pipeline_export_presets(client, "user-1", "org-1")
    assert len(presets) == 1
    assert presets[0]["included"] == ["NOM", "EMAIL"]


def test_delete_pipeline_export_preset():
    client = _FakeClient()
    save_pipeline_export_preset(client, "user-1", "org-1", "Standard", ["NOM"], [])
    preset_id = list_pipeline_export_presets(client, "user-1", "org-1")[0]["id"]

    delete_pipeline_export_preset(client, preset_id)

    assert list_pipeline_export_presets(client, "user-1", "org-1") == []
