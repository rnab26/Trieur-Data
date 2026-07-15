import io

import pandas as pd

from trieur.export import sanitize_filename
from trieur.io_excel import (
    apply_header_inference_excel,
    is_google_sheet_url,
    read_excel_all_sheets_from_file,
)


class FakeUpload(io.BytesIO):
    """Imite un fichier uploade Streamlit (attributs .name et .size)."""

    def __init__(self, data, name):
        super().__init__(data)
        self.name = name
        self.size = len(data)


def test_is_google_sheet_url():
    assert is_google_sheet_url("https://docs.google.com/spreadsheets/d/abc/edit") is True
    assert is_google_sheet_url("https://example.com/x.xlsx") is False
    assert is_google_sheet_url("") is False


def test_sanitize_filename():
    assert sanitize_filename("mon export") == "mon export"
    assert sanitize_filename("leads.csv") == "leads"
    assert sanitize_filename('a/b:c*d') == "a_b_c_d"
    assert sanitize_filename("") == "export_leads"


def test_lecture_excel_avec_entete_inchangee():
    buf = io.BytesIO()
    pd.DataFrame({
        "NOM": ["a", "b"], "PRENOM": ["c", "d"],
        "EMAIL": ["e@x.fr", "f@x.fr"], "CP": ["75001", "33000"],
    }).to_excel(buf, index=False, sheet_name="Feuil1")
    buf.seek(0)
    up = FakeUpload(buf.getvalue(), "avec_entete.xlsx")

    sheets = read_excel_all_sheets_from_file(up, up.name)
    cols_avant = list(sheets["Feuil1"].columns)
    sheets, inferred = apply_header_inference_excel(sheets, up)

    assert inferred == []                                   # aucune deduction
    assert list(sheets["Feuil1"].columns) == cols_avant     # colonnes intactes
    assert len(sheets["Feuil1"]) == 2                       # lignes intactes


def test_lecture_excel_sans_entete_recupere_la_premiere_ligne():
    buf = io.BytesIO()
    pd.DataFrame([
        ["Dupont", "j.dupont@mail.fr", "0612345678", "75001"],
        ["Martin", "p.martin@mail.fr", "0698765432", "33000"],
        ["Durand", "a.durand@mail.fr", "0655443322", "02100"],
    ]).to_excel(buf, index=False, header=False, sheet_name="Leads")
    buf.seek(0)
    up = FakeUpload(buf.getvalue(), "sans_entete.xlsx")

    sheets = read_excel_all_sheets_from_file(up, up.name)
    n_avant = len(sheets["Leads"])                          # 2 : 1re ligne prise comme entete
    sheets, inferred = apply_header_inference_excel(sheets, up)
    df = sheets["Leads"]

    assert inferred == ["Leads"]
    assert len(df) == 3 and len(df) > n_avant               # le lead Dupont est recupere
    assert "Dupont" in df.iloc[:, 0].tolist()
    assert "EMAIL" in df.columns and "TELEPHONE MOBILE" in df.columns and "CP" in df.columns
