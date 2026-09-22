"""Teste api/main.py avec un faux client Supabase (aucun réseau) --
même esprit que tests/test_db_saved_views.py, injecté via
app.dependency_overrides plutôt qu'en remplaçant trieur.db lui-même :
les endpoints appellent les VRAIES fonctions de trieur/db.py, avec un
faux client Supabase en entrée."""
import io
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.main import MANDAT_COLONNES_CANONIQUES, app, get_supabase_client


# ---------------------------------------------------------------
# Faux client Supabase générique : couvre juste assez de l'API
# postgrest (schema().table().select()/insert()/update()/upsert()/
# delete().eq()/in_()/order()/limit()/offset().execute()) et de l'API
# auth (get_user) pour que les fonctions de trieur/db.py utilisées par
# api/main.py fonctionnent sans réseau.
# ---------------------------------------------------------------

class _FakeTable:
    # Valeurs par défaut posées côté SQL (colonnes qu'un insert ne fournit
    # pas explicitement) -- sans ça, un insert sur ce faux client renverrait
    # une ligne incomplète par rapport à ce que Postgres renvoie réellement
    # (voir tests/test_db_pipeline.py, même besoin pour ces deux tables).
    _DEFAULTS = {
        "pipeline_sessions": {"status": "importing", "row_count": 0},
        "chantier_questions": {"answer": None, "comment": None, "answered_at": None},
        "prelevement_rule_request_questions": {"answer": None, "comment": None, "answered_at": None},
    }

    def __init__(self, store, name=None):
        self.store = store
        self.name = name
        self._filters = []
        self._select_count = None
        self._order = None
        self._limit = None
        self._offset = 0
        self._op = None
        self._payload = None
        self._on_conflict = None
        self._lt_filters = []

    def select(self, *_a, count=None):
        self._select_count = count
        return self

    def eq(self, field, value):
        self._filters.append((field, value))
        return self

    def in_(self, field, values):
        self._filters.append((field, ("in", set(values))))
        return self

    def lt(self, field, value):
        self._lt_filters.append((field, value))
        return self

    def order(self, field, desc=False):
        self._order = (field, desc)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def offset(self, n):
        self._offset = n
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def upsert(self, payload, on_conflict=None):
        self._op = "upsert"
        self._payload = payload
        self._on_conflict = on_conflict
        return self

    def delete(self):
        self._op = "delete"
        return self

    def _field_value(self, row, field):
        # Reproduit juste assez de l'opérateur jsonb `->>` de PostgREST
        # (ex. "data->>_sheet") pour tester list_pipeline_rows_for_sheet
        # sans réseau -- extrait la clé du dict jsonb au lieu de chercher
        # un champ littéral "data->>_sheet" qui n'existe jamais sur une
        # vraie ligne.
        if "->>" in field:
            col, key = field.split("->>", 1)
            return (row.get(col) or {}).get(key)
        return row.get(field)

    def _matches(self, row):
        for field, value in self._filters:
            if isinstance(value, tuple) and value[0] == "in":
                if self._field_value(row, field) not in value[1]:
                    return False
            elif self._field_value(row, field) != value:
                return False
        for field, value in self._lt_filters:
            if row.get(field) is None or not (row.get(field) < value):
                return False
        return True

    def execute(self):
        if self._op == "insert":
            payload = self._payload if isinstance(self._payload, list) else [self._payload]
            inserted = []
            for item in payload:
                row = {**self._DEFAULTS.get(self.name, {}), **item}
                row.setdefault("id", f"row-{len(self.store)}")
                self.store.append(row)
                inserted.append(row)
            return SimpleNamespace(data=inserted, count=None)
        if self._op == "update":
            matched = [r for r in self.store if self._matches(r)]
            for r in matched:
                r.update(self._payload)
            return SimpleNamespace(data=matched, count=None)
        if self._op == "delete":
            matched = [r for r in self.store if self._matches(r)]
            for r in matched:
                self.store.remove(r)
            return SimpleNamespace(data=matched, count=None)
        if self._op == "upsert":
            keys = (self._on_conflict or "").split(",")
            existing = next(
                (r for r in self.store if all(r.get(k) == self._payload.get(k) for k in keys)),
                None,
            )
            if existing is not None:
                existing.update(self._payload)
                row = existing
            else:
                row = dict(self._payload)
                row.setdefault("id", f"row-{len(self.store)}")
                self.store.append(row)
            return SimpleNamespace(data=[row], count=None)

        matched = [r for r in self.store if self._matches(r)]
        if self._order:
            field, desc = self._order
            matched = sorted(matched, key=lambda r: r.get(field), reverse=desc)
        total = len(matched)
        if self._offset:
            matched = matched[self._offset:]
        if self._limit is not None:
            matched = matched[: self._limit]
        count = total if self._select_count == "exact" else None
        return SimpleNamespace(data=matched, count=count)


class _FakePostgrest:
    def __init__(self, tables):
        self.tables = tables

    def schema(self, _name):
        return self

    def table(self, name):
        return _FakeTable(self.tables.setdefault(name, []), name=name)

    def rpc(self, name, params):
        # Reproduit trieur_data.adjust_pipeline_row_count (migration 0012) :
        # UPDATE atomique de row_count -- voir trieur/db.py:delete_pipeline_rows.
        # `rpc()` renvoie un objet chaînable avec `.execute()`, comme postgrest-py.
        if name == "adjust_pipeline_row_count":
            def _execute():
                session = next(
                    (r for r in self.tables.get("pipeline_sessions", []) if r["id"] == params["p_session_id"]), None,
                )
                if session is not None:
                    session["row_count"] = max(0, session["row_count"] + params["p_delta"])
                return SimpleNamespace(data=[{"adjust_pipeline_row_count": session["row_count"]}] if session else [])

            return SimpleNamespace(execute=_execute)
        # Reproduit trieur_data.try_lock_pipeline_dedupe / unlock_pipeline_dedupe
        # (migrations 0013/0014) : verrou court par UPDATE ... WHERE atomique,
        # avec propriétaire (p_owner) pour qu'une requête qui a dépassé sa TTL
        # et perdu le verrou ne libère jamais celui d'un appelant plus récent
        # -- voir trieur/db.py:try_lock_pipeline_dedupe. Pas de vraie
        # concurrence dans ce faux client synchrone : le verrou est simulé
        # fidèlement (un verrou déjà posé et non expiré bloque un 2e claim,
        # unlock ne fait rien si le propriétaire ne correspond plus) pour que
        # les tests puissent vérifier le comportement, mais aucun test
        # n'exécute deux requêtes en parallèle ici.
        if name == "try_lock_pipeline_dedupe":
            def _execute():
                session = next(
                    (r for r in self.tables.get("pipeline_sessions", []) if r["id"] == params["p_session_id"]), None,
                )
                if session is None:
                    return SimpleNamespace(data=False)
                lock_at = session.get("dedupe_lock_at")
                ttl = params.get("p_ttl_seconds", 30)
                if lock_at is not None and (datetime.now(timezone.utc) - lock_at).total_seconds() < ttl:
                    return SimpleNamespace(data=False)
                session["dedupe_lock_at"] = datetime.now(timezone.utc)
                session["dedupe_lock_owner"] = params["p_owner"]
                return SimpleNamespace(data=True)

            return SimpleNamespace(execute=_execute)
        if name == "unlock_pipeline_dedupe":
            def _execute():
                session = next(
                    (r for r in self.tables.get("pipeline_sessions", []) if r["id"] == params["p_session_id"]), None,
                )
                if session is not None and session.get("dedupe_lock_owner") == params["p_owner"]:
                    session["dedupe_lock_at"] = None
                    session["dedupe_lock_owner"] = None
                return SimpleNamespace(data=None)

            return SimpleNamespace(execute=_execute)
        # Reproduit trieur_data.is_pipeline_dedupe_lock_owner (migration
        # 0015) : revérification juste avant le DELETE que l'appelant est
        # toujours propriétaire du verrou, voir trieur/db.py:is_pipeline_dedupe_lock_owner.
        if name == "is_pipeline_dedupe_lock_owner":
            def _execute():
                session = next(
                    (r for r in self.tables.get("pipeline_sessions", []) if r["id"] == params["p_session_id"]), None,
                )
                is_owner = session is not None and session.get("dedupe_lock_owner") == params["p_owner"]
                return SimpleNamespace(data=is_owner)

            return SimpleNamespace(execute=_execute)
        raise NotImplementedError(f"RPC non simulé dans ce faux client : {name}")

    def auth(self, _token):
        return self


class _FakeAuth:
    def __init__(self, users_by_token):
        self.users_by_token = users_by_token

    def get_user(self, token):
        user = self.users_by_token.get(token)
        if user is None:
            raise Exception("invalid token")
        return SimpleNamespace(user=user)


class _FakeClient:
    def __init__(self, tables, users_by_token):
        self.postgrest = _FakePostgrest(tables)
        self.auth = _FakeAuth(users_by_token)


USER = SimpleNamespace(id="user-1", email="alice@example.com")
TOKEN = "valid-token"


def _make_client(**tables):
    default_tables = {
        "profiles": [{"id": "user-1", "full_name": "Alice", "is_super_admin": False}],
        "memberships": [
            {"user_id": "user-1", "org_id": "org-1", "role": "member", "organizations": {"slug": "leads", "name": "Leads"}}
        ],
        "organizations": [{"id": "org-1", "slug": "leads", "name": "Leads", "master_columns": ["NOM", "IBAN"]}],
        "records": [],
        "import_batches": [],
        "dedup_alerts": [],
        "db_saved_views": [],
        "pipeline_sessions": [],
        "pipeline_rows": [],
        "user_master_column_sets": [],
        "record_tags": [],
    }
    default_tables.update(tables)
    return _FakeClient(default_tables, users_by_token={TOKEN: USER})


@pytest.fixture(autouse=True)
def _clear_streamlit_caches():
    """get_my_profile/get_my_memberships/get_org_master_columns/
    list_saved_views (trieur/db.py) sont en @st.cache_data avec le
    client exclu de la clé (paramètre `_client`) -- sans ce nettoyage,
    un test réutilise le résultat mis en cache par le test précédent
    pour le même user_id/org_id, même avec un faux client différent."""
    from trieur.db import (
        get_my_memberships,
        get_my_profile,
        get_org_master_columns,
        get_record_tags_map,
        list_org_tags,
        list_saved_views,
        list_sections,
    )

    get_my_profile.clear()
    get_my_memberships.clear()
    get_org_master_columns.clear()
    list_saved_views.clear()
    list_sections.clear()
    list_org_tags.clear()
    get_record_tags_map.clear()
    yield


@pytest.fixture
def client_factory():
    """Retourne une fonction qui construit un TestClient FastAPI branché
    sur un faux client Supabase donné, et nettoie l'override ensuite."""
    created = []

    def _factory(fake_client):
        app.dependency_overrides[get_supabase_client] = lambda: fake_client
        tc = TestClient(app)
        created.append(tc)
        return tc

    yield _factory
    app.dependency_overrides.pop(get_supabase_client, None)


# ---------------------------------------------------------------
# Auth
# ---------------------------------------------------------------

def test_missing_token_is_rejected(client_factory):
    tc = client_factory(_make_client())
    res = tc.get("/orgs")
    assert res.status_code == 401


def test_invalid_token_is_rejected(client_factory):
    tc = client_factory(_make_client())
    res = tc.get("/orgs", headers={"Authorization": "Bearer nope"})
    assert res.status_code == 401


def test_malformed_authorization_header_is_rejected(client_factory):
    tc = client_factory(_make_client())
    res = tc.get("/orgs", headers={"Authorization": "nope"})
    assert res.status_code == 401


def test_valid_token_lists_accessible_orgs(client_factory):
    tc = client_factory(_make_client())
    res = tc.get("/orgs", headers={"Authorization": f"Bearer {TOKEN}"})
    assert res.status_code == 200
    assert [o["id"] for o in res.json()] == ["org-1"]


def test_org_not_a_member_of_is_forbidden(client_factory):
    fake = _make_client(memberships=[])
    tc = client_factory(fake)
    res = tc.get("/orgs/org-1/dashboard", headers={"Authorization": f"Bearer {TOKEN}"})
    assert res.status_code == 403


# ---------------------------------------------------------------
# Profil courant (/me)
# ---------------------------------------------------------------

def test_me_returns_profile(client_factory):
    fake = _make_client(profiles=[{"id": "user-1", "full_name": "Alice", "is_super_admin": True}])
    tc = client_factory(fake)
    res = tc.get("/me", headers={"Authorization": f"Bearer {TOKEN}"})
    assert res.status_code == 200
    assert res.json()["profile"]["is_super_admin"] is True


def test_me_requires_auth(client_factory):
    tc = client_factory(_make_client())
    res = tc.get("/me")
    assert res.status_code == 401


# ---------------------------------------------------------------
# Records : pagination
# ---------------------------------------------------------------

def _record(i, org_id="org-1"):
    return {
        "id": f"rec-{i}",
        "org_id": org_id,
        "data": {"NOM": f"Client {i}", "IBAN": "FR76..."},
        "created_at": f"2026-01-{i:02d}T00:00:00Z",
        "import_batches": {"source_filename": "a.csv", "imported_at": "2026-01-01"},
    }


def test_records_pagination_first_page(client_factory):
    records = [_record(i) for i in range(1, 6)]
    fake = _make_client(records=records)
    tc = client_factory(fake)

    res = tc.get(
        "/orgs/org-1/records",
        params={"page": 1, "page_size": 2},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 5
    assert body["fetched"] == 2
    assert len(body["rows"]) == 2


def test_records_pagination_second_page_offsets(client_factory):
    records = [_record(i) for i in range(1, 6)]
    fake = _make_client(records=records)
    tc = client_factory(fake)

    res = tc.get(
        "/orgs/org-1/records",
        params={"page": 2, "page_size": 2},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    body = res.json()
    assert body["fetched"] == 2
    ids = {r["_id"] for r in body["rows"]}
    assert ids.isdisjoint({"rec-1"})  # page 1 pas re-renvoyée


def test_records_search_filters_current_page(client_factory):
    records = [
        {**_record(1), "data": {"NOM": "Dupont"}},
        {**_record(2), "data": {"NOM": "Martin"}},
    ]
    fake = _make_client(records=records)
    tc = client_factory(fake)

    res = tc.get(
        "/orgs/org-1/records",
        params={"search": "dupont"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    rows = res.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["NOM"] == "Dupont"


def test_records_invalid_col_filters_json_is_400(client_factory):
    tc = client_factory(_make_client())
    res = tc.get(
        "/orgs/org-1/records",
        params={"col_filters": "not-json"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 400


def test_records_col_filters_operators(client_factory):
    """`col_filters` façon Google Sheets (contient/égal à/vide/non vide),
    combinés en ET -- reroute vers views/tab_database.py:_filter_by_columns
    (voir api/main.py:list_org_records), pas une logique dupliquée côté
    API. Vérifie aussi le piège connu du projet : une valeur falsy (0)
    n'est pas confondue avec un champ "vide"."""
    records = [
        {**_record(1), "data": {"NOM": "Dupont", "ENFANTS": 0}},
        {**_record(2), "data": {"NOM": "Martin", "ENFANTS": 2}},
        {**_record(3), "data": {"NOM": "Durand", "ENFANTS": None}},
    ]
    fake = _make_client(records=records)
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}

    # "égal à" sur une colonne texte.
    res = tc.get(
        "/orgs/org-1/records",
        params={"col_filters": json.dumps({"NOM": {"op": "égal à", "value": "dupont"}})},
        headers=headers,
    )
    rows = res.json()["rows"]
    assert [r["NOM"] for r in rows] == ["Dupont"]

    # "non vide" sur ENFANTS : la ligne à 0 doit rester incluse (valeur
    # falsy mais réelle), seule la ligne à None (jamais renseignée) doit
    # être exclue.
    res = tc.get(
        "/orgs/org-1/records",
        params={"col_filters": json.dumps({"ENFANTS": {"op": "non vide", "value": ""}})},
        headers=headers,
    )
    rows = res.json()["rows"]
    assert {r["NOM"] for r in rows} == {"Dupont", "Martin"}

    # "vide" : seule la ligne jamais renseignée (None) doit apparaître --
    # pas celle à 0.
    res = tc.get(
        "/orgs/org-1/records",
        params={"col_filters": json.dumps({"ENFANTS": {"op": "vide", "value": ""}})},
        headers=headers,
    )
    rows = res.json()["rows"]
    assert [r["NOM"] for r in rows] == ["Durand"]

    # Deux filtres combinés en ET : aucune ligne ne correspond aux deux.
    res = tc.get(
        "/orgs/org-1/records",
        params={
            "col_filters": json.dumps(
                {"NOM": {"op": "contient", "value": "dupont"}, "ENFANTS": {"op": "égal à", "value": "2"}}
            )
        },
        headers=headers,
    )
    assert res.json()["rows"] == []


# ---------------------------------------------------------------
# Record : update
# ---------------------------------------------------------------

def test_update_record(client_factory):
    records = [_record(1)]
    fake = _make_client(records=records)
    tc = client_factory(fake)

    res = tc.patch(
        "/orgs/org-1/records/rec-1",
        json={"data": {"NOM": "Nouveau nom"}},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    assert res.json()["updated"] is True

    stored = next(r for r in fake.postgrest.tables["records"] if r["id"] == "rec-1")
    assert stored["data"] == {"NOM": "Nouveau nom"}
    assert stored["updated_by"] == "user-1"


def test_update_unknown_record_is_404(client_factory):
    fake = _make_client(records=[])
    tc = client_factory(fake)

    res = tc.patch(
        "/orgs/org-1/records/does-not-exist",
        json={"data": {"NOM": "x"}},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 404


def test_get_single_record(client_factory):
    records = [_record(1)]
    fake = _make_client(records=records)
    tc = client_factory(fake)

    res = tc.get("/orgs/org-1/records/rec-1", headers={"Authorization": f"Bearer {TOKEN}"})
    assert res.status_code == 200
    assert res.json()["data"]["NOM"] == "Client 1"


def test_get_missing_record_is_404(client_factory):
    fake = _make_client(records=[])
    tc = client_factory(fake)

    res = tc.get("/orgs/org-1/records/nope", headers={"Authorization": f"Bearer {TOKEN}"})
    assert res.status_code == 404


# ---------------------------------------------------------------
# Étiquettes libres sur un client (migration 0021)
# ---------------------------------------------------------------

def test_add_tag_then_it_appears_in_org_tags_and_record_list(client_factory):
    records = [_record(1)]
    fake = _make_client(records=records)
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}

    res = tc.post("/orgs/org-1/records/rec-1/tags", json={"tag": "VIP"}, headers=headers)
    assert res.status_code == 200
    assert res.json() == {"record_id": "rec-1", "tag": "VIP"}

    tags = tc.get("/orgs/org-1/tags", headers=headers)
    assert tags.json() == {"tags": ["VIP"]}

    listed = tc.get("/orgs/org-1/records", headers=headers)
    row = next(r for r in listed.json()["rows"] if r["_id"] == "rec-1")
    assert row["Étiquettes"] == "VIP"


def test_add_same_tag_twice_does_not_duplicate(client_factory):
    fake = _make_client(records=[_record(1)])
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}

    tc.post("/orgs/org-1/records/rec-1/tags", json={"tag": "VIP"}, headers=headers)
    tc.post("/orgs/org-1/records/rec-1/tags", json={"tag": "VIP"}, headers=headers)

    assert len(fake.postgrest.tables["record_tags"]) == 1


def test_add_blank_tag_is_400(client_factory):
    fake = _make_client(records=[_record(1)])
    tc = client_factory(fake)

    res = tc.post(
        "/orgs/org-1/records/rec-1/tags", json={"tag": "   "},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 400
    assert fake.postgrest.tables["record_tags"] == []


def test_remove_tag_drops_only_that_one(client_factory):
    fake = _make_client(records=[_record(1)])
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}

    tc.post("/orgs/org-1/records/rec-1/tags", json={"tag": "VIP"}, headers=headers)
    tc.post("/orgs/org-1/records/rec-1/tags", json={"tag": "litige"}, headers=headers)

    res = tc.delete("/orgs/org-1/records/rec-1/tags/VIP", headers=headers)
    assert res.status_code == 200

    remaining = {t["tag"] for t in fake.postgrest.tables["record_tags"]}
    assert remaining == {"litige"}


def test_export_includes_tags_column(client_factory):
    fake = _make_client(records=[_record(1)])
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    tc.post("/orgs/org-1/records/rec-1/tags", json={"tag": "VIP"}, headers=headers)

    res = tc.get("/orgs/org-1/records/export", params={"format": "csv"}, headers=headers)
    assert res.status_code == 200
    assert "VIP" in res.text


def test_read_only_member_cannot_add_tag(client_factory):
    fake = _make_client(records=[_record(1)], memberships=READ_ONLY_MEMBERSHIP)
    tc = client_factory(fake)

    res = tc.post(
        "/orgs/org-1/records/rec-1/tags", json={"tag": "VIP"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 403
    assert fake.postgrest.tables["record_tags"] == []


def test_read_only_member_cannot_remove_tag(client_factory):
    fake = _make_client(
        records=[_record(1)],
        record_tags=[{"record_id": "rec-1", "tag": "VIP", "org_id": "org-1"}],
        memberships=READ_ONLY_MEMBERSHIP,
    )
    tc = client_factory(fake)

    res = tc.delete(
        "/orgs/org-1/records/rec-1/tags/VIP", headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 403
    assert len(fake.postgrest.tables["record_tags"]) == 1


def test_read_only_member_can_still_see_tags(client_factory):
    fake = _make_client(
        records=[_record(1)],
        record_tags=[{"record_id": "rec-1", "tag": "VIP", "org_id": "org-1"}],
        memberships=READ_ONLY_MEMBERSHIP,
    )
    tc = client_factory(fake)

    res = tc.get("/orgs/org-1/tags", headers={"Authorization": f"Bearer {TOKEN}"})
    assert res.status_code == 200
    assert res.json() == {"tags": ["VIP"]}


# ---------------------------------------------------------------
# Vues enregistrées : create / list / delete
# ---------------------------------------------------------------

def test_saved_view_create_list_delete(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}

    created = tc.post(
        "/orgs/org-1/saved-views",
        json={"name": "Vue A", "search": "dupont", "col_filters": {}, "visible_cols": ["NOM"]},
        headers=headers,
    )
    assert created.status_code == 200
    view_id = created.json()["id"]

    listed = tc.get("/orgs/org-1/saved-views", headers=headers)
    assert [v["name"] for v in listed.json()] == ["Vue A"]

    deleted = tc.delete(f"/orgs/org-1/saved-views/{view_id}", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True

    listed_after = tc.get("/orgs/org-1/saved-views", headers=headers)
    assert listed_after.json() == []


def test_cannot_delete_someone_elses_saved_view(client_factory):
    fake = _make_client(
        db_saved_views=[{"id": "view-other", "user_id": "user-2", "org_id": "org-1", "name": "Pas la mienne"}],
    )
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}

    res = tc.delete("/orgs/org-1/saved-views/view-other", headers=headers)
    assert res.status_code == 404
    # jamais supprimée
    assert any(v["id"] == "view-other" for v in fake.postgrest.tables["db_saved_views"])


# ---------------------------------------------------------------
# Colonnes maîtres : lecture ouverte à tous, écriture réservée admin
# ---------------------------------------------------------------

def test_master_columns_read(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    res = tc.get("/orgs/org-1/master-columns", headers={"Authorization": f"Bearer {TOKEN}"})
    assert res.status_code == 200
    assert res.json()["columns"] == ["NOM", "IBAN"]


def test_master_columns_write_forbidden_for_non_admin(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    res = tc.post(
        "/orgs/org-1/master-columns",
        json={"columns": ["NOM", "IBAN", "VILLE"]},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 403


def test_master_columns_write_allowed_for_admin(client_factory):
    fake = _make_client(profiles=[{"id": "user-1", "full_name": "Alice", "is_super_admin": True}])
    tc = client_factory(fake)
    res = tc.post(
        "/orgs/org-1/master-columns",
        json={"columns": ["NOM", "IBAN", "VILLE"]},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    assert res.json()["columns"] == ["NOM", "IBAN", "VILLE"]


# ---------------------------------------------------------------
# Import CSV/Excel
# ---------------------------------------------------------------

_CSV_CONTENT = b"NOM,VILLE\nDupont,Paris\nMartin,Lyon\n"


def test_import_rejects_oversized_upload_before_reading(client_factory, monkeypatch):
    """Trouvaille Copilot, PR #28 : le plafond de taille (voir POST
    .../pipeline/sessions) ne couvrait QUE l'import du Trieur de Data --
    ce parcours-ci (Base de données > Importer) lisait encore tout le
    fichier (await file.read()) puis pd.read_excel sans limite, même
    risque d'OOM sur un gros .xlsx. Corrigé avec le même plafond
    (PIPELINE_MAX_UPLOAD_BYTES). Vérifie aussi que le rejet a lieu AVANT
    la lecture -- pas juste le code retour."""
    from api import main as api_main

    from starlette.datastructures import UploadFile

    monkeypatch.setattr(api_main, "PIPELINE_MAX_UPLOAD_BYTES", 10)

    def _boom(*args, **kwargs):
        raise AssertionError("pd.read_csv ne doit jamais être atteint après le rejet 413")

    async def _boom_read(*args, **kwargs):
        raise AssertionError(
            "UploadFile.read ne doit jamais être atteint après le rejet 413 -- "
            "sinon le fichier est chargé en mémoire malgré le plafond."
        )

    monkeypatch.setattr(api_main.pd, "read_csv", _boom)
    monkeypatch.setattr(UploadFile, "read", _boom_read)

    fake = _make_client()
    tc = client_factory(fake)
    res = tc.post(
        "/orgs/org-1/import",
        files={"file": ("clients.csv", _CSV_CONTENT, "text/csv")},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 413
    assert "volumineux" in res.json()["detail"]
    assert fake.postgrest.tables["records"] == []


def test_import_rejects_upload_with_unknown_size():
    """Même défense en profondeur que POST .../pipeline/sessions (voir
    test_pipeline_session_create_rejects_upload_with_unknown_size) : un
    .size indisponible est refusé plutôt que silencieusement compté à 0
    octet. Appel direct de l'endpoint (impossible à simuler via
    TestClient, qui calcule toujours une vraie taille pendant le parsing
    multipart)."""
    import asyncio

    from fastapi import HTTPException

    from api import main as api_main

    fake = _make_client()
    ctx = api_main.get_current_ctx(authorization=f"Bearer {TOKEN}", client=fake)
    ctx = api_main.require_org_access("org-1", ctx)

    fake_upload = SimpleNamespace(size=None, filename="clients.csv")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            api_main.import_records(
                org_id="org-1",
                file=fake_upload,
                iban_col=None,
                add_unknown_columns=False,
                dry_run=False,
                ctx=ctx,
            )
        )

    assert exc_info.value.status_code == 413
    assert "indéterminable" in exc_info.value.detail
    assert fake.postgrest.tables["records"] == []


def test_import_dry_run_previews_without_writing(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    res = tc.post(
        "/orgs/org-1/import",
        files={"file": ("clients.csv", _CSV_CONTENT, "text/csv")},
        data={"dry_run": "true"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["columns"] == ["NOM", "VILLE"]
    # VILLE n'est pas une colonne maître connue ("NOM", "IBAN" -- voir
    # _make_client) : détectée comme inconnue, sans être ajoutée.
    assert body["unknown_columns"] == ["VILLE"]
    assert body["row_count"] == 2
    assert len(body["preview_rows"]) == 2
    # Rien écrit en base : un dry_run n'est qu'un aperçu.
    assert fake.postgrest.tables["records"] == []
    assert fake.postgrest.tables["import_batches"] == []


def test_import_writes_records_without_adding_unknown_columns(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    res = tc.post(
        "/orgs/org-1/import",
        files={"file": ("clients.csv", _CSV_CONTENT, "text/csv")},
        data={"iban_col": "", "add_unknown_columns": "false"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["n_imported"] == 2
    assert body["n_alerts"] == 0
    assert body["unknown_columns"] == ["VILLE"]
    assert body["added_to_master_columns"] == []
    assert len(fake.postgrest.tables["records"]) == 2
    assert len(fake.postgrest.tables["import_batches"]) == 1


def test_import_add_unknown_columns_forbidden_for_non_admin(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    res = tc.post(
        "/orgs/org-1/import",
        files={"file": ("clients.csv", _CSV_CONTENT, "text/csv")},
        data={"add_unknown_columns": "true"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 403
    # Refusé avant tout écriture -- aucune ligne importée.
    assert fake.postgrest.tables["records"] == []


def test_import_add_unknown_columns_allowed_for_admin(client_factory):
    fake = _make_client(profiles=[{"id": "user-1", "full_name": "Alice", "is_super_admin": True}])
    tc = client_factory(fake)
    res = tc.post(
        "/orgs/org-1/import",
        files={"file": ("clients.csv", _CSV_CONTENT, "text/csv")},
        data={"add_unknown_columns": "true"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["added_to_master_columns"] == ["VILLE"]
    assert fake.postgrest.tables["organizations"][0]["master_columns"] == ["NOM", "IBAN", "VILLE"]


# ---------------------------------------------------------------
# Imports récents / annulation d'un import entier
# ---------------------------------------------------------------

def _batch(i, org_id="org-1"):
    return {
        "id": f"batch-{i}",
        "org_id": org_id,
        "source_filename": f"fichier{i}.csv",
        "imported_at": f"2026-01-{i:02d}T00:00:00Z",
        "row_count": i,
    }


def test_list_import_batches_most_recent_first(client_factory):
    fake = _make_client(import_batches=[_batch(1), _batch(2)])
    tc = client_factory(fake)

    res = tc.get("/orgs/org-1/import-batches", headers={"Authorization": f"Bearer {TOKEN}"})
    assert res.status_code == 200
    assert [b["id"] for b in res.json()["batches"]] == ["batch-2", "batch-1"]


def test_cancel_import_batch_removes_it(client_factory):
    fake = _make_client(import_batches=[_batch(1), _batch(2)])
    tc = client_factory(fake)

    res = tc.delete("/orgs/org-1/import-batches/batch-1", headers={"Authorization": f"Bearer {TOKEN}"})
    assert res.status_code == 200
    assert res.json() == {"id": "batch-1", "cancelled": True}
    remaining = {b["id"] for b in fake.postgrest.tables["import_batches"]}
    assert remaining == {"batch-2"}


def test_read_only_member_cannot_cancel_import_batch(client_factory):
    fake = _make_client(import_batches=[_batch(1)], memberships=READ_ONLY_MEMBERSHIP)
    tc = client_factory(fake)

    res = tc.delete("/orgs/org-1/import-batches/batch-1", headers={"Authorization": f"Bearer {TOKEN}"})
    assert res.status_code == 403
    assert len(fake.postgrest.tables["import_batches"]) == 1


# ---------------------------------------------------------------
# Tableau de bord
# ---------------------------------------------------------------

def test_dashboard(client_factory):
    fake = _make_client(
        records=[_record(1)],
        import_batches=[{"org_id": "org-1", "source_filename": "a.csv", "imported_at": "2026-01-01"}],
    )
    tc = client_factory(fake)
    res = tc.get("/orgs/org-1/dashboard", headers={"Authorization": f"Bearer {TOKEN}"})
    assert res.status_code == 200
    body = res.json()
    assert body["total_records"] == 1
    assert body["alerts_pending"] == 0
    assert body["last_import"]["source_filename"] == "a.csv"


# ---------------------------------------------------------------
# Suppression groupée
# ---------------------------------------------------------------

def test_bulk_delete_records(client_factory):
    records = [_record(1), _record(2), _record(3)]
    fake = _make_client(records=records)
    tc = client_factory(fake)

    res = tc.request(
        "DELETE",
        "/orgs/org-1/records",
        json={"ids": ["rec-1", "rec-2"]},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    assert res.json()["n_deleted"] == 2
    remaining_ids = {r["id"] for r in fake.postgrest.tables["records"]}
    assert remaining_ids == {"rec-3"}


def test_bulk_delete_unknown_id_is_a_noop_not_an_error(client_factory):
    """Boucle sur delete_record() (trieur/db.py), qui ne renvoie rien à
    vérifier -- un id déjà supprimé entre-temps (autre onglet, autre
    utilisateur) ne fait donc jamais échouer le reste de la sélection."""
    records = [_record(1)]
    fake = _make_client(records=records)
    tc = client_factory(fake)

    res = tc.request(
        "DELETE",
        "/orgs/org-1/records",
        json={"ids": ["rec-1", "does-not-exist"]},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    assert res.json()["n_deleted"] == 2
    assert fake.postgrest.tables["records"] == []


# ---------------------------------------------------------------
# Modification en masse d'un seul champ
# ---------------------------------------------------------------

def test_bulk_update_applies_field_to_selection(client_factory):
    records = [_record(1), _record(2), _record(3)]
    fake = _make_client(records=records)
    tc = client_factory(fake)

    res = tc.patch(
        "/orgs/org-1/records/bulk",
        json={"ids": ["rec-1", "rec-2"], "field": "VILLE", "value": "Paris"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["n_updated"] == 2
    assert body["n_requested"] == 2

    by_id = {r["id"]: r for r in fake.postgrest.tables["records"]}
    assert by_id["rec-1"]["data"]["VILLE"] == "Paris"
    assert by_id["rec-2"]["data"]["VILLE"] == "Paris"
    assert "VILLE" not in by_id["rec-3"]["data"]


def test_bulk_update_falsy_value_is_not_treated_as_empty(client_factory):
    """Piège récurrent du projet : 0/False ne doit jamais être confondu
    avec un champ vide, y compris en modification en masse."""
    records = [_record(1)]
    fake = _make_client(records=records)
    tc = client_factory(fake)

    res = tc.patch(
        "/orgs/org-1/records/bulk",
        json={"ids": ["rec-1"], "field": "ENFANTS", "value": 0},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    stored = next(r for r in fake.postgrest.tables["records"] if r["id"] == "rec-1")
    assert stored["data"]["ENFANTS"] == 0


def test_bulk_update_empty_string_clears_field(client_factory):
    records = [{**_record(1), "data": {"NOM": "Dupont", "VILLE": "Lyon"}}]
    fake = _make_client(records=records)
    tc = client_factory(fake)

    res = tc.patch(
        "/orgs/org-1/records/bulk",
        json={"ids": ["rec-1"], "field": "VILLE", "value": ""},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    stored = next(r for r in fake.postgrest.tables["records"] if r["id"] == "rec-1")
    assert stored["data"]["VILLE"] is None


def test_bulk_update_skips_missing_record(client_factory):
    records = [_record(1)]
    fake = _make_client(records=records)
    tc = client_factory(fake)

    res = tc.patch(
        "/orgs/org-1/records/bulk",
        json={"ids": ["rec-1", "does-not-exist"], "field": "VILLE", "value": "Paris"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["n_requested"] == 2
    assert body["n_updated"] == 1


# ---------------------------------------------------------------
# Alertes de doublon IBAN : liste avec diff, résolution
# ---------------------------------------------------------------

def _dedup_alert(alert_id="alert-1", org_id="org-1", status="pending"):
    return {
        "id": alert_id,
        "org_id": org_id,
        "status": status,
        "note": "IBAN déjà vu dans a.csv (2026-01-01)",
        "created_at": "2026-01-02T00:00:00Z",
        # FakeTable ne fait pas de vrai jointure SQL -- ces clés imitent
        # directement ce que list_dedup_alerts() (trieur/db.py) attend en
        # sortie du select imbriqué réel côté Supabase.
        "record": {"data": {"NOM": "Dupont", "IBAN": "FR76..."}},
        "matched": {"data": {"NOM": "Dupont Jean", "IBAN": "FR76..."}},
    }


def test_dedup_alerts_lists_pending_with_diff(client_factory):
    fake = _make_client(dedup_alerts=[_dedup_alert()])
    tc = client_factory(fake)

    res = tc.get("/orgs/org-1/dedup-alerts", headers={"Authorization": f"Bearer {TOKEN}"})
    assert res.status_code == 200
    alerts = res.json()
    assert len(alerts) == 1
    diff_by_field = {row["Champ"]: row for row in alerts[0]["diff"]}
    assert diff_by_field["NOM"]["Différent"] == "⚠️"
    assert diff_by_field["IBAN"]["Différent"] == ""


def test_dedup_alerts_excludes_already_resolved(client_factory):
    fake = _make_client(dedup_alerts=[_dedup_alert(status="confirmed_duplicate")])
    tc = client_factory(fake)

    res = tc.get("/orgs/org-1/dedup-alerts", headers={"Authorization": f"Bearer {TOKEN}"})
    assert res.json() == []


def test_resolve_dedup_alert_as_duplicate(client_factory):
    fake = _make_client(dedup_alerts=[_dedup_alert()])
    tc = client_factory(fake)

    res = tc.post(
        "/orgs/org-1/dedup-alerts/alert-1/resolve",
        json={"status": "confirmed_duplicate"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    stored = fake.postgrest.tables["dedup_alerts"][0]
    assert stored["status"] == "confirmed_duplicate"
    assert stored["resolved_by"] == "user-1"


def test_resolve_dedup_alert_invalid_status_is_400(client_factory):
    fake = _make_client(dedup_alerts=[_dedup_alert()])
    tc = client_factory(fake)

    res = tc.post(
        "/orgs/org-1/dedup-alerts/alert-1/resolve",
        json={"status": "n_importe_quoi"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 400


def test_resolve_dedup_alert_wrong_org_is_404(client_factory):
    fake = _make_client(dedup_alerts=[_dedup_alert(org_id="org-2")])
    tc = client_factory(fake)

    res = tc.post(
        "/orgs/org-1/dedup-alerts/alert-1/resolve",
        json={"status": "confirmed_duplicate"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 404


# ---------------------------------------------------------------
# Accès en lecture seule par environnement (migration 0018) : un membre
# 'lecture_seule' peut lire (déjà couvert par les tests ci-dessus, qui
# utilisent tous le rôle 'member' par défaut) mais jamais écrire.
# ---------------------------------------------------------------

READ_ONLY_MEMBERSHIP = [
    {"user_id": "user-1", "org_id": "org-1", "role": "lecture_seule", "organizations": {"slug": "leads", "name": "Leads"}}
]


def test_read_only_member_cannot_bulk_delete_records(client_factory):
    fake = _make_client(records=[_record(1)], memberships=READ_ONLY_MEMBERSHIP)
    tc = client_factory(fake)

    res = tc.request(
        "DELETE", "/orgs/org-1/records", json={"ids": ["rec-1"]},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 403
    assert len(fake.postgrest.tables["records"]) == 1


def test_read_only_member_cannot_bulk_update_records(client_factory):
    fake = _make_client(records=[_record(1)], memberships=READ_ONLY_MEMBERSHIP)
    tc = client_factory(fake)

    res = tc.patch(
        "/orgs/org-1/records/bulk",
        json={"ids": ["rec-1"], "field": "VILLE", "value": "Paris"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 403
    assert "VILLE" not in fake.postgrest.tables["records"][0]["data"]


def test_read_only_member_cannot_patch_single_record(client_factory):
    fake = _make_client(records=[_record(1)], memberships=READ_ONLY_MEMBERSHIP)
    tc = client_factory(fake)

    res = tc.patch(
        "/orgs/org-1/records/rec-1",
        json={"data": {"NOM": "Nouveau"}},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 403


def test_read_only_member_cannot_resolve_dedup_alert(client_factory):
    fake = _make_client(dedup_alerts=[_dedup_alert()], memberships=READ_ONLY_MEMBERSHIP)
    tc = client_factory(fake)

    res = tc.post(
        "/orgs/org-1/dedup-alerts/alert-1/resolve",
        json={"status": "confirmed_duplicate"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 403
    assert fake.postgrest.tables["dedup_alerts"][0]["status"] == "pending"


def test_read_only_member_cannot_import(client_factory):
    fake = _make_client(memberships=READ_ONLY_MEMBERSHIP)
    tc = client_factory(fake)

    res = tc.post(
        "/orgs/org-1/import",
        files={"file": ("clients.csv", _CSV_CONTENT, "text/csv")},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 403
    assert fake.postgrest.tables["records"] == []


def test_read_only_member_can_still_read_records(client_factory):
    """La lecture (liste, export, alertes) n'est pas concernée par
    require_write_access -- seules les écritures le sont."""
    fake = _make_client(records=[_record(1)], memberships=READ_ONLY_MEMBERSHIP)
    tc = client_factory(fake)

    res = tc.get("/orgs/org-1/records", headers={"Authorization": f"Bearer {TOKEN}"})
    assert res.status_code == 200
    assert res.json()["total"] == 1


def test_super_admin_can_write_even_without_membership_row(client_factory):
    fake = _make_client(
        profiles=[{"id": "user-1", "full_name": "Alice", "is_super_admin": True}],
        records=[_record(1)],
        memberships=[],
    )
    tc = client_factory(fake)

    res = tc.request(
        "DELETE", "/orgs/org-1/records", json={"ids": ["rec-1"]},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200


# ---------------------------------------------------------------
# Membres d'un environnement (rôles, migration 0018) -- réservé aux
# administrateurs.
# ---------------------------------------------------------------

def test_list_members_forbidden_for_non_admin(client_factory):
    fake = _make_client()
    tc = client_factory(fake)

    res = tc.get("/orgs/org-1/members", headers={"Authorization": f"Bearer {TOKEN}"})
    assert res.status_code == 403


def test_list_members_as_admin(client_factory):
    fake = _make_client(
        profiles=[ADMIN_PROFILE],
        memberships=[
            {"user_id": "user-1", "org_id": "org-1", "role": "org_admin", "created_at": "2026-01-01", "organizations": {"slug": "leads", "name": "Leads"}},
            {"user_id": "user-2", "org_id": "org-1", "role": "member", "created_at": "2026-01-02", "organizations": {"slug": "leads", "name": "Leads"}},
        ],
    )
    tc = client_factory(fake)

    res = tc.get("/orgs/org-1/members", headers={"Authorization": f"Bearer {TOKEN}"})
    assert res.status_code == 200
    assert {m["user_id"] for m in res.json()} == {"user-1", "user-2"}


def test_patch_member_role_as_admin(client_factory):
    fake = _make_client(
        profiles=[ADMIN_PROFILE],
        memberships=[
            {"user_id": "user-1", "org_id": "org-1", "role": "org_admin", "created_at": "2026-01-01", "organizations": {"slug": "leads", "name": "Leads"}},
            {"user_id": "user-2", "org_id": "org-1", "role": "member", "created_at": "2026-01-02", "organizations": {"slug": "leads", "name": "Leads"}},
        ],
    )
    tc = client_factory(fake)

    res = tc.patch(
        "/orgs/org-1/members/user-2", json={"role": "lecture_seule"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    stored = next(m for m in fake.postgrest.tables["memberships"] if m["user_id"] == "user-2")
    assert stored["role"] == "lecture_seule"


def test_patch_member_role_invalid_role_is_400(client_factory):
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)

    res = tc.patch(
        "/orgs/org-1/members/user-1", json={"role": "n_importe_quoi"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 400


def test_patch_member_role_forbidden_for_non_admin(client_factory):
    fake = _make_client()
    tc = client_factory(fake)

    res = tc.patch(
        "/orgs/org-1/members/user-1", json={"role": "lecture_seule"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 403


def test_delete_member_as_admin(client_factory):
    fake = _make_client(
        profiles=[ADMIN_PROFILE],
        memberships=[
            {"user_id": "user-1", "org_id": "org-1", "role": "org_admin", "created_at": "2026-01-01", "organizations": {"slug": "leads", "name": "Leads"}},
            {"user_id": "user-2", "org_id": "org-1", "role": "member", "created_at": "2026-01-02", "organizations": {"slug": "leads", "name": "Leads"}},
        ],
    )
    tc = client_factory(fake)

    res = tc.delete("/orgs/org-1/members/user-2", headers={"Authorization": f"Bearer {TOKEN}"})
    assert res.status_code == 200
    remaining = {m["user_id"] for m in fake.postgrest.tables["memberships"]}
    assert remaining == {"user-1"}


# ---------------------------------------------------------------
# Export CSV/Excel
# ---------------------------------------------------------------

def test_export_csv_streams_all_records(client_factory):
    records = [
        {**_record(1), "data": {"NOM": "Dupont", "IBAN": "FR76..."}},
        {**_record(2), "data": {"NOM": "Martin", "IBAN": "FR77..."}},
    ]
    fake = _make_client(records=records)
    tc = client_factory(fake)

    res = tc.get(
        "/orgs/org-1/records/export",
        params={"format": "csv"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert "Leads.csv" in res.headers["content-disposition"]
    body = res.content.decode("utf-8-sig")
    assert "Dupont" in body
    assert "Martin" in body


def test_export_respects_search(client_factory):
    records = [
        {**_record(1), "data": {"NOM": "Dupont", "IBAN": "FR76..."}},
        {**_record(2), "data": {"NOM": "Martin", "IBAN": "FR77..."}},
    ]
    fake = _make_client(records=records)
    tc = client_factory(fake)

    res = tc.get(
        "/orgs/org-1/records/export",
        params={"format": "csv", "search": "dupont"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    body = res.content.decode("utf-8-sig")
    assert "Dupont" in body
    assert "Martin" not in body


def test_export_hides_explicitly_unchecked_column_but_keeps_unknown_ones(client_factory):
    """Une colonne CONNUE côté écran (`known_cols`) mais retirée de
    `visible_cols` reste hors export ; une colonne HORS de `known_cols`
    (jamais vue à l'écran, ex. lot pas encore chargé) est incluse quand
    même -- même règle que views/tab_database.py:_render_export."""
    records = [{**_record(1), "data": {"NOM": "Dupont", "IBAN": "FR76...", "VILLE": "Paris"}}]
    fake = _make_client(records=records)
    tc = client_factory(fake)

    res = tc.get(
        "/orgs/org-1/records/export",
        params={"format": "csv", "known_cols": "NOM,IBAN", "visible_cols": "NOM"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    body = res.content.decode("utf-8-sig")
    header = body.splitlines()[0]
    assert "NOM" in header
    assert "IBAN" not in header  # connue, décochée -> masquée
    assert "VILLE" in header  # jamais vue à l'écran -> incluse quand même


def test_export_xlsx_returns_spreadsheet_content_type(client_factory):
    records = [{**_record(1), "data": {"NOM": "Dupont"}}]
    fake = _make_client(records=records)
    tc = client_factory(fake)

    res = tc.get(
        "/orgs/org-1/records/export",
        params={"format": "xlsx"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    assert res.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert len(res.content) > 0


# ---------------------------------------------------------------
# Cockpit -- chantiers de développement (réservé aux administrateurs)
# ---------------------------------------------------------------

ADMIN_PROFILE = {"id": "user-1", "full_name": "Alice", "is_super_admin": True}


def test_cockpit_forbidden_for_non_admin(client_factory):
    fake = _make_client()  # profil par défaut : is_super_admin=False
    tc = client_factory(fake)
    res = tc.get("/orgs/org-1/chantiers", headers={"Authorization": f"Bearer {TOKEN}"})
    assert res.status_code == 403


def test_cockpit_forbidden_for_member_without_org_access(client_factory):
    """Un compte non-admin, même membre d'un AUTRE environnement, ne
    peut pas voir les chantiers de org-1 -- require_org_access s'applique
    avant require_cockpit_access."""
    fake = _make_client(memberships=[])
    tc = client_factory(fake)
    res = tc.get("/orgs/org-1/chantiers", headers={"Authorization": f"Bearer {TOKEN}"})
    assert res.status_code == 403


def test_create_and_list_chantiers(client_factory):
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}

    res = tc.post(
        "/orgs/org-1/chantiers",
        json={"title": "Migrer vers React", "priority": "haute", "theme": "Frontend"},
        headers=headers,
    )
    assert res.status_code == 200
    created = res.json()
    assert created["title"] == "Migrer vers React"
    assert created["priority"] == "haute"
    assert created["theme"] == "Frontend"

    res = tc.get("/orgs/org-1/chantiers", headers=headers)
    assert res.status_code == 200
    assert [c["title"] for c in res.json()] == ["Migrer vers React"]


def test_create_chantier_requires_title(client_factory):
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    res = tc.post(
        "/orgs/org-1/chantiers",
        json={"title": "   "},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 400


def test_create_chantier_rejects_invalid_priority(client_factory):
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    res = tc.post(
        "/orgs/org-1/chantiers",
        json={"title": "X", "priority": "urgentissime"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 400


def test_create_chantier_without_theme_infers_and_creates_section(client_factory):
    """Raphaël (2026-09-21) : plus de section à choisir à la main -- le
    serveur doit deviner un thème d'après le titre ET créer la section
    correspondante, sinon le chantier retomberait dans "À classer" côté
    CockpitScreen malgré tout."""
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}

    res = tc.post(
        "/orgs/org-1/chantiers",
        json={"title": "Export XML SEPA (pain.008)"},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["theme"] == "Export"

    res = tc.get("/orgs/org-1/sections", headers=headers)
    assert [s["nom"] for s in res.json()] == ["Export"]


def test_create_chantier_without_theme_reuses_existing_section(client_factory):
    """Une section déjà créée par Raphaël (ex. le nom de son activité)
    passe avant nos familles de mots-clés génériques."""
    fake = _make_client(
        profiles=[ADMIN_PROFILE],
        sections=[{"id": "s-1", "org_id": "org-1", "nom": "Prélèvement", "position": 0}],
    )
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}

    res = tc.post(
        "/orgs/org-1/chantiers",
        json={"title": "Export XML SEPA pour le Prélèvement"},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["theme"] == "Prélèvement"

    res = tc.get("/orgs/org-1/sections", headers=headers)
    assert [s["nom"] for s in res.json()] == ["Prélèvement"]


def test_create_chantier_without_theme_falls_back_to_general(client_factory):
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}

    res = tc.post(
        "/orgs/org-1/chantiers",
        json={"title": "Truc vague sans mot-clé connu"},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["theme"] == "Général"


def test_prelevement_rules_defaults_when_never_saved(client_factory):
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    res = tc.get("/orgs/org-1/prelevement/rules", headers={"Authorization": f"Bearer {TOKEN}"})
    assert res.status_code == 200
    body = res.json()
    assert body["org_id"] == "org-1"
    assert body["ics"] is None
    assert body["nature"] == "CORE"
    assert body["delay_days"] == 3
    assert body["frais_setup_eur"] == 20.0
    assert len(body["explication"]) > 0


def test_prelevement_rules_roundtrip(client_factory):
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}

    res = tc.post(
        "/orgs/org-1/prelevement/rules",
        json={"ics": "FR12ZZZ123456", "nature": "CORE", "delay_days": 5, "frais_setup_eur": 15.0},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["ics"] == "FR12ZZZ123456"
    assert res.json()["delay_days"] == 5
    assert res.json()["frais_setup_eur"] == 15.0

    res = tc.get("/orgs/org-1/prelevement/rules", headers=headers)
    assert res.json()["ics"] == "FR12ZZZ123456"


def test_prelevement_rules_explication_reflects_current_settings(client_factory):
    """"Règles appliquées" demandé par Raphaël (2026-09-22) : doit
    refléter les réglages réellement enregistrés (frais, délai), jamais
    un texte figé indépendant."""
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    res = tc.post(
        "/orgs/org-1/prelevement/rules",
        json={"ics": None, "nature": "CORE", "delay_days": 7, "frais_setup_eur": 12.5},
        headers=headers,
    )
    assert res.status_code == 200
    explication_text = " ".join(r["detail"] for r in res.json()["explication"])
    assert "12.5" in explication_text or "12,5" in explication_text
    assert "7 jour" in explication_text


def test_prelevement_rules_rejects_invalid_nature(client_factory):
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    res = tc.post(
        "/orgs/org-1/prelevement/rules",
        json={"nature": "AUTRE"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 400


def test_prelevement_rules_rejects_negative_frais_setup(client_factory):
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    res = tc.post(
        "/orgs/org-1/prelevement/rules",
        json={"frais_setup_eur": -5.0},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 400


def test_prelevement_rules_forbidden_for_non_admin(client_factory):
    fake = _make_client()  # profil par défaut : is_super_admin=False
    tc = client_factory(fake)
    res = tc.get("/orgs/org-1/prelevement/rules", headers={"Authorization": f"Bearer {TOKEN}"})
    assert res.status_code == 403


def test_prelevement_rules_prefills_frais_par_produit_and_periodicites(client_factory):
    """Frais par produit et libellés de périodicité (Raphaël, 2026-09-22) :
    tant que rien n'a été personnalisé, l'écran doit montrer ce qui
    s'applique RÉELLEMENT (frais_setup_eur pour chaque produit connu,
    libellés par défaut du moteur) -- jamais un écran vide."""
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    res = tc.get("/orgs/org-1/prelevement/rules", headers={"Authorization": f"Bearer {TOKEN}"})
    assert res.status_code == 200
    body = res.json()
    assert set(body["produits_connus"]) == set(body["frais_par_produit"].keys())
    assert all(v == 20.0 for v in body["frais_par_produit"].values())
    assert body["periodicites"]["mensuelle"] == "Tous les 1 mois"


def test_prelevement_rules_roundtrip_frais_par_produit_and_periodicites(client_factory):
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    res = tc.post(
        "/orgs/org-1/prelevement/rules",
        json={
            "frais_par_produit": {"Optilife": 30.0, "Carte MGS": 25.0},
            "periodicites": {"mensuelle": "Chaque mois"},
        },
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["frais_par_produit"] == {"Optilife": 30.0, "Carte MGS": 25.0}
    assert res.json()["periodicites"] == {"mensuelle": "Chaque mois"}

    res = tc.get("/orgs/org-1/prelevement/rules", headers=headers)
    body = res.json()
    assert body["frais_par_produit"]["Optilife"] == 30.0
    # Produit non personnalisé : absent du dict enregistré -- pas de
    # pré-remplissage une fois qu'au moins un réglage existe (le dict
    # enregistré en base fait foi tel quel, jamais complété en silence).
    assert "IMMO" not in body["frais_par_produit"]
    assert body["periodicites"] == {"mensuelle": "Chaque mois"}


def test_prelevement_rules_rejects_unknown_produit(client_factory):
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    res = tc.post(
        "/orgs/org-1/prelevement/rules",
        json={"frais_par_produit": {"Produit inventé": 10.0}},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 400


def test_prelevement_rules_rejects_negative_frais_par_produit(client_factory):
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    res = tc.post(
        "/orgs/org-1/prelevement/rules",
        json={"frais_par_produit": {"Optilife": -1.0}},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 400


def test_prelevement_rules_rejects_empty_periodicite_explication(client_factory):
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    res = tc.post(
        "/orgs/org-1/prelevement/rules",
        json={"periodicites": {"mensuelle": "   "}},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 400


def test_prelevement_rules_defaults_colonnes_mandat_to_full_canonical_order(client_factory):
    """"ORDRE DES COLONNES + MODIFICATIONS" (père de Raphaël, 2026-09-22) :
    tant que rien n'a été personnalisé, toutes les colonnes canoniques,
    dans l'ordre, toutes visibles -- jamais un écran vide."""
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    res = tc.get("/orgs/org-1/prelevement/rules", headers={"Authorization": f"Bearer {TOKEN}"})
    assert res.status_code == 200
    colonnes = res.json()["colonnes_mandat"]
    assert [c["cle"] for c in colonnes] == MANDAT_COLONNES_CANONIQUES
    assert all(c["visible"] for c in colonnes)


def test_prelevement_rules_colonnes_mandat_notes_cover_every_canonical_column(client_factory):
    """"je sais à quelle colonne s'attribue ces règles" (Raphaël,
    2026-09-22) -- une note pour CHAQUE colonne canonique, jamais une
    colonne sans explication affichable sur l'aperçu."""
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    res = tc.get("/orgs/org-1/prelevement/rules", headers={"Authorization": f"Bearer {TOKEN}"})
    notes = res.json()["colonnes_mandat_notes"]
    assert set(notes.keys()) == set(MANDAT_COLONNES_CANONIQUES)
    assert all(v.strip() for v in notes.values())


def test_prelevement_rules_roundtrip_colonnes_mandat(client_factory):
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    # Réordonné (RUM en premier) + Prenom masqué.
    reordered = [{"cle": "RUM", "visible": True}] + [
        {"cle": c, "visible": c != "Prenom"} for c in MANDAT_COLONNES_CANONIQUES if c != "RUM"
    ]
    res = tc.post(
        "/orgs/org-1/prelevement/rules",
        json={"colonnes_mandat": reordered},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["colonnes_mandat"][0] == {"cle": "RUM", "visible": True, "rule_request_id": None}
    prenom_entry = next(c for c in res.json()["colonnes_mandat"] if c["cle"] == "Prenom")
    assert prenom_entry["visible"] is False

    res = tc.get("/orgs/org-1/prelevement/rules", headers=headers)
    assert res.json()["colonnes_mandat"][0] == {"cle": "RUM", "visible": True, "rule_request_id": None}


def test_prelevement_rules_rejects_incomplete_colonnes_mandat(client_factory):
    """Jamais un sous-ensemble partiel -- ça perdrait silencieusement une
    colonne que l'utilisateur n'a pas explicitement décochée."""
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    res = tc.post(
        "/orgs/org-1/prelevement/rules",
        json={"colonnes_mandat": [{"cle": "Nom", "visible": True}]},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 400


def test_prelevement_rules_accepts_custom_column_in_addition_to_canonical(client_factory):
    """"➕ ajouter une colonne" (Raphaël, 2026-09-22) : une colonne
    personnalisée peut s'ajouter EN PLUS des 28 canoniques -- toujours
    acceptée tant que les canoniques restent toutes présentes."""
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with_custom = [{"cle": c, "visible": True} for c in MANDAT_COLONNES_CANONIQUES] + [
        {"cle": "Ma colonne perso", "visible": True}
    ]
    res = tc.post("/orgs/org-1/prelevement/rules", json={"colonnes_mandat": with_custom}, headers=headers)
    assert res.status_code == 200
    cles = [c["cle"] for c in res.json()["colonnes_mandat"]]
    assert "Ma colonne perso" in cles


def test_prelevement_rules_rejects_duplicate_or_empty_column_name(client_factory):
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    base = [{"cle": c, "visible": True} for c in MANDAT_COLONNES_CANONIQUES]
    res = tc.post(
        "/orgs/org-1/prelevement/rules",
        json={"colonnes_mandat": base + [{"cle": "Nom", "visible": True}]},
        headers=headers,
    )
    assert res.status_code == 400
    res = tc.post(
        "/orgs/org-1/prelevement/rules",
        json={"colonnes_mandat": base + [{"cle": "  ", "visible": True}]},
        headers=headers,
    )
    assert res.status_code == 400


def test_prelevement_generate_shows_custom_column_empty(client_factory):
    """Bout en bout : une colonne personnalisée apparaît dans l'aperçu de
    génération, toujours vide (aucune source dans le CRM)."""
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with_custom = [{"cle": c, "visible": True} for c in MANDAT_COLONNES_CANONIQUES] + [
        {"cle": "Ma colonne perso", "visible": True}
    ]
    res = tc.post("/orgs/org-1/prelevement/rules", json={"colonnes_mandat": with_custom}, headers=headers)
    assert res.status_code == 200

    res = tc.post(
        "/orgs/org-1/prelevement/generate",
        files=[("files", ("export.csv", _PRELEVEMENT_CSV, "text/csv"))],
        headers=headers,
    )
    assert res.status_code == 200
    mandat = res.json()["mandats"][0]
    assert mandat["Ma colonne perso"] in ("", None)


def test_prelevement_colonnes_mandat_preset_create_list_and_delete(client_factory):
    """Jeux de colonnes réutilisables (Raphaël, 2026-09-22 : "comme on
    avait sur Streamlit") -- enregistrer un instantané nommé, le
    retrouver, le supprimer."""
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    colonnes = [{"cle": "RUM", "visible": True}, {"cle": "Nom", "visible": False}]

    res = tc.post(
        "/orgs/org-1/prelevement/colonnes-mandat-presets",
        json={"name": "Export banque", "colonnes": colonnes},
        headers=headers,
    )
    assert res.status_code == 200
    preset = res.json()
    assert preset["name"] == "Export banque"
    assert preset["colonnes"] == [
        {"cle": "RUM", "visible": True, "rule_request_id": None},
        {"cle": "Nom", "visible": False, "rule_request_id": None},
    ]
    assert preset["org_id"] == "org-1"

    res = tc.get("/orgs/org-1/prelevement/colonnes-mandat-presets", headers=headers)
    assert res.status_code == 200
    assert [p["name"] for p in res.json()] == ["Export banque"]

    res = tc.delete(f"/orgs/org-1/prelevement/colonnes-mandat-presets/{preset['id']}", headers=headers)
    assert res.status_code == 200
    res = tc.get("/orgs/org-1/prelevement/colonnes-mandat-presets", headers=headers)
    assert res.json() == []


def test_prelevement_colonnes_mandat_preset_save_same_name_replaces(client_factory):
    """Enregistrer sous un nom déjà pris REMPLACE le jeu existant --
    jamais un doublon visuellement identique."""
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    tc.post(
        "/orgs/org-1/prelevement/colonnes-mandat-presets",
        json={"name": "Export banque", "colonnes": [{"cle": "RUM", "visible": True}]},
        headers=headers,
    )
    res = tc.post(
        "/orgs/org-1/prelevement/colonnes-mandat-presets",
        json={"name": "export banque", "colonnes": [{"cle": "Nom", "visible": False}]},
        headers=headers,
    )
    assert res.status_code == 200
    res = tc.get("/orgs/org-1/prelevement/colonnes-mandat-presets", headers=headers)
    presets = res.json()
    assert len(presets) == 1
    assert presets[0]["colonnes"] == [{"cle": "Nom", "visible": False, "rule_request_id": None}]


def test_prelevement_colonnes_mandat_preset_rejects_empty(client_factory):
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    res = tc.post(
        "/orgs/org-1/prelevement/colonnes-mandat-presets",
        json={"name": "  ", "colonnes": [{"cle": "RUM", "visible": True}]},
        headers=headers,
    )
    assert res.status_code == 400
    res = tc.post(
        "/orgs/org-1/prelevement/colonnes-mandat-presets",
        json={"name": "X", "colonnes": []},
        headers=headers,
    )
    assert res.status_code == 400


def test_prelevement_colonnes_mandat_preset_forbidden_for_non_admin(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    res = tc.post(
        "/orgs/org-1/prelevement/colonnes-mandat-presets",
        json={"name": "X", "colonnes": [{"cle": "RUM", "visible": True}]},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 403


def test_prelevement_colonnes_mandat_preset_patch_renames(client_factory):
    """"✏️ Modifier" (Modèles tableau, Raphaël 2026-09-22) : renommer un
    jeu existant, sans toucher ses colonnes."""
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    preset = tc.post(
        "/orgs/org-1/prelevement/colonnes-mandat-presets",
        json={"name": "Brouillon", "colonnes": [{"cle": "RUM", "visible": True}]},
        headers=headers,
    ).json()
    res = tc.patch(
        f"/orgs/org-1/prelevement/colonnes-mandat-presets/{preset['id']}",
        json={"name": "Export banque"},
        headers=headers,
    )
    assert res.status_code == 200
    updated = res.json()
    assert updated["name"] == "Export banque"
    assert updated["colonnes"] == [{"cle": "RUM", "visible": True, "rule_request_id": None}]


def test_prelevement_colonnes_mandat_preset_patch_updates_colonnes(client_factory):
    """"💾 Enregistrer" du panneau "Modèles tableau" : met à jour les
    colonnes du jeu sélectionné, nom inchangé."""
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    preset = tc.post(
        "/orgs/org-1/prelevement/colonnes-mandat-presets",
        json={"name": "Export banque", "colonnes": [{"cle": "RUM", "visible": True}]},
        headers=headers,
    ).json()
    res = tc.patch(
        f"/orgs/org-1/prelevement/colonnes-mandat-presets/{preset['id']}",
        json={"colonnes": [{"cle": "Nom", "visible": False}]},
        headers=headers,
    )
    assert res.status_code == 200
    updated = res.json()
    assert updated["name"] == "Export banque"
    assert updated["colonnes"] == [{"cle": "Nom", "visible": False, "rule_request_id": None}]


def test_prelevement_colonnes_mandat_preset_patch_not_found(client_factory):
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    res = tc.patch(
        "/orgs/org-1/prelevement/colonnes-mandat-presets/does-not-exist",
        json={"name": "X"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 404


def test_prelevement_colonnes_mandat_column_carries_rule_request_id(client_factory):
    """Attribution d'une règle à une colonne personnalisée (Modèles
    tableau, Raphaël 2026-09-22) -- simple référence, transportée telle
    quelle par colonnes_mandat et les jeux de colonnes."""
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with_custom = [{"cle": c, "visible": True} for c in MANDAT_COLONNES_CANONIQUES] + [
        {"cle": "Code société", "visible": True, "rule_request_id": "req-123"}
    ]
    res = tc.post("/orgs/org-1/prelevement/rules", json={"colonnes_mandat": with_custom}, headers=headers)
    assert res.status_code == 200
    custom = next(c for c in res.json()["colonnes_mandat"] if c["cle"] == "Code société")
    assert custom["rule_request_id"] == "req-123"


def test_prelevement_generate_respects_colonnes_mandat_order_and_visibility(client_factory):
    """Bout en bout : l'ordre/visibilité personnalisés s'appliquent
    réellement à l'aperçu de génération, pas seulement à l'affichage des
    réglages."""
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    reordered = [{"cle": "RUM", "visible": True}, {"cle": "Nom", "visible": True}] + [
        {"cle": c, "visible": c != "IBAN"}
        for c in MANDAT_COLONNES_CANONIQUES
        if c not in ("RUM", "Nom")
    ]
    res = tc.post("/orgs/org-1/prelevement/rules", json={"colonnes_mandat": reordered}, headers=headers)
    assert res.status_code == 200

    res = tc.post(
        "/orgs/org-1/prelevement/generate",
        files=[("files", ("export.csv", _PRELEVEMENT_CSV, "text/csv"))],
        headers=headers,
    )
    assert res.status_code == 200
    mandat = res.json()["mandats"][0]
    assert list(mandat.keys())[:2] == ["RUM", "Nom"]
    assert "IBAN" not in mandat


def test_prelevement_generate_uses_frais_par_produit(client_factory):
    """Bout en bout : les frais par produit enregistrés s'appliquent
    réellement à la génération, pas seulement à l'affichage."""
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    res = tc.post(
        "/orgs/org-1/prelevement/rules",
        json={"frais_par_produit": {"Optilife": 30.0}},
        headers=headers,
    )
    assert res.status_code == 200

    res = tc.post(
        "/orgs/org-1/prelevement/generate",
        files=[("files", ("export.csv", _PRELEVEMENT_CSV, "text/csv"))],
        headers=headers,
    )
    assert res.status_code == 200
    mandats = res.json()["mandats"]
    assert len(mandats) == 2  # FRST + RCUR, générés systématiquement
    frst = next(m for m in mandats if m["Type_prelevement"] == "FRST")
    assert frst["Montant_EUR"] == 129.0  # 99 (Optilife) + 30 (override)


_PRELEVEMENT_CSV = (
    "Référence du client,Nom complet,RUM,Statut,Type de prélèvement,"
    "Périodicité (Mensuel/trimestre/annuel),IBAN,BIC,Date de premier prélèvement,"
    "Adresse,Ville,Code postal,Email,Téléphone,"
    "Optilife,Optivie,Carte MGS,MYJURIS & MYHOSPI,Admin & Aide a dom,Auditif,IMMO,"
    "Total cotisation MYMO VETO SUR,Total frais de dossier,Total cotisation et frais de dossier\n"
    "MGS-1,CLIENT UN,RUM1,Sepa validé par le client,Prélèvement,Mensuelle,"
    "FR7615589228070085438594040,CMBRFR2B,24/09/2026,1 rue Test,Paris,75001,a@example.com,+33600000000,"
    "99,0,0,0,0,0,0,0,40,139\n"
    "MGS-2,CLIENT DEUX,RUM2,Sepa validé par le client,Prélèvement,Mensuelle,"
    "IBAN-INVALIDE,CMBRFR2B,24/09/2026,2 rue Test,Paris,75001,b@example.com,+33600000001,"
    "0,0,0,0,0,0,0,0,0,0\n"
).encode("utf-8")


def test_prelevement_generate_returns_ooff_rcur_and_exclus(client_factory):
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    res = tc.post(
        "/orgs/org-1/prelevement/generate",
        files=[("files", ("export.csv", _PRELEVEMENT_CSV, "text/csv"))],
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["counts"]["ooff"] == 1
    assert body["counts"]["rcur"] == 1  # générée systématiquement en plus de FRST
    assert body["counts"]["exclus"] == 1


def test_prelevement_generate_returns_mandat_rows_and_file_for_preview(client_factory):
    """Aperçu avant téléchargement demandé par Raphaël (2026-09-22) : le
    endpoint renvoie du JSON (lignes de l'onglet "Mandat" + classeur
    encodé en base64), plus de téléchargement automatique côté serveur.
    Structure du classeur inchangée : Mandat, FRST, RCUR, Exclus --
    jamais "OOFF" (renommé), jamais de colonne "Nature" (réglage global,
    pas une donnée par ligne). Chaque mandat génère systématiquement une
    ligne FRST et une ligne RCUR (2026-09-22)."""
    import base64

    import openpyxl

    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    res = tc.post(
        "/orgs/org-1/prelevement/generate",
        files=[("files", ("export.csv", _PRELEVEMENT_CSV, "text/csv"))],
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert len(body["mandats"]) == 2  # FRST + RCUR
    assert body["mandats"][0]["RUM"] == "RUM1"
    assert "Nature" not in body["mandats"][0]
    assert "Date d'effet" in body["mandats"][0]

    wb = openpyxl.load_workbook(io.BytesIO(base64.b64decode(body["file_base64"])))
    assert wb.sheetnames == ["Mandat", "FRST", "RCUR", "Exclus"]


def test_prelevement_generate_mandat_columns_match_requested_order(client_factory):
    """Ordre et noms de colonnes demandés par le père de Raphaël
    (2026-09-22, "ordre des colonnes du fichiers de mandats") --
    Motif/Référence client/Date d'effet gardés en plus à la fin (hors
    de sa liste, jamais supprimés sans confirmation explicite), Prenom
    vide (pas de source dans le CRM), ICS_Crediteur toujours vide."""
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    res = tc.post(
        "/orgs/org-1/prelevement/generate",
        files=[("files", ("export.csv", _PRELEVEMENT_CSV, "text/csv"))],
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    mandats = res.json()["mandats"]
    assert list(mandats[0].keys()) == [
        "Nom", "Prenom", "Email", "Telephone", "Adresse", "Ville", "Code_postal", "Pays",
        "IBAN", "BIC", "ICS_Crediteur", "RUM", "Type_prelevement", "Montant_EUR", "Devise",
        "Date_signature_mandat", "Date_premiere_echeance", "Periodicite", "Explication_periodicite",
        "Frequence_mois", "Jour_prelevement", "Prochaine_echeance", "Date_fin", "Statut",
        "Reference_facture", "Libelle", "Référence client", "Motif", "Date d'effet",
    ]
    frst = next(m for m in mandats if m["Type_prelevement"] == "FRST")
    assert frst["Prenom"] == ""
    assert frst["ICS_Crediteur"] == ""
    assert frst["Date_fin"] == "" and frst["Statut"] == ""
    # "La règle du MOTIF devient -> Référence Facture" (2026-09-22) --
    # même valeur que Motif, jamais vide alors que Motif la contient.
    assert frst["Reference_facture"] == frst["Motif"] != ""
    assert frst["Frequence_mois"] == 1  # "Mensuelle"
    # Jour_prelevement = jour du mois de Date_premiere_echeance (calculée
    # à partir d'aujourd'hui + délai, jamais une date fixe -- ne pas
    # figer "24" en dur ici).
    jour_attendu = int(frst["Date_premiere_echeance"].split("/")[0])
    assert frst["Jour_prelevement"] == jour_attendu
    import datetime
    assert frst["Libelle"] == f"intégré le {datetime.date.today().strftime('%d/%m/%Y')}"


def test_prelevement_generate_reachable_cross_origin(client_factory):
    """Le résultat (compteurs, aperçu, fichier) est maintenant dans le
    corps JSON, pas dans des en-têtes personnalisés -- plus besoin
    d'Access-Control-Expose-Headers pour que le frontend y accède (bug
    réel évité par PR #45 avec X-Ooff-Count, devenu sans objet ici).
    TestClient n'applique le middleware CORS que si un en-tête Origin est
    présent -- il faut donc le simuler explicitement ici."""
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    res = tc.post(
        "/orgs/org-1/prelevement/generate",
        files=[("files", ("export.csv", _PRELEVEMENT_CSV, "text/csv"))],
        headers={"Authorization": f"Bearer {TOKEN}", "Origin": "https://trieur-data-app-test.onrender.com"},
    )
    assert res.status_code == 200
    assert res.headers["access-control-allow-origin"] == "https://trieur-data-app-test.onrender.com"


def test_prelevement_generate_forbidden_for_non_admin(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    res = tc.post(
        "/orgs/org-1/prelevement/generate",
        files=[("files", ("export.csv", _PRELEVEMENT_CSV, "text/csv"))],
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 403


def test_prelevement_generate_merges_multiple_files(client_factory):
    """Plusieurs fichiers = fusionnés en un seul lot avant traitement --
    demandé par Raphaël pour pouvoir importer plusieurs exports CRM
    d'un coup (ex. un par mois)."""
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    res = tc.post(
        "/orgs/org-1/prelevement/generate",
        files=[
            ("files", ("export1.csv", _PRELEVEMENT_CSV, "text/csv")),
            ("files", ("export2.csv", _PRELEVEMENT_CSV, "text/csv")),
        ],
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    # Chaque fichier a 1 ligne valide (MGS-1) + 1 exclue (MGS-2) -- les
    # deux fichiers réunis donnent donc le double de chaque.
    body = res.json()
    assert body["counts"]["ooff"] == 2
    assert body["counts"]["exclus"] == 2


def test_prelevement_generate_summary_describes_processing(client_factory):
    """Résumé demandé par Raphaël (2026-09-21) : voir ce qui a été fait
    sur le fichier (lignes lues, exclusions, mandats), pas seulement
    les compteurs finaux. Structuré (2026-09-22) pour un affichage en
    tableau lisible plutôt qu'un bloc de phrases denses."""
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    res = tc.post(
        "/orgs/org-1/prelevement/generate",
        files=[("files", ("export.csv", _PRELEVEMENT_CSV, "text/csv"))],
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    summary = res.json()["summary"]
    assert summary["n_fichiers"] == 1
    assert summary["n_lignes"] == 2
    assert summary["n_exclus"] == 1
    assert len(summary["exclusions"]) == 1
    assert summary["exclusions"][0]["n"] == 1
    assert summary["n_mandats"] == 2  # FRST + RCUR
    assert summary["n_first"] == 1
    assert summary["n_rcur"] == 1


_PRELEVEMENT_CSV_NO_PHONE = (
    "Référence du client,Nom complet,RUM,Statut,Type de prélèvement,"
    "Périodicité (Mensuel/trimestre/annuel),IBAN,BIC,Date de premier prélèvement,"
    "Adresse,Ville,Code postal,Email,Téléphone,"
    "Optilife,Optivie,Carte MGS,MYJURIS & MYHOSPI,Admin & Aide a dom,Auditif,IMMO,"
    "Total cotisation MYMO VETO SUR,Total frais de dossier,Total cotisation et frais de dossier\n"
    "MGS-1,CLIENT SANS TEL,RUM1,Sepa validé par le client,Prélèvement,Mensuelle,"
    "FR7615589228070085438594040,CMBRFR2B,24/09/2026,1 rue Test,Paris,75001,a@example.com,,"
    "99,0,0,0,0,0,0,0,40,139\n"
).encode("utf-8")


def test_prelevement_generate_reports_missing_phone_without_blocking(client_factory):
    """Décision de Raphaël (2026-09-22) : un mandat sans AUCUN numéro (ni
    Téléphone ni Mobile trouvés sur la ligne CRM) n'est jamais exclu --
    contrairement à un IBAN invalide -- mais signalé immédiatement dans
    le résumé, sans avoir à ouvrir le fichier téléchargé."""
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    res = tc.post(
        "/orgs/org-1/prelevement/generate",
        files=[("files", ("export.csv", _PRELEVEMENT_CSV_NO_PHONE, "text/csv"))],
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["counts"]["ooff"] == 1  # le mandat part quand même
    # 2 lignes sans téléphone : FRST + RCUR générées systématiquement
    # pour ce mandat, depuis le 2026-09-22.
    assert body["counts"]["sans_telephone"] == 2
    assert len(body["telephones_manquants"]) == 2
    assert body["telephones_manquants"][0]["reference_client"] == "MGS-1"
    assert body["summary"]["n_sans_telephone"] == 2


def test_prelevement_mandats_saved_to_database(client_factory):
    """Bouton "Enregistré dans la base de données" demandé par Raphaël
    (2026-09-22), en anticipation de la future vue de consultation :
    doit vraiment persister les mandats, pas un accusé de réception
    vide. Un seul batch_id pour toutes les lignes d'un même appel."""
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    gen_res = tc.post(
        "/orgs/org-1/prelevement/generate",
        files=[("files", ("export.csv", _PRELEVEMENT_CSV, "text/csv"))],
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    mandats = gen_res.json()["mandats"]
    assert len(mandats) == 2  # FRST + RCUR, générés systématiquement

    res = tc.post(
        "/orgs/org-1/prelevement/mandats",
        json={"mandats": mandats},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["n_saved"] == 2
    assert body["batch_id"]

    stored = fake.postgrest.tables["prelevement_mandats"]
    assert len(stored) == 2
    assert stored[0]["org_id"] == "org-1"
    assert stored[0]["rum"] == "RUM1"
    assert stored[0]["montant_eur"] == mandats[0]["Montant_EUR"]
    assert stored[0]["batch_id"] == body["batch_id"]
    assert stored[0]["created_by"] == "user-1"


def test_prelevement_mandats_rejects_empty_payload(client_factory):
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    res = tc.post(
        "/orgs/org-1/prelevement/mandats",
        json={"mandats": []},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 400


def test_prelevement_mandats_forbidden_for_non_admin(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    res = tc.post(
        "/orgs/org-1/prelevement/mandats",
        json={"mandats": [{"RUM": "RUM1"}]},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 403


def _save_one_mandat(tc) -> str:
    """Génère et enregistre un seul mandat (la ligne FRST -- generate
    en renvoie toujours deux, FRST + RCUR, depuis le 2026-09-22), renvoie
    son id -- fixture partagée par les tests de la vue de consultation
    ci-dessous."""
    gen_res = tc.post(
        "/orgs/org-1/prelevement/generate",
        files=[("files", ("export.csv", _PRELEVEMENT_CSV, "text/csv"))],
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    mandats = [m for m in gen_res.json()["mandats"] if m["Type_prelevement"] == "FRST"]
    save_res = tc.post(
        "/orgs/org-1/prelevement/mandats",
        json={"mandats": mandats},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert save_res.status_code == 200
    return save_res.json()


def test_list_prelevement_mandats(client_factory):
    """Vue de consultation (Raphaël, 2026-09-22) : la liste renvoie bien
    les mandats déjà enregistrés, avec les colonnes affichables."""
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    _save_one_mandat(tc)

    res = tc.get("/orgs/org-1/prelevement/mandats", headers={"Authorization": f"Bearer {TOKEN}"})
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert len(body["rows"]) == 1
    assert body["rows"][0]["RUM"] == "RUM1"
    assert "_id" in body["rows"][0]
    assert "RUM" in body["columns"]
    assert "Enregistré le" in body["columns"]


def test_list_prelevement_mandats_search_filters_loaded_page(client_factory):
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    _save_one_mandat(tc)

    res = tc.get(
        "/orgs/org-1/prelevement/mandats",
        params={"search": "aucune-correspondance"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    assert res.json()["rows"] == []

    res = tc.get(
        "/orgs/org-1/prelevement/mandats",
        params={"search": "RUM1"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    assert len(res.json()["rows"]) == 1


def test_patch_prelevement_mandat(client_factory):
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    saved = _save_one_mandat(tc)
    mandat_id = fake.postgrest.tables["prelevement_mandats"][0]["id"]

    res = tc.patch(
        f"/orgs/org-1/prelevement/mandats/{mandat_id}",
        json={"data": {"Nom": "Nouveau nom"}},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    stored = fake.postgrest.tables["prelevement_mandats"][0]
    assert stored["nom"] == "Nouveau nom"
    # Les autres colonnes ne sont pas touchées -- PATCH mandat fusionne,
    # ne remplace jamais toute la ligne (contrairement à update_record).
    assert stored["rum"] == "RUM1"
    assert stored["batch_id"] == saved["batch_id"]


def test_patch_prelevement_mandat_not_found(client_factory):
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    res = tc.patch(
        "/orgs/org-1/prelevement/mandats/does-not-exist",
        json={"data": {"Nom": "X"}},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 404


def test_bulk_delete_prelevement_mandats(client_factory):
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    _save_one_mandat(tc)
    mandat_id = fake.postgrest.tables["prelevement_mandats"][0]["id"]

    res = tc.request(
        "DELETE",
        "/orgs/org-1/prelevement/mandats",
        json={"ids": [mandat_id]},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    assert res.json()["n_deleted"] == 1
    assert fake.postgrest.tables["prelevement_mandats"] == []


def test_bulk_update_prelevement_mandats(client_factory):
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    _save_one_mandat(tc)
    mandat_id = fake.postgrest.tables["prelevement_mandats"][0]["id"]

    res = tc.patch(
        "/orgs/org-1/prelevement/mandats/bulk",
        json={"ids": [mandat_id], "field": "Ville", "value": "Marseille"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    assert res.json()["n_updated"] == 1
    assert fake.postgrest.tables["prelevement_mandats"][0]["ville"] == "Marseille"


def test_bulk_update_prelevement_mandats_rejects_unknown_field(client_factory):
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    _save_one_mandat(tc)
    mandat_id = fake.postgrest.tables["prelevement_mandats"][0]["id"]

    res = tc.patch(
        "/orgs/org-1/prelevement/mandats/bulk",
        json={"ids": [mandat_id], "field": "org_id", "value": "autre-org"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 400


def test_export_prelevement_mandats(client_factory):
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    _save_one_mandat(tc)

    res = tc.get(
        "/orgs/org-1/prelevement/mandats/export",
        params={"format": "csv"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert "RUM1" in res.text


def test_prelevement_mandats_list_forbidden_for_non_admin(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    res = tc.get("/orgs/org-1/prelevement/mandats", headers={"Authorization": f"Bearer {TOKEN}"})
    assert res.status_code == 403


def test_prelevement_rule_requests_create_and_list(client_factory):
    """Demandes de modification des règles codées en dur (Raphaël,
    2026-09-22) : une file d'attente écrite depuis l'écran, jamais
    appliquée automatiquement -- juste enregistrée avec un statut de
    départ 'en_attente'."""
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    res = tc.post(
        "/orgs/org-1/prelevement/rule-requests",
        json={"titre": "Critère RCUR", "demande": "Ajouter un 3e statut agent IA déclencheur"},
        headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["titre"] == "Critère RCUR"
    assert body["statut"] == "en_attente"
    assert body["org_id"] == "org-1"

    res = tc.get("/orgs/org-1/prelevement/rule-requests", headers=headers)
    assert res.status_code == 200
    titres = [r["titre"] for r in res.json()]
    assert "Critère RCUR" in titres


def test_prelevement_rule_requests_rejects_empty_fields(client_factory):
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    res = tc.post(
        "/orgs/org-1/prelevement/rule-requests",
        json={"titre": "  ", "demande": "quelque chose"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 400
    res = tc.post(
        "/orgs/org-1/prelevement/rule-requests",
        json={"titre": "Un titre", "demande": "   "},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 400


def test_prelevement_rule_requests_patch_statut_and_text(client_factory):
    """Une session Claude Code fait avancer le statut (en_attente ->
    en_cours -> valide) sans toucher au texte de la demande -- et
    inversement, Raphaël peut corriger le texte sans repartir de
    en_attente."""
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    created = tc.post(
        "/orgs/org-1/prelevement/rule-requests",
        json={"titre": "Frais VETO", "demande": "Passer à 25€"},
        headers=headers,
    ).json()

    res = tc.patch(
        f"/orgs/org-1/prelevement/rule-requests/{created['id']}",
        json={"statut": "en_cours"},
        headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["statut"] == "en_cours"
    assert body["demande"] == "Passer à 25€"  # texte inchangé

    res = tc.patch(
        f"/orgs/org-1/prelevement/rule-requests/{created['id']}",
        json={"statut": "valide"},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["statut"] == "valide"


def test_prelevement_rule_requests_patch_rejects_invalid_statut(client_factory):
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    created = tc.post(
        "/orgs/org-1/prelevement/rule-requests",
        json={"titre": "X", "demande": "Y"},
        headers=headers,
    ).json()
    res = tc.patch(
        f"/orgs/org-1/prelevement/rule-requests/{created['id']}",
        json={"statut": "termine"},
        headers=headers,
    )
    assert res.status_code == 400


def test_prelevement_rule_requests_patch_not_found(client_factory):
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    res = tc.patch(
        "/orgs/org-1/prelevement/rule-requests/does-not-exist",
        json={"statut": "en_cours"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 404


def test_prelevement_rule_requests_delete(client_factory):
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    created = tc.post(
        "/orgs/org-1/prelevement/rule-requests",
        json={"titre": "À supprimer", "demande": "Z"},
        headers=headers,
    ).json()
    res = tc.delete(f"/orgs/org-1/prelevement/rule-requests/{created['id']}", headers=headers)
    assert res.status_code == 200
    res = tc.get("/orgs/org-1/prelevement/rule-requests", headers=headers)
    assert all(r["id"] != created["id"] for r in res.json())


def test_prelevement_rule_requests_forbidden_for_non_admin(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    res = tc.get("/orgs/org-1/prelevement/rule-requests", headers={"Authorization": f"Bearer {TOKEN}"})
    assert res.status_code == 403


def test_prelevement_rule_request_question_create_and_answer(client_factory):
    """Question à choix cliquables posée par une session Claude Code sur
    une demande ambiguë (Raphaël, 2026-09-22) -- même principe que
    chantier_questions côté Cockpit."""
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    created = tc.post(
        "/orgs/org-1/prelevement/rule-requests",
        json={"titre": "Critère RCUR", "demande": "Ajouter un 3e statut déclencheur"},
        headers=headers,
    ).json()

    res = tc.post(
        f"/orgs/org-1/prelevement/rule-requests/{created['id']}/questions",
        json={"question": "Quel statut exact ?", "options": ["Notifié J-1", "Validé banque", "Autre"]},
        headers=headers,
    )
    assert res.status_code == 200
    question = res.json()
    assert question["request_id"] == created["id"]
    assert question["options"] == ["Notifié J-1", "Validé banque", "Autre"]
    assert question["answered_at"] is None

    res = tc.patch(
        f"/orgs/org-1/prelevement/rule-requests/{created['id']}/questions/{question['id']}",
        json={"answer": "Notifié J-1", "comment": "Celui qu'on voit le plus"},
        headers=headers,
    )
    assert res.status_code == 200
    answered = res.json()
    assert answered["answer"] == "Notifié J-1"
    assert answered["comment"] == "Celui qu'on voit le plus"
    assert answered["answered_at"] is not None


def test_prelevement_rule_request_question_rejects_empty(client_factory):
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    created = tc.post(
        "/orgs/org-1/prelevement/rule-requests",
        json={"titre": "X", "demande": "Y"},
        headers=headers,
    ).json()
    res = tc.post(
        f"/orgs/org-1/prelevement/rule-requests/{created['id']}/questions",
        json={"question": "   "},
        headers=headers,
    )
    assert res.status_code == 400


def test_prelevement_rule_request_question_answer_rejects_empty(client_factory):
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    created = tc.post(
        "/orgs/org-1/prelevement/rule-requests",
        json={"titre": "X", "demande": "Y"},
        headers=headers,
    ).json()
    question = tc.post(
        f"/orgs/org-1/prelevement/rule-requests/{created['id']}/questions",
        json={"question": "Q ?"},
        headers=headers,
    ).json()
    res = tc.patch(
        f"/orgs/org-1/prelevement/rule-requests/{created['id']}/questions/{question['id']}",
        json={"answer": "  "},
        headers=headers,
    )
    assert res.status_code == 400


def test_prelevement_rule_request_question_forbidden_for_non_admin(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    res = tc.post(
        "/orgs/org-1/prelevement/rule-requests/does-not-exist/questions",
        json={"question": "Q ?"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 403


def test_prelevement_rule_request_event_create(client_factory):
    """Journal d'activité en direct sur une demande (Raphaël,
    2026-09-22) -- une session Claude Code note ici ce qu'elle est en
    train de faire, visible sur le site en quasi direct."""
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    created = tc.post(
        "/orgs/org-1/prelevement/rule-requests",
        json={"titre": "Critère RCUR", "demande": "Ajouter un 3e statut déclencheur"},
        headers=headers,
    ).json()

    res = tc.post(
        f"/orgs/org-1/prelevement/rule-requests/{created['id']}/events",
        json={"message": "Je regarde le code existant"},
        headers=headers,
    )
    assert res.status_code == 200
    event = res.json()
    assert event["request_id"] == created["id"]
    assert event["message"] == "Je regarde le code existant"

    res = tc.post(
        f"/orgs/org-1/prelevement/rule-requests/{created['id']}/events",
        json={"message": "PR créée, CI en cours"},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["message"] == "PR créée, CI en cours"


def test_prelevement_rule_request_event_rejects_empty(client_factory):
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    created = tc.post(
        "/orgs/org-1/prelevement/rule-requests",
        json={"titre": "X", "demande": "Y"},
        headers=headers,
    ).json()
    res = tc.post(
        f"/orgs/org-1/prelevement/rule-requests/{created['id']}/events",
        json={"message": "   "},
        headers=headers,
    )
    assert res.status_code == 400


def test_prelevement_rule_request_event_forbidden_for_non_admin(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    res = tc.post(
        "/orgs/org-1/prelevement/rule-requests/does-not-exist/events",
        json={"message": "Je regarde"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 403


def test_create_and_list_sections(client_factory):
    fake = _make_client(profiles=[ADMIN_PROFILE])
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}

    res = tc.post("/orgs/org-1/sections", json={"nom": "Frontend"}, headers=headers)
    assert res.status_code == 200
    assert res.json()["nom"] == "Frontend"

    res = tc.get("/orgs/org-1/sections", headers=headers)
    assert [s["nom"] for s in res.json()] == ["Frontend"]


def test_update_chantier_status(client_factory):
    fake = _make_client(
        profiles=[ADMIN_PROFILE],
        chantiers=[{
            "id": "ch-1", "org_id": "org-1", "title": "X", "status": "a_faire",
            "priority": "normale", "theme": None, "created_by": "user-1",
        }],
    )
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}

    res = tc.patch("/orgs/org-1/chantiers/ch-1/status", json={"status": "en_cours"}, headers=headers)
    assert res.status_code == 200

    res = tc.get("/orgs/org-1/chantiers", headers=headers)
    assert res.json()[0]["status"] == "en_cours"


def test_update_chantier_status_rejects_invalid_status(client_factory):
    fake = _make_client(
        profiles=[ADMIN_PROFILE],
        chantiers=[{"id": "ch-1", "org_id": "org-1", "title": "X", "status": "a_faire"}],
    )
    tc = client_factory(fake)
    res = tc.patch(
        "/orgs/org-1/chantiers/ch-1/status",
        json={"status": "nimportequoi"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 400


def test_update_chantier_status_wrong_org_is_404(client_factory):
    """Un chantier d'un autre environnement ne doit pas être modifiable
    en devinant juste son id -- même garde que resolve_dedup_alert."""
    fake = _make_client(
        profiles=[ADMIN_PROFILE],
        chantiers=[{"id": "ch-1", "org_id": "org-autre", "title": "X", "status": "a_faire"}],
    )
    tc = client_factory(fake)
    res = tc.patch(
        "/orgs/org-1/chantiers/ch-1/status",
        json={"status": "en_cours"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 404


def test_chantier_messages_roundtrip(client_factory):
    fake = _make_client(
        profiles=[ADMIN_PROFILE],
        chantiers=[{"id": "ch-1", "org_id": "org-1", "title": "X", "status": "a_faire"}],
    )
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}

    res = tc.get("/orgs/org-1/chantiers/ch-1/messages", headers=headers)
    assert res.status_code == 200
    assert res.json() == []

    res = tc.post(
        "/orgs/org-1/chantiers/ch-1/messages", json={"body": "Ça avance."}, headers=headers,
    )
    assert res.status_code == 200
    assert [m["body"] for m in res.json()] == ["Ça avance."]
    assert res.json()[0]["author_type"] == "user"


def test_chantier_message_empty_body_is_400(client_factory):
    fake = _make_client(
        profiles=[ADMIN_PROFILE],
        chantiers=[{"id": "ch-1", "org_id": "org-1", "title": "X", "status": "a_faire"}],
    )
    tc = client_factory(fake)
    res = tc.post(
        "/orgs/org-1/chantiers/ch-1/messages", json={"body": "   "},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 400


def test_chantier_messages_wrong_org_is_404(client_factory):
    fake = _make_client(
        profiles=[ADMIN_PROFILE],
        chantiers=[{"id": "ch-1", "org_id": "org-autre", "title": "X", "status": "a_faire"}],
    )
    tc = client_factory(fake)
    res = tc.get("/orgs/org-1/chantiers/ch-1/messages", headers={"Authorization": f"Bearer {TOKEN}"})
    assert res.status_code == 404


def test_chantier_todos_roundtrip_and_toggle(client_factory):
    fake = _make_client(
        profiles=[ADMIN_PROFILE],
        chantiers=[{"id": "ch-1", "org_id": "org-1", "title": "X", "status": "a_faire"}],
    )
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}

    res = tc.post("/orgs/org-1/chantiers/ch-1/todos", json={"body": "Écrire les tests"}, headers=headers)
    assert res.status_code == 200
    todos = res.json()
    assert [t["body"] for t in todos] == ["Écrire les tests"]
    assert not todos[0].get("done")
    todo_id = todos[0]["id"]

    res = tc.patch(
        f"/orgs/org-1/chantiers/ch-1/todos/{todo_id}", json={"done": True}, headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["done"] is True

    res = tc.get("/orgs/org-1/chantiers/ch-1/todos", headers=headers)
    assert res.json()[0]["done"] is True


def test_chantier_todo_unknown_id_is_404(client_factory):
    fake = _make_client(
        profiles=[ADMIN_PROFILE],
        chantiers=[{"id": "ch-1", "org_id": "org-1", "title": "X", "status": "a_faire"}],
    )
    tc = client_factory(fake)
    res = tc.patch(
        "/orgs/org-1/chantiers/ch-1/todos/todo-inconnu", json={"done": True},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 404


def test_chantier_questions_roundtrip_and_answer(client_factory):
    """Raphaël (2026-09-21) : la fiche de questions doit vivre dans le
    Cockpit lui-même, pas sur une page à part -- une question créée ici
    doit être lisible et répondable directement via l'API du Cockpit."""
    fake = _make_client(
        profiles=[ADMIN_PROFILE],
        chantiers=[{"id": "ch-1", "org_id": "org-1", "title": "X", "status": "attente_retour"}],
    )
    tc = client_factory(fake)
    headers = {"Authorization": f"Bearer {TOKEN}"}

    res = tc.post(
        "/orgs/org-1/chantiers/ch-1/questions",
        json={"question": "On garde l'ancien fichier ou pas ?", "options": ["Le garder", "Le supprimer"]},
        headers=headers,
    )
    assert res.status_code == 200
    questions = res.json()
    assert [q["question"] for q in questions] == ["On garde l'ancien fichier ou pas ?"]
    assert questions[0]["options"] == ["Le garder", "Le supprimer"]
    assert questions[0]["answer"] is None
    question_id = questions[0]["id"]

    res = tc.patch(
        f"/orgs/org-1/chantiers/ch-1/questions/{question_id}",
        json={"answer": "Le garder", "comment": "au cas où"},
        headers=headers,
    )
    assert res.status_code == 200
    answered = res.json()[0]
    assert answered["answer"] == "Le garder"
    assert answered["comment"] == "au cas où"
    assert answered["answered_at"] is not None

    res = tc.get("/orgs/org-1/chantiers/ch-1/questions", headers=headers)
    assert res.json()[0]["answer"] == "Le garder"


def test_chantier_question_empty_is_400(client_factory):
    fake = _make_client(
        profiles=[ADMIN_PROFILE],
        chantiers=[{"id": "ch-1", "org_id": "org-1", "title": "X", "status": "a_faire"}],
    )
    tc = client_factory(fake)
    res = tc.post(
        "/orgs/org-1/chantiers/ch-1/questions", json={"question": "   "},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 400


def test_chantier_question_unknown_id_is_404(client_factory):
    fake = _make_client(
        profiles=[ADMIN_PROFILE],
        chantiers=[{"id": "ch-1", "org_id": "org-1", "title": "X", "status": "a_faire"}],
    )
    tc = client_factory(fake)
    res = tc.patch(
        "/orgs/org-1/chantiers/ch-1/questions/question-inconnue", json={"answer": "Oui"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 404


# ---------------------------------------------------------------
# Pipeline "Trieur de Data" : import + mapping (étape 1)
# ---------------------------------------------------------------

def _upload_csv(tc, org_id, content: bytes, filename="clients.csv"):
    return tc.post(
        f"/orgs/{org_id}/pipeline/sessions",
        files={"files": (filename, content, "text/csv")},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )


def test_pipeline_session_create_rejects_oversized_upload_before_parsing(client_factory, monkeypatch):
    """Au-delà de PIPELINE_MAX_UPLOAD_BYTES (plafond ABSOLU même en mode
    flux -- protège le disque/le temps de requête, pas la RAM, voir sa
    docstring), rejeté en 413 AVANT tout parsing. Plafond réduit ici pour
    ne pas générer un vrai gros fichier de test.

    Trouvaille Copilot, PR #28 : un test qui ne vérifie QUE le code 413
    passerait encore si le contrôle de taille arrivait APRÈS un
    f.read()/parsing -- ne verrouille pas la propriété qui protège
    l'OOM. On fait donc explicitement planter le parsing s'il est
    jamais atteint, pour prouver que le rejet a bien lieu avant. Message
    ne suggère plus le CSV (contrairement à l'ancien plafond de #28) --
    devenu inutile une fois le mode flux fusionné : un .xlsx volumineux
    est désormais accepté nativement, seul un dépassement du plafond
    absolu (550 Mo) est rejeté."""
    from api import main as api_main

    monkeypatch.setattr(api_main, "PIPELINE_MAX_UPLOAD_BYTES", 10)

    def _boom(*args, **kwargs):
        raise AssertionError("le parsing ne doit jamais être atteint après le rejet 413")

    monkeypatch.setattr(api_main, "_parse_and_merge_pipeline_files", _boom)

    fake = _make_client()
    tc = client_factory(fake)
    res = _upload_csv(tc, "org-1", b"NOM,EMAIL\nDupont,d@x.com\n")

    assert res.status_code == 413
    assert "volumineux" in res.json()["detail"]
    assert not fake.postgrest.tables["pipeline_sessions"]


def test_pipeline_session_create_rejects_upload_with_unknown_size():
    """Même défense en profondeur que sur POST /orgs/{org_id}/import (voir
    test_import_rejects_upload_with_unknown_size) : un .size indisponible
    est refusé plutôt que silencieusement compté à 0 octet -- sinon
    `await f.read()` juste après matérialise le fichier en mémoire malgré
    le plafond (revue Copilot, PR #28). Appel direct de l'endpoint
    (impossible à simuler via TestClient, qui calcule toujours une vraie
    taille pendant le parsing multipart)."""
    import asyncio

    from fastapi import HTTPException

    from api import main as api_main

    fake = _make_client()
    ctx = api_main.get_current_ctx(authorization=f"Bearer {TOKEN}", client=fake)
    ctx = api_main.require_org_access("org-1", ctx)

    fake_upload = SimpleNamespace(size=None, filename="clients.csv")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            api_main.create_pipeline_session_endpoint(org_id="org-1", files=[fake_upload], ctx=ctx)
        )

    assert exc_info.value.status_code == 413
    assert "indéterminable" in exc_info.value.detail
    assert not fake.postgrest.tables["pipeline_sessions"]


def test_pipeline_session_create_streams_above_threshold(client_factory, monkeypatch):
    """Au-delà de PIPELINE_STREAM_THRESHOLD_BYTES (mais sous le plafond
    absolu), bascule en mode flux (_stream_import_pipeline_files) -- même
    résultat final que le mode classique pour l'appelant : mêmes lignes en
    base, même forme de réponse. Seuil réduit ici pour déclencher le mode
    flux sans générer un vrai gros fichier."""
    from api import main as api_main

    monkeypatch.setattr(api_main, "PIPELINE_STREAM_THRESHOLD_BYTES", 10)

    fake = _make_client()
    tc = client_factory(fake)
    content = b"NOM,EMAIL\nDupont,d@x.com\nMartin,m@x.com\n"
    res = _upload_csv(tc, "org-1", content)

    assert res.status_code == 200
    body = res.json()
    assert body["row_count"] == 2
    assert body["columns"] == ["NOM", "EMAIL"]
    assert [r["NOM"] for r in body["preview_rows"]] == ["Dupont", "Martin"]
    assert body["sheets"][0]["row_count"] == 2

    rows = fake.postgrest.tables["pipeline_rows"]
    assert sorted(r["data"]["NOM"] for r in rows) == ["Dupont", "Martin"]


def test_pipeline_session_create_never_streams_xls_even_above_threshold(client_factory, monkeypatch):
    """Trouvaille Copilot, PR #29 : stream_excel_sheets() repose sur
    openpyxl, qui ne lit PAS le format .xls binaire (Excel 97-2003,
    différent de .xlsx). Router un .xls volumineux vers le mode flux
    ferait donc échouer un import que le chemin classique (engines
    calamine/openpyxl via pandas, avec repli) pouvait réussir --
    régression de compatibilité. Un .xls reste donc TOUJOURS sur le
    chemin classique, quelle que soit sa taille : vérifié ici en
    empêchant explicitement stream_excel_sheets d'être appelée."""
    from api import main as api_main

    monkeypatch.setattr(api_main, "PIPELINE_STREAM_THRESHOLD_BYTES", 10)

    def _boom(*args, **kwargs):
        raise AssertionError("stream_excel_sheets ne doit jamais être appelée pour un .xls")

    monkeypatch.setattr(api_main, "stream_excel_sheets", _boom)

    import io as _io

    import pandas as pd

    buf = _io.BytesIO()
    pd.DataFrame({"NOM": ["Dupont"], "EMAIL": ["d@x.com"]}).to_excel(buf, index=False, sheet_name="Feuil1")

    fake = _make_client()
    tc = client_factory(fake)
    res = tc.post(
        "/orgs/org-1/pipeline/sessions",
        files=[("files", ("clients.xls", buf.getvalue(),
                           "application/vnd.ms-excel"))],
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    assert res.json()["row_count"] == 1


def test_pipeline_session_create_stages_rows_and_detects_columns(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    content = b"NOM,EMAIL\nDupont,d@x.com\nMartin,m@x.com\n"

    res = _upload_csv(tc, "org-1", content)
    assert res.status_code == 200
    body = res.json()
    assert body["row_count"] == 2
    assert body["columns"] == ["NOM", "EMAIL"]
    assert body["status"] == "importing"
    assert [r["NOM"] for r in body["preview_rows"]] == ["Dupont", "Martin"]
    # "IBAN" est colonne maître (_make_client) mais absent du fichier -> pas
    # "inconnue" pour autant : unknown_columns ne signale que l'inverse
    # (colonne du fichier absente des colonnes maîtres).
    assert body["unknown_columns"] == ["EMAIL"]

    # Les lignes sont bien en staging (pipeline_rows), pas juste renvoyées.
    session_id = body["session_id"]
    rows = fake.postgrest.tables["pipeline_rows"]
    assert len(rows) == 2
    assert all(r["session_id"] == session_id for r in rows)


def test_pipeline_session_create_returns_per_sheet_summaries(client_factory):
    """[7] de la référence Streamlit : chaque onglet reçoit son propre
    résumé (colonnes, lignes, doublons, aperçu) pour construire une carte
    par onglet côté écran, sans re-télécharger les fichiers."""
    fake = _make_client()
    tc = client_factory(fake)
    content = b"NOM,EMAIL\nDupont,d@x.com\nDupont,d@x.com\nMartin,m@x.com\n"

    body = _upload_csv(tc, "org-1", content).json()
    assert len(body["sheets"]) == 1
    sheet = body["sheets"][0]
    assert sheet["sheet_key"] == "clients"
    assert sheet["columns"] == ["NOM", "EMAIL"]
    assert sheet["row_count"] == 3
    assert sheet["n_duplicates"] == 1
    assert sheet["preview_rows"][0] == {"NOM": "Dupont", "EMAIL": "d@x.com"}


def test_pipeline_session_create_merges_multiple_files_into_one_session(client_factory):
    """Restaure le multi-fichiers de l'original Streamlit
    (st.file_uploader(accept_multiple_files=True), views/tab2_import_mapping.py) --
    régression signalée par l'utilisateur : un seul fichier sélectionnable
    dans le premier portage React. Plusieurs fichiers, même colonnes,
    doivent fusionner en UNE session avec toutes les lignes."""
    fake = _make_client()
    tc = client_factory(fake)

    res = tc.post(
        "/orgs/org-1/pipeline/sessions",
        files=[
            ("files", ("fichier1.csv", b"NOM,EMAIL\nDupont,d@x.com\n", "text/csv")),
            ("files", ("fichier2.csv", b"NOM,EMAIL\nMartin,m@x.com\nDurand,du@x.com\n", "text/csv")),
        ],
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["row_count"] == 3
    assert {r["NOM"] for r in body["preview_rows"]} == {"Dupont", "Martin", "Durand"}

    # Une seule session en base, avec TOUTES les lignes des deux fichiers.
    session_id = body["session_id"]
    rows = fake.postgrest.tables["pipeline_rows"]
    assert len(rows) == 3
    assert all(r["session_id"] == session_id for r in rows)

    session = next(r for r in fake.postgrest.tables["pipeline_sessions"] if r["id"] == session_id)
    assert session["source_filename"] == "2 fichiers (fichier1.csv, fichier2.csv)"
    assert session["row_count"] == 3


def test_pipeline_session_create_inserts_all_rows_across_parallel_batches(client_factory):
    """Import rapide (revue de l'utilisateur -- import trop lent) :
    insertion de plusieurs LOTS (PIPELINE_APPEND_BATCH=500) EN PARALLÈLE
    (asyncio.gather/to_thread), avec un seul row_count final au lieu d'un
    par lot. Vérifie qu'aucune ligne n'est perdue ni dupliquée sur un
    fichier qui déclenche plusieurs lots, et que le row_count final est
    exact malgré l'insertion concurrente."""
    fake = _make_client()
    tc = client_factory(fake)
    n_rows = 1200  # 3 lots de 500/500/200
    content = b"NOM\n" + b"\n".join(f"L{i}".encode() for i in range(n_rows)) + b"\n"

    res = tc.post(
        "/orgs/org-1/pipeline/sessions",
        files=[("files", ("gros_fichier.csv", content, "text/csv"))],
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["row_count"] == n_rows

    session_id = body["session_id"]
    rows = fake.postgrest.tables["pipeline_rows"]
    assert len(rows) == n_rows
    assert len({r["id"] for r in rows}) == n_rows, "pas de doublon d'id malgré l'insertion parallèle"
    assert {r["row_index"] for r in rows} == set(range(n_rows)), "aucune ligne perdue, index continu"

    session = next(r for r in fake.postgrest.tables["pipeline_sessions"] if r["id"] == session_id)
    assert session["row_count"] == n_rows, "un seul appel final au compteur, pas un par lot"


def test_pipeline_session_create_cleans_up_session_when_a_batch_fails(client_factory, monkeypatch):
    """Trouvaille Copilot, PR #27 : avec asyncio.gather par défaut, un lot
    qui plante faisait sortir l'endpoint immédiatement en 500 sans attendre
    les autres `to_thread` déjà lancés (qui continuaient d'écrire en
    arrière-plan après la réponse) ni nettoyer la session à moitié
    remplie. Simule l'échec du 2e lot sur un import à 3 lots : la réponse
    doit être 500 ET la session ne doit plus exister."""
    from api import main as api_main

    fake = _make_client()
    tc = client_factory(fake)
    n_rows = 1200  # 3 lots de 500/500/200

    real_insert = api_main.insert_pipeline_rows_only
    call_count = {"n": 0}

    def _fails_on_second_batch(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("panne réseau simulée sur le 2e lot")
        return real_insert(*args, **kwargs)

    monkeypatch.setattr(api_main, "insert_pipeline_rows_only", _fails_on_second_batch)

    content = b"NOM\n" + b"\n".join(f"L{i}".encode() for i in range(n_rows)) + b"\n"
    res = tc.post(
        "/orgs/org-1/pipeline/sessions",
        files=[("files", ("gros_fichier.csv", content, "text/csv"))],
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 500

    # La session à moitié remplie ne doit pas rester trainer en base.
    assert not any(
        r.get("source_filename") == "gros_fichier.csv" for r in fake.postgrest.tables["pipeline_sessions"]
    )


def test_pipeline_session_create_cleans_up_expired_sessions_of_same_org_first(client_factory):
    """Revue PR #24, point #8 : la création d'une nouvelle session
    nettoie d'abord les sessions EXPIRÉES de cet org (nettoyage
    opportuniste, pas de tâche planifiée) -- une session d'un AUTRE org,
    même expirée, n'est pas touchée (pas de RPC cross-org côté API, voir
    migration 0011)."""
    from datetime import datetime, timedelta, timezone

    fake = _make_client()
    tc = client_factory(fake)

    expired_own_org = _upload_csv(tc, "org-1", b"NOM\nA\n").json()["session_id"]
    expired_other_org = _upload_csv(tc, "org-1", b"NOM\nB\n").json()["session_id"]
    fresh_own_org = _upload_csv(tc, "org-1", b"NOM\nC\n").json()["session_id"]

    now = datetime.now(timezone.utc)
    by_id = {s["id"]: s for s in fake.postgrest.tables["pipeline_sessions"]}
    by_id[expired_own_org]["expires_at"] = (now - timedelta(hours=1)).isoformat()
    by_id[expired_other_org]["expires_at"] = (now - timedelta(hours=1)).isoformat()
    by_id[expired_other_org]["org_id"] = "org-2"
    by_id[fresh_own_org]["expires_at"] = (now + timedelta(hours=23)).isoformat()

    _upload_csv(tc, "org-1", b"NOM\nD\n")

    remaining_ids = {s["id"] for s in fake.postgrest.tables["pipeline_sessions"]}
    assert expired_own_org not in remaining_ids
    assert fresh_own_org in remaining_ids
    assert expired_other_org in remaining_ids


def test_pipeline_session_requires_org_access(client_factory):
    fake = _make_client(memberships=[])
    tc = client_factory(fake)
    res = _upload_csv(tc, "org-1", b"NOM\nDupont\n")
    assert res.status_code == 403


def test_pipeline_session_empty_file_is_400(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    res = _upload_csv(tc, "org-1", b"")
    assert res.status_code == 400


def test_pipeline_session_unreadable_file_is_400(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    res = tc.post(
        "/orgs/org-1/pipeline/sessions",
        files={"files": ("clients.xlsx", b"pas un vrai xlsx", "application/octet-stream")},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 400


def test_pipeline_session_get_returns_status_and_preview(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_csv(tc, "org-1", b"NOM,EMAIL\nDupont,d@x.com\n").json()["session_id"]

    res = tc.get(f"/orgs/org-1/pipeline/sessions/{session_id}", headers={"Authorization": f"Bearer {TOKEN}"})
    assert res.status_code == 200
    body = res.json()
    assert body["row_count"] == 1
    assert body["status"] == "importing"
    assert body["columns"] == ["NOM", "EMAIL"]
    assert body["preview_rows"] == [{"NOM": "Dupont", "EMAIL": "d@x.com"}]


def test_pipeline_session_get_unknown_id_is_404(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    res = tc.get("/orgs/org-1/pipeline/sessions/does-not-exist", headers={"Authorization": f"Bearer {TOKEN}"})
    assert res.status_code == 404


def test_pipeline_session_get_wrong_org_is_404(client_factory):
    """Une session appartenant à un AUTRE org qu'un utilisateur ayant
    accès à `org-1` ne doit pas être lisible via `/orgs/org-1/...`, même
    si un id a été deviné/copié -- l'API refait cette vérification elle-même
    (comme _get_chantier_or_404), pas seulement la RLS Supabase."""
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_csv(tc, "org-1", b"NOM\nDupont\n").json()["session_id"]

    # Simule une session qui appartient réellement à un autre org (RLS
    # empêcherait normalement de la voir depuis /orgs/org-1/... -- ici on
    # vérifie que l'API elle-même, pas seulement Supabase, applique cette
    # règle).
    fake.postgrest.tables["pipeline_sessions"][0]["org_id"] = "org-2"

    res = tc.get(f"/orgs/org-1/pipeline/sessions/{session_id}", headers={"Authorization": f"Bearer {TOKEN}"})
    assert res.status_code == 404


def test_pipeline_mapping_wrong_org_is_404(client_factory):
    """Même règle que test_pipeline_session_get_wrong_org_is_404, mais sur
    la route POST mapping : une session d'un autre org ne doit ni être
    lisible ni modifiable via /orgs/org-1/.../mapping."""
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_csv(tc, "org-1", b"NOM\nDupont\n").json()["session_id"]
    fake.postgrest.tables["pipeline_sessions"][0]["org_id"] = "org-2"

    res = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/mapping",
        json={},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 404

    # Les lignes n'ont pas été réécrites (toujours les clés source, pas
    # les clés colonnes maîtres qu'aurait produites le mapping).
    rows = fake.postgrest.tables["pipeline_rows"]
    assert rows[0]["data"] == {"NOM": "Dupont", "_sheet": "clients"}


def test_pipeline_mapping_dry_run_suggests_without_writing(client_factory):
    fake = _make_client()  # master_columns = ["NOM", "IBAN"]
    tc = client_factory(fake)
    session_id = _upload_csv(tc, "org-1", b"NOM,IBAN\nDupont,FR7630006000011234567890189\n").json()["session_id"]

    res = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/mapping",
        json={"dry_run": True},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    body = res.json()
    # La suggestion est PAR ONGLET (sheet_key -> {source: maître}) -- un
    # seul CSV = un seul onglet, nommé d'après le fichier ("clients.csv"
    # sans l'extension, voir trieur/io_excel.py:read_csv_file).
    assert body["suggested_mapping"] == {"clients": {"NOM": "NOM", "IBAN": "IBAN"}}

    # dry_run : rien n'est modifié en base.
    session = tc.get(f"/orgs/org-1/pipeline/sessions/{session_id}", headers={"Authorization": f"Bearer {TOKEN}"}).json()
    assert session["status"] == "importing"


def test_pipeline_mapping_apply_rekeys_rows_and_marks_mapped(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_csv(tc, "org-1", b"nom_client,iban_ref\nDupont,FR7630006000011234567890189\n").json()["session_id"]

    res = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/mapping",
        json={"mapping": {"clients": {"nom_client": "NOM", "iban_ref": "IBAN"}}},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "mapped"
    assert body["n_rows_updated"] == 1
    assert body["n_rows_excluded"] == 0
    assert body["mapping"] == {"clients": {"nom_client": "NOM", "iban_ref": "IBAN"}}

    rows = fake.postgrest.tables["pipeline_rows"]
    assert rows[0]["data"] == {"NOM": "Dupont", "IBAN": "FR7630006000011234567890189"}

    session = get_pipeline_session_via_api(tc, session_id)
    assert session["status"] == "mapped"


def test_pipeline_mapping_reapply_on_already_mapped_session_is_409(client_factory):
    """Trouvaille Copilot, PR #27 : merge_mapped_row retire `_sheet` des
    données à la 1re application. Sans ce garde, un retry (double clic,
    requête rejouée) regrouperait toutes les lignes sous "" -- ne
    correspondant plus à aucun onglet du mapping fourni -- et les
    supprimerait TOUTES via la boucle d'exclusion. Rejeté avant."""
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_csv(tc, "org-1", b"NOM\nDupont\n").json()["session_id"]

    first = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/mapping",
        json={"mapping": {"clients": {"NOM": "NOM"}}},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert first.status_code == 200

    second = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/mapping",
        json={"mapping": {"clients": {"NOM": "NOM"}}},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert second.status_code == 409
    # La ligne mappée par le 1er appel doit rester intacte.
    rows = fake.postgrest.tables["pipeline_rows"]
    assert len(rows) == 1
    assert rows[0]["data"] == {"NOM": "Dupont"}


def test_pipeline_mapping_dry_run_still_works_on_a_mapped_session(client_factory):
    """dry_run reste autorisé après coup (lecture seule, jamais d'écriture) --
    seule l'application réelle est bloquée sur une session déjà mappée."""
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_csv(tc, "org-1", b"NOM\nDupont\n").json()["session_id"]
    tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/mapping",
        json={"mapping": {"clients": {"NOM": "NOM"}}},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    res = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/mapping",
        json={"dry_run": True},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200


def test_pipeline_mapping_unknown_sheet_key_is_400_and_deletes_nothing(client_factory):
    """Trouvaille Copilot, PR #27 : un mapping référençant une clé d'onglet
    inexistante (typo côté client) laissait tous les VRAIS onglets sans
    assignation (absents du dict fourni) -> tous supprimés silencieusement,
    réponse "mapped" à zéro ligne. Rejeté avant toute mutation."""
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_csv(tc, "org-1", b"NOM\nDupont\nMartin\n").json()["session_id"]

    res = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/mapping",
        json={"mapping": {"onglet-qui-nexiste-pas": {"NOM": "NOM"}}},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 400

    rows = fake.postgrest.tables["pipeline_rows"]
    assert len(rows) == 2, "aucune ligne ne doit être supprimée sur un mapping invalide"
    session = get_pipeline_session_via_api(tc, session_id)
    assert session["status"] == "importing", "la session ne doit pas passer à 'mapped' sur un rejet"


def test_pipeline_mapping_excludes_one_of_two_sheets_across_multiple_batches(client_factory, monkeypatch):
    """Trouvaille Copilot, PR #27 : un onglet exclu supprimait toutes ses
    lignes en un seul appel .in_("id", ...) -- risque de dépasser les
    limites de taille de requête sur les gros volumes. Vérifie que
    l'exclusion fonctionne intégralement même sur plus d'un lot
    (PIPELINE_APPEND_BATCH réduit ici pour tester sans générer un vrai
    fichier de centaines de lignes)."""
    from api import main as api_main

    monkeypatch.setattr(api_main, "PIPELINE_APPEND_BATCH", 2)

    fake = _make_client()
    tc = client_factory(fake)
    content_a = b"NOM\n" + b"\n".join(f"A{i}".encode() for i in range(5)) + b"\n"
    content_b = b"NOM\nGarde\n"
    upload = tc.post(
        "/orgs/org-1/pipeline/sessions",
        files=[
            ("files", ("a.csv", content_a, "text/csv")),
            ("files", ("b.csv", content_b, "text/csv")),
        ],
        headers={"Authorization": f"Bearer {TOKEN}"},
    ).json()
    session_id = upload["session_id"]
    # Deux fichiers -> clés préfixées par le nom de fichier (voir
    # _parse_and_merge_pipeline_files) : on les lit dans la réponse plutôt
    # que de deviner le format exact.
    sheet_keys = {s["sheet_key"] for s in upload["sheets"]}
    sheet_key_b = next(k for k in sheet_keys if "b.csv" in k)

    res = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/mapping",
        json={"mapping": {sheet_key_b: {"NOM": "NOM"}}},  # "a" absent -> exclu, 5 lignes sur 3 lots de 2
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["n_rows_excluded"] == 5
    assert body["n_rows_updated"] == 1

    rows = fake.postgrest.tables["pipeline_rows"]
    assert len(rows) == 1
    assert rows[0]["data"] == {"NOM": "Garde"}


def test_pipeline_mapping_streaming_apply_excludes_and_updates_across_multiple_pages(client_factory, monkeypatch):
    """Même scénario que le test précédent (exclusion sur plusieurs lots),
    mais avec `sheet_keys` fourni -- exerce le NOUVEAU chemin par pages
    (_pages_for_sheet/_delete_sheet_pages/_update_sheet_pages), pas le
    repli sur le chargement complet. Vérifie surtout que la pagination
    "auto-consommante" (une page à la fois, sans offset explicite) ne
    saute ni ne double aucune ligne sur PLUSIEURS pages, à la fois pour
    la suppression (onglet exclu) ET la mise à jour (onglet mappé)."""
    from api import main as api_main

    monkeypatch.setattr(api_main, "PIPELINE_APPEND_BATCH", 2)

    fake = _make_client()
    tc = client_factory(fake)
    content_a = b"NOM\n" + b"\n".join(f"A{i}".encode() for i in range(5)) + b"\n"
    content_b = b"NOM\n" + b"\n".join(f"B{i}".encode() for i in range(5)) + b"\n"
    upload = tc.post(
        "/orgs/org-1/pipeline/sessions",
        files=[
            ("files", ("a.csv", content_a, "text/csv")),
            ("files", ("b.csv", content_b, "text/csv")),
        ],
        headers={"Authorization": f"Bearer {TOKEN}"},
    ).json()
    session_id = upload["session_id"]
    sheet_keys = [s["sheet_key"] for s in upload["sheets"]]
    sheet_key_b = next(k for k in sheet_keys if "b.csv" in k)

    res = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/mapping",
        json={"mapping": {sheet_key_b: {"NOM": "NOM"}}, "sheet_keys": sheet_keys},  # "a" absent -> exclu
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["n_rows_excluded"] == 5
    assert body["n_rows_updated"] == 5

    rows = fake.postgrest.tables["pipeline_rows"]
    assert len(rows) == 5
    assert sorted(r["data"]["NOM"] for r in rows) == [f"B{i}" for i in range(5)]


def test_pipeline_mapping_streaming_apply_rejects_unknown_sheet_key(client_factory):
    """Même garde que le chemin classique (400 avant toute mutation), mais
    validée contre `sheet_keys` fourni plutôt qu'un chargement complet."""
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_csv(tc, "org-1", b"NOM\nDupont\n").json()["session_id"]

    res = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/mapping",
        json={"mapping": {"typo": {"NOM": "NOM"}}, "sheet_keys": ["clients"]},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 400
    rows = fake.postgrest.tables["pipeline_rows"]
    assert len(rows) == 1  # rien touché


def test_pipeline_mapping_streaming_apply_rejects_incomplete_sheet_keys(client_factory, monkeypatch):
    """Trouvaille Copilot (PR #29) : known_sheet_keys = body.sheet_keys
    (mode flux) -- si le client fournit une liste incomplète (onglet
    ajouté entre l'aperçu et l'application, appel manuel de l'API...),
    les lignes du sheet_key MANQUANT n'étaient ni mises à jour ni
    exclues, mais la session passait quand même à 'mapped' : staging à
    moitié transformé et invisible. Garde ajoutée : n_updated +
    n_excluded comparé à session['row_count'], échec explicite (même
    filet que les autres échecs en cours de route -- session supprimée)
    si ça ne correspond pas."""
    import io as _io

    import pandas as pd

    from api import main as api_main

    monkeypatch.setattr(api_main, "PIPELINE_STREAM_THRESHOLD_BYTES", 10)

    buf = _io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        pd.DataFrame({"NOM": ["Dupont"]}).to_excel(w, index=False, sheet_name="Contacts")
        pd.DataFrame({"VILLE": ["Paris"]}).to_excel(w, index=False, sheet_name="Villes")

    fake = _make_client()
    tc = client_factory(fake)
    upload = tc.post(
        "/orgs/org-1/pipeline/sessions",
        files=[("files", ("deux_onglets.xlsx", buf.getvalue(),
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))],
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert upload.status_code == 200
    upload_body = upload.json()
    session_id = upload_body["session_id"]
    all_sheet_keys = [s["sheet_key"] for s in upload_body["sheets"]]
    assert len(all_sheet_keys) == 2
    contacts_key = next(k for k in all_sheet_keys if "Contacts" in k)

    res = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/mapping",
        json={
            "mapping": {contacts_key: {"NOM": "NOM"}},
            # "Villes" manque volontairement : la session le connaît (2
            # onglets réellement importés) mais le client n'en informe
            # que la moitié.
            "sheet_keys": [contacts_key],
        },
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert res.status_code == 500
    assert "supprimée" in res.json()["detail"]
    assert not fake.postgrest.tables["pipeline_sessions"]


def test_pipeline_full_flow_end_to_end_via_streaming_paths(client_factory, monkeypatch):
    """Parcours COMPLET (import -> suggestion -> application -> vérif des
    données finales) sur un fichier assez gros pour forcer PLUSIEURS
    pages à chaque étape, en mode flux de bout en bout -- pas juste
    l'import isolé (voir tests/test_io_excel_streaming.py pour la mesure
    mémoire) ni la mutation isolée (voir les tests streaming_apply
    ci-dessus) : ici, la VRAIE suite d'appels que fait le frontend."""
    import io as _io

    import pandas as pd

    from api import main as api_main

    monkeypatch.setattr(api_main, "PIPELINE_STREAM_THRESHOLD_BYTES", 10)
    monkeypatch.setattr(api_main, "PIPELINE_APPEND_BATCH", 7)  # force plusieurs pages sur 20 lignes

    n = 20
    buf = _io.BytesIO()
    pd.DataFrame({
        "NOM": [f"NOM{i}" for i in range(n)],
        "EMAIL": [f"user{i}@example.com" for i in range(n)],
    }).to_excel(buf, index=False, sheet_name="Feuil1")

    fake = _make_client()
    tc = client_factory(fake)
    upload = tc.post(
        "/orgs/org-1/pipeline/sessions",
        files=[("files", ("gros.xlsx", buf.getvalue(),
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))],
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert upload.status_code == 200
    upload_body = upload.json()
    assert upload_body["row_count"] == n
    session_id = upload_body["session_id"]
    sheet_keys = [s["sheet_key"] for s in upload_body["sheets"]]

    dry = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/mapping",
        json={"dry_run": True, "sheet_keys": sheet_keys},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert dry.status_code == 200
    suggestion = dry.json()["suggested_mapping"]
    assert suggestion[sheet_keys[0]].get("NOM") == "NOM"

    apply_res = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/mapping",
        json={"mapping": suggestion, "sheet_keys": sheet_keys},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert apply_res.status_code == 200
    apply_body = apply_res.json()
    assert apply_body["n_rows_updated"] == n
    assert apply_body["n_rows_excluded"] == 0

    rows = fake.postgrest.tables["pipeline_rows"]
    assert len(rows) == n
    assert {r["data"]["NOM"] for r in rows} == {f"NOM{i}" for i in range(n)}
    assert all("_sheet" not in r["data"] for r in rows)  # retiré à l'application, comme le chemin classique

    # Suite du parcours complet : filtrage (onglet 3) puis export (onglet 4)
    # -- vérifie que les lignes importées/mappées EN FLUX restent lisibles
    # par le reste du pipeline, pas juste correctement insérées.
    listed = tc.get(
        f"/orgs/org-1/pipeline/sessions/{session_id}/rows",
        params={"search": "NOM1"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert listed.status_code == 200
    listed_body = listed.json()
    assert listed_body["row_count"] == n
    assert {r["NOM"] for r in listed_body["rows"]} == {"NOM1", "NOM10", "NOM11", "NOM12", "NOM13",
                                                          "NOM14", "NOM15", "NOM16", "NOM17", "NOM18", "NOM19"}

    export_res = tc.get(
        f"/orgs/org-1/pipeline/sessions/{session_id}/export",
        params={"format": "csv"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert export_res.status_code == 200
    exported_text = export_res.content.decode("utf-8-sig")
    assert exported_text.count("\n") >= n  # en-tête + n lignes
    for i in range(n):
        assert f"NOM{i}" in exported_text


def test_pipeline_full_pipeline_all_stages_combined_in_streaming_mode(client_factory, monkeypatch):
    """Parcours COMPLET jusqu'à l'export, en combinant le plus de cas
    réels possible en une seule fois, tout en mode flux :
      - 2 fichiers (xlsx + csv) -> préfixage des clés d'onglet ;
      - le xlsx a 2 onglets, l'un avec en-tête normale, l'autre SANS
        en-tête (déduite par contenu) ;
      - un onglet exclu (absent du mapping) -> supprimé par pagination ;
      - détection + validation IBAN (une valeur invalide) ;
      - filtre multi-critères (groups, département par CP) ;
      - dédoublonnage (mode rule) SCOPÉ au filtre actif ;
      - export final en .xlsx (pas juste CSV, voir test précédent).
    Plusieurs pages forcées à chaque étape (PIPELINE_APPEND_BATCH réduit)
    pour exercer la pagination "auto-consommante" sur un scénario
    réaliste, pas seulement des cas isolés."""
    import io as _io

    import openpyxl
    import pandas as pd
    from openpyxl.utils.dataframe import dataframe_to_rows

    from api import main as api_main

    monkeypatch.setattr(api_main, "PIPELINE_STREAM_THRESHOLD_BYTES", 10)
    monkeypatch.setattr(api_main, "PIPELINE_APPEND_BATCH", 2)

    # --- Fichier A : xlsx, 2 onglets ---
    wb = openpyxl.Workbook()
    ws_clients = wb.active
    ws_clients.title = "Clients"
    clients_df = pd.DataFrame({
        "NOM": ["Dupont", "Dupont", "Martin"],
        "IBAN": [
            "FR76 3000 6000 0112 3456 7890 189",  # valide (espaces nettoyés)
            "FR76 3000 6000 0112 3456 7890 189",  # doublon volontaire (dédoublonnage)
            "FR0000000000000000000000000",         # checksum invalide
        ],
        "CP": ["34000", "34000", "71000"],
    })
    for row in dataframe_to_rows(clients_df, index=False, header=True):
        ws_clients.append(row)

    ws_prospects = wb.create_sheet("Prospects")  # PAS d'en-tête -- sera exclu (pas de mapping fourni)
    ws_prospects.append(["ProspectX", "0601020304"])
    ws_prospects.append(["ProspectY", "0601020305"])

    xlsx_buf = _io.BytesIO()
    wb.save(xlsx_buf)

    csv_content = b"NOM,IBAN,CP\nPetit,FR7630006000011234567890189,34500\n"

    fake = _make_client()
    tc = client_factory(fake)
    upload = tc.post(
        "/orgs/org-1/pipeline/sessions",
        files=[
            ("files", ("a.xlsx", xlsx_buf.getvalue(),
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
            ("files", ("b.csv", csv_content, "text/csv")),
        ],
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert upload.status_code == 200
    upload_body = upload.json()
    assert upload_body["row_count"] == 6  # 3 Clients + 2 Prospects + 1 csv
    session_id = upload_body["session_id"]
    sheet_keys = [s["sheet_key"] for s in upload_body["sheets"]]
    assert len(sheet_keys) == 3  # multi-fichiers -> préfixées "fichier :: onglet"
    clients_key = next(k for k in sheet_keys if "Clients" in k)
    prospects_key = next(k for k in sheet_keys if "Prospects" in k)
    csv_key = next(k for k in sheet_keys if "b.csv" in k)

    # Prospects (sans en-tête) doit quand même être détecté avec des
    # colonnes déduites -- vérifie que la déduction d'en-tête (testée en
    # isolation dans test_io_excel_streaming.py) fonctionne aussi à
    # travers le VRAI endpoint d'upload, pas seulement stream_excel_sheets
    # appelée directement.
    prospects_summary = next(s for s in upload_body["sheets"] if s["sheet_key"] == prospects_key)
    assert prospects_summary["row_count"] == 2
    assert prospects_summary["columns"]  # colonnes non vides, peu importe lesquelles

    # Mapping : Clients + csv mappés, Prospects absent -> exclu.
    apply_res = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/mapping",
        json={
            "mapping": {
                clients_key: {"NOM": "NOM", "IBAN": "IBAN", "CP": "CP"},
                csv_key: {"NOM": "NOM", "IBAN": "IBAN", "CP": "CP"},
            },
            "sheet_keys": sheet_keys,
        },
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert apply_res.status_code == 200
    apply_body = apply_res.json()
    assert apply_body["n_rows_updated"] == 4  # 3 Clients + 1 csv
    assert apply_body["n_rows_excluded"] == 2  # Prospects
    assert apply_body["iban_columns_detected"] == ["IBAN"]
    assert apply_body["iban_warnings"][0]["column"] == "IBAN"
    assert apply_body["iban_warnings"][0]["n_invalid"] == 1  # Martin

    rows_after_mapping = fake.postgrest.tables["pipeline_rows"]
    assert len(rows_after_mapping) == 4
    assert {r["data"]["NOM"] for r in rows_after_mapping} == {"Dupont", "Martin", "Petit"}

    # Filtre multi-critères (onglet 3) : département 34 -> Dupont(x2, 34000) + Petit(34500), pas Martin(71000).
    groups = json.dumps([[{"column": "CP", "kind": "departements", "values": ["34"]}]])
    filtered = tc.get(
        f"/orgs/org-1/pipeline/sessions/{session_id}/rows",
        params={"groups": groups},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert filtered.status_code == 200
    filtered_body = filtered.json()
    assert filtered_body["count"] == 3
    assert {r["NOM"] for r in filtered_body["rows"]} == {"Dupont", "Petit"}

    # Dédoublonnage SCOPÉ au filtre actif (même groupe que ci-dessus) --
    # Dupont(x2) dans le filtre -> 1 doublon retiré ; Martin (hors filtre)
    # jamais touché même s'il n'a pas de doublon.
    dedupe_res = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/dedupe",
        json={"column": "NOM", "mode": "rule", "keep": "first",
              "groups": [[{"column": "CP", "kind": "departements", "values": ["34"]}]]},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert dedupe_res.status_code == 200
    dedupe_body = dedupe_res.json()
    assert dedupe_body["n_removed"] == 1
    assert dedupe_body["row_count"] == 3  # total session restant : Dupont, Martin, Petit

    # Export final -- format .xlsx cette fois (pas juste CSV).
    export_res = tc.get(
        f"/orgs/org-1/pipeline/sessions/{session_id}/export",
        params={"format": "xlsx"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert export_res.status_code == 200
    exported_wb = openpyxl.load_workbook(_io.BytesIO(export_res.content))
    exported_rows = list(exported_wb.active.iter_rows(values_only=True))
    header, data_rows = exported_rows[0], exported_rows[1:]
    nom_idx = header.index("NOM")
    assert {r[nom_idx] for r in data_rows} == {"Dupont", "Martin", "Petit"}
    assert len(data_rows) == 3


def test_pipeline_session_create_cleans_up_if_row_count_rpc_fails(client_factory, monkeypatch):
    """Trouvaille Copilot, PR #27 : si le RPC final adjust_pipeline_row_count
    échoue APRÈS que tous les lots aient bien été insérés, la session
    restait en base avec toutes ses lignes mais row_count à 0 et le
    statut 'importing' -- invisible jusqu'au TTL (24h). Nettoyée
    maintenant avant de renvoyer 500."""
    from api import main as api_main

    def _boom(*args, **kwargs):
        raise RuntimeError("panne réseau simulée sur le compteur final")

    monkeypatch.setattr(api_main, "adjust_pipeline_row_count", _boom)

    fake = _make_client()
    tc = client_factory(fake)
    res = tc.post(
        "/orgs/org-1/pipeline/sessions",
        files=[("files", ("clients.csv", b"NOM\nDupont\n", "text/csv"))],
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 500
    assert not any(
        r.get("source_filename") == "clients.csv" for r in fake.postgrest.tables["pipeline_sessions"]
    ), "la session ne doit pas rester visible avec row_count à 0 jusqu'au TTL"
    # Cascade réelle des lignes vers la session supprimée : garantie par la
    # contrainte FK (migration 0010), pas simulée dans ce faux client.


def test_pipeline_mapping_dry_run_samples_every_sheet_even_if_first_is_huge(client_factory, monkeypatch):
    """Trouvaille Copilot, PR #27 : le dry_run échantillonnait avec un
    LIMIT global sur toute la session (PIPELINE_SUGGESTION_ROW_CAP), pas
    par onglet -- si le 1er onglet à lui seul dépasse ce plafond, les
    onglets suivants n'apparaissaient JAMAIS dans `suggested_mapping`, et
    "Auto-assigner tous" les laissait sans aucune colonne assignée (donc
    exclus/supprimés à l'application réelle). Ici le plafond est réduit à
    3 lignes et le fichier "a" en a 5 -- sans le fix, "b" serait absent."""
    from api import main as api_main

    monkeypatch.setattr(api_main, "PIPELINE_SUGGESTION_ROW_CAP", 3)

    fake = _make_client()
    tc = client_factory(fake)
    content_a = b"NOM\n" + b"\n".join(f"A{i}".encode() for i in range(5)) + b"\n"
    content_b = b"NOM\nGarde\n"
    upload = tc.post(
        "/orgs/org-1/pipeline/sessions",
        files=[
            ("files", ("a.csv", content_a, "text/csv")),
            ("files", ("b.csv", content_b, "text/csv")),
        ],
        headers={"Authorization": f"Bearer {TOKEN}"},
    ).json()
    session_id = upload["session_id"]
    sheet_keys = [s["sheet_key"] for s in upload["sheets"]]

    res = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/mapping",
        json={"dry_run": True, "sheet_keys": sheet_keys},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    suggestion = res.json()["suggested_mapping"]
    assert set(suggestion.keys()) == set(sheet_keys)
    # Chaque onglet a bien reçu SA PROPRE colonne "NOM" -> "NOM".
    for sheet_key in sheet_keys:
        assert suggestion[sheet_key].get("NOM") == "NOM"


def test_pipeline_mapping_deletes_session_if_row_rewrite_fails_midway(client_factory, monkeypatch):
    """Trouvaille Copilot, PR #27 : la réservation atomique écrit déjà le
    statut 'mapped' AVANT de réécrire les lignes une par une. Si cette
    réécriture échoue en cours de route (panne réseau), la session
    restait sinon visible comme 'mapped' avec un staging à moitié
    transformé, et tout retry était rejeté en 409 sans espoir de
    réparation (merge_mapped_row retire `_sheet` des lignes déjà
    traitées). Elle doit être supprimée entièrement plutôt que laissée
    dans cet état."""
    from api import main as api_main

    def _boom(*args, **kwargs):
        raise RuntimeError("panne réseau simulée en cours de réécriture")

    monkeypatch.setattr(api_main, "update_pipeline_row_data", _boom)

    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_csv(tc, "org-1", b"NOM\nDupont\n").json()["session_id"]

    res = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/mapping",
        json={"mapping": {"clients": {"NOM": "NOM"}}},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 500
    assert not any(
        r["id"] == session_id for r in fake.postgrest.tables["pipeline_sessions"]
    ), "la session ne doit pas rester visible comme 'mapped' avec un staging à moitié réécrit"


def get_pipeline_session_via_api(tc, session_id):
    return tc.get(f"/orgs/org-1/pipeline/sessions/{session_id}", headers={"Authorization": f"Bearer {TOKEN}"}).json()


def test_pipeline_mapping_applies_suggestion_when_no_mapping_given(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_csv(tc, "org-1", b"NOM,IBAN\nDupont,FR7630006000011234567890189\n").json()["session_id"]

    res = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/mapping",
        json={},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    assert res.json()["mapping"] == {"clients": {"NOM": "NOM", "IBAN": "IBAN"}}
    rows = fake.postgrest.tables["pipeline_rows"]
    assert rows[0]["data"] == {"NOM": "Dupont", "IBAN": "FR7630006000011234567890189"}


def test_pipeline_mapping_all_unassigned_is_400(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_csv(tc, "org-1", b"colonneinconnue\nx\n").json()["session_id"]

    res = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/mapping",
        json={"mapping": {"clients": {"colonneinconnue": "(non assigne)"}}},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 400


def test_pipeline_mapping_sheet_absent_from_mapping_is_excluded(client_factory):
    """Un onglet ABSENT du mapping fourni (décoché côté écran, cf. [3] de
    la référence Streamlit) est exclu de la base fusionnée -- ses lignes
    de staging sont retirées, pas laissées à moitié mappées."""
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_csv(tc, "org-1", b"NOM,IBAN\nDupont,FR7630006000011234567890189\n").json()["session_id"]

    res = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/mapping",
        json={"mapping": {}},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 400  # aucune colonne assignée nulle part

    res = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/mapping",
        json={"mapping": {"clients": {"NOM": "NOM"}}},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["n_rows_updated"] == 1
    assert body["mapping"] == {"clients": {"NOM": "NOM"}}
    # "IBAN" n'a jamais été assigné (mapping ne le mentionne pas) : ne
    # doit pas apparaître dans la ligne finale.
    rows = fake.postgrest.tables["pipeline_rows"]
    assert rows[0]["data"] == {"NOM": "Dupont"}


def test_pipeline_mapping_two_sheets_have_independent_mappings(client_factory):
    """Deux onglets peuvent mapper des colonnes sources DIFFÉRENTES sur la
    MÊME colonne maître (ex. onglet A "Tél" -> TELEPHONE MOBILE, onglet B
    "Portable" -> TELEPHONE MOBILE) -- chaque onglet garde SON PROPRE
    mapping, jamais un mapping global fusionné pour toute la session."""
    fake = _make_client()
    tc = client_factory(fake)

    res = tc.post(
        "/orgs/org-1/pipeline/sessions",
        files=[
            ("files", ("a.csv", b"Tel\n0601020304\n", "text/csv")),
            ("files", ("b.csv", b"Portable\n0708091011\n", "text/csv")),
        ],
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    body = res.json()
    sheet_keys = [s["sheet_key"] for s in body["sheets"]]
    assert len(sheet_keys) == 2
    session_id = body["session_id"]

    key_a = next(k for k in sheet_keys if k.startswith("a.csv"))
    key_b = next(k for k in sheet_keys if k.startswith("b.csv"))

    res = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/mapping",
        json={"mapping": {
            key_a: {"Tel": "TELEPHONE MOBILE"},
            key_b: {"Portable": "TELEPHONE MOBILE"},
        }},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    assert res.json()["n_rows_updated"] == 2

    rows = fake.postgrest.tables["pipeline_rows"]
    values = {r["data"]["TELEPHONE MOBILE"] for r in rows}
    assert values == {"0601020304", "0708091011"}


def test_pipeline_mapping_cleans_iban_per_sheet(client_factory):
    """Nettoyage IBAN (espaces internes retirés) appliqué à CHAQUE onglet
    indépendamment, quel que soit son propre mapping."""
    fake = _make_client()
    tc = client_factory(fake)

    res = tc.post(
        "/orgs/org-1/pipeline/sessions",
        files=[
            ("files", ("a.csv", b"Ref\nFR76 3000 6000 0112 3456 7890 189\n", "text/csv")),
            ("files", ("b.csv", b"Compte\nFR76 3000 6000 0112 3456 7890 189\n", "text/csv")),
        ],
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    body = res.json()
    sheet_keys = [s["sheet_key"] for s in body["sheets"]]
    key_a = next(k for k in sheet_keys if k.startswith("a.csv"))
    key_b = next(k for k in sheet_keys if k.startswith("b.csv"))
    session_id = body["session_id"]

    res = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/mapping",
        json={"mapping": {
            key_a: {"Ref": "IBAN"},
            key_b: {"Compte": "IBAN"},
        }},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    rows = fake.postgrest.tables["pipeline_rows"]
    for r in rows:
        assert r["data"]["IBAN"] == "FR7630006000011234567890189"


def test_pipeline_mapping_unknown_session_is_404(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    res = tc.post(
        "/orgs/org-1/pipeline/sessions/does-not-exist/mapping",
        json={},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 404


def test_pipeline_requires_auth(client_factory):
    tc = client_factory(_make_client())
    res = tc.post("/orgs/org-1/pipeline/sessions", files={"files": ("a.csv", b"NOM\nX\n", "text/csv")})
    assert res.status_code == 401


# ---------------------------------------------------------------
# Pipeline : lignes filtrées + export (trieur_data.pipeline_rows, staging)
# ---------------------------------------------------------------

def _upload_pipeline_rows(tc, org_id, content: bytes):
    return _upload_csv(tc, org_id, content).json()["session_id"]


def test_pipeline_rows_filter_contient(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_pipeline_rows(
        tc, "org-1", b"NOM,VILLE\nDupont,Paris\nMartin,Lyon\n",
    )

    res = tc.get(
        f"/orgs/org-1/pipeline/sessions/{session_id}/rows",
        params={"col_filters": json.dumps({"VILLE": {"op": "contient", "value": "par"}})},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["row_count"] == 2
    assert body["count"] == 1
    assert [r["NOM"] for r in body["rows"]] == ["Dupont"]


def test_pipeline_rows_filter_egal_a(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_pipeline_rows(
        tc, "org-1", b"NOM,VILLE\nDupont,Paris\nMartin,Lyon\n",
    )

    res = tc.get(
        f"/orgs/org-1/pipeline/sessions/{session_id}/rows",
        params={"col_filters": json.dumps({"VILLE": {"op": "égal à", "value": "paris"}})},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.json()["count"] == 1


def test_pipeline_rows_filter_vide(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_pipeline_rows(
        tc, "org-1", b"NOM,SCORE\nDupont,\nMartin,5\n",
    )

    res = tc.get(
        f"/orgs/org-1/pipeline/sessions/{session_id}/rows",
        params={"col_filters": json.dumps({"SCORE": {"op": "vide", "value": ""}})},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert [r["NOM"] for r in res.json()["rows"]] == ["Dupont"]


def test_pipeline_rows_filter_non_vide_traite_zero_comme_une_vraie_valeur(client_factory):
    """Une valeur "fausse" (0) est une vraie valeur, pas une case vide --
    même règle que _matches_filter (views/tab_database.py), déjà couverte
    côté /records ; ce test vérifie qu'elle s'applique aussi au pipeline."""
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_pipeline_rows(
        tc, "org-1", b"NOM,SCORE\nDupont,0\nMartin,\n",
    )

    res = tc.get(
        f"/orgs/org-1/pipeline/sessions/{session_id}/rows",
        params={"col_filters": json.dumps({"SCORE": {"op": "non vide", "value": ""}})},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    body = res.json()
    assert body["count"] == 1
    assert body["rows"][0]["NOM"] == "Dupont"
    # Lu en dtype=str (trieur/io_excel.py:read_csv_file, garde les zéros
    # initiaux) : "0" reste la chaîne "0", falsy en Python mais une vraie
    # valeur pour _matches_filter (pas None/"").
    assert body["rows"][0]["SCORE"] == "0"


def test_pipeline_rows_search(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_pipeline_rows(
        tc, "org-1", b"NOM,VILLE\nDupont,Paris\nMartin,Lyon\n",
    )

    res = tc.get(
        f"/orgs/org-1/pipeline/sessions/{session_id}/rows",
        params={"search": "martin"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert [r["NOM"] for r in res.json()["rows"]] == ["Martin"]


def test_pipeline_rows_paginates_with_page_and_page_size(client_factory):
    """Revue PR #24, point #7 : avant, cette route renvoyait TOUTE la
    session en une réponse -- vérifie qu'elle est maintenant vraiment
    paginée (page/page_size), comme GET /orgs/{org_id}/records."""
    fake = _make_client()
    tc = client_factory(fake)
    content = b"NOM\n" + b"\n".join(f"row{i}".encode() for i in range(5)) + b"\n"
    session_id = _upload_pipeline_rows(tc, "org-1", content)

    res = tc.get(
        f"/orgs/org-1/pipeline/sessions/{session_id}/rows",
        params={"page": 1, "page_size": 2},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    body = res.json()
    assert body["page"] == 1
    assert body["page_size"] == 2
    # `count`/`row_count` restent les totaux réels (pas la taille de la
    # page renvoyée) -- l'écran doit pouvoir afficher "2/5" correctement.
    assert body["row_count"] == 5
    assert body["count"] == 5
    assert [r["NOM"] for r in body["rows"]] == ["row0", "row1"]

    res2 = tc.get(
        f"/orgs/org-1/pipeline/sessions/{session_id}/rows",
        params={"page": 3, "page_size": 2},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert [r["NOM"] for r in res2.json()["rows"]] == ["row4"]


def test_pipeline_rows_pagination_applies_after_filtering(client_factory):
    """La pagination découpe le résultat FILTRÉ, pas la table brute --
    sinon une page pourrait rater des lignes qui matchent le filtre mais
    sont situées après la page brute demandée."""
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_pipeline_rows(
        tc, "org-1", b"NOM,VILLE\nA,Paris\nB,Lyon\nC,Paris\nD,Lyon\nE,Paris\n",
    )

    res = tc.get(
        f"/orgs/org-1/pipeline/sessions/{session_id}/rows",
        params={
            "page": 2,
            "page_size": 2,
            "col_filters": json.dumps({"VILLE": {"op": "égal à", "value": "paris"}}),
        },
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    body = res.json()
    assert body["count"] == 3
    assert [r["NOM"] for r in body["rows"]] == ["E"]


def test_pipeline_rows_wrong_org_is_404(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_pipeline_rows(tc, "org-1", b"NOM\nDupont\n")
    fake.postgrest.tables["pipeline_sessions"][0]["org_id"] = "org-2"

    res = tc.get(
        f"/orgs/org-1/pipeline/sessions/{session_id}/rows",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 404


def test_pipeline_export_csv_content_type_and_content(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_pipeline_rows(
        tc, "org-1", b"NOM,VILLE\nDupont,Paris\nMartin,Lyon\n",
    )

    res = tc.get(
        f"/orgs/org-1/pipeline/sessions/{session_id}/export",
        params={"format": "csv"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    body = res.content.decode("utf-8-sig")
    assert "Dupont" in body
    assert "Martin" in body


def test_pipeline_export_xlsx_content_type(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_pipeline_rows(tc, "org-1", b"NOM\nDupont\n")

    res = tc.get(
        f"/orgs/org-1/pipeline/sessions/{session_id}/export",
        params={"format": "xlsx"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    assert res.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert len(res.content) > 0


def test_pipeline_export_respects_filters(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_pipeline_rows(
        tc, "org-1", b"NOM,VILLE\nDupont,Paris\nMartin,Lyon\n",
    )

    unfiltered = tc.get(
        f"/orgs/org-1/pipeline/sessions/{session_id}/export",
        params={"format": "csv"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    filtered = tc.get(
        f"/orgs/org-1/pipeline/sessions/{session_id}/export",
        params={"format": "csv", "search": "dupont"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    n_unfiltered = len(unfiltered.content.decode("utf-8-sig").splitlines())
    n_filtered = len(filtered.content.decode("utf-8-sig").splitlines())
    assert n_filtered < n_unfiltered


def test_pipeline_export_columns_reorders_and_filters_selection(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_pipeline_rows(
        tc, "org-1", b"NOM,VILLE,EMAIL\nDupont,Paris,d@x.com\n",
    )

    res = tc.get(
        f"/orgs/org-1/pipeline/sessions/{session_id}/export",
        params={"format": "csv", "columns": "EMAIL,NOM"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    body = res.content.decode("utf-8-sig")
    header = body.splitlines()[0]
    # Ordre demandé respecté, VILLE (absente de `columns`) exclue.
    assert header == "EMAIL,NOM"


def test_pipeline_export_columns_ignores_unknown_column_silently(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_pipeline_rows(tc, "org-1", b"NOM\nDupont\n")

    res = tc.get(
        f"/orgs/org-1/pipeline/sessions/{session_id}/export",
        params={"format": "csv", "columns": "NOM,COLONNE_INCONNUE"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    header = res.content.decode("utf-8-sig").splitlines()[0]
    assert header == "NOM"


def test_pipeline_export_wrong_org_is_404(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_pipeline_rows(tc, "org-1", b"NOM\nDupont\n")
    fake.postgrest.tables["pipeline_sessions"][0]["org_id"] = "org-2"

    res = tc.get(
        f"/orgs/org-1/pipeline/sessions/{session_id}/export",
        params={"format": "csv"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 404


# ---------------------------------------------------------------
# Pipeline : mapping fidèle (première valeur non vide, Source Data,
# IBAN) -- voir api/pipeline_mapping.py, règles portées de
# views/tab2_import_mapping.py.
# ---------------------------------------------------------------

def test_pipeline_mapping_first_non_empty_value_wins_on_collision(client_factory):
    """Deux colonnes source vers la même colonne maître : la PREMIÈRE
    valeur non vide gagne (jamais "la dernière écrase") -- même règle
    que views/tab2_import_mapping.py, cf api/pipeline_mapping.py."""
    fake = _make_client(
        organizations=[{"id": "org-1", "slug": "leads", "name": "Leads", "master_columns": ["NOM", "TELEPHONE MOBILE"]}],
    )
    tc = client_factory(fake)
    session_id = _upload_csv(tc, "org-1", b"nom,tel1,tel2\nDupont,,0601020304\n").json()["session_id"]

    res = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/mapping",
        json={"mapping": {"clients": {"nom": "NOM", "tel1": "TELEPHONE MOBILE", "tel2": "TELEPHONE MOBILE"}}},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    rows = fake.postgrest.tables["pipeline_rows"]
    assert rows[0]["data"] == {"NOM": "Dupont", "TELEPHONE MOBILE": "0601020304"}


def test_pipeline_mapping_sets_source_data_automatically(client_factory):
    fake = _make_client(
        organizations=[{"id": "org-1", "slug": "leads", "name": "Leads", "master_columns": ["NOM", "Source Data"]}],
    )
    tc = client_factory(fake)
    session_id = _upload_csv(tc, "org-1", b"nom\nDupont\n", filename="clients.csv").json()["session_id"]

    res = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/mapping",
        json={"mapping": {"clients": {"nom": "NOM"}}},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    rows = fake.postgrest.tables["pipeline_rows"]
    assert rows[0]["data"]["Source Data"] == "clients.csv (clients)"


def test_pipeline_mapping_cleans_iban_spaces_and_reports_invalid_checksum(client_factory):
    fake = _make_client()  # master_columns = ["NOM", "IBAN"]
    tc = client_factory(fake)
    session_id = _upload_csv(
        tc, "org-1", b"NOM,IBAN\nDupont,FR76 3000 6000 0112 3456 7890 189\nMartin,FR0000000000000000000000000\n",
    ).json()["session_id"]

    res = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/mapping",
        json={"mapping": {"clients": {"NOM": "NOM", "IBAN": "IBAN"}}},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["iban_columns_detected"] == ["IBAN"]
    assert len(body["iban_warnings"]) == 1
    assert body["iban_warnings"][0]["column"] == "IBAN"
    assert body["iban_warnings"][0]["n_invalid"] == 1
    assert len(body["iban_warnings"][0]["sample_row_ids"]) == 1

    rows = {r["data"]["NOM"]: r["data"]["IBAN"] for r in fake.postgrest.tables["pipeline_rows"]}
    # Espaces internes retirés, checksum FR7630006000011234567890189 valide.
    assert rows["Dupont"] == "FR7630006000011234567890189"
    assert rows["Martin"] == "FR0000000000000000000000000"


def test_pipeline_mapping_detects_iban_column_with_generic_name_beyond_preview_size(client_factory):
    """Trouvaille Copilot PR #25 (#3, sévérité moyenne) : la détection
    IBAN par CONTENU ne scannait avant que PIPELINE_PREVIEW_SIZE (10)
    lignes -- une colonne au nom générique ("Compte") dont les vraies
    valeurs IBAN commencent après la ligne 10 n'était jamais détectée.
    Ici : 10 lignes de "bruit" (pas des IBAN) suivies de 45 lignes IBAN
    valides (espaces internes) -- 45/55 = 81,8% de la session ressemble à
    un IBAN, largement au-dessus du seuil de detect_iban_column (80%),
    mais 0% des 10 premières lignes. Doit quand même être détectée et
    nettoyée sur TOUTE la session, pas seulement l'aperçu."""
    fake = _make_client(
        organizations=[{"id": "org-1", "slug": "leads", "name": "Leads", "master_columns": ["NOM", "Compte"]}],
    )
    tc = client_factory(fake)

    lines = ["NOM,Compte"]
    for i in range(10):
        lines.append(f"Bruit{i},valeur-non-iban-{i}")
    for i in range(45):
        lines.append(f"Client{i},FR76 3000 6000 0112 3456 7890 189")
    content = ("\n".join(lines) + "\n").encode()

    session_id = _upload_csv(tc, "org-1", content).json()["session_id"]
    res = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/mapping",
        json={"mapping": {"clients": {"NOM": "NOM", "Compte": "Compte"}}},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["iban_columns_detected"] == ["Compte"]

    rows = {r["data"]["NOM"]: r["data"]["Compte"] for r in fake.postgrest.tables["pipeline_rows"]}
    # Espaces internes retirés sur une ligne bien après la 10e -- preuve
    # que le nettoyage/la détection a bien porté sur toute la session.
    assert rows["Client44"] == "FR7630006000011234567890189"


# ---------------------------------------------------------------
# Pipeline : filtre multi-critères groupes OU / critères ET (`groups`,
# format EXACT de trieur/filters.py:apply_filter_groups) -- le "cœur
# métier" de l'onglet 3, absent de l'API avant ce portage.
# ---------------------------------------------------------------

def test_pipeline_rows_groups_filter_departements_and_or(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_pipeline_rows(
        tc, "org-1",
        b"NOM,CP,VILLE\nA,34000,Montpellier\nB,71000,Lyon\nC,71000,Macon\nD,75001,Paris\n",
    )
    groups = [
        [{"column": "CP", "kind": "departements", "values": ["34"]}],
        [
            {"column": "CP", "kind": "departements", "values": ["71"]},
            {"column": "VILLE", "kind": "valeurs", "values": ["Lyon"]},
        ],
    ]
    res = tc.get(
        f"/orgs/org-1/pipeline/sessions/{session_id}/rows",
        params={"groups": json.dumps(groups)},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert {r["NOM"] for r in body["rows"]} == {"A", "B"}
    assert body["count"] == 2


def test_pipeline_rows_invalid_groups_json_is_400(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_pipeline_rows(tc, "org-1", b"NOM\nDupont\n")
    res = tc.get(
        f"/orgs/org-1/pipeline/sessions/{session_id}/rows",
        params={"groups": "not-json"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 400


def test_pipeline_rows_malformed_groups_structure_is_400_not_500(client_factory):
    """Trouvaille Copilot PR #25 (#1, sévérité haute) : un `groups` dont
    la structure ne respecte pas le format attendu (ex: un GROUPE envoyé
    comme un objet au lieu d'une liste de critères) atteignait
    apply_filter_groups (trieur/filters.py) et y faisait planter
    `c.get(...)` (AttributeError sur un str) -- 500 au lieu d'une 400
    propre. Le cas ["column":"CP"] à la place de [[{"column":"CP",...}]]."""
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_pipeline_rows(tc, "org-1", b"NOM,CP\nA,34000\n")

    # Un groupe qui est un objet (dict) au lieu d'une liste de critères.
    res = tc.get(
        f"/orgs/org-1/pipeline/sessions/{session_id}/rows",
        params={"groups": json.dumps([{"column": "CP"}])},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 400

    # Un critère qui n'est pas un objet.
    res = tc.get(
        f"/orgs/org-1/pipeline/sessions/{session_id}/rows",
        params={"groups": json.dumps([["CP"]])},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 400

    # `values` d'un mauvais type (pas une liste).
    res = tc.get(
        f"/orgs/org-1/pipeline/sessions/{session_id}/rows",
        params={"groups": json.dumps([[{"column": "CP", "kind": "departements", "values": "34"}]])},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 400

    # `kind` hors des valeurs attendues.
    res = tc.get(
        f"/orgs/org-1/pipeline/sessions/{session_id}/rows",
        params={"groups": json.dumps([[{"column": "CP", "kind": "n_importe_quoi", "values": ["34"]}]])},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 400


def test_pipeline_rows_incomplete_group_is_still_ignored_gracefully(client_factory):
    """Un groupe/critère juste INCOMPLET (colonne ou valeurs pas encore
    choisies côté écran, ex: `values: []`) n'est PAS une erreur -- même
    comportement documenté par trieur/filters.py:apply_filter_groups
    (ignoré, pas de filtre actif), la validation ne doit pas le rejeter."""
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_pipeline_rows(tc, "org-1", b"NOM,CP\nA,34000\nB,75001\n")

    res = tc.get(
        f"/orgs/org-1/pipeline/sessions/{session_id}/rows",
        params={"groups": json.dumps([[{"column": "CP", "kind": "departements", "values": []}]])},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    assert res.json()["count"] == 2


def test_pipeline_dedupe_malformed_groups_body_is_400(client_factory):
    """Même validation côté POST .../dedupe (body.groups, pas la query
    string `groups` des GET) -- même structure malformée, même 400."""
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_pipeline_rows(tc, "org-1", b"NOM,EMAIL\nDupont,x@y.com\n")

    res = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/dedupe",
        json={"column": "EMAIL", "mode": "rule", "keep": "first", "groups": [{"column": "CP"}]},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 400


def test_pipeline_export_groups_filter(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_pipeline_rows(tc, "org-1", b"NOM,CP\nA,34000\nB,75001\n")
    groups = [[{"column": "CP", "kind": "departements", "values": ["34"]}]]

    res = tc.get(
        f"/orgs/org-1/pipeline/sessions/{session_id}/export",
        params={"format": "csv", "groups": json.dumps(groups)},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    content = res.content.decode("utf-8-sig")
    assert "A" in content
    assert "B" not in content


# ---------------------------------------------------------------
# Pipeline : détection et suppression de doublons (onglet 3, le "cœur
# métier" -- trieur/filters.py, porté via api/pipeline_engine.py).
# ---------------------------------------------------------------

def test_pipeline_duplicates_detects_groups_and_suggests_most_complete(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_pipeline_rows(
        tc, "org-1", b"NOM,EMAIL\nDupont,x@y.com\n,x@y.com\nMartin,z@y.com\n",
    )

    res = tc.get(
        f"/orgs/org-1/pipeline/sessions/{session_id}/duplicates",
        params={"column": "EMAIL"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["group_count"] == 1
    assert body["duplicate_row_count"] == 2
    assert body["group_threshold"] == 50
    group = body["groups"][0]
    assert group["value"] == "x@y.com"
    assert len(group["row_ids"]) == 2
    assert group["suggested_keep_id"] in group["row_ids"]


def test_pipeline_duplicates_no_duplicates_is_empty(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_pipeline_rows(tc, "org-1", b"NOM,EMAIL\nDupont,x@y.com\nMartin,z@y.com\n")

    res = tc.get(
        f"/orgs/org-1/pipeline/sessions/{session_id}/duplicates",
        params={"column": "EMAIL"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.json()["groups"] == []


def test_pipeline_dedupe_rule_first_removes_all_but_the_first_per_value(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_pipeline_rows(
        tc, "org-1", b"NOM,EMAIL\nDupont,x@y.com\nDupont2,x@y.com\nMartin,z@y.com\n",
    )

    res = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/dedupe",
        json={"column": "EMAIL", "mode": "rule", "keep": "first"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["n_removed"] == 1
    assert body["row_count"] == 2

    remaining = fake.postgrest.tables["pipeline_rows"]
    assert len(remaining) == 2
    assert [r["data"]["NOM"] for r in remaining] == ["Dupont", "Martin"]


def test_pipeline_dedupe_concurrent_call_on_same_session_is_409_not_a_race(client_factory):
    """Migration 0013 (revue Copilot, PR #25) : un dédoublonnage déjà en
    cours sur une session doit rejeter un 2e appel plutôt que de laisser
    deux requêtes analyser le même groupe et supprimer chacune la ligne
    que l'autre voulait garder. Simule la concurrence en posant le verrou
    manuellement avant l'appel HTTP, comme le ferait une 1re requête
    encore en cours."""
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_pipeline_rows(
        tc, "org-1", b"NOM,EMAIL\nDupont,x@y.com\nDupont2,x@y.com\nMartin,z@y.com\n",
    )
    session = next(r for r in fake.postgrest.tables["pipeline_sessions"] if r["id"] == session_id)
    session["dedupe_lock_at"] = datetime.now(timezone.utc)

    res = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/dedupe",
        json={"column": "EMAIL", "mode": "rule", "keep": "first"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 409
    remaining = fake.postgrest.tables["pipeline_rows"]
    assert len(remaining) == 3, "rien ne doit être supprimé quand le verrou est déjà pris"


def test_pipeline_dedupe_releases_lock_after_success_so_a_later_call_works(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_pipeline_rows(
        tc, "org-1", b"NOM,EMAIL\nDupont,x@y.com\nDupont2,x@y.com\nMartin,z@y.com\n",
    )
    first = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/dedupe",
        json={"column": "EMAIL", "mode": "rule", "keep": "first"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert first.status_code == 200

    second = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/dedupe",
        json={"column": "NOM", "mode": "rule", "keep": "first"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert second.status_code == 200, "le verrou doit être libéré après un appel réussi"


def test_pipeline_dedupe_expired_owner_cannot_unlock_a_newer_owner(client_factory):
    """Migration 0014 (revue Copilot sur la migration 0013 elle-même) :
    sans jeton propriétaire, une requête qui dépasse la TTL et perd la
    propriété du verrou pourrait, dans son `finally`, libérer sans le
    savoir le verrou posé entre-temps par une requête plus récente."""
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_pipeline_rows(
        tc, "org-1", b"NOM,EMAIL\nDupont,x@y.com\nMartin,z@y.com\n",
    )
    session = next(r for r in fake.postgrest.tables["pipeline_sessions"] if r["id"] == session_id)

    # Simule une 1re requête dont le verrou vient d'expirer (owner "stale"),
    # et une 2e requête qui vient de réclamer le verrou juste après.
    session["dedupe_lock_at"] = datetime.now(timezone.utc)
    session["dedupe_lock_owner"] = "owner-recent"

    # La 1re requête (propriétaire périmé) tente de libérer son propre jeton,
    # qui n'est plus celui posé en base : ça ne doit RIEN changer.
    fake.postgrest.rpc(
        "unlock_pipeline_dedupe", {"p_session_id": session_id, "p_owner": "owner-stale"},
    ).execute()

    assert session["dedupe_lock_owner"] == "owner-recent", (
        "un propriétaire périmé ne doit jamais pouvoir libérer le verrou d'un propriétaire plus récent"
    )

    # Un 3e appel HTTP doit donc toujours recevoir 409 : le verrou tenu par
    # "owner-recent" est toujours actif.
    third = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/dedupe",
        json={"column": "EMAIL", "mode": "rule", "keep": "first"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert third.status_code == 409


def test_pipeline_dedupe_lock_stolen_mid_operation_deletes_nothing(client_factory, monkeypatch):
    """Migration 0015 (revue Copilot sur la migration 0014 elle-même) :
    le jeton propriétaire empêche une requête périmée de libérer le
    verrou d'une requête plus récente, mais ne protège pas à lui seul
    l'opération entière. Simule un calcul de dédoublonnage si long qu'un
    autre appel reprend le verrou (TTL dépassée) AVANT le DELETE :
    l'appel en cours doit détecter qu'il n'est plus propriétaire à la
    revérification et abandonner sans rien supprimer."""
    from api import main as api_main

    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_pipeline_rows(
        tc, "org-1", b"NOM,EMAIL\nDupont,x@y.com\nDupont2,x@y.com\nMartin,z@y.com\n",
    )

    real_dedupe_rule = api_main.pipeline_engine.dedupe_rule

    def _steal_lock_then_dedupe(*args, **kwargs):
        # Simule une autre requête qui réclame le verrou pendant que
        # celle-ci calcule encore -- la TTL a expiré entretemps côté réel,
        # ici on le simule directement en changeant le propriétaire.
        session = next(
            r for r in fake.postgrest.tables["pipeline_sessions"] if r["id"] == session_id
        )
        session["dedupe_lock_owner"] = "owner-du-nouvel-appel"
        return real_dedupe_rule(*args, **kwargs)

    monkeypatch.setattr(api_main.pipeline_engine, "dedupe_rule", _steal_lock_then_dedupe)

    res = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/dedupe",
        json={"column": "EMAIL", "mode": "rule", "keep": "first"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 409
    remaining = fake.postgrest.tables["pipeline_rows"]
    assert len(remaining) == 3, "rien ne doit être supprimé si le verrou a changé de propriétaire entretemps"


def test_pipeline_dedupe_rule_complete_keeps_fullest_row(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_pipeline_rows(
        tc, "org-1", b"NOM,EMAIL,VILLE\nDupont,x@y.com,\nDupontComplet,x@y.com,Paris\n",
    )

    res = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/dedupe",
        json={"column": "EMAIL", "mode": "rule", "keep": "complete"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    remaining = fake.postgrest.tables["pipeline_rows"]
    assert [r["data"]["NOM"] for r in remaining] == ["DupontComplet"]


def test_pipeline_dedupe_manual_keeps_chosen_row_per_group(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_pipeline_rows(
        tc, "org-1", b"NOM,EMAIL\nDupont,x@y.com\nDupont2,x@y.com\n",
    )
    analysis = tc.get(
        f"/orgs/org-1/pipeline/sessions/{session_id}/duplicates",
        params={"column": "EMAIL"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    ).json()
    keep_id = analysis["groups"][0]["row_ids"][1]

    res = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/dedupe",
        json={"column": "EMAIL", "mode": "manual", "keep_ids": [keep_id]},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    assert res.json()["n_removed"] == 1
    remaining = fake.postgrest.tables["pipeline_rows"]
    assert len(remaining) == 1
    assert remaining[0]["id"] == keep_id


def test_pipeline_dedupe_manual_without_keep_ids_is_400(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_pipeline_rows(tc, "org-1", b"NOM,EMAIL\nDupont,x@y.com\nDupont2,x@y.com\n")

    res = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/dedupe",
        json={"column": "EMAIL", "mode": "manual", "keep_ids": []},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 400


def test_pipeline_dedupe_manual_group_uncovered_by_keep_ids_is_400_and_deletes_nothing(client_factory):
    """Trouvaille Copilot PR #25 (#2, sévérité haute) : si un groupe de
    doublons de l'analyse filtrée actuelle n'a AUCUN id dans `keep_ids`
    (analyse périmée, sélection incomplète côté écran), l'ancien code
    laissait dedupe_dataframe_manual ne garder AUCUNE ligne de ce groupe
    -- perte de données. Ici, 2 groupes de doublons (EMAIL) mais
    `keep_ids` ne couvre que le 1er : la requête doit être rejetée en
    400 et RIEN ne doit être supprimé (les 4 lignes doivent toutes
    encore être là après)."""
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_pipeline_rows(
        tc, "org-1",
        b"NOM,EMAIL\nDupont,x@y.com\nDupont2,x@y.com\nMartin,z@y.com\nMartin2,z@y.com\n",
    )
    analysis = tc.get(
        f"/orgs/org-1/pipeline/sessions/{session_id}/duplicates",
        params={"column": "EMAIL"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    ).json()
    assert analysis["group_count"] == 2
    # Ne couvre que le groupe x@y.com, pas z@y.com.
    covered_group = next(g for g in analysis["groups"] if g["value"] == "x@y.com")
    keep_id = covered_group["row_ids"][0]

    res = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/dedupe",
        json={"column": "EMAIL", "mode": "manual", "keep_ids": [keep_id]},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 400
    remaining = fake.postgrest.tables["pipeline_rows"]
    assert len(remaining) == 4  # rien supprimé


def test_pipeline_dedupe_manual_keep_id_from_wrong_group_is_400(client_factory):
    """`keep_ids` contient un id qui n'appartient à AUCUN groupe de
    doublons (ex: id d'une ligne unique, ou d'une autre session) : rejeté
    aussi, plutôt que silencieusement ignoré."""
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_pipeline_rows(
        tc, "org-1", b"NOM,EMAIL\nDupont,x@y.com\nDupont2,x@y.com\nSeul,unique@y.com\n",
    )
    rows = fake.postgrest.tables["pipeline_rows"]
    unique_row_id = next(r["id"] for r in rows if r["data"]["EMAIL"] == "unique@y.com")

    res = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/dedupe",
        json={"column": "EMAIL", "mode": "manual", "keep_ids": [unique_row_id]},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 400
    assert len(fake.postgrest.tables["pipeline_rows"]) == 3


def test_pipeline_dedupe_invalid_mode_is_400(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_pipeline_rows(tc, "org-1", b"NOM,EMAIL\nDupont,x@y.com\n")

    res = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/dedupe",
        json={"column": "EMAIL", "mode": "n_importe_quoi"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 400


def test_pipeline_dedupe_respects_active_filter_scope(client_factory):
    """Comme l'onglet 3 (dedup appliqué sur `filtered_df`, jamais sur les
    lignes déjà exclues par le filtre) : une ligne hors du filtre actif
    n'est jamais supprimée, même si elle ferait doublon."""
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_pipeline_rows(
        tc, "org-1", b"NOM,EMAIL,VILLE\nA,x@y.com,Paris\nB,x@y.com,Lyon\n",
    )
    groups = [[{"column": "VILLE", "kind": "valeurs", "values": ["Paris"]}]]

    res = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/dedupe",
        json={"column": "EMAIL", "mode": "rule", "keep": "first", "groups": groups},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    assert res.json()["n_removed"] == 0
    assert len(fake.postgrest.tables["pipeline_rows"]) == 2


def test_pipeline_duplicates_wrong_org_is_404(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_pipeline_rows(tc, "org-1", b"NOM,EMAIL\nDupont,x@y.com\n")
    fake.postgrest.tables["pipeline_sessions"][0]["org_id"] = "org-2"

    res = tc.get(
        f"/orgs/org-1/pipeline/sessions/{session_id}/duplicates",
        params={"column": "EMAIL"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 404


# ---------------------------------------------------------------
# Pipeline : import PDF (relevés SEPA, trieur/io_pdf.py) -- routage
# vérifié via monkeypatch (pas de vrai PDF de test disponible, voir
# tests/test_sepa.py pour la logique d'extraction elle-même).
# ---------------------------------------------------------------

def test_parse_pipeline_file_routes_pdf_to_sepa_reader(monkeypatch):
    import pandas as pd

    from api import main as api_main

    called = {}

    def _fake_read_pdf_sepa(file_obj, filename):
        called["filename"] = filename
        return {"PDF": pd.DataFrame([{"Montant": 41.66}])}, []

    monkeypatch.setattr(api_main, "read_pdf_sepa", _fake_read_pdf_sepa)
    sheets = api_main._parse_pipeline_file("releve.pdf", b"contenu-pdf-quelconque")

    assert called["filename"] == "releve.pdf"
    assert list(sheets.keys()) == ["PDF"]


# ---------------------------------------------------------------
# Jeux de colonnes maîtres personnels (compte, /me/column-sets*)
# ---------------------------------------------------------------

def test_column_sets_empty_by_default(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    res = tc.get("/me/column-sets", headers={"Authorization": f"Bearer {TOKEN}"})
    assert res.status_code == 200
    assert res.json()["sets"] == []


def test_column_set_save_then_list(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    res = tc.post(
        "/me/column-sets",
        json={"name": "Prélèvement", "columns": ["NOM", "IBAN"]},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    saved = res.json()
    assert saved["name"] == "Prélèvement"
    assert saved["columns"] == ["NOM", "IBAN"]

    listed = tc.get("/me/column-sets", headers={"Authorization": f"Bearer {TOKEN}"})
    assert [s["name"] for s in listed.json()["sets"]] == ["Prélèvement"]

    # Enregistrer marque aussi ce jeu actif -- /me le renvoie tout de suite.
    me = tc.get("/me", headers={"Authorization": f"Bearer {TOKEN}"})
    assert me.json()["profile"]["active_master_column_set_id"] == saved["id"]


def test_column_set_save_empty_name_is_400(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    res = tc.post(
        "/me/column-sets",
        json={"name": "   ", "columns": ["NOM"]},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 400


def test_column_set_save_empty_columns_is_400(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    res = tc.post(
        "/me/column-sets",
        json={"name": "Vide", "columns": []},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 400


def test_column_set_save_same_name_replaces(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    tc.post(
        "/me/column-sets",
        json={"name": "Vue A", "columns": ["NOM"]},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    tc.post(
        "/me/column-sets",
        json={"name": "Vue A", "columns": ["NOM", "VILLE"]},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    listed = tc.get("/me/column-sets", headers={"Authorization": f"Bearer {TOKEN}"})
    sets = listed.json()["sets"]
    assert len(sets) == 1
    assert sets[0]["columns"] == ["NOM", "VILLE"]


def test_column_set_apply_marks_active_and_returns_columns(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    saved = tc.post(
        "/me/column-sets",
        json={"name": "Vue A", "columns": ["NOM"]},
        headers={"Authorization": f"Bearer {TOKEN}"},
    ).json()
    tc.post(
        "/me/column-sets",
        json={"name": "Vue B", "columns": ["VILLE"]},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    res = tc.post(
        f"/me/column-sets/{saved['id']}/apply",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    assert res.json()["columns"] == ["NOM"]

    me = tc.get("/me", headers={"Authorization": f"Bearer {TOKEN}"})
    assert me.json()["profile"]["active_master_column_set_id"] == saved["id"]


def test_column_set_apply_unknown_id_is_404(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    res = tc.post(
        "/me/column-sets/does-not-exist/apply",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 404


def test_column_set_delete(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    saved = tc.post(
        "/me/column-sets",
        json={"name": "Vue A", "columns": ["NOM"]},
        headers={"Authorization": f"Bearer {TOKEN}"},
    ).json()

    res = tc.delete(
        f"/me/column-sets/{saved['id']}",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    assert res.json() == {"id": saved["id"], "deleted": True}

    listed = tc.get("/me/column-sets", headers={"Authorization": f"Bearer {TOKEN}"})
    assert listed.json()["sets"] == []


def test_column_set_delete_someone_elses_is_404(client_factory):
    other_user = SimpleNamespace(id="user-2", email="bob@example.com")
    fake = _make_client(
        user_master_column_sets=[
            {"id": "set-1", "user_id": "user-2", "name": "Vue B", "columns": ["VILLE"]},
        ],
    )
    fake.auth.users_by_token["other-token"] = other_user
    tc = client_factory(fake)

    res = tc.delete(
        "/me/column-sets/set-1",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 404


def test_column_sets_require_auth(client_factory):
    tc = client_factory(_make_client())
    res = tc.get("/me/column-sets")
    assert res.status_code == 401
