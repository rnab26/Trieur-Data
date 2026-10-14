#!/usr/bin/env python3
"""Parcours réel de la page Leads dans Chromium, sur un écran de téléphone (390x844) --
chantier cockpit 6547bd6a. L'API et Supabase sont simulés (interception des requêtes) : ce qui
est vérifié, c'est l'écran (états vide / chargement / erreur, aperçu paginé, sélection, export
avec suivi et annulation, import avec reprise, sources). Aucune vraie donnée, aucune base.

    python3 scripts/verifier_leads_page.py [dossier-de-captures]

Le Chromium du conteneur est celui de /opt/pw-browsers (ne pas lancer `playwright install`).
"""
import base64
import http.server
import json
import os
import pathlib
import re
import socketserver
import subprocess
import sys
import tempfile
import threading
from urllib.parse import unquote
import time

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
CAPTURES = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(tempfile.mkdtemp(prefix="leads_page_"))
CAPTURES.mkdir(parents=True, exist_ok=True)
CHROMIUM = os.environ.get("CHROMIUM", "/opt/pw-browsers/chromium")
API = "http://api.test"
SB = "http://supabase.test"
resultats = []


def ok(label, obtenu, attendu=True):
    resultats.append((label, obtenu == attendu, obtenu, attendu))


def jwt():
    b = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{b({'alg': 'HS256'})}.{b({'sub': 'u1', 'exp': 4102444800, 'role': 'authenticated'})}.sig"


def construire(dossier):
    env = {**os.environ, "VITE_SUPABASE_URL": SB, "VITE_SUPABASE_ANON_KEY": "anon", "VITE_API_URL": API}
    subprocess.run(["npx", "vite", "build", "--outDir", str(dossier), "--emptyOutDir"], cwd=ROOT / "frontend", env=env,
                   check=True, capture_output=True)


class Fausse:
    """État de l'API simulée."""

    def __init__(self):
        self.sources = [
            {"id": 1, "nom": "Salon 2026", "statut": "bonne", "note": None, "lignes": 4000, "lignes_lues": 4200, "doublons_rejetes": 200, "invalides": 5},
            {"id": 2, "nom": "Fournisseur X", "statut": "a_verifier", "note": None, "lignes": 2500, "lignes_lues": 2500, "doublons_rejetes": 0, "invalides": 0},
            {"id": 3, "nom": "Liste douteuse", "statut": "mauvaise", "note": None, "lignes": 900, "lignes_lues": 1000, "doublons_rejetes": 100, "invalides": 0},
        ]
        self.depts = [{"dept": d, "libelle": f"{d:02d}", "n": 100 * d} for d in (1, 13, 33, 69, 75, 92)]
        self.journal = []
        self.apercu_erreur = False
        self.pages = 3
        self.jobs = [
            {"id": "J-IMP-1", "kind": "import", "status": "termine", "filename": "salon.csv", "source_id": 1, "lignes_lues": 4200,
             "lignes_total": 4200, "inserees": 4000, "doublons": 200, "invalides": 5, "message": "Import terminé.", "params": None,
             "created_at": "2026-10-14T10:00:00Z", "updated_at": "2026-10-14T10:05:00Z"},
            {"id": "J-IMP-2", "kind": "import", "status": "interrompu", "filename": "gros.csv", "source_id": 2, "lignes_lues": 1000,
             "lignes_total": 5000, "inserees": 900, "doublons": 100, "invalides": 0, "message": "Réseau coupé. Reprends l'import avec le même fichier.",
             "params": None, "created_at": "2026-10-14T11:00:00Z", "updated_at": "2026-10-14T11:01:00Z"},
        ]
        self.export_en_cours = False
        self.comptage_etapes = 0
        self.reprises = []

    def total(self, depts, exclues):
        t = sum(d["n"] for d in self.depts if not depts or d["dept"] in depts)
        return t


def lancer_serveur(dossier):
    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(dossier), **k)

        def log_message(self, *a):
            pass

    srv = socketserver.TCPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main():
    dossier = pathlib.Path(tempfile.mkdtemp(prefix="leads_dist_"))
    construire(dossier)
    srv = lancer_serveur(dossier)
    base = f"http://127.0.0.1:{srv.server_address[1]}/"
    F = Fausse()
    cors = {"access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "*"}

    def rep(route, data, status=200, headers=None):
        route.fulfill(status=status, content_type="application/json", headers={**cors, **(headers or {})}, body=json.dumps(data))

    def api(route, request):
        if request.method == "OPTIONS":
            return route.fulfill(status=204, headers=cors)
        url = request.url[len(API):]
        chemin, _, qs = url.partition("?")
        params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
        listes = lambda k: [int(x) for x in params.get(k, "").replace("%2C", ",").split(",") if x]
        F.journal.append((request.method, url))
        if chemin == "/me":
            return rep(route, {"profile": {"id": "u1", "is_super_admin": True}})
        if chemin == "/orgs":
            return rep(route, [{"id": "o1", "name": "Leads"}])
        if chemin == "/leads/sources" and request.method == "GET":
            return rep(route, {"sources": F.sources})
        m = re.match(r"/leads/sources/(\d+)", chemin)
        if m and request.method == "PATCH":
            s = next(x for x in F.sources if x["id"] == int(m.group(1)))
            s["statut"] = json.loads(request.post_data)["statut"]
            return rep(route, {"id": s["id"], "statut": s["statut"]})
        if chemin == "/leads/compter":
            ex = listes("exclues")
            retire = sum(1 for s in F.sources if s["id"] in ex)
            return rep(route, {"par_departement": [{**d, "n": d["n"] - 10 * retire} for d in F.depts], "total": 0})
        if chemin == "/leads/apercu":
            if F.apercu_erreur:
                return rep(route, {"detail": "La base a mis trop de temps à répondre. Réduis la sélection et réessaie."}, 504)
            page = int(re.match(r"\((\d+),", unquote(params["apres"])).group(1)) if "apres" in params else 0
            filtres = params.get("filtres", "%7B%7D")
            if "zzz" in filtres:
                return rep(route, {"rows": [], "suite": None, "taille_page": 300})
            rows = [{"curseur": f"({page},{i})", "dept": "75", "source": "Salon 2026", "nom": f"NOM{page}-{i}", "prenom": "Prenom",
                     "email": f"p{i}@exemple.fr", "tel_mobile": f"06{i:08d}", "tel_fixe": None, "cp": "75001", "ville": "Paris",
                     "adresse": "1 rue des Tests", "naissance": "1980-01-01"} for i in range(8)]
            suite = {"dept": 75, "apres": f"({page + 1},0)"} if page + 1 < F.pages else None
            return rep(route, {"rows": rows, "suite": suite, "taille_page": 300})
        if chemin == "/leads/comptages":
            F.comptage_etapes = 0
            return rep(route, {"job": {"id": "J-CPT", "kind": "comptage", "status": "en_cours", "lignes_lues": 0, "params": {}}})
        if chemin == "/leads/jobs/J-CPT":
            F.comptage_etapes += 1
            if F.comptage_etapes < 2:
                return rep(route, {"id": "J-CPT", "kind": "comptage", "status": "en_cours", "lignes_lues": 1500, "lignes_total": None, "params": {}})
            return rep(route, {"id": "J-CPT", "kind": "comptage", "status": "termine", "lignes_lues": 321, "params": {"resultat": 321}})
        if chemin == "/leads/exports" and request.method == "POST":
            F.export_en_cours = True
            return rep(route, {"job": {"id": "J-EXP", "kind": "export", "status": "en_cours", "lignes_lues": 0, "lignes_total": 5000},
                               "url": "/leads/exports/J-EXP/fichier?jeton=abc"})
        if chemin == "/leads/jobs/J-EXP":
            if F.export_en_cours:
                return rep(route, {"id": "J-EXP", "kind": "export", "status": "en_cours", "lignes_lues": 1800, "lignes_total": 5000, "params": {}})
            return rep(route, {"id": "J-EXP", "kind": "export", "status": "annule", "lignes_lues": 1800, "lignes_total": 5000, "params": {}})
        if chemin == "/leads/jobs/J-EXP/annuler":
            F.export_en_cours = False
            return rep(route, {"id": "J-EXP", "status": "annule"})
        if chemin == "/leads/exports/J-EXP/fichier":
            return route.fulfill(status=200, headers={**cors, "content-type": "text/csv; charset=utf-8",
                                                      "content-disposition": 'attachment; filename="leads_export.csv"'},
                                 body="Département,Source\n75,Salon 2026\n")
        if chemin == "/leads/jobs":
            return rep(route, {"jobs": F.jobs})
        if chemin == "/leads/imports" and request.method == "POST":
            corps = request.post_data_buffer.decode("utf-8", "replace")
            reprise = 'name="reprendre"' in corps
            F.reprises.append(reprise)
            F.jobs.insert(0, {"id": "J-IMP-3", "kind": "import", "status": "en_cours", "filename": "nouveau.csv", "source_id": 1,
                              "lignes_lues": 700, "lignes_total": 2000, "inserees": 650, "doublons": 50, "invalides": 0, "message": None,
                              "params": None, "created_at": "2026-10-14T12:00:00Z", "updated_at": "2026-10-14T12:00:01Z"})
            return rep(route, {"job": F.jobs[0], "colonnes_reconnues": {"nom": "NOM", "email": "EMAIL", "tel_mobile": "TELEPHONE MOBILE"},
                               "colonnes_ignorees": ["Source Data"], "reprise": reprise})
        if chemin == "/leads/jobs/J-IMP-3/annuler":
            F.jobs[0]["status"] = "annule"
            return rep(route, F.jobs[0])
        if chemin.endswith("/doublons"):
            return rep(route, {"doublons": [{"dept": "75", "cle": 1, "nom": "DUPONT", "source": "Salon 2026", "source_existante": "Fournisseur X"}]})
        return rep(route, {"detail": f"non simulé : {chemin}"}, 404)

    def vide(route, request):
        if request.method == "OPTIONS":
            return route.fulfill(status=204, headers=cors)
        rep(route, {})

    with sync_playwright() as p:
        nav = p.chromium.launch(executable_path=CHROMIUM, args=["--no-sandbox"])
        ctx = nav.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True,
                              accept_downloads=True)
        session = {"access_token": jwt(), "refresh_token": "r", "expires_at": 4102444800, "expires_in": 3600, "token_type": "bearer",
                   "user": {"id": "u1", "aud": "authenticated", "email": "test@example.fr", "app_metadata": {}, "user_metadata": {},
                            "created_at": "2026-01-01T00:00:00Z"}}
        ctx.add_init_script(f"localStorage.setItem('sb-supabase-auth-token', {json.dumps(json.dumps(session))}); "
                            "localStorage.setItem('trieur_dernier_ecran', 'database');")
        ctx.route(re.compile(r"^http://api\.test/.*"), api)
        ctx.route(re.compile(r"^http://supabase\.test/.*"), vide)
        ctx.route(re.compile(r"^https?://(?!127\.0\.0\.1|api\.test|supabase\.test).*"), lambda r, q: r.abort())
        page = ctx.new_page()
        erreurs_js = []
        page.on("pageerror", lambda e: erreurs_js.append(str(e)))
        page.goto(base)

        # --- accès : onglet Leads pour un administrateur
        page.get_by_role("button", name="Leads", exact=True).click()
        page.get_by_role("heading", name="Leads").wait_for(timeout=15000)
        page.wait_for_selector("[data-testid=total]", timeout=15000)
        ok("onglet Leads visible pour un administrateur", True)
        total = page.locator("[data-testid=total]").inner_text()
        # les sources « mauvaise » sont exclues d'office : la 3e source (id 3) est retirée des comptes
        compter = [u for m, u in F.journal if u.startswith("/leads/compter")][-1]
        ok("source mauvaise exclue d'office dans le compte", "exclues=3" in compter, True)
        ok("total affiché (espaces insécables acceptés)", re.sub(r"\s", "", total), str(sum(d["n"] - 10 for d in F.depts)))
        page.screenshot(path=str(CAPTURES / "01-exporter.png"), full_page=True)
        ok("pas de défilement horizontal de la page (téléphone)", page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), True)
        page.wait_for_selector("table tbody tr", timeout=10000)
        ok("aperçu chargé (tableau)", page.locator("table tbody tr").count(), 8)

        # --- départements
        page.get_by_role("button", name=re.compile("Départements")).click()
        page.get_by_text("92", exact=True).first.click()
        page.get_by_text("75", exact=True).first.click()
        page.wait_for_function("document.querySelector('[data-testid=total]').innerText.replace(/\\s/g,'') == '" + str((9200 - 10) + (7500 - 10)) + "'")
        ok("total = départements cochés", True)
        page.wait_for_timeout(900)
        ok("l'aperçu est relu avec les départements", any("depts=75%2C92" in u or "depts=75,92" in u for m, u in F.journal if "apercu" in u), True)
        page.screenshot(path=str(CAPTURES / "02-departements.png"), full_page=True)
        page.get_by_role("button", name=re.compile("Départements")).click()

        # --- pagination de l'aperçu
        ok("Précédent désactivé sur la 1re page", page.get_by_role("button", name=re.compile("Précédent")).is_disabled(), True)
        page.get_by_role("button", name=re.compile("Suivant")).click()
        page.wait_for_function("document.body.innerText.includes('NOM1-0')")
        ok("page 2 de l'aperçu", True)
        page.get_by_role("button", name=re.compile("Suivant")).click()
        page.wait_for_function("document.body.innerText.includes('NOM2-0')")
        ok("Suivant désactivé à la dernière page", page.get_by_role("button", name=re.compile("Suivant")).is_disabled(), True)
        page.get_by_role("button", name=re.compile("Précédent")).click()
        page.wait_for_function("document.body.innerText.includes('NOM1-0')")
        ok("retour à la page précédente", True)

        # --- filtre de colonne -> compte exact en tâche de fond
        page.get_by_role("button", name="+ Ajouter un filtre").click()
        page.get_by_label("Valeur").fill("par")
        page.wait_for_function("document.querySelector('[data-testid=total]').innerText.startsWith('jusqu')")
        ok("avec filtre : « jusqu'à N » (jamais un faux exact)", True)
        page.get_by_role("button", name="Compter exactement").click()
        page.wait_for_function("document.querySelector('[data-testid=total]').innerText.replace(/\\s/g,'') == '321'", timeout=15000)
        ok("compte exact en tâche de fond affiché", True)
        page.screenshot(path=str(CAPTURES / "03-filtre-exact.png"), full_page=True)
        # filtre sans résultat -> état vide
        page.get_by_label("Valeur").fill("zzz")
        page.wait_for_function("document.body.innerText.includes('Aucune ligne ne correspond')")
        ok("état vide de l'aperçu", True)
        page.get_by_role("button", name="Retirer").click()

        # --- erreur d'aperçu visible + Réessayer
        F.apercu_erreur = True
        page.get_by_role("button", name=re.compile("Départements")).click()
        page.get_by_text("33", exact=True).first.click()
        page.wait_for_selector("[role=alert]", timeout=10000)
        ok("erreur d'aperçu visible avec Réessayer", "trop de temps" in page.locator("[role=alert]").first.inner_text(), True)
        page.screenshot(path=str(CAPTURES / "04-erreur.png"), full_page=True)
        F.apercu_erreur = False
        page.get_by_role("button", name="Réessayer").first.click()
        page.wait_for_function("document.querySelectorAll('table tbody tr').length == 8", timeout=10000)
        ok("Réessayer relit l'aperçu", True)
        page.get_by_role("button", name=re.compile("Départements")).click()

        # --- export : téléchargement, suivi, annulation
        with page.expect_download(timeout=15000) as dl:
            page.get_by_role("button", name=re.compile("^Exporter")).click()
        d = dl.value
        chemin_dl = CAPTURES / "export.csv"
        d.save_as(str(chemin_dl))
        ok("le fichier CSV est téléchargé", chemin_dl.read_text(encoding="utf-8").startswith("Département,Source"), True)
        page.wait_for_selector("[data-testid=suivi-export]")
        page.wait_for_function("document.querySelector('[data-testid=suivi-export]').innerText.replace(/\\s/g,'').includes('1800')")
        ok("suivi d'avancement de l'export (lignes et %)", "36 %" in page.locator("[data-testid=suivi-export]").inner_text(), True)
        page.screenshot(path=str(CAPTURES / "05-export-en-cours.png"), full_page=True)
        page.get_by_role("button", name="Annuler l'export").click()
        page.wait_for_function("document.querySelector('[data-testid=suivi-export]').innerText.includes('annulé')")
        ok("annulation de l'export visible", ("POST", "/leads/jobs/J-EXP/annuler") in F.journal, True)

        # --- import
        page.get_by_role("tab", name="Importer").click()
        page.wait_for_selector("[data-testid=import-job]")
        ok("liste des imports récents", page.locator("[data-testid=import-job]").count(), 2)
        ok("bouton Voir des doublons (import avec doublons)", page.get_by_role("button", name="Voir des doublons").count() >= 1, True)
        ok("import désactivé sans source ni fichier", page.get_by_role("button", name="Importer", exact=True).is_disabled(), True)
        fich = CAPTURES / "a-importer.csv"
        fich.write_text("NOM,EMAIL,TELEPHONE MOBILE,Source Data\nDupont,d@x.fr,0612345678,x\n", encoding="utf-8")
        page.locator("input[type=file]").first.set_input_files(str(fich))
        page.get_by_placeholder(re.compile("Salon 2026")).fill("Salon 2026")
        page.get_by_role("button", name="Importer", exact=True).click()
        page.wait_for_selector("[data-testid=colonnes]")
        ok("colonnes reconnues affichées", "TELEPHONE MOBILE → tel_mobile" in page.locator("[data-testid=colonnes]").inner_text(), True)
        ok("colonne ignorée affichée", "Source Data" in page.locator("[data-testid=colonnes]").inner_text(), True)
        page.wait_for_function("document.querySelectorAll('[data-testid=import-job]').length == 3")
        ok("le nouvel import apparaît avec sa progression", "35 %" in page.locator("[data-testid=import-job]").first.inner_text(), True)
        page.screenshot(path=str(CAPTURES / "06-import.png"), full_page=True)
        page.once("dialog", lambda dlg: dlg.accept())
        page.get_by_role("button", name="Annuler", exact=True).first.click()
        page.wait_for_function("document.querySelector('[data-testid=import-job]').innerText.includes('Annulé')")
        ok("annulation d'import confirmée puis visible", True)
        # reprise
        with page.expect_file_chooser() as fc:
            page.get_by_role("button", name="Reprendre", exact=True).first.click()
        fc.value.set_files(str(fich))
        page.wait_for_timeout(800)
        ok("reprise : le même fichier est renvoyé avec l'identifiant de la tâche", F.reprises, [False, True])
        page.get_by_role("button", name="Voir des doublons").first.click()
        page.wait_for_function("document.body.innerText.includes('DUPONT')")
        ok("exemples de doublons", True)

        # --- sources
        page.get_by_role("tab", name="Sources").click()
        page.get_by_text("Fournisseur X").first.wait_for()
        page.screenshot(path=str(CAPTURES / "07-sources.png"), full_page=True)
        page.get_by_role("group", name="Statut de Fournisseur X").get_by_role("button", name="Mauvaise").click()
        page.wait_for_function("document.body.innerText.includes('« Fournisseur X » : mauvaise.')")
        ok("source marquée mauvaise (message de succès)", ("PATCH", "/leads/sources/2") in F.journal, True)
        # état vide
        F.sources = []
        page.get_by_role("tab", name="Exporter").click()
        page.get_by_role("tab", name="Sources").click()
        page.get_by_role("tab", name="Importer").click()
        page.get_by_role("tab", name="Sources").click()
        ok("pas d'erreur JavaScript pendant tout le parcours", erreurs_js, [])
        nav.close()
    srv.shutdown()
    mauvais = 0
    for label, bon, got, want in resultats:
        print(("OK  " if bon else "KO  ") + label + ("" if bon else f"  (obtenu {got!r}, attendu {want!r})"))
        mauvais += 0 if bon else 1
    print(f"{len(resultats) - mauvais}/{len(resultats)} contrôles OK ; captures dans {CAPTURES}")
    return 1 if mauvais else 0


if __name__ == "__main__":
    sys.exit(main())
