import io
from contextlib import contextmanager

import pandas as pd

import trieur.io_excel as IOE
from trieur.export import sanitize_filename
from trieur.io_excel import (
    apply_header_inference_excel,
    is_google_sheet_url,
    read_excel_all_sheets_from_file,
    read_google_sheets_all_sheets,
    _extract_sheet_id,
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


def test_extract_sheet_id():
    assert _extract_sheet_id("https://docs.google.com/spreadsheets/d/1AbCdEf/edit#gid=0") == "1AbCdEf"
    assert _extract_sheet_id("https://docs.google.com/spreadsheets/d/1AbCdEf") == "1AbCdEf"
    assert _extract_sheet_id("https://docs.google.com/spreadsheets/d/1AbCdEf/") == "1AbCdEf"
    assert _extract_sheet_id("https://docs.google.com/spreadsheets/") is None


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


def _fake_urlopen_returning(payload, content_disposition=""):
    """Fabrique un remplacant de urllib.request.urlopen qui renvoie payload."""
    @contextmanager
    def _fake(url, timeout=None):
        class R:
            headers = {"Content-Disposition": content_disposition}

            def read(self):
                return payload
        yield R()
    return _fake


def test_google_sheets_via_xlsx_une_seule_requete(monkeypatch):
    # Vrai classeur xlsx en memoire (2 onglets)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as w:
        pd.DataFrame({"NOM": ["a"], "EMAIL": ["a@x.fr"]}).to_excel(w, index=False, sheet_name="Contacts")
        pd.DataFrame({"VILLE": ["Paris"]}).to_excel(w, index=False, sheet_name="Villes")
    payload = buf.getvalue()

    monkeypatch.setattr(
        IOE.urllib.request, "urlopen",
        _fake_urlopen_returning(payload, content_disposition='attachment; filename="AZ.xlsx"'),
    )
    sheets, inferred, name = read_google_sheets_all_sheets(
        "https://docs.google.com/spreadsheets/d/ABC123/edit"
    )
    assert set(sheets.keys()) == {"Contacts", "Villes"}   # vrais noms d'onglets
    assert "NOM" in sheets["Contacts"].columns
    assert name == "AZ"                                    # vrai nom du classeur


def test_name_from_content_disposition():
    f = IOE._name_from_content_disposition
    assert f('attachment; filename="AZ.xlsx"; filename*=UTF-8\'\'AZ.xlsx') == "AZ"
    assert f('attachment; filename="Mes Leads 2026.xlsx"') == "Mes Leads 2026"
    assert f("") is None


def test_google_sheets_repli_si_pas_un_xlsx(monkeypatch):
    # Google renvoie une page HTML (acces refuse) -> pas de 'PK' -> repli CSV.
    monkeypatch.setattr(IOE.urllib.request, "urlopen",
                        _fake_urlopen_returning(b"<html>error</html>"))
    # Le repli CSV echoue hors-ligne : on verifie surtout qu'il n'y a pas de crash.
    monkeypatch.setattr(IOE.pd, "read_csv",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    sheets, inferred, _name = read_google_sheets_all_sheets(
        "https://docs.google.com/spreadsheets/d/ABC123/edit"
    )
    assert sheets == {}
    assert inferred == []
