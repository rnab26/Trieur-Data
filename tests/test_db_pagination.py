"""Teste trieur.db.list_all_records() : doit toujours ramener TOUTE la
table, jamais tronquer -- même si le serveur limite silencieusement une
page à moins que ce qui a été demandé (simulé ici en imposant un plafond
au faux client, indépendant du `page_size` passé par l'appelant)."""
from types import SimpleNamespace

from trieur.db import list_all_records


class _FakeRecordsTable:
    """Reproduit juste assez de l'API postgrest pour list_records/
    count_records : select(count=...).eq(...).order(...).limit(...)
    .offset(...).execute()."""

    def __init__(self, all_rows, server_cap):
        self._all_rows = all_rows
        self._server_cap = server_cap
        self._org_id = None
        self._limit = None
        self._offset = 0
        self._count_mode = None

    def select(self, *_args, count=None):
        self._count_mode = count
        return self

    def eq(self, _field, value):
        self._org_id = value
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def offset(self, n):
        self._offset = n
        return self

    def execute(self):
        matched = [r for r in self._all_rows if r["org_id"] == self._org_id]
        if self._count_mode == "exact":
            return SimpleNamespace(data=matched[:1], count=len(matched))
        # Le "plafond serveur" s'applique quel que soit le limit demande --
        # c'est exactement le cas qu'on veut couvrir : une limite serveur
        # plus petite que page_size ne doit jamais tronquer le resultat.
        effective_limit = min(self._limit or len(matched), self._server_cap)
        page = matched[self._offset: self._offset + effective_limit]
        return SimpleNamespace(data=page, count=None)


class _FakePostgrest:
    def __init__(self, table):
        self._table = table

    def schema(self, _name):
        return self

    def table(self, _name):
        return self._table


class _FakeClient:
    def __init__(self, all_rows, server_cap):
        self.postgrest = _FakePostgrest(_FakeRecordsTable(all_rows, server_cap))


def _make_rows(org_id, n):
    return [{"id": f"{org_id}-{i}", "org_id": org_id, "data": {}} for i in range(n)]


def test_list_all_records_returns_everything_in_one_server_capped_page():
    """Plafond serveur (50) plus petit que page_size (300) : sans la
    correction (avancer de len(page) plutot que de page_size), la
    premiere page de 50 lignes (< 300 demandees) aurait ete prise pour la
    derniere et le reste silencieusement perdu."""
    rows = _make_rows("org-1", 137)
    client = _FakeClient(rows, server_cap=50)

    result = list_all_records(client, "org-1", page_size=300)

    assert len(result) == 137
    assert {r["id"] for r in result} == {r["id"] for r in rows}


def test_list_all_records_multiple_pages_no_duplicate_no_missing():
    rows = _make_rows("org-1", 725)
    client = _FakeClient(rows, server_cap=300)

    result = list_all_records(client, "org-1", page_size=300)

    ids = [r["id"] for r in result]
    assert len(ids) == 725
    assert len(set(ids)) == 725  # aucun doublon


def test_list_all_records_respects_org_id_and_empty_org():
    rows = _make_rows("org-1", 10) + _make_rows("org-2", 5)
    client = _FakeClient(rows, server_cap=300)

    assert len(list_all_records(client, "org-1")) == 10
    assert len(list_all_records(client, "org-2")) == 5
    assert list_all_records(client, "org-empty") == []
