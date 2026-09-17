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
