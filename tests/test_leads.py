"""Base Leads à très grand volume (chantier cockpit 6547bd6a) : logique Python (trieur/leads.py) et
routes (api/leads.py) avec un faux client Supabase, sans réseau. Les règles de données (normalisation,
dédoublonnage, comptes) sont testées dans la vraie base par scripts/verifier_leads_sql.py, et le trajet
complet API -> base par scripts/verifier_leads_api.py."""
import io
import os
import time
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api.main import app, get_current_ctx, get_supabase_client
from trieur import leads as L

REGL = {
    "lot_import": "4", "fenetre_blocs": "1000", "apercu_taille": "300", "apercu_blocs_max": "3000",
    "separateur_csv": ",", "export_pause_ms": "0", "import_max_mo": "1", "jeton_telechargement_s": "900",
    "silence_job_s": "120", "jobs_paralleles": "1", "doublons_exemples_max": "1000",
}


class FauxRpc:
    """Faux client : .postgrest.schema(s).rpc(nom, params).execute() -> handlers[nom](params)."""

    def __init__(self, handlers):
        self.handlers = handlers
        self.appels = []

    @property
    def postgrest(self):
        return self

    def schema(self, _):
        return self

    def rpc(self, nom, params=None):
        self.appels.append((nom, params))

        def _execute():
            h = self.handlers[nom]
            if isinstance(h, Exception):
                raise h
            return SimpleNamespace(data=h(params or {}) if callable(h) else h)

        return SimpleNamespace(execute=_execute)


class ErreurSql(Exception):
    def __init__(self, message, code=""):
        super().__init__(message)
        self.message = message
        self.code = code


def reglages_rpc(_params=None):
    return {k: {"valeur": v, "aide": ""} for k, v in REGL.items()}


# ---------------------------------------------------------------
# Colonnes d'un fichier
# ---------------------------------------------------------------

def test_reconnait_les_colonnes_maitres_leads_et_ignore_le_reste():
    cols = ["NOM", "PRENOM", "GENRE/CIVILITE", "VILLE", "CP", "ADRESSE", "TELEPHONE MOBILE", "TELEPHONE FIXE",
            "EMAIL", "DATE DE NAISSANCE", "Source Data", "Autre"]
    m, ignorees = L.reconnaitre_colonnes(cols)
    assert m == {"nom": "NOM", "prenom": "PRENOM", "civilite": "GENRE/CIVILITE", "ville": "VILLE", "cp": "CP",
                 "adresse": "ADRESSE", "tel_mobile": "TELEPHONE MOBILE", "tel_fixe": "TELEPHONE FIXE",
                 "email": "EMAIL", "naissance": "DATE DE NAISSANCE"}
    assert ignorees == ["Source Data", "Autre"]


def test_intitules_avec_accents_et_casse():
    m, _ = L.reconnaitre_colonnes(["Téléphone", "E-mail", "Code Postal", "Prénom"])
    assert m == {"tel_mobile": "Téléphone", "email": "E-mail", "cp": "Code Postal", "prenom": "Prénom"}


def test_sans_telephone_ni_email_refuse_avec_message_clair():
    m, _ = L.reconnaitre_colonnes(["NOM", "VILLE"])
    with pytest.raises(L.LeadsError) as e:
        L.verifier_mapping(m)
    assert e.value.status == 400 and "doublons" in e.value.message


def test_un_seul_email_suffit():
    L.verifier_mapping({"email": "mail"})


# ---------------------------------------------------------------
# Lecture de fichiers
# ---------------------------------------------------------------

def _ecrire(tmp_path, nom, contenu, encodage="utf-8"):
    p = tmp_path / nom
    p.write_bytes(contenu.encode(encodage))
    return str(p)


def test_csv_point_virgule_morceaux_et_reprise(tmp_path):
    lignes = "\n".join(f"Nom{i};06{i:08d};a{i}@x.fr" for i in range(10))
    chemin = _ecrire(tmp_path, "a.csv", "NOM;TELEPHONE MOBILE;EMAIL\n" + lignes + "\n")
    assert L.lire_entete(chemin, "a.csv") == ["NOM", "TELEPHONE MOBILE", "EMAIL"]
    assert L.compter_lignes(chemin, "a.csv") == 10
    tailles = [len(df) for df in L.morceaux(chemin, "a.csv", 4)]
    assert tailles == [4, 4, 2]
    reprise = list(L.morceaux(chemin, "a.csv", 4, a_sauter=6))
    assert sum(len(d) for d in reprise) == 4 and reprise[0].iloc[0]["NOM"] == "Nom6"


def test_csv_latin1_et_cellules_vides_restent_du_texte(tmp_path):
    chemin = _ecrire(tmp_path, "b.csv", "NOM,EMAIL\nJosé,\nÉlise,e@x.fr\n", "cp1252")
    df = next(L.morceaux(chemin, "b.csv", 10))
    assert list(df["NOM"]) == ["José", "Élise"] and list(df["EMAIL"]) == ["", "e@x.fr"]


def test_excel_lu_par_morceaux(tmp_path):
    p = tmp_path / "c.xlsx"
    pd.DataFrame({"NOM": ["a", "b", "c"], "EMAIL": ["a@x.fr", "b@x.fr", "c@x.fr"]}).to_excel(p, index=False)
    assert L.lire_entete(str(p), "c.xlsx") == ["NOM", "EMAIL"]
    assert [len(d) for d in L.morceaux(str(p), "c.xlsx", 2)] == [2, 1]
    assert [len(d) for d in L.morceaux(str(p), "c.xlsx", 2, a_sauter=2)] == [1]


def test_charge_utile_ne_garde_que_les_colonnes_reconnues():
    df = pd.DataFrame({"N": ["x"], "M": ["0612345678"], "Z": ["inutile"]})
    assert L.charge_utile(df, {"nom": "N", "tel_mobile": "M"}) == [{"nom": "x", "tel_mobile": "0612345678"}]


# ---------------------------------------------------------------
# Import par lots
# ---------------------------------------------------------------

def _fichier_import(tmp_path, n=10):
    lignes = "\n".join(f"N{i},06{i:08d}" for i in range(n))
    return _ecrire(tmp_path, "i.csv", "NOM,TELEPHONE MOBILE\n" + lignes + "\n")


def test_import_envoie_des_lots_et_termine(tmp_path):
    chemin = _fichier_import(tmp_path, 10)
    lots, etats = [], []
    client = FauxRpc({
        "leads_importer_lot": lambda p: lots.append(p) or {},
        "leads_job_etat": lambda p: etats.append(p) or {},
    })
    r = L.lancer_import(client, "J", 3, chemin, "i.csv", {"nom": "NOM", "tel_mobile": "TELEPHONE MOBILE"}, REGL)
    assert r == "termine"
    assert [p["p_lues"] for p in lots] == [4, 4, 2]
    assert all(p["p_source"] == 3 and p["p_job"] == "J" for p in lots)
    assert etats[-1]["p_status"] == "termine"
    assert not os.path.exists(chemin), "le fichier téléversé est supprimé à la fin"


def test_import_repris_saute_les_lignes_deja_traitees(tmp_path):
    chemin = _fichier_import(tmp_path, 10)
    lots = []
    client = FauxRpc({"leads_importer_lot": lambda p: lots.append(p) or {}, "leads_job_etat": {}})
    L.lancer_import(client, "J", 1, chemin, "i.csv", {"nom": "NOM", "tel_mobile": "TELEPHONE MOBILE"}, REGL, a_sauter=8)
    assert sum(p["p_lues"] for p in lots) == 2 and lots[0]["p_rows"][0]["nom"] == "N8"


def test_lot_coupe_par_la_base_est_decoupe_en_deux(tmp_path):
    chemin = _fichier_import(tmp_path, 4)
    vus = []

    def lot(p):
        if len(p["p_rows"]) > 2:
            raise ErreurSql("canceling statement due to statement timeout", "57014")
        vus.append(len(p["p_rows"]))

    client = FauxRpc({"leads_importer_lot": lot, "leads_job_etat": {}})
    assert L.lancer_import(client, "J", 1, chemin, "i.csv", {"nom": "NOM", "tel_mobile": "TELEPHONE MOBILE"}, REGL) == "termine"
    assert vus == [2, 2]


def test_erreur_reseau_reessayee_puis_import_interrompu_avec_message(tmp_path):
    chemin = _fichier_import(tmp_path, 4)
    essais = []
    etats = []

    def lot(p):
        essais.append(1)
        raise ConnectionError("réseau")

    client = FauxRpc({"leads_importer_lot": lot, "leads_job_etat": lambda p: etats.append(p) or {}})
    r = L.lancer_import(client, "J", 1, chemin, "i.csv", {"nom": "NOM", "tel_mobile": "TELEPHONE MOBILE"}, REGL,
                        essais=3, pause_s=0)
    assert r == "interrompu" and len(essais) == 3
    assert etats[-1]["p_status"] == "interrompu" and "Reprends" in etats[-1]["p_message"]


def test_import_annule_s_arrete_sans_marquer_erreur(tmp_path):
    chemin = _fichier_import(tmp_path, 8)
    appels, etats = [], []

    def lot(p):
        appels.append(1)
        raise ErreurSql("tache_annule")

    client = FauxRpc({"leads_importer_lot": lot, "leads_job_etat": lambda p: etats.append(p) or {}})
    r = L.lancer_import(client, "J", 1, chemin, "i.csv", {"nom": "NOM", "tel_mobile": "TELEPHONE MOBILE"}, REGL)
    assert r == "annule" and len(appels) == 1 and etats == []


# ---------------------------------------------------------------
# Export en flux
# ---------------------------------------------------------------

def _export_client(fenetres, statut=lambda n: "en_cours", etats=None):
    suivi = {"i": 0}

    def lire(p):
        f = fenetres[suivi["i"]]
        suivi["i"] += 1
        if isinstance(f, Exception):
            raise f
        return f

    return FauxRpc({
        "leads_entete_csv": "A,B",
        "leads_job_lire": lambda p: {"status": statut(suivi["i"]), "lignes_lues": 5},
        "leads_lire": lire,
        "leads_job_etat": lambda p: etats.append(p) if etats is not None else {},
    })


def test_export_entete_bom_puis_fenetres_jusqu_a_la_fin():
    etats = []
    c = _export_client([
        {"csv": "1,a\n2,b", "n": 2, "suite": {"dept": 3, "apres": "(10,0)"}},
        {"csv": "3,c", "n": 1, "suite": None},
    ], etats=etats)
    sortie = b"".join(L.flux_export(c, "J", [3], None, None, REGL)).decode("utf-8")
    assert sortie.startswith("﻿A,B\n") and sortie.endswith("3,c\n")
    assert sortie.count("\n") == 4
    assert etats[-1]["p_status"] == "termine" and etats[-1]["p_lues"] == 3
    lires = [a[1] for a in c.appels if a[0] == "leads_lire"]
    assert lires[1]["p_dept"] == 3 and lires[1]["p_apres"] == "(10,0)" and lires[0]["p_mode"] == "csv"


def test_export_fenetre_coupee_par_la_base_reessayee_plus_petite():
    c = _export_client([
        ErreurSql("canceling statement due to statement timeout", "57014"),
        {"csv": "1,a", "n": 1, "suite": None},
    ])
    b"".join(L.flux_export(c, "J", None, None, None, REGL))
    tailles = [a[1]["p_blocs_max"] for a in c.appels if a[0] == "leads_lire"]
    assert tailles == [1000, 500]


def test_export_annule_coupe_le_flux_net():
    c = _export_client([{"csv": "1,a", "n": 1, "suite": {"dept": 1, "apres": "(1,0)"}}] * 3,
                       statut=lambda n: "en_cours" if n < 1 else "annule")
    g = L.flux_export(c, "J", None, None, None, REGL)
    next(g)  # entête
    next(g)  # première fenêtre
    with pytest.raises(L.ExportInterrompu):
        next(g)


def test_export_erreur_marque_interrompu_et_coupe_le_flux():
    etats = []
    c = _export_client([ErreurSql("boom")], etats=etats)
    with pytest.raises(L.ExportInterrompu):
        b"".join(L.flux_export(c, "J", None, None, None, REGL))
    assert etats[-1]["p_status"] == "interrompu" and "Reprendre" in etats[-1]["p_message"]


def test_export_repris_sans_entete_et_avec_le_compteur_existant():
    c = _export_client([{"csv": "9,z", "n": 1, "suite": None}])
    sortie = b"".join(L.flux_export(c, "J", None, None, None, REGL, reprise={"dept": 5, "apres": "(7,0)"})).decode()
    assert sortie == "9,z\n"
    lire = [a[1] for a in c.appels if a[0] == "leads_lire"][0]
    assert lire["p_dept"] == 5 and lire["p_apres"] == "(7,0)"


def test_deconnexion_du_navigateur_marque_interrompu():
    etats = []
    c = _export_client([{"csv": "1,a", "n": 1, "suite": {"dept": 1, "apres": "(1,0)"}}] * 3, etats=etats)
    g = L.flux_export(c, "J", None, None, None, REGL)
    next(g)
    next(g)
    next(g)
    g.close()
    assert etats[-1]["p_status"] == "interrompu"
    reprise = [e for e in etats if e.get("p_params")][-1]["p_params"]["suite"]
    assert reprise == {"dept": 1, "apres": "(1,0)"}, "point de reprise = début de la fenêtre en cours (aucune ligne perdue)"


# ---------------------------------------------------------------
# Divers
# ---------------------------------------------------------------

def test_jeton_a_usage_unique_et_borne_au_job():
    j = L.creer_jeton("CLIENT", "J1", 60)
    with pytest.raises(L.LeadsError):
        L.consommer_jeton(j, "J2")  # mauvais job : refusé (et consommé)
    j = L.creer_jeton("CLIENT", "J1", 60)
    assert L.consommer_jeton(j, "J1") == "CLIENT"
    with pytest.raises(L.LeadsError):
        L.consommer_jeton(j, "J1")  # déjà utilisé


def test_jeton_expire():
    j = L.creer_jeton("CLIENT", "J1", -1)
    with pytest.raises(L.LeadsError):
        L.consommer_jeton(j, "J1")


def test_tache_silencieuse():
    t = {"status": "en_cours", "updated_at": "2026-01-01T00:00:00+00:00"}
    base = time.mktime((2026, 1, 1, 0, 0, 0, 0, 0, 0))
    assert L.silencieuse(t, 120, maintenant=L.__dict__["time"].time()) is True
    assert L.silencieuse({**t, "status": "termine"}, 120) is False
    assert L.silencieuse({"status": "en_cours", "updated_at": None}, 120) is False
    assert base > 0


def test_traduction_des_erreurs_sql():
    assert L.traduire_erreur(ErreurSql("acces_refuse: lecture")).status == 403
    assert L.traduire_erreur(ErreurSql("x", "PGRST202")).status == 503
    assert L.traduire_erreur(ErreurSql("canceling statement due to statement timeout", "57014")).status == 504
    assert L.traduire_erreur(ErreurSql("colonne_inconnue: data")).status == 400
    assert L.traduire_erreur(ErreurSql("autre chose")).status == 502


# ---------------------------------------------------------------
# Routes
# ---------------------------------------------------------------

@pytest.fixture
def http():
    holder = SimpleNamespace(client=None, admin=True)

    def ctx():
        return SimpleNamespace(client=holder.client, user=SimpleNamespace(id="U"),
                               profile={"is_super_admin": holder.admin}, memberships=[])

    app.dependency_overrides[get_current_ctx] = ctx
    holder.http = TestClient(app)
    yield holder
    app.dependency_overrides.pop(get_current_ctx, None)


def test_route_compter_totalise_les_departements(http):
    http.client = FauxRpc({"leads_compter": [{"dept": 75, "libelle": "75", "n": 10}, {"dept": 13, "libelle": "13", "n": 5}]})
    r = http.http.get("/leads/compter?depts=75,13&exclues=2")
    assert r.status_code == 200 and r.json()["total"] == 15
    assert http.client.appels[0][1] == {"p_depts": [75, 13], "p_exclues": [2]}


def test_route_compter_refuse_une_liste_invalide(http):
    http.client = FauxRpc({})
    assert http.http.get("/leads/compter?depts=75,abc").status_code == 400
    assert http.http.get("/leads/compter?depts=-1").status_code == 400


def test_route_apercu_utilise_la_taille_de_page_des_reglages(http):
    http.client = FauxRpc({"leads_reglages_lire": reglages_rpc, "leads_lire": {"rows": [{"nom": "A"}], "suite": None}})
    r = http.http.get("/leads/apercu?depts=75&filtres=" + '{"ville":{"op":"contient","value":"par"}}')
    assert r.status_code == 200 and r.json()["rows"] == [{"nom": "A"}] and r.json()["taille_page"] == 300
    lire = [a[1] for a in http.client.appels if a[0] == "leads_lire"][0]
    assert lire["p_limite"] == 300 and lire["p_mode"] == "apercu" and lire["p_filters"]["ville"]["op"] == "contient"


def test_route_apercu_refuse_filtre_sur_colonne_inconnue_ou_json_casse(http):
    http.client = FauxRpc({"leads_reglages_lire": reglages_rpc})
    assert http.http.get("/leads/apercu?filtres=" + '{"data":{"op":"vide"}}').status_code == 400
    assert http.http.get("/leads/apercu?filtres=pas-du-json").status_code == 400


def test_migration_absente_donne_un_message_clair(http):
    http.client = FauxRpc({"leads_sources_lister": ErreurSql("Could not find the function", "PGRST202")})
    r = http.http.get("/leads/sources")
    assert r.status_code == 503 and "migration 0035" in r.json()["detail"]


def test_non_membre_recoit_403(http):
    http.client = FauxRpc({"leads_sources_lister": ErreurSql("acces_refuse: lecture Leads non autorisee")})
    assert http.http.get("/leads/sources").status_code == 403


def test_route_regler_source(http):
    http.client = FauxRpc({"leads_source_regler": None})
    r = http.http.patch("/leads/sources/4", json={"statut": "mauvaise"})
    assert r.status_code == 200
    assert http.client.appels[0][1] == {"p_id": 4, "p_statut": "mauvaise", "p_note": None}


def test_reglage_reserve_aux_admins(http):
    http.client = FauxRpc({"leads_reglage_poser": None})
    http.admin = False
    assert http.http.put("/leads/reglages/lot_import", json={"valeur": "100"}).status_code == 403
    http.admin = True
    assert http.http.put("/leads/reglages/lot_import", json={"valeur": "100"}).status_code == 200


def test_import_refuse_un_fichier_sans_telephone_ni_email(http):
    http.client = FauxRpc({"leads_reglages_lire": reglages_rpc})
    r = http.http.post("/leads/imports", data={"source": "S"}, files={"file": ("a.csv", b"NOM,VILLE\nx,y\n")})
    assert r.status_code == 400 and "doublons" in r.json()["detail"]


def test_import_refuse_un_fichier_vide_et_un_fichier_trop_gros(http):
    http.client = FauxRpc({"leads_reglages_lire": reglages_rpc})
    assert http.http.post("/leads/imports", data={"source": "S"}, files={"file": ("a.csv", b"")}).status_code == 400
    gros = b"EMAIL\n" + b"a@b.fr\n" * 300_000  # > 1 Mo (réglage de test)
    r = http.http.post("/leads/imports", data={"source": "S"}, files={"file": ("a.csv", gros)})
    assert r.status_code == 413


def test_import_ok_cree_la_tache_et_ne_laisse_aucun_fichier(http, monkeypatch, tmp_path):
    import api.leads as A

    monkeypatch.setattr(A, "DOSSIER_IMPORTS", str(tmp_path))
    lances = []
    monkeypatch.setattr(L, "executer_en_fond", lambda f, *a, **k: lances.append((f, a)))
    http.client = FauxRpc({
        "leads_reglages_lire": reglages_rpc,
        "leads_source_obtenir": 7,
        "leads_job_creer": lambda p: {"id": "JOB", "status": "en_cours", "lignes_total": p["p_total"]},
    })
    r = http.http.post("/leads/imports", data={"source": "Fichier A"},
                       files={"file": ("a.csv", b"NOM;EMAIL\nx;x@y.fr\nz;z@y.fr\n")})
    assert r.status_code == 200
    body = r.json()
    assert body["job"]["lignes_total"] == 2 and body["colonnes_reconnues"] == {"nom": "NOM", "email": "EMAIL"}
    assert lances and lances[0][0] is L.lancer_import and lances[0][1][2] == 7
    assert len(os.listdir(tmp_path)) == 1, "le fichier reste le temps de l'import (supprimé par la tâche)"


def test_import_en_echec_de_creation_supprime_le_fichier(http, monkeypatch, tmp_path):
    import api.leads as A

    monkeypatch.setattr(A, "DOSSIER_IMPORTS", str(tmp_path))
    http.client = FauxRpc({"leads_reglages_lire": reglages_rpc, "leads_source_obtenir": ErreurSql("source_vide: x")})
    r = http.http.post("/leads/imports", data={"source": " "}, files={"file": ("a.csv", b"EMAIL\na@b.fr\n")})
    assert r.status_code == 400 and os.listdir(tmp_path) == []


def test_reprise_exige_meme_fichier_et_meme_source(http, monkeypatch, tmp_path):
    import api.leads as A

    monkeypatch.setattr(A, "DOSSIER_IMPORTS", str(tmp_path))
    monkeypatch.setattr(L, "executer_en_fond", lambda *a, **k: None)
    ancien = {"id": "OLD", "kind": "import", "status": "interrompu", "source_id": 7, "filename": "autre.csv",
              "lignes_lues": 5, "lignes_total": 10}
    http.client = FauxRpc({"leads_reglages_lire": reglages_rpc, "leads_source_obtenir": 7,
                           "leads_job_lire": lambda p: ancien, "leads_job_etat": lambda p: {**ancien, "status": "en_cours"}})
    r = http.http.post("/leads/imports", data={"source": "S", "reprendre": "OLD"},
                       files={"file": ("a.csv", b"EMAIL\na@b.fr\n")})
    assert r.status_code == 409 and os.listdir(tmp_path) == []
    ancien["filename"] = "a.csv"
    r = http.http.post("/leads/imports", data={"source": "S", "reprendre": "OLD"},
                       files={"file": ("a.csv", b"EMAIL\na@b.fr\n")})
    assert r.status_code == 200


def test_reprise_refusee_si_la_tache_n_est_pas_interrompue(http, monkeypatch, tmp_path):
    import api.leads as A

    monkeypatch.setattr(A, "DOSSIER_IMPORTS", str(tmp_path))
    ancien = {"id": "OLD", "kind": "import", "status": "termine", "source_id": 7, "filename": "a.csv",
              "lignes_lues": 5, "updated_at": "2026-01-01T00:00:00+00:00"}
    http.client = FauxRpc({"leads_reglages_lire": reglages_rpc, "leads_source_obtenir": 7, "leads_job_lire": lambda p: ancien})
    r = http.http.post("/leads/imports", data={"source": "S", "reprendre": "OLD"},
                       files={"file": ("a.csv", b"EMAIL\na@b.fr\n")})
    assert r.status_code == 409


def test_export_cree_la_tache_puis_telecharge_une_seule_fois(http):
    job = {"id": "JOB", "kind": "export", "status": "en_cours",
           "params": {"depts": [75], "exclues": [2], "filtres": {}}}
    http.client = FauxRpc({
        "leads_reglages_lire": reglages_rpc,
        "leads_compter": [{"dept": 75, "libelle": "75", "n": 3}],
        "leads_job_creer": lambda p: {**job, "lignes_total": p["p_total"]},
        "leads_job_lire": lambda p: job,
        "leads_entete_csv": "A,B",
        "leads_lire": {"csv": "1,2\n3,4", "n": 2, "suite": None},
        "leads_job_etat": {},
    })
    r = http.http.post("/leads/exports", json={"depts": [75], "exclues": [2]})
    assert r.status_code == 200 and r.json()["job"]["lignes_total"] == 3
    url = r.json()["url"]
    f = http.http.get(url)
    assert f.status_code == 200 and f.headers["content-type"].startswith("text/csv")
    assert f.headers["content-disposition"].startswith("attachment")
    assert f.content.decode("utf-8-sig") == "A,B\n1,2\n3,4\n"
    assert http.http.get(url).status_code == 403, "lien à usage unique"


def test_export_sans_ligne_refuse(http):
    http.client = FauxRpc({"leads_reglages_lire": reglages_rpc, "leads_compter": []})
    r = http.http.post("/leads/exports", json={"depts": [75]})
    assert r.status_code == 400 and "Aucune ligne" in r.json()["detail"]


def test_telechargement_sans_jeton_valide_refuse(http):
    http.client = FauxRpc({})
    assert http.http.get("/leads/exports/JOB/fichier?jeton=nimporte").status_code == 403
    assert http.http.get("/leads/exports/JOB/fichier").status_code == 422


def test_reprise_d_export_exige_une_tache_interrompue_avec_suite(http):
    t = {"id": "JOB", "kind": "export", "status": "en_cours", "updated_at": "2099-01-01T00:00:00+00:00", "params": {}}
    http.client = FauxRpc({"leads_reglages_lire": reglages_rpc, "leads_job_lire": lambda p: t,
                           "leads_job_etat": lambda p: t})
    assert http.http.post("/leads/exports/JOB/reprise").status_code == 409
    t["status"] = "interrompu"
    assert http.http.post("/leads/exports/JOB/reprise").status_code == 409  # pas de suite enregistrée
    t["params"] = {"suite": {"dept": 3, "apres": "(5,0)"}}
    r = http.http.post("/leads/exports/JOB/reprise")
    assert r.status_code == 200 and "reprise=1" in r.json()["url"]


def test_annuler_une_tache_deja_finie_est_refuse(http):
    http.client = FauxRpc({"leads_job_annuler": None})
    assert http.http.post("/leads/jobs/J/annuler").status_code == 409


def test_les_taches_silencieuses_sont_signalees(http):
    http.client = FauxRpc({"leads_reglages_lire": reglages_rpc,
                           "leads_jobs_lister": [{"id": "A", "status": "en_cours", "updated_at": "2020-01-01T00:00:00Z"},
                                                 {"id": "B", "status": "termine", "updated_at": "2020-01-01T00:00:00Z"}]})
    jobs = http.http.get("/leads/jobs").json()["jobs"]
    assert [j["silencieuse"] for j in jobs] == [True, False]


def test_les_routes_existantes_ne_sont_pas_touchees():
    chemins = set(app.openapi()['paths'])
    assert "/orgs/{org_id}/records" in chemins and "/leads/apercu" in chemins
