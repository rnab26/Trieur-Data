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
