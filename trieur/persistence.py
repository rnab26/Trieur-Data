"""Persistance des colonnes maitres dans un fichier JSON local.
Survit au rechargement de page ; reinitialise au redeploiement Cloud."""
import json
import os

from trieur.matching import DEFAULT_MASTER_COLUMNS


MASTER_CONFIG_PATH = "user_master_columns.json"

def load_master_columns():
    try:
        if os.path.exists(MASTER_CONFIG_PATH):
            with open(MASTER_CONFIG_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            cols = data.get("master_columns")
            if isinstance(cols, list) and cols:
                cleaned = [str(c).strip() for c in cols if str(c).strip()]
                if cleaned:
                    return cleaned
    except Exception:
        pass
    return DEFAULT_MASTER_COLUMNS.copy()

def save_master_columns(cols):
    try:
        with open(MASTER_CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump({"master_columns": cols}, fh, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


# -------------------------------------------------------------
# [5] FILTRES PRE-ENREGISTRES
# Chaque filtre = {"name", "column", "kind", "values"} ou :
#   kind = "departements" -> values = ["33", "77", ...] (prefixes CP)
#   kind = "valeurs"      -> values = ["Paris", "Lyon", ...]
# -------------------------------------------------------------
FILTERS_CONFIG_PATH = "saved_filters.json"


def _is_valid_filter(f):
    return bool(
        isinstance(f, dict)
        and isinstance(f.get("name"), str) and f["name"].strip()
        and isinstance(f.get("column"), str) and f["column"]
        and f.get("kind") in ("departements", "valeurs")
        and isinstance(f.get("values"), list)
    )


def load_saved_filters():
    """Charge la liste des filtres enregistres (liste vide si absente/invalide)."""
    try:
        if os.path.exists(FILTERS_CONFIG_PATH):
            with open(FILTERS_CONFIG_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                return [f for f in data if _is_valid_filter(f)]
    except Exception:
        pass
    return []


def save_saved_filters(filters):
    """Enregistre la liste des filtres. Retourne True si succes."""
    try:
        clean = [f for f in filters if _is_valid_filter(f)]
        with open(FILTERS_CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(clean, fh, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False
