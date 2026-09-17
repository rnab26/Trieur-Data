"""Teste views/_ui.py:unknown_columns() -- pure, sans Streamlit."""
from views._ui import unknown_columns


def test_unknown_columns_returns_only_columns_not_in_master_cols():
    result = unknown_columns(["NOM", "IBAN", "TELEPHONE"], master_cols=["NOM", "IBAN"])
    assert result == ["TELEPHONE"]


def test_unknown_columns_preserves_order_and_dedupes():
    result = unknown_columns(["B", "A", "B", "C"], master_cols=[])
    assert result == ["B", "A", "C"]


def test_unknown_columns_empty_when_everything_known():
    assert unknown_columns(["NOM", "IBAN"], master_cols=["NOM", "IBAN", "EMAIL"]) == []


def test_unknown_columns_empty_input():
    assert unknown_columns([], master_cols=["NOM"]) == []


def test_unknown_columns_case_insensitive_against_master_cols():
    """"EMAIL" ne doit pas être proposé comme nouvelle colonne si "Email"
    existe déjà -- même convention que le dédoublonnage des colonnes
    maîtres (views/tab1_colonnes_maitres.py), sinon deux colonnes quasi
    identiques finissent dans les réglages de l'environnement."""
    assert unknown_columns(["EMAIL", "Nouvelle"], master_cols=["Email", "NOM"]) == ["Nouvelle"]


def test_unknown_columns_case_insensitive_dedup_within_result():
    result = unknown_columns(["Ville", "VILLE", "ville"], master_cols=[])
    assert result == ["Ville"]
