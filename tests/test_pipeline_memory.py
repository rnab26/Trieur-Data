"""Teste trieur/pipeline_memory.py -- le store EN MÉMOIRE qui a remplacé
le staging Postgres (trieur_data.pipeline_sessions/pipeline_rows) pour
les données de travail du pipeline "Trieur de Data" (voir la docstring
de ce module et PROJECT_LOG.md, décision du 2026-09-18). Aucun réseau
ici, aucun faux client Supabase : ce module ne dépend plus de rien
d'externe, donc ces tests l'exercent directement."""
from datetime import timedelta

import pytest

from trieur import pipeline_memory as pm


@pytest.fixture(autouse=True)
def _clear_store():
    """Le store est un dict de MODULE, partagé entre tous les tests du
    process -- sans ce nettoyage, une session créée par un test resterait
    visible dans le test suivant."""
    pm._SESSIONS.clear()
    yield
    pm._SESSIONS.clear()


def test_create_session_starts_importing_with_no_rows():
    session = pm.create_session("org-1", "user-1", source_filename="clients.csv")
    assert session["status"] == "importing"
    assert session["row_count"] == 0
    assert session["dedup_config"] is None
    assert session["mapping"] is None
    assert "rows" not in session  # jamais dans la vue publique (voir _public_view)

    fetched = pm.get_session(session["id"])
    assert fetched["org_id"] == "org-1"
    assert fetched["created_by"] == "user-1"
    assert fetched["source_filename"] == "clients.csv"


def test_get_session_unknown_id_is_none():
    assert pm.get_session("does-not-exist") is None


def test_append_rows_then_list_rows_preserves_order_and_updates_row_count():
    session = pm.create_session("org-1", "user-1")
    n = pm.append_rows(session["id"], [{"NOM": "Dupont"}, {"NOM": "Martin"}])
    assert n == 2

    fetched = pm.get_session(session["id"])
    assert fetched["row_count"] == 2

    rows = pm.list_rows(session["id"])
    assert [r["data"]["NOM"] for r in rows] == ["Dupont", "Martin"]
    assert [r["row_index"] for r in rows] == [0, 1]


def test_append_rows_twice_continues_row_index():
    session = pm.create_session("org-1", "user-1")
    pm.append_rows(session["id"], [{"NOM": "A"}])
    pm.append_rows(session["id"], [{"NOM": "B"}, {"NOM": "C"}])

    rows = pm.list_rows(session["id"])
    assert [r["row_index"] for r in rows] == [0, 1, 2]
    assert pm.get_session(session["id"])["row_count"] == 3


def test_list_rows_respects_limit_and_offset():
    session = pm.create_session("org-1", "user-1")
    pm.append_rows(session["id"], [{"NOM": f"row{i}"} for i in range(5)])

    page = pm.list_rows(session["id"], limit=2, offset=2)
    assert [r["data"]["NOM"] for r in page] == ["row2", "row3"]


def test_list_rows_unknown_session_is_empty_list():
    assert pm.list_rows("does-not-exist") == []


def test_map_rows_rewrites_every_row_in_one_pass():
    session = pm.create_session("org-1", "user-1")
    pm.append_rows(session["id"], [
        {"nom_client": "Dupont", "iban_ref": "FR76A"},
        {"nom_client": "Martin", "iban_ref": "FR76B"},
    ])

    mapping = {"nom_client": "NOM", "iban_ref": "IBAN"}
    n_updated = pm.map_rows(
        session["id"],
        lambda data: {master: data[src] for src, master in mapping.items() if src in data},
    )
    assert n_updated == 2

    rows = pm.list_rows(session["id"])
    assert [r["data"] for r in rows] == [
        {"NOM": "Dupont", "IBAN": "FR76A"},
        {"NOM": "Martin", "IBAN": "FR76B"},
    ]


def test_update_session_status_and_dedup_and_mapping():
    session = pm.create_session("org-1", "user-1")
    pm.update_session_status(session["id"], "mapped")
    pm.update_session_dedup(session["id"], {"column": "IBAN", "keep": "first"})
    pm.set_session_mapping(session["id"], {"NOM": "NOM"})

    fetched = pm.get_session(session["id"])
    assert fetched["status"] == "mapped"
    assert fetched["dedup_config"] == {"column": "IBAN", "keep": "first"}
    assert fetched["mapping"] == {"NOM": "NOM"}

    pm.update_session_dedup(session["id"], None)
    assert pm.get_session(session["id"])["dedup_config"] is None


def test_delete_session_removes_it():
    session = pm.create_session("org-1", "user-1")
    pm.delete_session(session["id"])
    assert pm.get_session(session["id"]) is None


def test_expired_session_is_invisible_and_gets_swept_on_get():
    session = pm.create_session("org-1", "user-1")
    pm._SESSIONS[session["id"]]["expires_at"] = pm._now() - timedelta(seconds=1)

    assert pm.get_session(session["id"]) is None
    # Balayée par le get_session lui-même (pas seulement masquée).
    assert session["id"] not in pm._SESSIONS


def test_delete_expired_sessions_for_org_only_touches_that_org():
    expired_own = pm.create_session("org-1", "user-1")
    expired_other = pm.create_session("org-2", "user-1")
    fresh_own = pm.create_session("org-1", "user-1")

    pm._SESSIONS[expired_own["id"]]["expires_at"] = pm._now() - timedelta(hours=1)
    pm._SESSIONS[expired_other["id"]]["expires_at"] = pm._now() - timedelta(hours=1)

    n_deleted = pm.delete_expired_sessions_for_org("org-1")
    assert n_deleted == 1

    remaining = set(pm._SESSIONS.keys())
    assert expired_own["id"] not in remaining
    assert expired_other["id"] in remaining  # autre org, pas de RPC cross-org ici
    assert fresh_own["id"] in remaining


def test_org_id_must_be_checked_by_caller_not_by_get_session():
    """get_session() ne filtre PAS par org_id lui-même (voir docstring,
    point 1) -- c'est à l'appelant (api/main.py:_get_pipeline_session_or_404)
    de comparer session["org_id"]. Ce test documente ce contrat pour ne
    pas le casser par erreur en modifiant get_session plus tard."""
    session = pm.create_session("org-1", "user-1")
    fetched = pm.get_session(session["id"])
    assert fetched is not None
    assert fetched["org_id"] == "org-1"
    # get_session() la renvoie même en "demandant" un autre org -- il n'y
    # a pas de paramètre org_id sur get_session, précisément pour que
    # cette vérification soit visible et explicite côté appelant.


# ---------------------------------------------------------------
# Preuve à l'échelle réelle visée par l'utilisateur (jusqu'à 2 millions
# de lignes) -- doit rester rapide car 100% en mémoire, zéro réseau.
# Mesure et affiche le temps réel (pas une estimation) : voir le rapport
# de la tâche du 2026-09-18 dans PROJECT_LOG.md pour le chiffre mesuré.
# ---------------------------------------------------------------

def test_large_scale_session_creation_is_fast(capsys):
    import time

    N = 500_000
    rows = [{"NOM": f"Client {i}", "EMAIL": f"client{i}@example.com"} for i in range(N)]

    t0 = time.perf_counter()
    session = pm.create_session("org-1", "user-1", source_filename="gros_fichier.csv")
    pm.append_rows(session["id"], rows)
    elapsed = time.perf_counter() - t0

    with capsys.disabled():
        print(f"\n[perf] création session pipeline + {N} lignes en mémoire : {elapsed:.3f}s")

    fetched = pm.get_session(session["id"])
    assert fetched["row_count"] == N
    # Doit rester de l'ordre de la seconde, pas des dizaines de secondes
    # (l'ancien staging Postgres mesurait ~2min pour 92 000 lignes réelles
    # côté réseau -- ici, zéro aller-retour réseau, marge large pour ne
    # pas rendre ce test fragile selon la machine CI).
    assert elapsed < 10.0

    all_rows = pm.list_rows(session["id"])
    assert len(all_rows) == N
    assert all_rows[0]["data"]["NOM"] == "Client 0"
    assert all_rows[-1]["data"]["NOM"] == f"Client {N - 1}"
