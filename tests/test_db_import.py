"""Teste trieur.db.import_dataframe() avec un faux client Supabase (aucun
reseau) : c'est le chemin d'import UNIQUE partage par l'upload direct de
l'onglet Base de donnees et le bouton "Enregistrer dans la base de
donnees" de l'onglet Export -- un bug ici casse les deux."""
from types import SimpleNamespace

import pandas as pd

from trieur.db import import_dataframe


class _FakeTable:
    def __init__(self, store, name):
        self._store = store
        self._name = name
        self._payload = None

    def insert(self, payload):
        self._payload = dict(payload)
        return self

    def execute(self):
        rec = dict(self._payload)
        rec["id"] = f"{self._name}-{len(self._store[self._name])}"
        self._store[self._name].append(rec)
        return SimpleNamespace(data=[rec])


class _FakePostgrest:
    def __init__(self, store, iban_matcher):
        self._store = store
        self._iban_matcher = iban_matcher

    def schema(self, _name):
        return self

    def table(self, name):
        return _FakeTable(self._store, name)

    def rpc(self, name, params):
        assert name == "find_iban_matches"
        result = self._iban_matcher(params["p_org_id"], params["p_iban"])
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=result))


class _FakeClient:
    """Reproduit juste assez de l'API supabase-py pour import_dataframe :
    _td(client, table) -> client.postgrest.schema(...).table(...), et le
    rpc find_iban_matches. Le "matcher" simule la colonne generee
    iban_normalized (meme normalisation que supabase/migrations/0001)."""

    def __init__(self):
        self.store = {"import_batches": [], "records": [], "dedup_alerts": []}
        self.postgrest = _FakePostgrest(self.store, self._find_matches)

    @staticmethod
    def _normalize(iban):
        return iban.strip().upper().replace(" ", "")

    def _find_matches(self, org_id, iban):
        norm = self._normalize(iban)
        matches = []
        for rec in self.store["records"]:
            if rec.get("org_id") != org_id:
                continue
            rec_iban = (rec.get("data") or {}).get("iban")
            if rec_iban and self._normalize(str(rec_iban)) == norm:
                matches.append({
                    "record_id": rec["id"],
                    "source_filename": "precedent.csv",
                    "imported_at": "2026-01-01",
                })
        return matches


def test_iban_key_is_copied_from_the_chosen_column():
    """Bug reel corrige : la colonne generee iban_normalized lit la cle
    JSON fixe "iban" (minuscule), jamais le nom reel de la colonne choisie
    a l'import (ex: "IBAN")."""
    client = _FakeClient()
    df = pd.DataFrame([{"NOM": "Dupont", "IBAN": "FR76 1234 5678"}])

    import_dataframe(client, "org-1", "fichier.csv", "user-1", df, iban_col="IBAN")

    assert client.store["records"][0]["data"]["iban"] == "FR76 1234 5678"
    assert client.store["records"][0]["data"]["IBAN"] == "FR76 1234 5678"


def test_blank_cell_becomes_none_not_nan():
    """Une cellule vide devient NaN cote pandas -- vrai en booleen et non
    serialisable en JSON standard : doit devenir None avant insertion,
    sinon l'import plante sur la premiere colonne vide venue."""
    client = _FakeClient()
    df = pd.DataFrame([{"NOM": "Dupont", "IBAN": None}, {"NOM": "Martin", "IBAN": "FR76 0000"}])

    n_imported, n_alerts = import_dataframe(client, "org-1", "fichier.csv", "user-1", df, iban_col="IBAN")

    assert n_imported == 2
    assert n_alerts == 0
    first_row = client.store["records"][0]["data"]
    assert first_row["IBAN"] is None
    assert "iban" not in first_row  # pas de cle IBAN vide copiee


def test_duplicate_iban_across_two_imports_raises_an_alert():
    """Le meme IBAN revient dans un import ulterieur, sous un nom
    different -- doit creer une alerte au lieu d'etre importe en double
    silencieusement (coeur du besoin prelevement/SEPA)."""
    client = _FakeClient()

    first = pd.DataFrame([{"NOM": "Rachel Daniel", "IBAN": "FR76 1111 2222"}])
    import_dataframe(client, "org-1", "fichier1.csv", "user-1", first, iban_col="IBAN")

    second = pd.DataFrame([{"NOM": "Daniel Rachel", "IBAN": "fr76111122 22"}])
    n_imported, n_alerts = import_dataframe(client, "org-1", "fichier2.csv", "user-1", second, iban_col="IBAN")

    assert n_imported == 1
    assert n_alerts == 1
    assert len(client.store["dedup_alerts"]) == 1


def test_no_iban_column_selected_never_checks_or_flags():
    """iban_col=None (ex: fichier Leads, sans IBAN) : import normal, zero
    appel de detection de doublon, zero alerte."""
    client = _FakeClient()
    df = pd.DataFrame([{"NOM": "Dupont"}, {"NOM": "Martin"}])

    n_imported, n_alerts = import_dataframe(client, "org-1", "fichier.csv", "user-1", df, iban_col=None)

    assert n_imported == 2
    assert n_alerts == 0
    assert client.store["dedup_alerts"] == []


def test_on_progress_called_for_each_row_in_order():
    client = _FakeClient()
    df = pd.DataFrame([{"NOM": "A"}, {"NOM": "B"}, {"NOM": "C"}])
    seen = []

    import_dataframe(client, "org-1", "fichier.csv", "user-1", df, on_progress=lambda done, total: seen.append((done, total)))

    assert seen == [(1, 3), (2, 3), (3, 3)]
