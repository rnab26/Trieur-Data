# =============================================================
# trieur/io_pdf.py
# Import des PDF de prelevements SEPA (format stable Hub Business Solutions).
# Renvoie ({ "PDF": DataFrame }, []) pour s'integrer au meme flux que le CSV.
# Le Montant est renvoye en NOMBRE (float, ex: 41.66) et non en texte.
# =============================================================

import re

import pandas as pd

try:
    import pdfplumber
except Exception:  # pragma: no cover
    pdfplumber = None


PDF_SEPA_COLUMNS = [
    "Prélevés",
    "Référence bancaire",
    "Numéro de mandat",
    "Ref. End-to-End",
    "Montant",
    "Libellé",
    "DATE EXECUTION",
]

_DATE_RE = re.compile(r"Date d['\u2019\u02bc]ex[eé]cution\s*:??\s*(\d{2}/\d{2}/\d{4})")


def _clean_cell(value):
    """Nettoie une cellule : retours ligne -> espace, espaces multiples reduits."""
    if value is None:
        return ""
    return " ".join(str(value).split()).strip()


def _parse_montant(value):
    """
    Convertit un montant francais texte en NOMBRE.
      "41,66 EUR"    -> 41.66
      "1 234,56 EUR" -> 1234.56
    Retourne None si non convertible.
    """
    if value is None:
        return None
    s = str(value).upper().replace("EUR", "")
    s = s.replace("\u00a0", "").replace(" ", "").strip()
    if not s:
        return None
    s = s.replace(".", "").replace(",", ".")
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def read_pdf_sepa(file_obj, filename):
    """
    Lit un PDF de prelevements SEPA et renvoie (sheets, inferred) :
      - sheets   : { "PDF": DataFrame }  (toutes les pages fusionnees)
      - inferred : []  (en-tetes connues)
    La colonne Montant est numerique (float). DATE EXECUTION reprend la date
    d'execution de la page. Retourne ({}, []) si aucune ligne exploitable.
    """
    if pdfplumber is None:
        return {}, []

    rows = []
    try:
        try:
            file_obj.seek(0)
        except Exception:
            pass

        with pdfplumber.open(file_obj) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                m = _DATE_RE.search(text)
                date_exec = m.group(1) if m else ""

                for table in (page.extract_tables() or []):
                    if not table or not table[0]:
                        continue
                    header = [_clean_cell(c) for c in table[0]]
                    if not any("Prélev" in h for h in header):
                        continue

                    for raw in table[1:]:
                        cells = [_clean_cell(c) for c in raw]
                        if not any(cells):
                            continue
                        joined = " ".join(cells)
                        if "Nombre de pr" in joined:
                            continue
                        cells = (cells + [""] * 6)[:6]
                        rows.append(cells + [date_exec])
    except Exception:
        return {}, []

    if not rows:
        return {}, []

    df = pd.DataFrame(rows, columns=PDF_SEPA_COLUMNS)
    df["Montant"] = df["Montant"].map(_parse_montant)
    return {"PDF": df}, []
