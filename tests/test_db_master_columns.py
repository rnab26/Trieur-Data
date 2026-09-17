"""Teste trieur.db.add_org_master_columns() avec un faux client Supabase
(aucun réseau) : chemin unique partagé par l'upload direct (Base de
données) et le bouton "Enregistrer dans la base de données" (Export)
pour ajouter des colonnes détectées à l'import."""
from types import SimpleNamespace

from trieur.db import add_org_master_columns, get_org_master_columns


class _FakeOrgsTable:
    def __init__(self, orgs):
        self._orgs = orgs
        self._filter_id = None
        self._payload = None

    def select(self, *_args, **_kwargs):
        return self

    def update(self, payload):
        self._payload = dict(payload)
        return self

    def eq(self, _field, value):
        self._filter_id = value
        return self

    def limit(self, _n):
        return self

    def execute(self):
        org = next((o for o in self._orgs if o["id"] == self._filter_id), None)
        if self._payload is not None and org is not None:
            org.update(self._payload)
        return SimpleNamespace(data=[org] if org else [])


class _FakePostgrest:
    def __init__(self, orgs):
        self._orgs = orgs

    def schema(self, _name):
        return self

    def table(self, _name):
        return _FakeOrgsTable(self._orgs)


class _FakeClient:
    def __init__(self, orgs):
        self.orgs = orgs
        self.postgrest = _FakePostgrest(orgs)


def _fresh(org_id, master_columns):
    """Un client + un org_id distincts par test, et le cache de
    get_org_master_columns vidé au préalable -- ce cache est partagé au
    niveau du process de test (clé basée sur org_id, le client étant
    exclu de la clé par convention `_client`) : sans ce nettoyage, un
    org_id réutilisé entre tests renverrait la valeur d'un test
    précédent."""
    get_org_master_columns.clear()
    return _FakeClient([{"id": org_id, "master_columns": master_columns}])


def test_add_org_master_columns_appends_new_ones():
    client = _fresh("org-add-1", ["NOM"])
    add_org_master_columns(client, "org-add-1", ["IBAN", "EMAIL"])
    assert client.orgs[0]["master_columns"] == ["NOM", "IBAN", "EMAIL"]


def test_add_org_master_columns_never_duplicates_case_insensitive():
    client = _fresh("org-add-2", ["Email"])
    add_org_master_columns(client, "org-add-2", ["EMAIL", "Nouvelle"])
    assert client.orgs[0]["master_columns"] == ["Email", "Nouvelle"]


def test_add_org_master_columns_noop_when_nothing_new():
    client = _fresh("org-add-3", ["NOM", "IBAN"])
    add_org_master_columns(client, "org-add-3", ["nom", "iban"])
    assert client.orgs[0]["master_columns"] == ["NOM", "IBAN"]
