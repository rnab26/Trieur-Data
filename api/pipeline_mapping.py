# =============================================================
# Applique un mapping colonnes source -> colonnes maîtres à UNE ligne de
# staging, avec les mêmes règles que views/tab2_import_mapping.py
# (bouton "Construire la base de travail fusionnée") :
#   - si plusieurs colonnes source pointent vers la même colonne
#     maître, la PREMIÈRE valeur non vide gagne, les colonnes
#     suivantes ne comblent que les cases encore vides (jamais
#     "la dernière écrase les autres") ;
#   - "Source Data" est toujours renseignée automatiquement (fichier +
#     onglet d'origine), jamais mappée depuis une colonne source ;
#   - les colonnes IBAN détectées (nom OU contenu -- trieur/matching.py)
#     ont leurs espaces internes retirés (clean_iban).
# Logique pure, testable sans base de données -- le pont avec le
# staging Postgres (trieur_data.pipeline_rows) reste dans api/main.py.
# =============================================================
from __future__ import annotations

import pandas as pd

from trieur.matching import clean_iban, detect_iban_column, is_iban_master


def _is_empty(value) -> bool:
    """Même notion de "case vide" que trieur/filters.py:_non_empty_mask,
    étendue à une valeur Python simple (pas forcément issue d'un
    DataFrame) : None, NaN, ou chaîne ne contenant que des espaces."""
    if value is None:
        return True
    if isinstance(value, float) and value != value:  # NaN
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def merge_mapped_row(
    src_data: dict,
    mapping: dict[str, str],
    master_columns: list[str],
    source_label: str | None,
    iban_masters: set[str],
) -> dict:
    """Construit la ligne mappée (clés = colonnes maîtres) depuis une
    ligne source `src_data` (déjà sans la clé technique "_sheet")."""
    new_data: dict = {}
    for src, master in mapping.items():
        if not master or master == "(non assigne)" or master == "Source Data":
            continue
        if src not in src_data:
            continue
        val = src_data[src]
        if master not in new_data or _is_empty(new_data[master]):
            new_data[master] = val

    if "Source Data" in master_columns and source_label:
        new_data["Source Data"] = source_label

    for master in iban_masters:
        if master in new_data:
            new_data[master] = clean_iban(new_data[master])

    return new_data


def detect_iban_master_columns(mapped_sample_rows: list[dict], master_columns: list[str]) -> set[str]:
    """Colonnes maîtres à traiter comme des IBAN : soit par le SENS de
    leur nom (is_iban_master), soit par la FORME de leur contenu sur un
    échantillon déjà mappé (detect_iban_column) -- même détection à
    deux niveaux que views/tab2_import_mapping.py, pour repérer une
    colonne maître renommée ("Référence", "Compte"...) que le nom seul
    raterait."""
    iban_masters = {m for m in master_columns if is_iban_master(m)}
    if not mapped_sample_rows:
        return iban_masters
    df = pd.DataFrame(mapped_sample_rows)
    for master in master_columns:
        if master in iban_masters or master not in df.columns:
            continue
        if detect_iban_column(df[master]):
            iban_masters.add(master)
    return iban_masters
