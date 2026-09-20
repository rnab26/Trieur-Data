"""Teste stream_excel_sheets (trieur/io_excel.py) -- le lecteur EN FLUX
utilisé pour les gros fichiers (voir PIPELINE_STREAM_THRESHOLD_BYTES,
api/main.py). Deux exigences : (1) mêmes résultats que le chemin
classique (read_excel_all_sheets_from_file) sur un même fichier, pour ne
jamais diverger silencieusement entre les deux modes ; (2) mémoire
réellement bornée sur un fichier significatif -- pas supposé, mesuré."""
import datetime
import io
import resource

import pandas as pd
import pytest

from trieur.io_excel import read_excel_all_sheets_from_file, stream_excel_sheets


def _xlsx_bytes(df, sheet_name="Feuil1", header=True):
    buf = io.BytesIO()
    df.to_excel(buf, index=False, header=header, sheet_name=sheet_name)
    return buf.getvalue()


def _collect(gen):
    """Consomme le générateur (nom, colonnes, n_dup, itérateur) en
    {nom: (colonnes, n_dup, [lignes])} pour comparer facilement."""
    out = {}
    for name, columns, n_dup, row_iter in gen:
        out[name] = (columns, n_dup, list(row_iter))
    return out


def test_stream_excel_sheets_avec_entete_normale():
    data = _xlsx_bytes(pd.DataFrame({
        "NOM": ["Dupont", "Martin"], "EMAIL": ["a@x.fr", "b@x.fr"],
    }))
    result = _collect(stream_excel_sheets(io.BytesIO(data)))

    assert list(result.keys()) == ["Feuil1"]
    columns, n_dup, rows = result["Feuil1"]
    assert columns == ["NOM", "EMAIL"]
    assert n_dup == 0
    assert rows == [
        {"NOM": "Dupont", "EMAIL": "a@x.fr"},
        {"NOM": "Martin", "EMAIL": "b@x.fr"},
    ]


def test_stream_excel_sheets_sans_entete_deduit_les_colonnes_comme_le_chemin_classique():
    """Même fichier, même résultat final que
    read_excel_all_sheets_from_file + apply_header_inference_excel."""
    from trieur.io_excel import apply_header_inference_excel

    df = pd.DataFrame([
        ["Dupont", "j.dupont@mail.fr", "0612345678", "75001"],
        ["Martin", "p.martin@mail.fr", "0698765432", "33000"],
        ["Durand", "a.durand@mail.fr", "0655443322", "02100"],
    ])
    data = _xlsx_bytes(df, sheet_name="Leads", header=False)

    classic = read_excel_all_sheets_from_file(io.BytesIO(data), "sans_entete.xlsx")
    classic, inferred = apply_header_inference_excel(classic, io.BytesIO(data))
    classic_df = classic["Leads"]

    streamed = _collect(stream_excel_sheets(io.BytesIO(data)))
    columns, n_dup, rows = streamed["Leads"]

    assert inferred == ["Leads"]  # confirme que le chemin classique a bien dû deviner
    assert columns == list(classic_df.columns)
    assert len(rows) == len(classic_df) == 3
    assert [r[columns[0]] for r in rows] == list(classic_df[columns[0]])


def test_stream_excel_sheets_plusieurs_onglets():
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        pd.DataFrame({"NOM": ["a"], "EMAIL": ["a@x.fr"]}).to_excel(w, index=False, sheet_name="Contacts")
        pd.DataFrame({"VILLE": ["Paris", "Lyon"]}).to_excel(w, index=False, sheet_name="Villes")
    data = buf.getvalue()

    result = _collect(stream_excel_sheets(io.BytesIO(data)))

    assert set(result.keys()) == {"Contacts", "Villes"}
    assert result["Contacts"][2] == [{"NOM": "a", "EMAIL": "a@x.fr"}]
    assert result["Villes"][2] == [{"VILLE": "Paris"}, {"VILLE": "Lyon"}]


def test_stream_excel_sheets_onglet_vide_ignore():
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        pd.DataFrame({"NOM": ["a"]}).to_excel(w, index=False, sheet_name="Plein")
        pd.DataFrame().to_excel(w, index=False, sheet_name="Vide")
    data = buf.getvalue()

    result = _collect(stream_excel_sheets(io.BytesIO(data)))

    assert list(result.keys()) == ["Plein"]


def test_stream_excel_sheets_types_convertis_comme_pandas_dtype_str():
    """Vérifié en amont (mesure manuelle) : str(valeur) matche
    pandas(dtype=str) sur les types courants -- nombres entiers,
    décimaux, dates. Ce test fige ce contrat."""
    buf = io.BytesIO()
    pd.DataFrame({
        "MONTANT": [123.45, 100],
        "DATE": [datetime.date(2024, 1, 15), datetime.datetime(2024, 3, 1, 10, 30)],
        "CP": [75001, 33000],
    }).to_excel(buf, index=False, sheet_name="Feuil1")
    data = buf.getvalue()

    classic = pd.read_excel(io.BytesIO(data), dtype=str, engine="openpyxl")
    streamed = _collect(stream_excel_sheets(io.BytesIO(data)))
    _columns, _n_dup, rows = streamed["Feuil1"]

    for i, row in enumerate(rows):
        for col in classic.columns:
            assert row[col] == classic.iloc[i][col], f"col={col} row={i}"


def test_stream_excel_sheets_duplicates_comptes_sur_echantillon():
    buf = io.BytesIO()
    pd.DataFrame({"NOM": ["Dupont", "Dupont", "Martin"]}).to_excel(buf, index=False, sheet_name="Feuil1")
    data = buf.getvalue()

    result = _collect(stream_excel_sheets(io.BytesIO(data)))
    _columns, n_dup, _rows = result["Feuil1"]

    assert n_dup == 1


def test_stream_excel_sheets_memoire_bornee_sur_un_fichier_significatif():
    """Mesure réelle (pas supposée) : un fichier de ~50 000 lignes ne doit
    pas faire grimper le pic mémoire au-delà de quelques dizaines de Mo au
    DELTA (contre ~45x la taille du fichier mesuré sur le chemin
    classique en conditions réelles Render) -- consommé en flux, jamais
    matérialisé entièrement."""
    n = 50_000
    df = pd.DataFrame({
        "NOM": [f"NOM{i}" for i in range(n)],
        "EMAIL": [f"user{i}@example.com" for i in range(n)],
        "TELEPHONE": [f"06{i:08d}" for i in range(n)],
    })
    data = _xlsx_bytes(df)

    import gc
    gc.collect()
    before_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    total_rows = 0
    for _name, _columns, _n_dup, row_iter in stream_excel_sheets(io.BytesIO(data)):
        for _row in row_iter:
            total_rows += 1

    after_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    delta_mb = (after_kb - before_kb) / 1024

    assert total_rows == n
    # Généreux (le process porte déjà pandas/openpyxl importés) : le vrai
    # test est que ça reste très en-dessous du ratio ~45x mesuré côté
    # chemin classique (qui aurait donné plusieurs centaines de Mo ici).
    assert delta_mb < 150, f"delta mémoire trop élevé : {delta_mb:.1f} Mo pour {n} lignes"
