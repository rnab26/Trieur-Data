# =============================================================
# Adapte le moteur de filtrage/dédoublonnage déjà écrit dans
# trieur/filters.py -- même logique EXACTE que l'onglet 3 Streamlit
# (views/tab3_filtrage_dedup.py) -- à des lignes {id, data} issues du
# staging Postgres (trieur_data.pipeline_rows), au lieu d'un DataFrame
# en mémoire avec un index entier généré par pandas.
#
# Aucune règle métier n'est réécrite ici : chaque fonction se contente
# de construire un DataFrame indexé par id de ligne (le id Postgres
# jouant le rôle que l'index pandas jouait côté Streamlit), d'appeler
# la fonction trieur/filters.py correspondante telle quelle, puis de
# reconvertir le résultat en ids -- c'est le pont entre le "cœur
# métier" (pur, testé indépendamment dans tests/test_filters.py) et le
# stockage par ligne Postgres choisi pour l'API (voir docstring de
# supabase/migrations/0010_pipeline_staging.sql).
# =============================================================
from __future__ import annotations

import pandas as pd

from trieur.filters import (
    apply_filter_groups,
    dedupe_dataframe,
    dedupe_dataframe_manual,
    duplicate_groups,
    most_complete_row_index,
)


def rows_to_df(rows: list[dict]) -> pd.DataFrame:
    """`rows` : [{"id": ..., "data": {...}}, ...] -> DataFrame dont
    l'index est l'id de ligne (au lieu de l'index entier pandas côté
    Streamlit) -- permet de réutiliser trieur/filters.py sans y changer
    une seule ligne : ces fonctions ne font jamais d'hypothèse sur la
    NATURE de l'index, seulement sur le fait qu'il identifie une ligne
    de façon stable."""
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([r["data"] for r in rows])
    df.index = [r["id"] for r in rows]
    return df


def filter_rows(rows: list[dict], groups: list) -> list[dict]:
    """Filtre multi-critères (groupes combinés en OU, critères d'un même
    groupe combinés en ET) -- trieur/filters.py:apply_filter_groups,
    inchangé. Renvoie le sous-ensemble de `rows` qui passe le filtre,
    dans le même ordre."""
    if not rows:
        return []
    df = rows_to_df(rows)
    filtered = apply_filter_groups(df, groups or [])
    keep_ids = set(filtered.index)
    return [r for r in rows if r["id"] in keep_ids]


def duplicate_groups_for_rows(rows: list[dict], column: str) -> list[dict]:
    """Groupes de doublons sur `column`, avec la ligne suggérée à garder
    (la plus complète -- même pré-sélection que la revue manuelle de
    l'onglet 3) -- trieur/filters.py:duplicate_groups +
    most_complete_row_index, inchangés."""
    if not rows:
        return []
    df = rows_to_df(rows)
    groups = duplicate_groups(df, column)
    result = []
    for value, ids in groups:
        suggested = most_complete_row_index(df, ids)
        result.append({
            "value": None if pd.isna(value) else str(value),
            "row_ids": list(ids),
            "suggested_keep_id": suggested,
        })
    return result


def dedupe_rule(rows: list[dict], column: str, keep: str = "first") -> tuple[list[str], list[str]]:
    """Applique une règle globale à TOUS les groupes de doublons (garder
    la première ligne importée, ou la plus complète) --
    trieur/filters.py:dedupe_dataframe, inchangé. Renvoie
    (ids_conservés, ids_supprimés), dans l'ordre d'origine de `rows`."""
    if not rows:
        return [], []
    df = rows_to_df(rows)
    deduped = dedupe_dataframe(df, column, keep=keep)
    kept_ids = set(deduped.index)
    all_ids = [r["id"] for r in rows]
    return (
        [i for i in all_ids if i in kept_ids],
        [i for i in all_ids if i not in kept_ids],
    )


def dedupe_manual(rows: list[dict], column: str, keep_ids: list[str]) -> tuple[list[str], list[str]]:
    """Applique une sélection MANUELLE (un id choisi par groupe de
    doublons, cf revue groupe par groupe de l'onglet 3) --
    trieur/filters.py:dedupe_dataframe_manual, inchangé. Renvoie
    (ids_conservés, ids_supprimés)."""
    if not rows:
        return [], []
    df = rows_to_df(rows)
    deduped = dedupe_dataframe_manual(df, column, set(keep_ids))
    kept_ids = set(deduped.index)
    all_ids = [r["id"] for r in rows]
    return (
        [i for i in all_ids if i in kept_ids],
        [i for i in all_ids if i not in kept_ids],
    )
