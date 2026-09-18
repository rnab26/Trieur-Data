"""Stockage EN MÉMOIRE (process API) des données de travail du pipeline
"Trieur de Data" (import -> mapping -> filtre/dedup -> export, onglets
1-4), remplaçant le staging Postgres (trieur_data.pipeline_sessions /
pipeline_rows, voir supabase/migrations/0010_pipeline_staging.sql et
suivantes) par un simple dict de module -- même modèle que
`st.session_state` dans l'app Streamlit d'origine (all_sheets/final_df/
filtered_df), qui ne touchait JAMAIS le réseau tant que l'utilisateur
n'avait pas validé l'import final vers `trieur_data.records`.

Pourquoi ce changement (2026-09-18, voir PROJECT_LOG.md -- "Migration
React", décision du même jour) : la version Postgres écrivait CHAQUE
ligne importée en base dès l'upload, avant tout mapping/confirmation --
un coût réseau que l'app Streamlit d'origine n'avait jamais eu. Sur un
fichier réel de 92 000 lignes, même après le correctif de perf des lots
en parallèle (append_pipeline_rows_bulk), ce coût réseau ne tient pas à
l'échelle visée par l'utilisateur (jusqu'à 2 millions de lignes). Ici :
zéro écriture réseau pour les données de travail du pipeline -- elles
vivent entièrement dans ce process, exactement comme avant.

Conséquences RÉELLES à connaître (documentées aussi dans PROJECT_LOG.md) :

1. SÉCURITÉ -- la RLS Postgres ne protège plus rien ici : ces données ne
   passent jamais par Supabase, donc aucune policy ne peut les isoler
   par organisation. `get_session(session_id, org_id)` ci-dessous est
   DÉSORMAIS LA SEULE protection contre l'accès cross-org (même principe
   que l'ancien `api/main.py:_get_pipeline_session_or_404`, mais avant
   ce changement une policy RLS existait aussi en secours côté Postgres
   -- ici il n'y a plus de secours du tout). Tout code qui accède à une
   session DOIT passer par cette fonction avec le bon `org_id`, jamais
   par un accès direct à `_SESSIONS`.

2. PERTE AU REDÉMARRAGE -- ce dict vit dans la mémoire du process
   uvicorn : un déploiement, un crash ou un simple restart le vide
   entièrement, pour toutes les sessions de pipeline en cours, quel que
   soit l'org. Ce n'est PAS une régression : `st.session_state` avait
   très exactement la même limite avant (perdu à chaque redémarrage du
   serveur Streamlit). Mais ça veut dire que cette API ne peut PAS
   tourner en plusieurs instances derrière un load-balancer sans un
   store partagé (Redis, etc.) -- une session créée sur l'instance A
   serait invisible sur l'instance B. Sans objet sur l'hébergement actuel
   (une seule instance Render) ; limite réelle à lever si l'app doit un
   jour scaler horizontalement.

3. CONCURRENCE -- FastAPI/uvicorn peut exécuter plusieurs requêtes en
   parallèle sur le même worker (les endpoints sync de api/main.py sont
   passés dans le thread pool de Starlette). `_LOCK` protège chaque
   mutation de ce dict ; les lectures passent aussi par le lock (juste
   des lookups/slices de listes déjà construites, jamais une copie
   profonde de millions de lignes).

Tables Postgres devenues inutilisées par ce changement (voir rapport de
la tâche du 2026-09-18 dans PROJECT_LOG.md) : trieur_data.pipeline_sessions
et trieur_data.pipeline_rows (migrations 0010/0011/0012) -- gardées
volontairement en base (aucune suppression destructrice ici), les
fonctions trieur/db.py correspondantes (create_pipeline_session,
get_pipeline_session, append_pipeline_rows(_bulk), list_pipeline_rows,
update_pipeline_row_data, update_pipeline_session_status/dedup,
delete_pipeline_session, delete_expired_pipeline_sessions_for_org) aussi
-- ce sont maintenant du code mort côté API, à une décision humaine de
les retirer ou non.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable

PIPELINE_TTL_HOURS = 24

# Un seul verrou pour tout le module : les mutations sont rapides (pas
# d'I/O réseau) donc le contenir large ne coûte rien de mesurable, et ça
# évite tout risque d'oubli de verrouillage sur un futur ajout.
_LOCK = threading.Lock()
_SESSIONS: dict[str, dict] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_expired(session: dict, now: datetime) -> bool:
    return session["expires_at"] < now


def _public_view(session: dict) -> dict:
    """Copie superficielle de la session SANS la clé "rows" (peut
    contenir jusqu'à plusieurs millions d'entrées) -- l'appelant qui a
    besoin des lignes passe explicitement par `list_rows`/`map_rows`
    ci-dessous, jamais par cette vue."""
    return {k: v for k, v in session.items() if k != "rows"}


def create_session(org_id: str, created_by: str, source_filename: str | None = None) -> dict:
    """Ouvre une nouvelle session de pipeline -- statut initial
    'importing', TTL 24h (même durée que la migration 0010 qu'elle
    remplace). `rows` commence vide, rempli ensuite par `append_rows` ;
    aucune écriture réseau ici, contrairement à l'ancien
    `trieur.db.create_pipeline_session`."""
    now = _now()
    session_id = str(uuid.uuid4())
    session = {
        "id": session_id,
        "org_id": org_id,
        "created_by": created_by,
        "created_at": now,
        "expires_at": now + timedelta(hours=PIPELINE_TTL_HOURS),
        "source_filename": source_filename,
        "status": "importing",
        "row_count": 0,
        "dedup_config": None,
        "mapping": None,
        "rows": [],
    }
    with _LOCK:
        _SESSIONS[session_id] = session
    return _public_view(session)


def get_session(session_id: str) -> dict | None:
    """Session (SANS la clé "rows", voir `_public_view`) si elle existe
    et n'est pas expirée -- sinon `None`, jamais une erreur (même
    contrat que l'ancien `trieur.db.get_pipeline_session`). Ne vérifie
    PAS `org_id` ici : c'est à l'appelant de comparer `session["org_id"]`
    lui-même (voir api/main.py:_get_pipeline_session_or_404) -- même
    séparation des responsabilités qu'avant ce changement, seule la
    source de vérité change."""
    with _LOCK:
        session = _SESSIONS.get(session_id)
        if session is None:
            return None
        if _is_expired(session, _now()):
            del _SESSIONS[session_id]
            return None
        return _public_view(session)


def delete_session(session_id: str) -> None:
    with _LOCK:
        _SESSIONS.pop(session_id, None)


def delete_expired_sessions_for_org(org_id: str) -> int:
    """Purge les sessions EXPIRÉES de cet org seulement -- même
    nettoyage opportuniste (appelé au début de la création d'une
    nouvelle session, voir api/main.py) que l'ancien
    `trieur.db.delete_expired_pipeline_sessions_for_org`, mais en
    mémoire : une session d'un AUTRE org n'est jamais touchée ici."""
    now = _now()
    with _LOCK:
        expired_ids = [
            sid for sid, s in _SESSIONS.items()
            if s["org_id"] == org_id and _is_expired(s, now)
        ]
        for sid in expired_ids:
            del _SESSIONS[sid]
        return len(expired_ids)


def update_session_status(session_id: str, status: str) -> None:
    with _LOCK:
        session = _SESSIONS.get(session_id)
        if session is not None:
            session["status"] = status


def update_session_dedup(session_id: str, dedup_config: dict | None) -> None:
    with _LOCK:
        session = _SESSIONS.get(session_id)
        if session is not None:
            session["dedup_config"] = dedup_config


def set_session_mapping(session_id: str, mapping: dict) -> None:
    """Mémorise le mapping CONFIRMÉ (pas juste suggéré) sur la session
    elle-même -- purement informatif pour l'écran (l'auto-assignation
    "mémorisée par forme de fichier", elle, reste en base via
    trieur/db.py:save_remembered_mapping_for_shape, seule source de
    vérité pour la RÉUTILISATION au prochain import -- volontairement
    pas dupliquée ici)."""
    with _LOCK:
        session = _SESSIONS.get(session_id)
        if session is not None:
            session["mapping"] = mapping


def append_rows(session_id: str, rows: list[dict]) -> int:
    """Ajoute des lignes à la session (fin de liste, `row_index` =
    position dans le fichier source) -- aucun aller-retour réseau,
    contrairement à l'ancien `trieur.db.append_pipeline_rows_bulk` : plus
    besoin du lot/parallélisme qui compensait la latence Postgres."""
    if not rows:
        return 0
    with _LOCK:
        session = _SESSIONS.get(session_id)
        if session is None:
            return 0
        start = len(session["rows"])
        session["rows"].extend(
            {"id": f"{session_id}:{start + i}", "row_index": start + i, "data": row}
            for i, row in enumerate(rows)
        )
        session["row_count"] = len(session["rows"])
        return len(rows)


def list_rows(session_id: str, limit: int | None = None, offset: int = 0) -> list[dict]:
    """Lignes de la session, dans l'ordre du fichier importé
    (`row_index`) -- `limit=None` renvoie tout (remplace l'ancienne
    boucle de pagination `_all_pipeline_rows`, devenue inutile : plus de
    coût réseau à amortir en chargeant tout d'un coup en mémoire)."""
    with _LOCK:
        session = _SESSIONS.get(session_id)
        if session is None:
            return []
        rows = session["rows"]
        if limit is None:
            return rows[offset:]
        return rows[offset:offset + limit]


def map_rows(session_id: str, transform: Callable[[dict], dict]) -> int:
    """Réécrit CHAQUE ligne de la session avec `transform(data) ->
    new_data` (le mapping colonnes source -> colonnes maîtres, voir
    api/main.py:apply_pipeline_mapping) en UN SEUL passage O(n) -- pas un
    appel par ligne comme l'ancien `update_pipeline_row_data` (qui
    coûtait un aller-retour réseau par ligne ; ici tout est déjà en
    mémoire donc un seul passage suffit, plus rapide ET plus simple).
    Renvoie le nombre de lignes réécrites."""
    with _LOCK:
        session = _SESSIONS.get(session_id)
        if session is None:
            return 0
        rows = session["rows"]
        for row in rows:
            row["data"] = transform(row["data"])
        return len(rows)
