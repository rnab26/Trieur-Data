"""Teste api/main.py avec un faux client Supabase (aucun réseau) --
même esprit que tests/test_db_saved_views.py, injecté via
app.dependency_overrides plutôt qu'en remplaçant trieur.db lui-même :
les endpoints appellent les VRAIES fonctions de trieur/db.py, avec un
faux client Supabase en entrée."""
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.main import app, get_supabase_client


# ---------------------------------------------------------------
# Faux client Supabase générique : couvre juste assez de l'API
# postgrest (schema().table().select()/insert()/update()/upsert()/
# delete().eq()/in_()/order()/limit()/offset().execute()) et de l'API
# auth (get_user) pour que les fonctions de trieur/db.py utilisées par
# api/main.py fonctionnent sans réseau.
# ---------------------------------------------------------------

class _FakeTable:
    def __init__(self, store):
        self.store = store
        self._filters = []
        self._select_count = None
        self._order = None
        self._limit = None
        self._offset = 0
        self._op = None
        self._payload = None
        self._on_conflict = None

    def select(self, *_a, count=None):
        self._select_count = count
        return self

    def eq(self, field, value):
        self._filters.append((field, value))
        return self

    def in_(self, field, values):
        self._filters.append((field, ("in", set(values))))
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

    def _matches(self, row):
        for field, value in self._filters:
            if isinstance(value, tuple) and value[0] == "in":
                if row.get(field) not in value[1]:
                    return False
            elif row.get(field) != value:
                return False
        return True

    def execute(self):
        if self._op == "insert":
            row = dict(self._payload)
            row.setdefault("id", f"row-{len(self.store)}")
            self.store.append(row)
            return SimpleNamespace(data=[row], count=None)
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
        return _FakeTable(self.tables.setdefault(name, []))

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
    from trieur.db import get_my_memberships, get_my_profile, get_org_master_columns, list_saved_views

    get_my_profile.clear()
    get_my_memberships.clear()
    get_org_master_columns.clear()
    list_saved_views.clear()
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
