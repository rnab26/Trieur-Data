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
# [5][13] FILTRES PRE-ENREGISTRES (multi-criteres depuis [13])
# Chaque filtre = {"name", "groups": [[critere, ...], ...]} ou :
#   - les criteres d'un meme groupe (liste interne) sont combines en ET
#   - les groupes entre eux (liste externe) sont combines en OU
#   - un critere = {"column", "kind", "values"} avec :
#       kind = "departements" -> values = ["33", "77", ...] (prefixes CP)
#       kind = "valeurs"      -> values = ["Paris", "Lyon", ...]
# -------------------------------------------------------------
FILTERS_CONFIG_PATH = "saved_filters.json"


def _is_valid_criterion(c):
    return bool(
        isinstance(c, dict)
        and isinstance(c.get("column"), str) and c["column"]
        and c.get("kind") in ("departements", "valeurs")
        and isinstance(c.get("values"), list)
    )


def _is_valid_filter(f):
    if not (isinstance(f, dict) and isinstance(f.get("name"), str) and f["name"].strip()):
        return False
    groups = f.get("groups")
    if not isinstance(groups, list) or not groups:
        return False
    return all(
        isinstance(g, list) and g and all(_is_valid_criterion(c) for c in g)
        for g in groups
    )


def _migrate_filter(f):
    """Convertit un filtre de l'ANCIEN format {name,column,kind,values}
    (avant le multi-criteres) vers le nouveau format {name, groups:[[...]]}
    -- un groupe unique avec un seul critere -- pour que les filtres deja
    enregistres continuent de fonctionner sans rien perdre."""
    if isinstance(f, dict) and "groups" not in f and "column" in f:
        return {
            "name": f.get("name"),
            "groups": [[{
                "column": f.get("column"),
                "kind": f.get("kind"),
                "values": f.get("values"),
            }]],
        }
    return f


def load_saved_filters():
    """Charge la liste des filtres enregistres (liste vide si absente/invalide)."""
    try:
        if os.path.exists(FILTERS_CONFIG_PATH):
            with open(FILTERS_CONFIG_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                migrated = [_migrate_filter(f) for f in data]
                return [f for f in migrated if _is_valid_filter(f)]
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


# -------------------------------------------------------------
# [11] PRESETS D'EXPORT (ordre + selection des colonnes)
# Chaque preset = {"name", "included": [...], "excluded": [...]}
# -------------------------------------------------------------
EXPORT_PRESETS_PATH = "export_presets.json"


def _is_valid_export_preset(p):
    return bool(
        isinstance(p, dict)
        and isinstance(p.get("name"), str) and p["name"].strip()
        and isinstance(p.get("included"), list)
        and isinstance(p.get("excluded"), list)
    )


def load_export_presets():
    """Charge la liste des presets d'export (liste vide si absente/invalide)."""
    try:
        if os.path.exists(EXPORT_PRESETS_PATH):
            with open(EXPORT_PRESETS_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                return [p for p in data if _is_valid_export_preset(p)]
    except Exception:
        pass
    return []


def save_export_presets(presets):
    """Enregistre la liste des presets d'export. Retourne True si succes."""
    try:
        clean = [p for p in presets if _is_valid_export_preset(p)]
        with open(EXPORT_PRESETS_PATH, "w", encoding="utf-8") as fh:
            json.dump(clean, fh, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


# -------------------------------------------------------------
# [12] MEMOIRE DU MAPPING PAR FORME DE FICHIER
# {empreinte_colonnes: {nom_colonne_source_normalise: colonne_maitre}}
# -------------------------------------------------------------
REMEMBERED_MAPPINGS_PATH = "remembered_mappings.json"


def load_remembered_mappings():
    """Charge les mappings memorises par forme de fichier (dict vide si absent/invalide)."""
    try:
        if os.path.exists(REMEMBERED_MAPPINGS_PATH):
            with open(REMEMBERED_MAPPINGS_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                return {
                    fp: mapping for fp, mapping in data.items()
                    if isinstance(fp, str) and isinstance(mapping, dict)
                }
    except Exception:
        pass
    return {}


def save_remembered_mappings(mappings):
    """Enregistre les mappings memorises par forme de fichier. Retourne True si succes."""
    try:
        clean = {
            fp: mapping for fp, mapping in mappings.items()
            if isinstance(fp, str) and isinstance(mapping, dict)
        }
        with open(REMEMBERED_MAPPINGS_PATH, "w", encoding="utf-8") as fh:
            json.dump(clean, fh, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False
