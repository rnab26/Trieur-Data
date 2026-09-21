"""Tests du moteur de génération des mandats de prélèvement --
domaine "zéro droit à l'erreur" (Raphaël, 2026-09-21), chaque règle
vérifiée individuellement avant le test de bout en bout."""

from datetime import date

import pytest

from trieur.prelevement import (
    GenerationResult,
    PrelevementRules,
    build_motif,
    compute_first_prelevement_date,
    generate_mandats,
    iban_checksum_valid,
    normalize_iban,
    pad_bic,
    to_amount,
)

VALID_IBAN = "FR7615589228070085438594040"  # IBAN réel du fichier de référence, IBAN VALIDATOR=true


def test_normalize_iban_strips_spaces_and_uppercases():
    assert normalize_iban("fr76 1558 9228 0700 8543 8594 040") == VALID_IBAN


def test_normalize_iban_none_is_empty():
    assert normalize_iban(None) == ""


def test_iban_checksum_valid_true_for_real_client_iban():
    assert iban_checksum_valid(VALID_IBAN) is True


def test_iban_checksum_valid_false_for_altered_iban():
    altered = VALID_IBAN[:-1] + str((int(VALID_IBAN[-1]) + 1) % 10)
    assert iban_checksum_valid(altered) is False


def test_iban_checksum_valid_false_for_garbage():
    assert iban_checksum_valid("PAS UN IBAN") is False
    assert iban_checksum_valid("") is False


def test_pad_bic_completes_8_char_bic():
    assert pad_bic("cmbrfr2b") == "CMBRFR2BXXX"


def test_pad_bic_leaves_11_char_bic_untouched():
    assert pad_bic("psstfrpplim") == "PSSTFRPPLIM"


def test_to_amount_handles_dot_and_comma_decimal():
    assert to_amount("99.90") == 99.9
    assert to_amount("99,90") == 99.9
    assert to_amount(49.9) == 49.9


def test_to_amount_missing_is_zero_not_error():
    assert to_amount(None) == 0.0
    assert to_amount("") == 0.0
    assert to_amount("n'importe quoi") == 0.0


def test_compute_first_prelevement_date_never_before_delay():
    today = date(2026, 9, 21)
    # Prévue trop tôt (demain) -> repoussée au plancher (aujourd'hui + 3 jours)
    assert compute_first_prelevement_date("22/09/2026", today, 3) == date(2026, 9, 24)


def test_compute_first_prelevement_date_keeps_later_scheduled_date():
    today = date(2026, 9, 21)
    # Prévue largement après le plancher -> gardée telle quelle
    assert compute_first_prelevement_date("15/10/2026", today, 3) == date(2026, 10, 15)


def test_compute_first_prelevement_date_none_when_not_scheduled():
    assert compute_first_prelevement_date("", date(2026, 9, 21), 3) is None
    assert compute_first_prelevement_date(None, date(2026, 9, 21), 3) is None


def test_build_motif_one_product():
    motif = build_motif("1422647", {"Optilife": 99.0})
    assert motif == "MGS-1422647-O"


def test_build_motif_several_products_in_fixed_order():
    amounts = {
        "IMMO": 5.9,
        "Optilife": 99.0,
        "Carte MGS": 20.0,
    }
    assert build_motif("42", amounts) == "MGS-42-O-M-IM"


def test_build_motif_no_product_is_bare_rum():
    assert build_motif("42", {}) == "MGS-42"


def _base_row(**overrides) -> dict:
    row = {
        "Référence du client ": "MGS-000001",
        "Nom complet": "TEST CLIENT",
        "RUM": "RUM000001",
        "Statut": "Sepa validé par le client",
        "Type de prélèvement": "Prélèvement",
        "Périodicité (Mensuel/trimestre/annuel)             ": "Mensuelle",
        "IBAN  ": VALID_IBAN,
        "BIC": "CMBRFR2B",
        "Date création": "01/01/2026",
        "Date de premier prélèvement": "24/09/2026",
        "Adresse": "1 rue Test",
        "Ville": "Paris",
        "Code postal": "75001",
        "Email": "test@example.com",
        "Téléphone": "+33600000000",
        "Optilife": 99.0,
        "Optivie": 0,
        "Carte MGS": 0,
        "MYJURIS & MYHOSPI": 0,
        "Admin & Aide a dom": 0,
        "Auditif": 0,
        "IMMO": 0,
        "Total cotisation MYMO VETO SUR ": 0,
        "Total frais de dossier": 40.0,
        "Total cotisation et frais de dossier": 139.0,
    }
    row.update(overrides)
    return row


def test_generate_mandats_ooff_when_frais_present():
    result = generate_mandats([_base_row()], PrelevementRules(), today=date(2026, 9, 21))
    assert len(result.ooff) == 1
    assert len(result.rcur) == 0
    assert len(result.exclus) == 0
    mandat = result.ooff[0]
    assert mandat.type_sequence == "FRST"
    assert mandat.montant_eur == 139.0
    assert mandat.iban == VALID_IBAN
    assert mandat.bic == "CMBRFR2BXXX"
    assert mandat.motif == "MGS-RUM000001-O"
    assert mandat.date_premiere_echeance == "24/09/2026"
    # Date de signature = date de création du contrat, PAS la date de
    # génération du fichier ("today" ci-dessus) -- vérifié contre un
    # vrai client du fichier de référence (2026-09-21).
    assert mandat.date_signature_mandat == "01/01/2026"
    # Vide pour un 1er prélèvement -- ne décrit que la récurrence des
    # prélèvements SUIVANTS (vérifié contre le fichier de référence).
    assert mandat.explication_periodicite == ""


def test_generate_mandats_rcur_when_no_frais():
    row = _base_row(**{"Total frais de dossier": 0.0, "Total cotisation et frais de dossier": 99.0})
    result = generate_mandats([row], PrelevementRules(), today=date(2026, 9, 21))
    assert len(result.rcur) == 1
    assert len(result.ooff) == 0
    assert result.rcur[0].type_sequence == "RCUR"
    assert result.rcur[0].montant_eur == 99.0


def test_generate_mandats_excludes_carte_bleue():
    row = _base_row(**{"Type de prélèvement": "Carte bleue"})
    result = generate_mandats([row], PrelevementRules(), today=date(2026, 9, 21))
    assert result.ooff == [] and result.rcur == []
    assert len(result.exclus) == 1
    assert "carte bleue" in result.exclus[0].raison.lower() or "Carte bleue" in result.exclus[0].raison


def test_generate_mandats_excludes_invalid_iban():
    row = _base_row(**{"IBAN  ": "FR0000000000000000000000000"})
    result = generate_mandats([row], PrelevementRules(), today=date(2026, 9, 21))
    assert len(result.exclus) == 1
    assert "iban" in result.exclus[0].raison.lower()


def test_generate_mandats_excludes_missing_iban():
    row = _base_row(**{"IBAN  ": ""})
    result = generate_mandats([row], PrelevementRules(), today=date(2026, 9, 21))
    assert len(result.exclus) == 1


def test_generate_mandats_excludes_missing_first_prelevement_date():
    row = _base_row(**{"Date de premier prélèvement": ""})
    result = generate_mandats([row], PrelevementRules(), today=date(2026, 9, 21))
    assert len(result.exclus) == 1
    assert "date" in result.exclus[0].raison.lower()


def test_generate_mandats_merges_optivie_into_optilife_motif():
    row = _base_row(**{"Optilife": 0, "Optivie": 39.99})
    result = generate_mandats([row], PrelevementRules(), today=date(2026, 9, 21))
    assert len(result.ooff) == 1
    assert "-O" in result.ooff[0].motif


def test_generate_mandats_ignores_casse_auditif_column_entirely():
    """Colonne "Contrat MYMO casse & perte appareil auditif" -- Raphaël
    (2026-09-21) : "je ne la prends pas en compte pour l'instant". Ne
    doit influencer ni le montant ni le motif, même si présente dans le
    fichier importé."""
    row = _base_row(**{"Contrat MYMO casse & perte appareil auditif ": 15.0})
    result = generate_mandats([row], PrelevementRules(), today=date(2026, 9, 21))
    assert result.ooff[0].montant_eur == 139.0  # inchangé


def test_generate_mandats_matches_real_reference_client():
    """Comparaison ligne par ligne avec un vrai client du fichier Excel
    de référence (RUM/IBAN/montants réels, nom et adresse fictifs ici
    pour ne pas committer plus de PII que nécessaire au dépôt) --
    vérifié à la main contre les onglets "3 Sheet1"/"Mandats CAIXA" du
    classeur "3_creations_des_mandats" (2026-09-21). A trouvé 2 bugs
    réels avant ce test : date de signature = aujourd'hui au lieu de la
    date de création du contrat, et explication de périodicité non
    vidée pour un 1er prélèvement."""
    row = {
        "Référence du client ": "MGS-20230",
        "Nom complet": "CLIENT TEST",
        "RUM": "1422647",
        "Statut": "Sepa validé par le client",
        "Type de prélèvement": "Prélèvement",
        "Périodicité (Mensuel/trimestre/annuel)             ": "Mensuelle",
        "IBAN  ": VALID_IBAN,
        "BIC": "CMBRFR2B",
        "Date création": "21/08/2026",
        "Date de premier prélèvement": "10/09/2026",
        "Adresse": "1 rue Fictive",
        "Ville": "Ville Test",
        "Code postal": "00000",
        "Email": "client-test@example.com",
        "Téléphone": "+33600000000",
        "Optilife": 99.0,
        "Total frais de dossier": 20.0,
        "Total cotisation et frais de dossier": 119.0,
    }
    # "today" volontairement différent de la date de création (mais
    # encore avant la date prévue + délai, pour ne pas interférer avec
    # la règle J+3 testée ailleurs) -- le test échoue si
    # date_signature_mandat repart de "today" au lieu de "Date création"
    # (le bug trouvé en vérifiant contre le fichier réel).
    result = generate_mandats([row], PrelevementRules(), today=date(2026, 8, 25))
    assert len(result.ooff) == 1
    mandat = result.ooff[0]
    assert mandat.type_sequence == "FRST"
    assert mandat.montant_eur == 119.0
    assert mandat.motif == "MGS-1422647-O"
    assert mandat.bic == "CMBRFR2BXXX"
    assert mandat.date_premiere_echeance == "10/09/2026"
    assert mandat.date_signature_mandat == "21/08/2026"
    assert mandat.explication_periodicite == ""


def test_generate_mandats_empty_input_returns_empty_result():
    result = generate_mandats([], PrelevementRules(), today=date(2026, 9, 21))
    assert result == GenerationResult()


def test_generate_mandats_one_bad_row_does_not_break_the_batch():
    rows = [_base_row(), _base_row(**{"IBAN  ": ""}, **{"Référence du client ": "MGS-000002"})]
    result = generate_mandats(rows, PrelevementRules(), today=date(2026, 9, 21))
    assert len(result.ooff) == 1
    assert len(result.exclus) == 1
