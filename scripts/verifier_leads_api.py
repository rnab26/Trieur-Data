#!/usr/bin/env python3
"""Trajet complet API -> base de la base Leads (chantier cockpit 6547bd6a) sur un schéma JETABLE.

Fait tourner le VRAI code de api/leads.py + trieur/leads.py (import en tâche de fond, aperçu, export
en flux, reprise, annulation) contre la vraie base Postgres, en remplaçant seulement le transport
(PostgREST -> scripts/sql.sh) : ce qui est vérifié, ce sont les noms et types de paramètres échangés
entre Python et les fonctions SQL, que les tests à faux client ne peuvent pas voir.
Schéma `test_leads_<aléatoire>` créé puis supprimé ; données fictives.

    python3 scripts/verifier_leads_api.py
"""
import json
import secrets
import sys
import time
from types import SimpleNamespace

import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from verifier_leads_sql import CLAIMS, creer_schema, sql, supprimer_schema  # noqa: E402


def litteral(v):
    """Valeur Python -> littéral SQL (type inféré par la fonction appelée)."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return f"'{v}'"  # littéral non typé, comme PostgREST : la fonction choisit smallint / int / bigint
    if isinstance(v, list) and v and all(isinstance(x, int) for x in v):
        return "'{" + ",".join(str(x) for x in v) + "}'"
    if isinstance(v, (dict, list)):
        return "'" + json.dumps(v, ensure_ascii=False).replace("'", "''") + "'"
    return "'" + str(v).replace("'", "''") + "'"


class ClientSql:
    """Imite client.postgrest.schema(s).rpc(nom, params).execute() en passant par la vraie base."""

    def __init__(self, schema):
        self.schema_nom = schema
        self.nb = 0

    @property
    def postgrest(self):
        return self

    def schema(self, s):
        self._s = s
        return self

    def rpc(self, nom, params=None):
        args = ", ".join(f"{k} => {litteral(v)}" for k, v in (params or {}).items())
        s = self.schema_nom
        q = f"with c as (select {CLAIMS}) select {s}.{nom}({args}) as r from c"

        def execute():
            self.nb += 1
            rows = sql(q)
            return SimpleNamespace(data=rows[0]["r"] if rows else None)

        return SimpleNamespace(execute=execute)


def main():
    from fastapi.testclient import TestClient

    from api.main import app, get_current_ctx
    from trieur import leads as L

    S = "test_leads_" + secrets.token_hex(4)
    L.SCHEMA = S  # le code applicatif vise le schéma jetable
    resultats = []

    def ok(label, obtenu, attendu):
        resultats.append((label, obtenu == attendu, obtenu, attendu))

    client = ClientSql(S)
    app.dependency_overrides[get_current_ctx] = lambda: SimpleNamespace(
        client=client, user=SimpleNamespace(id="U"), profile={"is_super_admin": True}, memberships=[])
    http = TestClient(app)
    try:
        creer_schema(S)
        # lots et fenêtres minuscules : on veut plusieurs allers-retours avec 600 lignes
        sql(f"update {S}.leads_reglages set valeur='200' where cle='lot_import'")
        sql(f"update {S}.leads_reglages set valeur='1' where cle='pas_blocs'")
        sql(f"update {S}.leads_reglages set valeur='3' where cle='fenetre_blocs'")
        sql(f"update {S}.leads_reglages set valeur='5' where cle='apercu_taille'")

        n = 600
        lignes = ["NOM;PRENOM;EMAIL;TELEPHONE MOBILE;CP;VILLE;Source Data"]
        for g in range(n):
            tel = f"06{g:08d}" if g % 7 else ""
            mail = f"p{g}@exemple.fr" if g % 7 == 0 else ""
            lignes.append(f"Nom{g};Pre{g % 9};{mail};{tel};{(1 + g % 4) * 1000:05d};Ville{g % 5};x")
        def fichier(prefixe):
            return ("\n".join(x.replace(";06", f";{prefixe}") if i else x for i, x in enumerate(lignes)) + "\n").encode("utf-8")

        contenu = fichier("06")

        def attendre(job_id, fin=("termine", "erreur", "interrompu", "annule"), plafond=120):
            t0 = time.time()
            while time.time() - t0 < plafond:
                j = http.get(f"/leads/jobs/{job_id}").json()
                if j["status"] in fin:
                    return j
                time.sleep(1.5)
            raise TimeoutError(f"tâche {job_id} toujours en cours après {plafond}s")

        # --- import
        r = http.post("/leads/imports", data={"source": "Fichier A"}, files={"file": ("a.csv", contenu)})
        ok("import : accepté", r.status_code, 200)
        if r.status_code != 200:
            print("RÉPONSE", r.status_code, r.text[:500])
        ok("import : colonnes reconnues", sorted(r.json()["colonnes_reconnues"]),
           ["cp", "email", "nom", "prenom", "tel_mobile", "ville"])
        ok("import : 'Source Data' ignorée", r.json()["colonnes_ignorees"], ["Source Data"])
        j = attendre(r.json()["job"]["id"])
        ok("import : terminé", j["status"], "termine")
        ok("import : lignes lues = lignes du fichier", int(j["lignes_lues"]), n)
        ok("import : toutes insérées (téléphone ou e-mail sur chaque ligne)", int(j["inserees"]), n)
        ok("import : progression visible (lignes_total connu)", int(j["lignes_total"]), n)
        # même fichier, autre source : que des doublons
        r2 = http.post("/leads/imports", data={"source": "Fichier B"}, files={"file": ("a.csv", contenu)})
        j2 = attendre(r2.json()["job"]["id"])
        ok("réimport : 0 inséré, 600 doublons", (int(j2["inserees"]), int(j2["doublons"])), (0, n))
        d = http.get(f"/leads/jobs/{j2['id']}/doublons").json()["doublons"]
        ok("réimport : exemples de doublons (avec la source d'origine)", (len(d) > 0, d[0]["source_existante"]), (True, "Fichier A"))
        src = {s["nom"]: s for s in http.get("/leads/sources").json()["sources"]}
        ok("sources : lignes et doublons comptés", (int(src["Fichier A"]["lignes"]), int(src["Fichier B"]["doublons_rejetes"])), (n, n))

        # --- comptes
        c = http.get("/leads/compter").json()
        ok("compter : total exact", c["total"], n)
        sb = src["Fichier B"]["id"]
        sa = src["Fichier A"]["id"]
        r = http.patch(f"/leads/sources/{sb}", json={"statut": "mauvaise"})
        ok("source marquée mauvaise", r.status_code, 200)
        ok("compter : source A exclue -> 0", http.get(f"/leads/compter?exclues={sa}").json()["total"], 0)

        # --- aperçu paginé (5 lignes par page)
        vus, dept, apres, pages = [], None, None, 0
        while pages < 400:
            q = "/leads/apercu?" + (f"dept={dept}&apres={apres}" if dept is not None else "")
            a = http.get(q).json()
            vus += [x["curseur"] + x["dept"] for x in a["rows"]]
            pages += 1
            if not a["suite"]:
                break
            dept, apres = a["suite"]["dept"], a["suite"]["apres"]
        ok("aperçu : 600 lignes, une fois chacune, par pages de 5", (len(vus), len(set(vus))), (n, n))
        a = http.get("/leads/apercu?depts=1&filtres=" + json.dumps({"ville": {"op": "égal à", "value": "ville2"}})).json()
        ok("aperçu : filtre ville + département", {x["ville"] for x in a["rows"]} <= {"Ville2"}, True)

        # --- comptage exact avec filtre de colonne (tâche de fond)
        r = http.post("/leads/comptages", json={"depts": [], "exclues": [], "filtres": {"ville": {"op": "égal à", "value": "ville2"}}})
        jc = attendre(r.json()["job"]["id"])
        attendu = int(sql(f"select count(*) c from {S}.leads where lower(ville)='ville2'")[0]["c"])
        ok("comptage exact avec filtre = comptage SQL", (jc["status"], jc["params"]["resultat"]), ("termine", attendu))

        # --- export en flux (fenêtres de 3 blocs, plusieurs requêtes)
        r = http.post("/leads/exports", json={"depts": [], "exclues": [sb]})
        ok("export : lien créé", r.status_code, 200)
        je = r.json()["job"]
        f = http.get(r.json()["url"])
        texte = f.content.decode("utf-8-sig")
        lignes_csv = [x for x in texte.split("\n") if x]
        ok("export : entête + 600 lignes", (len(lignes_csv), lignes_csv[0].startswith("Département")), (n + 1, True))
        ok("export : première ligne de données lisible", lignes_csv[1].count(",") >= 11, True)
        fin = attendre(je["id"], plafond=30)
        ok("export : tâche terminée avec le bon nombre de lignes", (fin["status"], int(fin["lignes_lues"])), ("termine", n))
        ok("export : lien à usage unique", http.get(r.json()["url"]).status_code, 403)
        # export avec la source A exclue : rien à exporter
        r = http.post("/leads/exports", json={"depts": [], "exclues": [sa]})
        ok("export : sélection vide refusée", r.status_code, 400)

        # --- annulation d'un export en cours puis reprise
        r = http.post("/leads/exports", json={"depts": [], "exclues": []})
        jid = r.json()["job"]["id"]
        gen = L.flux_export(client, jid, None, None, None, L.reglages(client))
        morceaux = [next(gen), next(gen)]  # entête + 1re fenêtre
        gen.close()  # le navigateur coupe
        etat = http.get(f"/leads/jobs/{jid}").json()
        ok("export coupé : tâche interrompue + suite gardée", (etat["status"], bool(etat["params"].get("suite"))), ("interrompu", True))
        rep = http.post(f"/leads/exports/{jid}/reprise")
        ok("reprise : lien créé", rep.status_code, 200)
        if rep.status_code != 200:
            print("RÉPONSE reprise", rep.status_code, rep.text[:300], etat)
        suite = http.get(rep.json()["url"]).content.decode("utf-8")
        a_la_main = [x for x in morceaux[1].decode().split("\n") if x]
        reprise_l = [x for x in suite.split("\n") if x]
        ok("coupure + reprise : toutes les lignes, aucune perdue", len(set(a_la_main) | set(reprise_l)), n)
        ok("coupure + reprise : au pire la fenêtre en cours est renvoyée (aucun autre doublon)",
           len(a_la_main) + len(reprise_l) - n <= len(a_la_main), True)
        ok("reprise : pas de second entête", suite.startswith("Département"), False)

        # --- annulation d'un import en cours
        r3 = http.post("/leads/imports", data={"source": "Fichier C"}, files={"file": ("c.csv", fichier("07"))})
        jid = r3.json()["job"]["id"]
        an = http.post(f"/leads/jobs/{jid}/annuler")
        jfin = attendre(jid, plafond=60)
        ok("import annulé : tâche annulée", jfin["status"], "annule")
        ok("import annulé : moins que tout importé ou fini avant l'annulation", int(jfin["inserees"]) <= n, True)
        ok("tâche annulée : annuler encore -> 409", http.post(f"/leads/jobs/{jid}/annuler").status_code, 409)
        ok("liste des tâches", len(http.get("/leads/jobs").json()["jobs"]) >= 6, True)

        # --- reprise d'un import interrompu : mêmes lignes, aucun doublon d'écart
        r4 = http.post("/leads/imports", data={"source": "Fichier D"}, files={"file": ("d.csv", fichier("08"))})
        jid = r4.json()["job"]["id"]
        attendre(jid)
        avant = int(sql(f"select count(*) c from {S}.leads where source_id=(select id from {S}.leads_sources where nom='Fichier D')")[0]["c"])
        # on simule une coupure : tâche remise « interrompue » à 200 lignes lues
        sql(f"update {S}.leads_jobs set status='interrompu', lignes_lues=200 where id='{jid}'")
        r5 = http.post("/leads/imports", data={"source": "Fichier D", "reprendre": jid}, files={"file": ("d.csv", fichier("08"))})
        ok("reprise d'import : acceptée", r5.status_code, 200)
        jr = attendre(jid)
        apres_n = int(sql(f"select count(*) c from {S}.leads where source_id=(select id from {S}.leads_sources where nom='Fichier D')")[0]["c"])
        n_tel = len([g for g in range(n) if g % 7])  # les autres lignes n'ont qu'un e-mail, déjà vu dans le fichier A
        ok("reprise d'import : aucune ligne en trop ni en moins", (avant, apres_n), (n_tel, n_tel))
        ok("reprise d'import : les 400 lignes restantes sont revues comme doublons (+ les e-mails déjà vus en A)",
           int(jr["doublons"]), 400 + (n - n_tel))
        # --- réglage
        ok("réglage modifiable", http.put("/leads/reglages/lot_import", json={"valeur": "300"}).status_code, 200)
        ok("réglage inconnu refusé", http.put("/leads/reglages/inconnu", json={"valeur": "1"}).status_code, 404)
        ok("requêtes envoyées à la base", client.nb > 50, True)
    finally:
        app.dependency_overrides.pop(get_current_ctx, None)
        try:
            supprimer_schema(S)
        except Exception as exc:  # noqa: BLE001
            print(f"ATTENTION : schéma jetable {S} à supprimer à la main : {exc}", file=sys.stderr)
    bad = 0
    for label, good, got, want in resultats:
        print(("OK  " if good else "KO  ") + label + ("" if good else f"  (obtenu {got!r}, attendu {want!r})"))
        bad += 0 if good else 1
    print(f"{len(resultats) - bad}/{len(resultats)} contrôles OK")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
