"""Règles SEPA (prélèvement) qui ne dépendent PAS du format d'export
bancaire exact -- logique métier pure, testable sans base de données.

Le générateur XML pain.008 lui-même reste bloqué tant qu'on n'a pas :
1. un exemple réel de fichier accepté par la banque (version de schéma)
2. l'ICS (identifiant créancier SEPA) de l'organisme
Voir le chantier "Export XML SEPA" dans le Cockpit (environnement
Prélèvement) pour le contexte complet.
"""

from trieur.matching import clean_iban

SEQUENCE_FIRST = "FRST"
SEQUENCE_RECURRING = "RCUR"


def normalize_iban_key(value) -> str | None:
    """Même normalisation que la colonne générée `records.iban_normalized`
    côté base (espaces retirés, majuscules) -- pour comparer une valeur
    Python à ce qui est stocké en base sans divergence entre les deux."""
    cleaned = clean_iban(value)
    if cleaned is None or (isinstance(cleaned, float) and cleaned != cleaned):  # NaN
        return None
    cleaned = str(cleaned).strip().upper()
    return cleaned or None


def determine_sequence_type(has_prior_debit: bool) -> str:
    """FRST (premier prélèvement) si cet IBAN n'a jamais été débité pour cet
    organisme, RCUR (récurrent) s'il l'a déjà été. Ne couvre pas FNAL
    (dernier prélèvement, fin de mandat) ni OOFF (ponctuel) -- pas demandés,
    à ajouter seulement si le besoin réel se confirme."""
    return SEQUENCE_RECURRING if has_prior_debit else SEQUENCE_FIRST


# =============================================================
# Génération du fichier XML SEPA (pain.008.001.08) -- structure calquée sur
# un fichier réel accepté par la banque (fourni par l'utilisateur le
# 2026-09-17, jamais copié dans ce dépôt -- voir
# tests/fixtures/pain008_sample_reference.xml, entièrement fictif, qui
# reproduit uniquement la STRUCTURE observée).
#
# Regroupement : un bloc <PmtInf> par type de séquence (FRST puis RCUR),
# toutes les transactions d'un même export partageant la même date de
# prélèvement demandée -- c'est le cas observé le plus simple et le plus
# fréquent sur l'échantillon réel. Étendre à plusieurs dates par export
# seulement si le besoin réel se confirme (ne pas anticiper).
# =============================================================

PAIN008_NAMESPACE = "urn:iso:std:iso:20022:tech:xsd:pain.008.001.08"


class SepaXmlError(ValueError):
    """Donnée manquante ou invalide empêchant de générer un XML SEPA valide
    -- on ne génère jamais un fichier partiel ou avec une valeur devinée."""


def _xml_escape(value: str) -> str:
    from xml.sax.saxutils import escape

    return escape(str(value))


def _require(d: dict, key: str, context: str) -> str:
    value = d.get(key)
    if value in (None, ""):
        raise SepaXmlError(f"Champ obligatoire manquant « {key} » ({context}).")
    return str(value)


def _format_amount(value) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError) as exc:
        raise SepaXmlError(f"Montant invalide : {value!r}") from exc


def _build_payment_info_block(creditor: dict, seq_type: str, requested_date: str, txs: list[dict], block_index: int) -> str:
    creditor_name = _xml_escape(_require(creditor, "name", "créancier"))
    creditor_country = _xml_escape(creditor.get("country") or "FR")
    creditor_iban = _require(creditor, "iban", "créancier")
    creditor_bic = _require(creditor, "bic", "créancier")
    ics = _require(creditor, "ics", "créancier")

    ctrl_sum = sum(float(tx["amount"]) for tx in txs)
    pmt_inf_id = f"TRIEUR-{requested_date.replace('-', '')}-{seq_type}-{block_index:03d}"

    tx_blocks = []
    for tx in txs:
        end_to_end_id = _xml_escape(_require(tx, "end_to_end_id", "transaction"))
        amount = _format_amount(_require(tx, "amount", "transaction"))
        mandate_id = _xml_escape(_require(tx, "mandate_id", "transaction"))
        signature_date = _require(tx, "signature_date", "transaction")
        debtor_bic = _xml_escape(_require(tx, "debtor_bic", "transaction"))
        debtor_name = _xml_escape(_require(tx, "debtor_name", "transaction"))
        debtor_country = _xml_escape(tx.get("debtor_country") or "FR")
        debtor_iban = _require(tx, "debtor_iban", "transaction")
        remittance = _xml_escape(tx.get("remittance_info") or "")

        tx_blocks.append(
            f"<DrctDbtTxInf><PmtId><EndToEndId>{end_to_end_id}</EndToEndId></PmtId>"
            f'<InstdAmt Ccy="EUR">{amount}</InstdAmt>'
            f"<DrctDbtTx><MndtRltdInf><MndtId>{mandate_id}</MndtId>"
            f"<DtOfSgntr>{signature_date}</DtOfSgntr></MndtRltdInf></DrctDbtTx>"
            f"<DbtrAgt><FinInstnId><BICFI>{debtor_bic}</BICFI></FinInstnId></DbtrAgt>"
            f"<Dbtr><Nm>{debtor_name}</Nm><PstlAdr><Ctry>{debtor_country}</Ctry></PstlAdr></Dbtr>"
            f"<DbtrAcct><Id><IBAN>{debtor_iban}</IBAN></Id></DbtrAcct>"
            f"<RmtInf><Ustrd>{remittance}</Ustrd></RmtInf></DrctDbtTxInf>"
        )

    return (
        f"<PmtInf><PmtInfId>{pmt_inf_id}</PmtInfId><PmtMtd>DD</PmtMtd><BtchBookg>true</BtchBookg>"
        f"<NbOfTxs>{len(txs)}</NbOfTxs><CtrlSum>{ctrl_sum:.2f}</CtrlSum>"
        f"<PmtTpInf><SvcLvl><Cd>SEPA</Cd></SvcLvl><LclInstrm><Cd>CORE</Cd></LclInstrm>"
        f"<SeqTp>{seq_type}</SeqTp></PmtTpInf><ReqdColltnDt>{requested_date}</ReqdColltnDt>"
        f"<Cdtr><Nm>{creditor_name}</Nm><PstlAdr><Ctry>{creditor_country}</Ctry></PstlAdr></Cdtr>"
        f"<CdtrAcct><Id><IBAN>{creditor_iban}</IBAN></Id></CdtrAcct>"
        f"<CdtrAgt><FinInstnId><BICFI>{creditor_bic}</BICFI></FinInstnId></CdtrAgt>"
        f"<CdtrSchmeId><Id><PrvtId><Othr><Id>{ics}</Id><SchmeNm><Prtry>SEPA</Prtry></SchmeNm></Othr></PrvtId></Id></CdtrSchmeId>"
        + "".join(tx_blocks)
        + "</PmtInf>"
    )


def build_pain008_xml(creditor: dict, transactions: list[dict], requested_collection_date: str, msg_id: str | None = None) -> bytes:
    """Construit un fichier XML SEPA Direct Debit (pain.008.001.08).

    `creditor` : {name, iban, bic, ics, country?}
    `transactions` : liste de {end_to_end_id, amount, mandate_id,
        signature_date, sequence_type ("FRST"/"RCUR"), debtor_name,
        debtor_iban, debtor_bic, debtor_country?, remittance_info?}
    `requested_collection_date` : "AAAA-MM-JJ", commune à tout l'export.

    Ne devine jamais une valeur manquante -- lève SepaXmlError plutôt que
    de générer un fichier avec un champ vide ou approximatif (impact
    financier réel en cas d'erreur)."""
    if not transactions:
        raise SepaXmlError("Aucune transaction à exporter.")

    from datetime import datetime, timezone

    groups: dict[str, list[dict]] = {}
    for tx in transactions:
        seq_type = _require(tx, "sequence_type", "transaction")
        if seq_type not in (SEQUENCE_FIRST, SEQUENCE_RECURRING):
            raise SepaXmlError(f"Type de séquence inconnu : {seq_type!r}")
        groups.setdefault(seq_type, []).append(tx)

    for tx in transactions:
        _format_amount(_require(tx, "amount", "transaction"))  # valide chaque montant
    total_amount = sum(float(tx["amount"]) for tx in transactions)
    creditor_name = _xml_escape(_require(creditor, "name", "créancier"))
    ics = _require(creditor, "ics", "créancier")
    msg_id = msg_id or f"TRIEUR-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    cre_dt_tm = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    ordered_seq_types = [s for s in (SEQUENCE_FIRST, SEQUENCE_RECURRING) if s in groups]
    payment_blocks = "".join(
        _build_payment_info_block(creditor, seq_type, requested_collection_date, groups[seq_type], idx + 1)
        for idx, seq_type in enumerate(ordered_seq_types)
    )

    xml = (
        "<?xml version='1.0' encoding='utf-8'?>"
        f'<Document xmlns="{PAIN008_NAMESPACE}"><CstmrDrctDbtInitn>'
        f"<GrpHdr><MsgId>{_xml_escape(msg_id)}</MsgId><CreDtTm>{cre_dt_tm}</CreDtTm>"
        f"<NbOfTxs>{len(transactions)}</NbOfTxs><CtrlSum>{total_amount:.2f}</CtrlSum>"
        f"<InitgPty><Nm>{creditor_name}</Nm><Id><OrgId><Othr><Id>{ics}</Id>"
        f"<SchmeNm><Prtry>SEPA</Prtry></SchmeNm></Othr></OrgId></Id></InitgPty></GrpHdr>"
        + payment_blocks
        + "</CstmrDrctDbtInitn></Document>\n"
    )
    return xml.encode("utf-8")
