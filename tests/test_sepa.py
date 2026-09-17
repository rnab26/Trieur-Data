import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from trieur.sepa import (
    PAIN008_NAMESPACE,
    SEQUENCE_FIRST,
    SEQUENCE_RECURRING,
    SepaXmlError,
    build_pain008_xml,
    determine_sequence_type,
    normalize_iban_key,
)

FIXTURE = Path(__file__).parent / "fixtures" / "pain008_sample_reference.xml"
NS = {"p": PAIN008_NAMESPACE}

CREDITOR = {"name": "CREANCIER TEST", "iban": "FR7630000000000000000000001", "bic": "TESTFRPPXXX", "ics": "FR00ZZZ000000"}

TX_FRST = {
    "end_to_end_id": "E2E-000001", "amount": 100.0, "mandate_id": "MANDAT-001",
    "signature_date": "2026-01-01", "sequence_type": SEQUENCE_FIRST,
    "debtor_name": "PERSONNE TEST 001", "debtor_iban": "FR7630000000000000000000002",
    "debtor_bic": "TESTFRPPYYY",
}
TX_RCUR = {
    "end_to_end_id": "E2E-000002", "amount": 50.0, "mandate_id": "MANDAT-002",
    "signature_date": "2025-06-01", "sequence_type": SEQUENCE_RECURRING,
    "debtor_name": "PERSONNE TEST 002", "debtor_iban": "FR7630000000000000000000003",
    "debtor_bic": "TESTFRPPZZZ",
}


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


def _tags(elem):
    return elem.tag.split("}")[-1]


def test_build_pain008_xml_matches_reference_structure():
    """Compare la structure du XML genere a celle du fichier de reference
    (namespace, arborescence, groupement FRST/RCUR) -- pas juste "ca parse"."""
    generated = build_pain008_xml(CREDITOR, [TX_FRST, TX_RCUR], "2026-01-05", msg_id="TRIEUR-20260101120000")
    gen_root = ET.fromstring(generated)
    ref_root = ET.fromstring(FIXTURE.read_bytes())

    assert gen_root.tag == f"{{{PAIN008_NAMESPACE}}}Document"
    assert gen_root.tag == ref_root.tag

    gen_pmt_infs = gen_root.findall(".//p:PmtInf", NS)
    ref_pmt_infs = ref_root.findall(".//p:PmtInf", NS)
    assert len(gen_pmt_infs) == len(ref_pmt_infs) == 2

    gen_seq_types = [p.findtext(".//p:SeqTp", namespaces=NS) for p in gen_pmt_infs]
    ref_seq_types = [p.findtext(".//p:SeqTp", namespaces=NS) for p in ref_pmt_infs]
    assert gen_seq_types == ref_seq_types == [SEQUENCE_FIRST, SEQUENCE_RECURRING]

    # Meme forme d'arborescence a l'interieur d'une transaction (memes tags,
    # dans le meme ordre) entre genere et reference.
    gen_tx = gen_root.find(".//p:DrctDbtTxInf", NS)
    ref_tx = ref_root.find(".//p:DrctDbtTxInf", NS)
    gen_tags = [_tags(e) for e in gen_tx.iter()]
    ref_tags = [_tags(e) for e in ref_tx.iter()]
    assert gen_tags == ref_tags


def test_build_pain008_xml_values():
    generated = build_pain008_xml(CREDITOR, [TX_FRST, TX_RCUR], "2026-01-05", msg_id="TRIEUR-20260101120000")
    root = ET.fromstring(generated)

    assert root.findtext(".//p:GrpHdr/p:NbOfTxs", namespaces=NS) == "2"
    assert root.findtext(".//p:GrpHdr/p:CtrlSum", namespaces=NS) == "150.00"

    frst_block = root.find(".//p:PmtInf[1]", NS)
    assert frst_block.findtext("p:ReqdColltnDt", namespaces=NS) == "2026-01-05"
    assert frst_block.findtext(".//p:MndtId", namespaces=NS) == "MANDAT-001"
    assert frst_block.findtext(".//p:InstdAmt", namespaces=NS) == "100.00"
    assert frst_block.find(".//p:InstdAmt", NS).get("Ccy") == "EUR"

    rcur_block = root.find(".//p:PmtInf[2]", NS)
    assert rcur_block.findtext(".//p:MndtId", namespaces=NS) == "MANDAT-002"


def test_build_pain008_xml_rejects_missing_field_instead_of_guessing():
    incomplete = {k: v for k, v in TX_FRST.items() if k != "debtor_bic"}
    with pytest.raises(SepaXmlError):
        build_pain008_xml(CREDITOR, [incomplete], "2026-01-05")


def test_build_pain008_xml_rejects_empty_transaction_list():
    with pytest.raises(SepaXmlError):
        build_pain008_xml(CREDITOR, [], "2026-01-05")


def test_build_pain008_xml_rejects_unknown_sequence_type():
    bad = {**TX_FRST, "sequence_type": "OOFF"}
    with pytest.raises(SepaXmlError):
        build_pain008_xml(CREDITOR, [bad], "2026-01-05")
