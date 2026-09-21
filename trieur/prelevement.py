"""Génération des mandats de prélèvement SEPA (environnement Prélèvement).

Règles reconstruites à partir des 3 fichiers Excel de référence + le
classeur Drive historique que Raphaël a fournis (2026-09-21), et
confirmées avec lui question par question -- voir PROJECT_LOG.md pour
le détail. Chaque règle ici correspond à une formule ou une décision
du fichier Excel d'origine du père de Raphaël ; ne rien changer sans
l'avoir revérifié avec lui, c'est un domaine "zéro droit à l'erreur".

Portée de cette première version (Raphaël a explicitement demandé de
NE PAS faire plus pour l'instant) :
- prend un export CRM brut (mêmes colonnes que le fichier "1_récupération
  du CRM") ;
- nettoie/valide chaque ligne, calcule les dates et le montant ;
- classe chaque client en OOFF (1er prélèvement, avec frais de dossier)
  ou RCUR (prélèvement récurrent, sans frais de dossier) ;
- exclut proprement (avec la raison) tout ce qui ne peut pas partir en
  banque.

PAS dans cette version (chantier séparé, voir Cockpit "Historique,
doublons, impayés et relevé bancaire") : comparaison à l'historique
des remises passées, détection de doublons/noms inversés, suivi des
impayés, réconciliation du relevé bancaire.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

# ---------------------------------------------------------------
# Colonnes attendues dans l'export CRM (mêmes noms que le fichier Excel
# de référence -- espaces superflus compris, volontairement pas
# nettoyés à la source pour rester reconnaissable si Raphaël compare
# avec l'original). `_norm_key` ci-dessous absorbe ces espaces à la
# lecture, donc l'ordre/l'espacement exact du fichier importé n'a pas
# besoin d'être identique au caractère près.
# ---------------------------------------------------------------

COL_NOM = "Nom complet"
COL_REFERENCE = "Référence du client"
COL_RUM = "RUM"
COL_STATUT = "Statut"
COL_TYPE_PRELEVEMENT = "Type de prélèvement"
COL_PERIODICITE = "Périodicité (Mensuel/trimestre/annuel)"
COL_IBAN = "IBAN"
COL_BIC = "BIC"
COL_DATE_PREMIER = "Date de premier prélèvement"
COL_DATE_CREATION = "Date création"
COL_ADRESSE = "Adresse"
COL_VILLE = "Ville"
COL_CODE_POSTAL = "Code postal"
COL_EMAIL = "Email"
COL_TELEPHONE = "Téléphone"

# Colonnes produit -- montants en euros. "Optivie" est fusionné dans
# "Optilife" (Raphaël, 2026-09-21 : "les deux mêmes produits avec les
# deux mêmes règles d'utilisation"). "Contrat MYMO casse & perte
# appareil auditif" est délibérément IGNORÉ (Raphaël : "je ne la prends
# pas en compte pour l'instant") -- jamais additionné, jamais dans le
# motif.
COL_OPTILIFE = "Optilife"
COL_OPTIVIE = "Optivie"
COL_CARTE_MGS = "Carte MGS"
COL_MYJURIS = "MYJURIS & MYHOSPI"
COL_ADMIN_AIDE = "Admin & Aide a dom"
COL_AUDITIF = "Auditif"
COL_IMMO = "IMMO"
COL_VETO = "Total cotisation MYMO VETO SUR"
COL_TOTAL_FRAIS = "Total frais de dossier"
COL_TOTAL_COTIS_FRAIS = "Total cotisation et frais de dossier"

# Suffixe du motif par produit -- ordre et lettres copiés de la formule
# `="MGS-"&RUM&IF(Optilife>0,"-O","")&IF(CarteMGS>0,"-M","")&...` du
# fichier "3_creations_des_mandats" (onglet "3 Sheet1", colonne Motif).
_MOTIF_SUFFIXES: list[tuple[str, str]] = [
    (COL_OPTILIFE, "-O"),
    (COL_CARTE_MGS, "-M"),
    (COL_MYJURIS, "-J"),
    (COL_ADMIN_AIDE, "-AD"),
    (COL_AUDITIF, "-AU"),
    (COL_IMMO, "-IM"),
    (COL_VETO, "-V"),
]


def _norm_key(s: str) -> str:
    """Espaces (y compris multiples/en fin de chaîne) et casse ignorés --
    les en-têtes du fichier Excel d'origine ont des espaces parasites
    (ex. "IBAN  ", "Référence du client ") qu'un import réel ne
    reproduira pas forcément à l'identique."""
    return re.sub(r"\s+", " ", s or "").strip().lower()


@dataclass
class PrelevementRules:
    """Réglages ajustables sans toucher au code -- stockés par
    organisation dans trieur_data.prelevement_rules, jamais codés en
    dur dans ce module."""

    ics: str | None = None
    nature: str = "CORE"
    delay_days: int = 3


@dataclass
class MandatRow:
    reference_client: str
    nom: str
    rum: str
    iban: str
    bic: str
    adresse: str
    ville: str
    code_postal: str
    pays: str
    email: str
    telephone: str
    type_sequence: str  # "FRST" (OOFF) ou "RCUR"
    montant_eur: float
    devise: str
    date_signature_mandat: str
    date_premiere_echeance: str
    periodicite: str
    explication_periodicite: str
    motif: str


@dataclass
class ExclusionRow:
    reference_client: str
    nom: str
    raison: str


@dataclass
class GenerationResult:
    ooff: list[MandatRow] = field(default_factory=list)
    rcur: list[MandatRow] = field(default_factory=list)
    exclus: list[ExclusionRow] = field(default_factory=list)


def normalize_iban(raw: object) -> str:
    """Retire tous les espaces, met en majuscules -- règle donnée par
    Raphaël (2026-09-21) : "le seul correctif qu'on fait sur l'IBAN
    c'est supprimer les blancs entre les chiffres et changer le fr
    minuscule en FR majuscule"."""
    if raw is None:
        return ""
    return re.sub(r"\s+", "", str(raw)).upper()


def iban_checksum_valid(iban: str) -> bool:
    """Contrôle mod-97 (ISO 7064 MOD 97-10) -- le VRAI calcul de
    validité d'un IBAN, pas juste "il y a quelque chose". Reproduit la
    colonne "IBAN ctrl" du fichier de référence (onglet "3 Sheet1"),
    qui fait le même calcul en plusieurs cellules à la suite."""
    iban = normalize_iban(iban)
    if len(iban) < 15 or not re.fullmatch(r"[A-Z]{2}[0-9]{2}[A-Z0-9]+", iban):
        return False
    rearranged = iban[4:] + iban[:4]
    digits = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(digits) % 97 == 1


def pad_bic(raw: object) -> str:
    """BIC à 8 caractères -> complété à 11 avec "XXX" (code d'agence
    générique), comme la formule `IF(LEN(bic)=8,UPPER(bic)&"XXX",...)`
    du fichier de référence -- un BIC à 11 caractères est déjà complet,
    laissé tel quel (juste mis en majuscules)."""
    if raw is None:
        return ""
    bic = str(raw).strip().upper()
    return bic + "XXX" if len(bic) == 8 else bic


def to_amount(raw: object) -> float:
    """Convertit un montant qui peut arriver en texte avec virgule OU
    point comme séparateur décimal (l'export CRM d'origine mélange les
    deux selon les colonnes -- la formule Excel de référence fait
    `SUBSTITUTE(valeur,".",",")* 1` pour forcer la conversion). Une
    valeur vide/invalide vaut 0, jamais une erreur bloquante : un
    montant manquant sur UN produit ne doit pas faire échouer toute la
    ligne du client."""
    if raw is None or raw == "":
        return 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip().replace(" ", "")
    if not text:
        return 0.0
    # Un seul séparateur présent -> c'est le séparateur décimal, quel
    # qu'il soit. Les deux présents -> celui qui vient en dernier est
    # le décimal (l'autre est un séparateur de milliers).
    if "," in text and "." in text:
        text = text.replace(",", "") if text.rfind(".") > text.rfind(",") else text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return 0.0


def _parse_date(raw: object) -> date | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    text = str(raw).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def compute_first_prelevement_date(raw_scheduled: object, today: date, delay_days: int) -> date | None:
    """La date du 1er prélèvement n'est JAMAIS avant aujourd'hui +
    délai (3 jours par défaut, toujours le même -- confirmé par
    Raphaël) : `MAX(TODAY()+3, date_prévue)` dans le fichier de
    référence. Si aucune date n'était prévue au départ, retourne None
    -- ce cas est exclu du lot par `generate_mandats` plutôt que
    d'inventer une date."""
    scheduled = _parse_date(raw_scheduled)
    if scheduled is None:
        return None
    plancher = today + timedelta(days=delay_days)
    return max(plancher, scheduled)


def build_motif(rum: str, amounts: dict[str, float]) -> str:
    """"MGS-{RUM}" + un suffixe par produit facturé -- reproduit la
    formule Motif du fichier de référence (onglet "3 Sheet1")."""
    motif = f"MGS-{rum}"
    for col, suffix in _MOTIF_SUFFIXES:
        if amounts.get(col, 0.0) > 0:
            motif += suffix
    return motif


def _get(row: dict, col: str, keyed: dict[str, str]) -> object:
    key = keyed.get(_norm_key(col))
    return row.get(key) if key is not None else None


def generate_mandats(rows: list[dict], rules: PrelevementRules, today: date | None = None) -> GenerationResult:
    """Traite chaque ligne de l'export CRM brut et la range dans OOFF,
    RCUR, ou "exclus" avec la raison. Ne lève jamais d'exception sur
    une ligne individuelle mal formée -- elle part en exclusion avec la
    raison, le reste du lot continue (un fichier de 300 clients ne doit
    pas échouer en entier à cause d'une seule ligne cassée)."""
    today = today or date.today()
    result = GenerationResult()
    if not rows:
        return result

    # Colonnes réellement présentes dans CE fichier, normalisées --
    # construit une fois, pas à chaque ligne.
    keyed = {_norm_key(c): c for c in rows[0].keys()}

    for row in rows:
        ref_client = str(_get(row, COL_REFERENCE, keyed) or "")
        nom = str(_get(row, COL_NOM, keyed) or "")

        def exclure(raison: str) -> None:
            result.exclus.append(ExclusionRow(reference_client=ref_client, nom=nom, raison=raison))

        type_prelevement = str(_get(row, COL_TYPE_PRELEVEMENT, keyed) or "").strip()
        if type_prelevement.lower() != "prélèvement":
            exclure(f"Mode de paiement \"{type_prelevement or 'non renseigné'}\", pas un prélèvement SEPA")
            continue

        iban = normalize_iban(_get(row, COL_IBAN, keyed))
        if not iban or not iban_checksum_valid(iban):
            exclure("IBAN manquant ou invalide")
            continue

        rum = str(_get(row, COL_RUM, keyed) or "").strip()
        if not rum:
            exclure("RUM manquant")
            continue

        date_premiere = compute_first_prelevement_date(
            _get(row, COL_DATE_PREMIER, keyed), today, rules.delay_days,
        )
        if date_premiere is None:
            exclure("Pas de date de premier prélèvement renseignée")
            continue

        optilife_optivie = to_amount(_get(row, COL_OPTILIFE, keyed)) + to_amount(_get(row, COL_OPTIVIE, keyed))
        amounts = {
            COL_OPTILIFE: optilife_optivie,
            COL_CARTE_MGS: to_amount(_get(row, COL_CARTE_MGS, keyed)),
            COL_MYJURIS: to_amount(_get(row, COL_MYJURIS, keyed)),
            COL_ADMIN_AIDE: to_amount(_get(row, COL_ADMIN_AIDE, keyed)),
            COL_AUDITIF: to_amount(_get(row, COL_AUDITIF, keyed)),
            COL_IMMO: to_amount(_get(row, COL_IMMO, keyed)),
            COL_VETO: to_amount(_get(row, COL_VETO, keyed)),
        }

        total_frais = to_amount(_get(row, COL_TOTAL_FRAIS, keyed))
        total_cotis_frais = to_amount(_get(row, COL_TOTAL_COTIS_FRAIS, keyed))
        if total_cotis_frais <= 0:
            exclure("Montant à prélever nul ou absent")
            continue

        # OOFF (1er prélèvement, avec frais de dossier) vs RCUR
        # (récurrent, sans frais) -- règle donnée par Raphaël
        # (2026-09-21) : "le montant est différent pour les autres
        # prélèvements [...] moins élevé avec le montant des frais en
        # moins".
        if total_frais > 0:
            type_sequence = "FRST"
            montant = total_cotis_frais
        else:
            type_sequence = "RCUR"
            montant = total_cotis_frais - total_frais  # frais=0 ici, mais explicite plutôt que réutiliser total_cotis_frais

        # Date de signature du mandat = la date de création du contrat
        # dans le CRM, PAS la date à laquelle ce fichier est généré --
        # vérifié contre le fichier de référence (2026-09-21) : un
        # client créé le 21/08 garde cette date, même généré des
        # semaines après. Repli sur aujourd'hui seulement si absente.
        date_signature = _parse_date(_get(row, COL_DATE_CREATION, keyed)) or today

        # "Explication périodicité" (ex. "Tous les 1 mois") : laissée
        # vide pour un 1er prélèvement (FRST) -- elle ne décrit que la
        # récurrence des prélèvements SUIVANTS, vérifié contre le
        # fichier de référence.
        explication = "" if type_sequence == "FRST" else _explication_periodicite(
            _get(row, COL_PERIODICITE, keyed),
        )

        mandat = MandatRow(
            reference_client=ref_client,
            nom=nom,
            rum=rum,
            iban=iban,
            bic=pad_bic(_get(row, COL_BIC, keyed)),
            adresse=str(_get(row, COL_ADRESSE, keyed) or ""),
            ville=str(_get(row, COL_VILLE, keyed) or ""),
            code_postal=str(_get(row, COL_CODE_POSTAL, keyed) or ""),
            pays="FR",
            email=str(_get(row, COL_EMAIL, keyed) or ""),
            telephone=str(_get(row, COL_TELEPHONE, keyed) or ""),
            type_sequence=type_sequence,
            montant_eur=round(montant, 2),
            devise="EUR",
            date_signature_mandat=date_signature.strftime("%d/%m/%Y"),
            date_premiere_echeance=date_premiere.strftime("%d/%m/%Y"),
            periodicite=str(_get(row, COL_PERIODICITE, keyed) or ""),
            explication_periodicite=explication,
            motif=build_motif(rum, amounts),
        )
        (result.ooff if type_sequence == "FRST" else result.rcur).append(mandat)

    return result


_PERIODICITE_EXPLICATIONS = {
    "mensuelle": "Tous les 1 mois",
    "bimestrielle": "Tous les 2 mois",
    "trimestrielle": "Tous les 3 mois",
    "semestrielle": "Tous les 6 mois",
    "annuel": "Tous les 12 mois",
    "annuelle": "Tous les 12 mois",
}


def _explication_periodicite(raw: object) -> str:
    return _PERIODICITE_EXPLICATIONS.get(str(raw or "").strip().lower(), "")
