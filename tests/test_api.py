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
    # Valeurs par défaut posées côté SQL (colonnes qu'un insert ne fournit
    # pas explicitement) -- sans ça, un insert sur ce faux client renverrait
    # une ligne incomplète par rapport à ce que Postgres renvoie réellement
    # (voir tests/test_db_pipeline.py, même besoin pour ces deux tables).
    _DEFAULTS = {
        "pipeline_sessions": {"status": "importing", "row_count": 0},
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


# ---------------------------------------------------------------
# Pipeline "Trieur de Data" : import + mapping (étape 1)
# ---------------------------------------------------------------

def _upload_csv(tc, org_id, content: bytes, filename="clients.csv"):
    return tc.post(
        f"/orgs/{org_id}/pipeline/sessions",
        files={"file": (filename, content, "text/csv")},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )


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
        files={"file": ("clients.xlsx", b"pas un vrai xlsx", "application/octet-stream")},
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
    assert body["suggested_mapping"] == {"NOM": "NOM", "IBAN": "IBAN"}

    # dry_run : rien n'est modifié en base.
    session = tc.get(f"/orgs/org-1/pipeline/sessions/{session_id}", headers={"Authorization": f"Bearer {TOKEN}"}).json()
    assert session["status"] == "importing"


def test_pipeline_mapping_apply_rekeys_rows_and_marks_mapped(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_csv(tc, "org-1", b"nom_client,iban_ref\nDupont,FR7630006000011234567890189\n").json()["session_id"]

    res = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/mapping",
        json={"mapping": {"nom_client": "NOM", "iban_ref": "IBAN"}},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "mapped"
    assert body["n_rows_updated"] == 1

    rows = fake.postgrest.tables["pipeline_rows"]
    assert rows[0]["data"] == {"NOM": "Dupont", "IBAN": "FR7630006000011234567890189"}

    session = get_pipeline_session_via_api(tc, session_id)
    assert session["status"] == "mapped"


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
    assert res.json()["mapping"] == {"NOM": "NOM", "IBAN": "IBAN"}
    rows = fake.postgrest.tables["pipeline_rows"]
    assert rows[0]["data"] == {"NOM": "Dupont", "IBAN": "FR7630006000011234567890189"}


def test_pipeline_mapping_all_unassigned_is_400(client_factory):
    fake = _make_client()
    tc = client_factory(fake)
    session_id = _upload_csv(tc, "org-1", b"colonneinconnue\nx\n").json()["session_id"]

    res = tc.post(
        f"/orgs/org-1/pipeline/sessions/{session_id}/mapping",
        json={"mapping": {"colonneinconnue": "(non assigne)"}},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert res.status_code == 400


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
    res = tc.post("/orgs/org-1/pipeline/sessions", files={"file": ("a.csv", b"NOM\nX\n", "text/csv")})
    assert res.status_code == 401
