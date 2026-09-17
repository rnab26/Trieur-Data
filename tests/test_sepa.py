from trieur.sepa import (
    SEQUENCE_FIRST,
    SEQUENCE_RECURRING,
    determine_sequence_type,
    normalize_iban_key,
)


def test_determine_sequence_type_first_when_no_prior_debit():
    assert determine_sequence_type(has_prior_debit=False) == SEQUENCE_FIRST


def test_determine_sequence_type_recurring_when_prior_debit():
    assert determine_sequence_type(has_prior_debit=True) == SEQUENCE_RECURRING


def test_normalize_iban_key_strips_spaces_and_uppercases():
    assert normalize_iban_key("fr76 1234 5678 9012 3456 7890 189") == "FR7612345678901234567890189"


def test_normalize_iban_key_none_for_empty_or_missing():
    assert normalize_iban_key(None) is None
    assert normalize_iban_key("") is None
    assert normalize_iban_key("   ") is None


def test_normalize_iban_key_matches_sql_normalization_shape():
    # Meme resultat qu'un IBAN deja "propre" -- pas de transformation en trop
    assert normalize_iban_key("FR7612345") == "FR7612345"
