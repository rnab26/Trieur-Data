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


def test_compute_first_prelevement_date_falls_back_to_delay_when_not_scheduled():
    """Depuis le 2026-09-22 (demande du père de Raphaël, réponse : "la
    date du jour + 3") : aucune date renseignée n'exclut plus le
    client -- utilise directement le plancher aujourd'hui + délai."""
    assert compute_first_prelevement_date("", date(2026, 9, 21), 3) == date(2026, 9, 24)
    assert compute_first_prelevement_date(None, date(2026, 9, 21), 3) == date(2026, 9, 24)


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
    assert len(result.exclus) == 0
    mandat = result.ooff[0]
    assert mandat.type_sequence == "FRST"
    assert mandat.montant_eur == 119.0  # 99 (Optilife) + 20 (frais)
    assert mandat.iban == VALID_IBAN
    assert mandat.bic == "CMBRFR2BXXX"
    assert mandat.motif == "MGS-RUM000001-O"
    # Optilife : pas de date d'effet dans cette ligne -> date du 1er
    # prélèvement + 1 mois (règle spécifique Optilife, voir plus bas).
    assert mandat.date_premiere_echeance == "24/10/2026"
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


def test_generate_mandats_always_pairs_frst_with_rcur():
    """Depuis le 2026-09-22 (demande du père de Raphaël, question posée
    et confirmée -- risque de double prélèvement signalé explicitement
    avant de coder) : CHAQUE mandat génère systématiquement une ligne
    FRST ET une ligne RCUR, peu importe "Statut agent IA" -- ce champ
    ne sert plus qu'à l'exclusion (Refusé/Annuler), jamais à choisir
    entre les deux. Remplace l'ancienne règle où "Notifié" déclenchait
    RCUR seul (bug corrigé le 2026-09-22, cf. l'historique de ce
    fichier) et où les autres statuts déclenchaient FRST seul."""
    for statut in ("", "Validé par le client", "Notifié le 10/09/26"):
        row = _base_row(**{"Statut agent IA": statut})
        result = generate_mandats([row], PrelevementRules(), today=date(2026, 9, 21))
        assert len(result.ooff) == 1, f"statut={statut!r}"
        assert len(result.rcur) == 1, f"statut={statut!r}"
        assert result.ooff[0].type_sequence == "FRST"
        assert result.rcur[0].type_sequence == "RCUR"
        # RCUR = valeur brute du produit, jamais de frais -- FRST = valeur
        # + frais de dossier (20€ par défaut).
        assert result.ooff[0].montant_eur == 119.0
        assert result.rcur[0].montant_eur == 99.0
        assert result.ooff[0].motif == result.rcur[0].motif == "MGS-RUM000001-O"


def test_generate_mandats_rcur_date_shifted_by_periodicite():
    """La date de la ligne RCUR = date du 1er prélèvement décalée de la
    périodicité du contrat (demande du père de Raphaël, 2026-09-22) --
    pas la même date que FRST. Produit hors Optilife (Carte MGS) pour
    ne pas mélanger avec la règle "date d'effet", spécifique à
    Optilife (voir plus bas)."""
    row = _base_row(**{
        "Optilife": 0,
        "Carte MGS": 99.0,
        "Périodicité (Mensuel/trimestre/annuel)             ": "Trimestrielle",
    })
    result = generate_mandats([row], PrelevementRules(), today=date(2026, 9, 21))
    assert result.ooff[0].date_premiere_echeance == "24/09/2026"
    assert result.rcur[0].date_premiere_echeance == "24/12/2026"  # +3 mois
    assert result.rcur[0].explication_periodicite == "Tous les 3 mois"


def test_generate_mandats_rcur_date_defaults_to_one_month_for_unknown_periodicite():
    """Une périodicité non reconnue (colonne vide/texte inattendu) ne
    doit jamais faire échouer la génération -- repli à 1 mois, jamais
    une exception bloquante pour une seule ligne mal renseignée."""
    row = _base_row(**{
        "Optilife": 0,
        "Carte MGS": 99.0,
        "Périodicité (Mensuel/trimestre/annuel)             ": "???",
    })
    result = generate_mandats([row], PrelevementRules(), today=date(2026, 9, 21))
    assert result.rcur[0].date_premiere_echeance == "24/10/2026"  # +1 mois par défaut


def test_generate_mandats_frais_setup_eur_is_adjustable():
    """Les frais de dossier sont un réglage, pas une valeur codée en
    dur -- demande explicite de Raphaël dès le départ de ce chantier."""
    result = generate_mandats(
        [_base_row()], PrelevementRules(frais_setup_eur=15.0), today=date(2026, 9, 21),
    )
    assert result.ooff[0].montant_eur == 114.0  # 99 + 15


def test_generate_mandats_frais_par_produit_overrides_frais_setup_eur():
    """Frais de dossier réglables PAR PRODUIT (Raphaël, 2026-09-22) --
    un montant explicite pour "Optilife" prime sur le réglage global."""
    result = generate_mandats(
        [_base_row()],
        PrelevementRules(frais_setup_eur=20.0, frais_par_produit={"Optilife": 30.0}),
        today=date(2026, 9, 21),
    )
    assert result.ooff[0].montant_eur == 129.0  # 99 + 30 (override), pas 99 + 20


def test_generate_mandats_frais_par_produit_falls_back_for_unlisted_product():
    """Un produit absent de frais_par_produit retombe sur frais_setup_eur
    -- jamais 0€ silencieux."""
    row = _base_row(**{"Carte MGS": "50"})
    result = generate_mandats(
        [row],
        PrelevementRules(frais_setup_eur=20.0, frais_par_produit={"Optilife": 30.0}),
        today=date(2026, 9, 21),
    )
    montants = {m.motif[-2:]: m.montant_eur for m in result.ooff}
    assert montants["-O"] == 129.0  # 99 + 30 (override Optilife)
    assert montants["-M"] == 70.0  # 50 + 20 (repli sur frais_setup_eur, Carte MGS non listée)


def test_generate_mandats_periodicites_override_defaults():
    """Libellés de périodicité réglables (Raphaël, 2026-09-22) -- un
    texte personnalisé remplace le libellé par défaut."""
    row = _base_row(**{
        "Statut agent IA": "Notifié le 10/09/26",
        "Périodicité (Mensuel/trimestre/annuel)": "mensuelle",
    })
    result = generate_mandats(
        [row],
        PrelevementRules(periodicites={"mensuelle": "Chaque mois, le même jour"}),
        today=date(2026, 9, 21),
    )
    assert result.rcur[0].explication_periodicite == "Chaque mois, le même jour"


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
    by_motif = {m.motif: m for m in result.ooff}
    assert set(by_motif) == {"MGS-1419267-O", "MGS-1419267-J"}
    # Montants réels vérifiés contre le vrai fichier de remise bancaire
    # (onglet "remises CAIXA+Sabadell" du classeur Drive) : FRST
    # Optilife = 69,90€, FRST MYJURIS = 49,89€.
    assert by_motif["MGS-1419267-O"].montant_eur == 69.90
    assert by_motif["MGS-1419267-J"].montant_eur == 49.89


def test_generate_mandats_multi_product_rcur_matches_real_remise():
    """Même client que ci-dessus, ligne RCUR (générée systématiquement
    en plus de FRST depuis le 2026-09-22) -- montants vérifiés contre
    le vrai fichier de remise (49,90€ et 29,89€, exactement les valeurs
    brutes des colonnes produit, sans frais)."""
    row = _base_row(**{
        "RUM": "1419267",
        "Optilife": 49.90,
        "MYJURIS & MYHOSPI": 29.89,
    })
    result = generate_mandats([row], PrelevementRules(), today=date(2026, 9, 21))
    assert len(result.rcur) == 2
    by_motif = {m.motif: m for m in result.rcur}
    assert by_motif["MGS-1419267-O"].montant_eur == 49.90
    assert by_motif["MGS-1419267-J"].montant_eur == 29.89


def test_generate_mandats_immo_column_uses_im_suffix():
    """La colonne IMMO correspond au suffixe "-IM" -- formule d'origine
    du père de Raphaël, RÉTABLIE le 2026-09-22 (question posée sur le
    conflit avec la correction du 21/09, réponse explicite : "revenir
    à ma formule... la correction du 21/09 était une erreur"). Voir
    l'historique de ce fichier pour la correction intermédiaire du
    21/09, tranchée fausse par le père de Raphaël lui-même."""
    row = _base_row(**{"Optilife": 0, "IMMO": 5.90, "Total frais de dossier": 20.0})
    result = generate_mandats([row], PrelevementRules(), today=date(2026, 9, 21))
    assert len(result.ooff) == 1
    assert result.ooff[0].motif.endswith("-IM")
    assert result.ooff[0].montant_eur == 25.90  # 5.90 + 20


def test_generate_mandats_myjuris_and_immo_bundle_into_one_mandat():
    """MYJURIS + IMMO actifs ensemble = UN SEUL mandat "-J-IM" (montants
    additionnés, frais comptés 2 fois) -- cas particulier du groupe de
    cumul étendu le 2026-09-22 (voir test suivant pour le groupe
    complet), confirmé sur 2 clients réels croisés avec le vrai fichier
    de remise (RCUR = somme exacte des 2 colonnes, FRST = RCUR + 2x les
    frais de dossier)."""
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
    assert set(by_motif) == {"MGS-1425316-O", "MGS-1425316-J-IM"}
    assert by_motif["MGS-1425316-O"].montant_eur == 119.0  # 99 + 20
    assert by_motif["MGS-1425316-J-IM"].montant_eur == 65.80  # (19.90+5.90) + 2x20
    # La ligne RCUR du mandat fusionné existe aussi, sans les frais.
    rcur_fusion = next(m for m in result.rcur if m.motif == "MGS-1425316-J-IM")
    assert rcur_fusion.montant_eur == 25.80  # 19.90 + 5.90, sans frais


def test_generate_mandats_full_cumul_group_bundles_into_one_mandat():
    """Le groupe de cumul étendu le 2026-09-22 (demande du père de
    Raphaël, question posée et confirmée) : MYJURIS & MYHOSPI, Admin &
    Aide a dom, Auditif, IMMO et VETO actifs ensemble fusionnent TOUS en
    UN SEUL mandat, suffixe combiné dans l'ordre des produits connus
    ("-J-AD-AU-IM-V"). Optilife reste hors du groupe, son propre
    mandat."""
    row = _base_row(**{
        "RUM": "9000001",
        "Optilife": 10.0,
        "MYJURIS & MYHOSPI": 1.0,
        "Admin & Aide a dom": 2.0,
        "Auditif": 3.0,
        "IMMO": 4.0,
        "Total cotisation MYMO VETO SUR ": 5.0,
        "Total frais de dossier": 120.0,  # 6 produits actifs x 20€
    })
    result = generate_mandats([row], PrelevementRules(), today=date(2026, 9, 21))
    assert len(result.ooff) == 2  # Optilife seul + le groupe cumulé
    by_motif = {m.motif: m for m in result.ooff}
    assert set(by_motif) == {"MGS-9000001-O", "MGS-9000001-J-AD-AU-IM-V"}
    # 1+2+3+4+5 = 15€ de produits, + 5x20€ de frais (un par produit du groupe)
    assert by_motif["MGS-9000001-J-AD-AU-IM-V"].montant_eur == 115.0
    rcur_groupe = next(m for m in result.rcur if m.motif == "MGS-9000001-J-AD-AU-IM-V")
    assert rcur_groupe.montant_eur == 15.0  # sans frais


def test_generate_mandats_myjuris_alone_stays_standalone():
    """MYJURIS actif SEUL (aucun autre produit du groupe de cumul actif)
    reste un mandat "-J" normal -- le cumul ne s'applique que si au
    moins deux produits du groupe sont actifs ensemble."""
    row = _base_row(**{"Optilife": 0, "MYJURIS & MYHOSPI": 19.90, "Total frais de dossier": 20.0})
    result = generate_mandats([row], PrelevementRules(), today=date(2026, 9, 21))
    assert len(result.ooff) == 1
    assert result.ooff[0].motif.endswith("-J")
    assert not result.ooff[0].motif.endswith("-AU")


def test_generate_mandats_mandats_list_combines_ooff_and_rcur():
    """result.mandats (l'onglet "Mandat" combiné demandé par Raphaël)
    contient bien tous les mandats générés, FRST et RCUR mélangés --
    depuis le 2026-09-22, chaque mandat produit systématiquement les
    deux."""
    row = _base_row(**{
        "RUM": "1419267",
        "Optilife": 49.90,
        "MYJURIS & MYHOSPI": 29.89,
        "Total frais de dossier": 40.0,
    })
    result = generate_mandats([row], PrelevementRules(), today=date(2026, 9, 21))
    assert len(result.mandats) == 4  # 2 produits x (FRST + RCUR)
    assert len(result.mandats) == len(result.ooff) + len(result.rcur)
    assert all(m in result.mandats for m in result.ooff)
    assert all(m in result.mandats for m in result.rcur)


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


def test_generate_mandats_no_longer_excludes_missing_first_prelevement_date():
    """Depuis le 2026-09-22 (demande du père de Raphaël, question posée,
    réponse : "la date du jour + 3") : plus d'exclusion sur ce critère --
    le mandat est généré avec la date plancher (aujourd'hui + délai)."""
    row = _base_row(**{"Date de premier prélèvement": ""})
    result = generate_mandats([row], PrelevementRules(), today=date(2026, 9, 21))
    assert result.exclus == []
    assert len(result.ooff) == 1
    # +1 mois : règle Optilife existante (date d'effet absente/passée),
    # sans rapport avec ce correctif -- part bien de 24/09 (aujourd'hui
    # + 3 jours, plus de date renseignée) avant ce décalage.
    assert result.ooff[0].date_premiere_echeance == "24/10/2026"


def test_generate_mandats_no_longer_excludes_refused_or_cancel_status():
    """"Statut agent IA" contenant "Refusé"/"Annuler" excluait le
    client jusqu'au 2026-09-22 -- retiré sur demande du père de
    Raphaël (question posée AVEC le risque signalé explicitement : "un
    client qui a explicitement refusé... pourrait être envoyé en
    banque" -- réponse reçue : "Oui, retirer les deux critères").
    "Statut agent IA" est maintenant un champ entièrement ignoré par le
    moteur, quelle que soit sa valeur."""
    for statut in ("Refusé par le client", "Nrp J-1 - Annuler contrat"):
        row = _base_row(**{"Statut agent IA": statut})
        result = generate_mandats([row], PrelevementRules(), today=date(2026, 9, 21))
        assert len(result.exclus) == 0, f"statut={statut!r}"
        assert len(result.ooff) == 1, f"statut={statut!r}"


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


def test_generate_mandats_optilife_date_premiere_uses_future_date_effet():
    """Demande du père de Raphaël (2026-09-22, question posée et
    confirmée) : pour le mandat Optilife uniquement, si la date d'effet
    est renseignée ET future (> aujourd'hui), la date du 1er
    prélèvement = date d'effet + 1 mois -- pas la date de premier
    prélèvement du fichier."""
    row = _base_row(**{"Date d'effet du nouveau contrat (OPTILIFE)": "15/12/2026"})
    result = generate_mandats([row], PrelevementRules(), today=date(2026, 9, 21))
    assert result.ooff[0].date_premiere_echeance == "15/01/2027"  # 15/12/2026 + 1 mois


def test_generate_mandats_optilife_date_premiere_falls_back_when_date_effet_past():
    """Réponse du père de Raphaël (2026-09-22) au cas manquant de la
    règle initiale : date d'effet renseignée mais déjà passée -> traité
    comme si elle n'existait pas, date du 1er prélèvement = date de 1er
    prélèvement (calculée normalement) + 1 mois."""
    row = _base_row(**{"Date d'effet du nouveau contrat (OPTILIFE)": "15/03/2026"})  # passée (today = 21/09/2026)
    result = generate_mandats([row], PrelevementRules(), today=date(2026, 9, 21))
    assert result.ooff[0].date_premiere_echeance == "24/10/2026"  # 24/09/2026 (date_premiere) + 1 mois


def test_generate_mandats_optilife_date_premiere_falls_back_when_no_date_effet():
    row = _base_row()  # pas de colonne "Date d'effet..." dans _base_row par défaut
    result = generate_mandats([row], PrelevementRules(), today=date(2026, 9, 21))
    assert result.ooff[0].date_premiere_echeance == "24/10/2026"  # 24/09/2026 (date_premiere) + 1 mois


def test_generate_mandats_date_effet_rule_does_not_apply_outside_optilife():
    """La règle ci-dessus est scopée au mandat Optilife UNIQUEMENT --
    un autre produit actif garde la date de 1er prélèvement normale,
    même avec une date d'effet future renseignée sur la ligne."""
    row = _base_row(**{
        "Optilife": 0,
        "MYJURIS & MYHOSPI": 19.90,
        "Total frais de dossier": 20.0,
        "Date d'effet du nouveau contrat (OPTILIFE)": "15/12/2026",
    })
    result = generate_mandats([row], PrelevementRules(), today=date(2026, 9, 21))
    assert result.ooff[0].date_premiere_echeance == "24/09/2026"  # inchangé, pas de +1 mois


def test_generate_mandats_decalage_remise_shifts_smaller_mandats_by_month():
    """Décalage remise (demande du père de Raphaël, 2026-09-22, questions
    posées et confirmées) : si un contrat a plusieurs mandats, celui au
    montant FRST le plus élevé garde sa date normale, les autres
    décalent d'un mois de plus chacun, dans l'ordre décroissant du
    montant. Le décalage se répercute sur la ligne RCUR correspondante
    (réponse confirmée : "décaler pareil les RCUR")."""
    row = _base_row(**{
        "Optilife": 0,  # évite la règle date d'effet, qui ajoute déjà +1 mois
        "Carte MGS": 99.0,  # le plus gros montant FRST (99+20=119) -> garde sa date
        "MYJURIS & MYHOSPI": 19.90,  # le plus petit (19.90+20=39.90) -> décale +1 mois
        "Total frais de dossier": 40.0,
    })
    result = generate_mandats([row], PrelevementRules(), today=date(2026, 9, 21))
    by_motif = {m.motif: m for m in result.ooff}
    assert by_motif["MGS-RUM000001-M"].date_premiere_echeance == "24/09/2026"  # inchangé
    assert by_motif["MGS-RUM000001-J"].date_premiere_echeance == "24/10/2026"  # +1 mois
    # La ligne RCUR correspondante suit le même décalage.
    by_motif_rcur = {m.motif: m for m in result.rcur}
    assert by_motif_rcur["MGS-RUM000001-J"].date_premiere_echeance == "24/11/2026"  # 24/10 + 1 mois (périodicité)


def test_generate_mandats_decalage_remise_ties_broken_by_canonical_product_order():
    """Égalité de montant FRST entre deux mandats -> départagé par
    l'ordre canonique des produits dans le moteur (Optilife, Carte MGS,
    MYJURIS...) -- réponse confirmée du père de Raphaël. Optilife (rang
    0) garde sa date, Carte MGS (rang 1) décale."""
    row = _base_row(**{
        "Optilife": 50.0,
        "Carte MGS": 50.0,  # même montant brut qu'Optilife
        "Total frais de dossier": 40.0,
    })
    result = generate_mandats([row], PrelevementRules(), today=date(2026, 9, 21))
    by_motif = {m.motif: m for m in result.ooff}
    # Optilife (rang 0, mandat ANCRE) applique aussi la règle "date
    # d'effet" (+1 mois, pas de date d'effet renseignée) -- 24/09/2026 +
    # 1 mois = 24/10/2026, gardée telle quelle (rang 0 = pas de décalage
    # supplémentaire).
    assert by_motif["MGS-RUM000001-O"].date_premiere_echeance == "24/10/2026"
    # Carte MGS (rang 1, montant égal) décale d'un mois DEPUIS LA DATE DE
    # L'ANCRE (24/10 + 1 mois), pas depuis sa propre date de base --
    # sinon elle retomberait par coïncidence sur la même date qu'Optilife
    # (24/09 + 1 = 24/10), ce qui annulerait l'objectif de la règle.
    assert by_motif["MGS-RUM000001-M"].date_premiere_echeance == "24/11/2026"


def test_generate_mandats_decalage_remise_no_shift_for_single_mandat():
    """Un seul mandat actif sur le contrat -> aucun décalage, même règle
    qu'avant cette fonctionnalité."""
    row = _base_row(**{"Optilife": 0, "Carte MGS": 99.0, "Total frais de dossier": 20.0})
    result = generate_mandats([row], PrelevementRules(), today=date(2026, 9, 21))
    assert result.ooff[0].date_premiere_echeance == "24/09/2026"


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
    # 10/09/2026 (date de premier prélèvement d'origine, vérifiée contre
    # le fichier réel avant l'ajout de la règle "date d'effet" du
    # 2026-09-22) + 1 mois -- Optilife actif sans date d'effet
    # renseignée applique désormais ce décalage (voir generate_mandats).
    assert mandat.date_premiere_echeance == "10/10/2026"
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
