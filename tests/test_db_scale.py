"""Garde-fous d'échelle (chantier cockpit 6547bd6a) : recherche, filtres et
export calculés par la base, parcours par curseur, migration 0034 sûre."""
import re
from pathlib import Path
from types import SimpleNamespace

from trieur.db import (
    COLUMNS_NOT_FILTERABLE_IN_DB,
    count_matching_records,
    iter_records_filtered,
    search_records,
    split_db_filters,
)

MIGRATION = Path(__file__).resolve().parent.parent / "supabase" / "migrations" / "0034_records_echelle.sql"


class _FakeRpcClient:
    """Faux client : `rpc("search_records", params)` sur une liste de lignes
    triées (created_at desc, id desc), avec un plafond serveur par page."""

    def __init__(self, n_rows, server_cap=None):
        self.rows = [
            {"id": f"id-{i:06d}", "data": {"n": i}, "created_at": f"2026-01-01T00:00:00.{i:06d}Z"}
            for i in range(n_rows, 0, -1)
        ]
        self.server_cap = server_cap
        self.calls = []

    @property
    def postgrest(self):
        return self

    def schema(self, _):
        return self

    def rpc(self, name, params):
        assert name == "search_records"
        self.calls.append(params)

        def _execute():
            rows = self.rows
            if params.get("p_after_id") is not None:
                key = (params["p_after_created"], params["p_after_id"])
                rows = [r for r in rows if (r["created_at"], r["id"]) < key]
            else:
                rows = rows[params["p_offset"]:]
            limit = min(params["p_limit"], self.server_cap or params["p_limit"])
            page = rows[:limit]
            total = len(self.rows) if params.get("p_with_total") else None
            return SimpleNamespace(data=[
                {**r, "updated_at": None, "updated_by": None, "source_filename": "f.csv",
                 "imported_at": "2026-01-01", "tags": "", "total": total}
                for r in page
            ])

        return SimpleNamespace(execute=_execute)


def test_search_records_returns_list_records_shape_and_total():
    c = _FakeRpcClient(5)
    rows, total = search_records(c, "org", "dup", {"v": {"op": "contient", "value": "x"}}, limit=3, with_total=True)
    assert total == 5 and len(rows) == 3
    assert rows[0]["import_batches"] == {"source_filename": "f.csv", "imported_at": "2026-01-01"}
    p = c.calls[0]
    assert p["p_search"] == "dup" and p["p_filters"] == {"v": {"op": "contient", "value": "x"}}
    assert "p_after_id" not in p  # pas de curseur sur la première page


def test_iter_records_filtered_walks_everything_by_cursor_even_with_server_cap():
    """Plafond serveur (max_rows) plus petit que la page demandée : le parcours
    avance de ce qui est RÉELLEMENT reçu et ne saute ni ne duplique aucune ligne."""
    c = _FakeRpcClient(2500, server_cap=1000)
    got = [r["id"] for r in iter_records_filtered(c, "org", page_size=5000)]
    assert len(got) == 2500 and len(set(got)) == 2500
    assert all("p_offset" in p and p["p_offset"] == 0 for p in c.calls)  # jamais d'offset profond
    assert len(c.calls) == 4  # 1000 + 1000 + 500 + page vide


def test_iter_records_filtered_empty():
    assert list(iter_records_filtered(_FakeRpcClient(0), "org")) == []


def test_count_matching_records():
    assert count_matching_records(_FakeRpcClient(7), "org") == 7
    assert count_matching_records(_FakeRpcClient(0), "org") == 0


def test_split_db_filters_keeps_modifier_name_for_python():
    f = {"Ville": {"op": "contient", "value": "a"}, "Modifié par": {"op": "égal à", "value": "x"}}
    in_db, in_py = split_db_filters(f)
    assert list(in_db) == ["Ville"] and list(in_py) == ["Modifié par"]
    assert split_db_filters(None) == ({}, {})
    assert "Modifié par" in COLUMNS_NOT_FILTERABLE_IN_DB


def test_migration_0034_only_adds():
    """La migration s'applique à la vraie base : elle ne doit rien supprimer ni
    modifier, et rester rejouable (idempotente)."""
    sql = MIGRATION.read_text(encoding="utf-8")
    code = re.sub(r"--[^\n]*", "", sql).lower()
    for forbidden in (r"\bdrop\b", r"\bdelete\b", r"\btruncate\b", r"\bupdate\b", r"alter table"):
        assert not re.search(forbidden, code), forbidden
    assert code.count("create index") == code.count("create index if not exists")
    assert "create or replace function" in code and "create function" not in code.replace("create or replace function", "")
    # fonctions security definer : l'appartenance à l'environnement est vérifiée
    # explicitement (jamais d'accès sans contrôle) et l'accès public est retiré
    assert code.count("security definer") == code.count("is_org_member(p_org_id)")
    assert code.count("revoke all on function") == code.count("security definer")
    assert "set search_path" in code
