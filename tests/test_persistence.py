import trieur.persistence as P


def test_load_saved_filters_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "FILTERS_CONFIG_PATH", str(tmp_path / "none.json"))
    assert P.load_saved_filters() == []


def test_save_puis_load_filtres(tmp_path, monkeypatch):
    path = str(tmp_path / "saved_filters.json")
    monkeypatch.setattr(P, "FILTERS_CONFIG_PATH", path)
    filtres = [
        {"name": "Sud-Ouest", "column": "CP", "kind": "departements", "values": ["33", "40", "64"]},
        {"name": "Grandes villes", "column": "VILLE", "kind": "valeurs", "values": ["Paris", "Lyon"]},
    ]
    assert P.save_saved_filters(filtres) is True
    rel = P.load_saved_filters()
    assert rel == filtres


def test_les_filtres_invalides_sont_ignores(tmp_path, monkeypatch):
    path = str(tmp_path / "saved_filters.json")
    monkeypatch.setattr(P, "FILTERS_CONFIG_PATH", path)
    mixte = [
        {"name": "OK", "column": "CP", "kind": "departements", "values": ["75"]},
        {"name": "", "column": "CP", "kind": "departements", "values": ["75"]},   # nom vide
        {"name": "X", "column": "CP", "kind": "autre", "values": []},              # kind invalide
        {"name": "Y", "column": "CP", "kind": "valeurs", "values": "pasuneliste"}, # values non liste
        "pas un dict",
    ]
    P.save_saved_filters(mixte)
    rel = P.load_saved_filters()
    assert len(rel) == 1
    assert rel[0]["name"] == "OK"


def test_is_valid_filter():
    assert P._is_valid_filter({"name": "a", "column": "CP", "kind": "valeurs", "values": []}) is True
    assert P._is_valid_filter({"name": "a", "column": "CP", "kind": "x", "values": []}) is False
    assert P._is_valid_filter({"name": "", "column": "CP", "kind": "valeurs", "values": []}) is False
    assert P._is_valid_filter({}) is False


def test_load_export_presets_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "EXPORT_PRESETS_PATH", str(tmp_path / "none.json"))
    assert P.load_export_presets() == []


def test_save_puis_load_export_presets(tmp_path, monkeypatch):
    path = str(tmp_path / "export_presets.json")
    monkeypatch.setattr(P, "EXPORT_PRESETS_PATH", path)
    presets = [
        {"name": "Rapport banque", "included": ["NOM", "Référence bancaire"], "excluded": ["EMAIL"]},
    ]
    assert P.save_export_presets(presets) is True
    assert P.load_export_presets() == presets


def test_les_presets_export_invalides_sont_ignores(tmp_path, monkeypatch):
    path = str(tmp_path / "export_presets.json")
    monkeypatch.setattr(P, "EXPORT_PRESETS_PATH", path)
    mixte = [
        {"name": "OK", "included": ["NOM"], "excluded": []},
        {"name": "", "included": ["NOM"], "excluded": []},          # nom vide
        {"name": "X", "included": "pasuneliste", "excluded": []},   # included non liste
        "pas un dict",
    ]
    P.save_export_presets(mixte)
    rel = P.load_export_presets()
    assert len(rel) == 1
    assert rel[0]["name"] == "OK"


def test_is_valid_export_preset():
    assert P._is_valid_export_preset({"name": "a", "included": [], "excluded": []}) is True
    assert P._is_valid_export_preset({"name": "", "included": [], "excluded": []}) is False
    assert P._is_valid_export_preset({}) is False
