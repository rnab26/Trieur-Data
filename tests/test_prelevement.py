"""Tests du moteur de génération des mandats de prélèvement --
domaine "zéro droit à l'erreur" (Raphaël, 2026-09-21), chaque règle
vérifiée individuellement avant le test de bout en bout."""

from datetime import date

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
    to_telephone,
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


def test_to_amount_nan_is_zero_not_contagious():
    """Bug réel (2026-09-21, client MACEDO ANNIE/MGS-18397) :
    pandas.DataFrame.where(pd.notnull(df), None) ne remplace pas
    toujours une cellule vide par None sur une colonne de nombres --
    elle arrive ici en float('nan'). Sans ce contrôle, 49.9 + nan = nan,
    et un client avec un vrai produit actif était exclu à tort."""
    nan = float("nan")
    assert to_amount(nan) == 0.0
    assert 49.9 + to_amount(nan) == 49.9  # ne doit jamais "contaminer" une somme


def test_to_telephone_strips_pandas_dot_zero_artifact():
    """Bug réel (2026-09-22, signalé par Raphaël sur un lot réel) :
    quand une cellule numéro est enregistrée comme un NOMBRE dans le
    fichier source, pandas la lit en float64 -- str(33630653771.0)
    donne "33630653771.0", un ".0" qui n'a jamais existé dans le vrai
    numéro. Reformaté en "+33..." pour rester cohérent avec les
    cellules déjà en texte du même fichier."""
    assert to_telephone(33630653771.0) == "+33630653771"
    assert to_telephone(33630653771) == "+33630653771"


def test_to_telephone_keeps_already_formatted_text_untouched():
    assert to_telephone("+33630653771") == "+33630653771"
    assert to_telephone("0630653771") == "0630653771"  # forme non reconnue -> jamais modifiée


def test_to_telephone_missing_is_empty_not_invented():
    assert to_telephone(None) == ""
    assert to_telephone("") == ""
    assert to_telephone(float("nan")) == ""


def test_generate_mandats_falls_back_to_mobile_when_telephone_empty():
    """Bug réel (2026-09-22) : la colonne "Téléphone" (fixe) est vide
    pour ~32% des clients du fichier CRM de référence, alors que
    "Mobile" est remplie à 100% sur les mêmes lignes -- ne lire que
    "Téléphone" laissait ces mandats partir en banque sans aucun
    numéro. Vérifié sur les deux colonnes réelles du fichier CRM."""
    row = _base_row()
    row["Téléphone"] = ""
    row["Mobile"] = "+33612345678"
    result = generate_mandats([row], PrelevementRules())
    assert result.mandats[0].telephone == "+33612345678"


def test_generate_mandats_prefers_telephone_over_mobile_when_both_filled():
    row = _base_row()
    row["Téléphone"] = "+33600000001"
    row["Mobile"] = "+33600000002"
    result = generate_mandats([row], PrelevementRules())
    assert result.mandats[0].telephone == "+33600000001"


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


def test_build_motif_one_mandate_one_suffix():
    """Un mandat = UN produit = UN suffixe, jamais plusieurs combinés --
    voir generate_mandats pour la règle d'éclatement."""
    assert build_motif("1422647", "-O") == "MGS-1422647-O"
    assert build_motif("42", "-J") == "MGS-42-J"


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
        "Total frais de dossier": 20.0,
    }
    row.update(overrides)
    return row


def test_generate_mandats_ooff_when_frais_present():
    """FRST (1er prélèvement) = valeur du produit + frais de dossier
    (20€ par défaut, réglable) -- PAS "Total cotisation et frais de
    dossier" (colonne trouvée fausse le 2026-09-21 en croisant avec le
    vrai fichier de remise bancaire du Drive, jamais réutilisée)."""
    result = generate_mandats([_base_row()], PrelevementRules(), today=date(2026, 9, 21))
    assert len(result.ooff) == 1
    assert len(result.rcur) == 0
    assert len(result.exclus) == 0
    mandat = result.ooff[0]
    assert mandat.type_sequence == "FRST"
    assert mandat.montant_eur == 119.0  # 99 (Optilife) + 20 (frais)
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
    # Pas de colonne "date d'effet" dans cette ligne de test -> vide,
    # jamais inventée.
    assert mandat.date_effet == ""


def test_generate_mandats_rcur_when_notified():
    """RCUR (récurrent) = valeur du produit TELLE QUELLE, jamais de
    frais ajouté. Déclenché par "Statut agent IA" = "Notifié le ..." --
    bug réel corrigé le 2026-09-22 (Raphaël : "aucun prélèvement n'est
    récurrent") : l'ancienne règle ("Total frais de dossier" == 0)
    faisait dépendre FRST/RCUR d'une colonne qui ne concordait qu'à 63%
    avec le vrai historique des remises bancaires du Drive."""
    row = _base_row(**{"Statut agent IA": "Notifié le 10/09/26"})
    result = generate_mandats([row], PrelevementRules(), today=date(2026, 9, 21))
    assert len(result.rcur) == 1
    assert len(result.ooff) == 0
    assert result.rcur[0].type_sequence == "RCUR"
    assert result.rcur[0].montant_eur == 99.0


def test_generate_mandats_frais_setup_eur_is_adjustable():
    """Les frais de dossier sont un réglage, pas une valeur codée en
    dur -- demande explicite de Raphaël dès le départ de ce chantier."""
    result = generate_mandats(
        [_base_row()], PrelevementRules(frais_setup_eur=15.0), today=date(2026, 9, 21),
    )
    assert result.ooff[0].montant_eur == 114.0  # 99 + 15


def test_generate_mandats_splits_multi_product_client_into_separate_mandats():
    """LA règle centrale trouvée le 2026-09-21 en croisant le fichier
    CRM de référence avec le vrai fichier de remise bancaire du Drive
    (lecture seule, RUM 1419267) : un client avec Optilife (49,90€) ET
    MYJURIS (29,89€) génère DEUX mandats séparés -- jamais un mandat
    combiné à 79,79€ (ce que l'ancien moteur faisait, et qui n'a jamais
    correspondu à aucun montant réel envoyé en banque)."""
    row = _base_row(**{
        "RUM": "1419267",
        "Optilife": 49.90,
        "MYJURIS & MYHOSPI": 29.89,
        "Total frais de dossier": 40.0,  # 20€ x 2 produits actifs
    })
    result = generate_mandats([row], PrelevementRules(), today=date(2026, 9, 21))
    assert len(result.ooff) == 2
    assert len(result.rcur) == 0
    by_motif = {m.motif: m for m in result.ooff}
    assert set(by_motif) == {"MGS-1419267-O", "MGS-1419267-J"}
    # Montants réels vérifiés contre le vrai fichier de remise bancaire
    # (onglet "remises CAIXA+Sabadell" du classeur Drive) : FRST
    # Optilife = 69,90€, FRST MYJURIS = 49,89€.
    assert by_motif["MGS-1419267-O"].montant_eur == 69.90
    assert by_motif["MGS-1419267-J"].montant_eur == 49.89


def test_generate_mandats_multi_product_rcur_matches_real_remise():
    """Même client que ci-dessus, mais en récurrent (sans frais) --
    montants RCUR vérifiés contre le vrai fichier de remise (49,90€ et
    29,89€, exactement les valeurs brutes des colonnes produit)."""
    row = _base_row(**{
        "RUM": "1419267",
        "Optilife": 49.90,
        "MYJURIS & MYHOSPI": 29.89,
        "Statut agent IA": "Notifié le 10/09/26",
    })
    result = generate_mandats([row], PrelevementRules(), today=date(2026, 9, 21))
    assert len(result.rcur) == 2
    by_motif = {m.motif: m for m in result.rcur}
    assert by_motif["MGS-1419267-O"].montant_eur == 49.90
    assert by_motif["MGS-1419267-J"].montant_eur == 29.89


def test_generate_mandats_immo_column_uses_au_suffix_not_im():
    """La colonne IMMO correspond au suffixe "-AU" dans les vraies
    remises bancaires, jamais "-IM" -- trouvé le 2026-09-21 en croisant
    5 clients du CRM avec le vrai fichier de remise du Drive (le
    mapping d'origine, reverse-engineered depuis une formule Excel,
    avait les deux lettres inversées)."""
    row = _base_row(**{"Optilife": 0, "IMMO": 5.90, "Total frais de dossier": 20.0})
    result = generate_mandats([row], PrelevementRules(), today=date(2026, 9, 21))
    assert len(result.ooff) == 1
    assert result.ooff[0].motif.endswith("-AU")
    assert result.ooff[0].montant_eur == 25.90  # 5.90 + 20


def test_generate_mandats_myjuris_and_immo_bundle_into_one_mandat():
    """MYJURIS + IMMO actifs ensemble = UN SEUL mandat "-J-AU" (montants
    additionnés, frais comptés 2 fois) -- seule exception à la règle
    "un mandat par produit", confirmée sur 2 clients réels croisés avec
    le vrai fichier de remise (RCUR = somme exacte des 2 colonnes, FRST
    = RCUR + 2x les frais de dossier)."""
    row = _base_row(**{
        "RUM": "1425316",
        "Optilife": 99.0,
        "MYJURIS & MYHOSPI": 19.90,
        "IMMO": 5.90,
        "Total frais de dossier": 60.0,  # 3 produits actifs x 20€
    })
    result = generate_mandats([row], PrelevementRules(), today=date(2026, 9, 21))
    assert len(result.ooff) == 2  # Optilife seul + le duo MYJURIS/IMMO fusionné
    by_motif = {m.motif: m for m in result.ooff}
    assert set(by_motif) == {"MGS-1425316-O", "MGS-1425316-J-AU"}
    assert by_motif["MGS-1425316-O"].montant_eur == 119.0  # 99 + 20
    assert by_motif["MGS-1425316-J-AU"].montant_eur == 65.80  # (19.90+5.90) + 2x20


def test_generate_mandats_myjuris_alone_stays_standalone():
    """MYJURIS actif SEUL (sans IMMO) reste un mandat "-J" normal --
    la fusion ne s'applique que si les DEUX sont actifs ensemble."""
    row = _base_row(**{"Optilife": 0, "MYJURIS & MYHOSPI": 19.90, "Total frais de dossier": 20.0})
    result = generate_mandats([row], PrelevementRules(), today=date(2026, 9, 21))
    assert len(result.ooff) == 1
    assert result.ooff[0].motif.endswith("-J")
    assert not result.ooff[0].motif.endswith("-AU")


def test_generate_mandats_mandats_list_combines_ooff_and_rcur():
    """result.mandats (l'onglet "Mandat" combiné demandé par Raphaël)
    contient bien tous les mandats générés, FRST et RCUR mélangés."""
    row = _base_row(**{
        "RUM": "1419267",
        "Optilife": 49.90,
        "MYJURIS & MYHOSPI": 29.89,
        "Total frais de dossier": 40.0,
    })
    result = generate_mandats([row], PrelevementRules(), today=date(2026, 9, 21))
    assert len(result.mandats) == 2
    assert result.mandats == result.ooff


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


def test_generate_mandats_excludes_client_refused():
    """Bug réel corrigé le 2026-09-22 (Raphaël, en revérifiant les
    fichiers maîtres) : un client "Refusé par le client" était généré
    et envoyé en banque comme n'importe quel autre mandat -- jamais
    remarqué faute d'exploiter "Statut agent IA"."""
    row = _base_row(**{"Statut agent IA": "Refusé par le client"})
    result = generate_mandats([row], PrelevementRules(), today=date(2026, 9, 21))
    assert result.ooff == [] and result.rcur == []
    assert len(result.exclus) == 1
    assert "refus" in result.exclus[0].raison.lower()


def test_generate_mandats_excludes_contract_to_cancel():
    row = _base_row(**{"Statut agent IA": "Nrp J-1 - Annuler contrat"})
    result = generate_mandats([row], PrelevementRules(), today=date(2026, 9, 21))
    assert result.ooff == [] and result.rcur == []
    assert len(result.exclus) == 1


def test_generate_mandats_frst_when_statut_ia_blank_or_valide():
    """Sans "Notifié" -- vide ou "Validé par le client" (première
    validation, pas encore de cycle récurrent) -- reste FRST."""
    for statut in ("", "Validé par le client"):
        row = _base_row(**{"Statut agent IA": statut})
        result = generate_mandats([row], PrelevementRules(), today=date(2026, 9, 21))
        assert len(result.ooff) == 1, f"statut={statut!r}"
        assert result.ooff[0].type_sequence == "FRST"


def test_generate_mandats_excludes_when_no_product_active():
    row = _base_row(**{"Optilife": 0})
    result = generate_mandats([row], PrelevementRules(), today=date(2026, 9, 21))
    assert result.ooff == [] and result.rcur == []
    assert len(result.exclus) == 1
    assert "produit" in result.exclus[0].raison.lower()


def test_generate_mandats_merges_optivie_into_optilife_motif():
    row = _base_row(**{"Optilife": 0, "Optivie": 39.99})
    result = generate_mandats([row], PrelevementRules(), today=date(2026, 9, 21))
    assert len(result.ooff) == 1
    assert "-O" in result.ooff[0].motif


def test_generate_mandats_ignores_casse_auditif_column_entirely():
    """Colonne "Contrat MYMO casse & perte appareil auditif" -- Raphaël
    (2026-09-21) : "je ne la prends pas en compte pour l'instant". Ne
    doit générer aucun mandat, même présente et non-nulle dans le
    fichier importé."""
    row = _base_row(**{"Contrat MYMO casse & perte appareil auditif ": 15.0})
    result = generate_mandats([row], PrelevementRules(), today=date(2026, 9, 21))
    assert len(result.ooff) == 1  # seulement Optilife, la casse est ignorée
    assert result.ooff[0].montant_eur == 119.0  # inchangé (99 + 20)


def test_generate_mandats_reads_date_effet_column():
    row = _base_row(**{"Date d'effet du nouveau contrat (OPTILIFE)": "15/03/2026"})
    result = generate_mandats([row], PrelevementRules(), today=date(2026, 9, 21))
    assert result.ooff[0].date_effet == "15/03/2026"


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
    assert mandat.montant_eur == 119.0  # 99 (Optilife) + 20 (frais)
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
