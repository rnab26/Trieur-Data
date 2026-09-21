"""Test de fumee bout-en-bout : lance la vraie app Streamlit dans un
navigateur headless et verifie que le parcours complet (import -> mapping
-> construction de la base -> export) ne plante pas.

Les tests unitaires (tests/test_*.py) verifient la logique Python pure ;
ils n'auraient PAS detecte le crash "TypeError: width=\"stretch\"" qui a
touche la production, car celui-ci venait d'une incompatibilite au niveau
de l'API Streamlit elle-meme, pas de la logique metier. Ce test couvre
exactement cette classe de regression.
"""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import expect, sync_playwright  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_CSV = Path(__file__).resolve().parent / "fixtures" / "sample_leads.csv"


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_server(url, timeout=60):
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except Exception:
            time.sleep(1)
    return False


@pytest.fixture(scope="module")
def streamlit_server():
    port = _free_port()
    env = {**os.environ, "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false"}
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run", "app.py",
            "--server.headless", "true",
            "--server.port", str(port),
            "--server.address", "127.0.0.1",
        ],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        ready = _wait_for_server(url)
        if not ready:
            proc.terminate()
            out = proc.stdout.read().decode(errors="replace") if proc.stdout else ""
            pytest.fail(f"Streamlit server never became ready.\n{out}")
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        # Nettoyage des fichiers ecrits par persistence.py pendant le test.
        for name in ("user_master_columns.json", "saved_filters.json",
                     "export_presets.json", "remembered_mappings.json"):
            p = REPO_ROOT / name
            if p.exists():
                p.unlink()


_CRASH_MARKERS = ("TypeError", "Traceback", "encountered an error", "erreur est survenue")


def _assert_no_crash(page, where):
    # Streamlit keeps every tab's DOM in the page but hides inactive ones
    # (display:none), and Playwright's inner_text() skips hidden text -- so
    # this MUST be called right after clicking into a tab, while it is the
    # visible one, or a crash on a tab you've since navigated away from goes
    # undetected.
    body = page.inner_text("body")
    for needle in _CRASH_MARKERS:
        assert needle not in body, f"'{needle}' found on {where}:\n{body}"
    return body


def test_full_pipeline_no_crash(streamlit_server):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        try:
            page.goto(streamlit_server, wait_until="load", timeout=30000)
            tabs = page.get_by_role("tab")
            tabs.first.wait_for(state="visible", timeout=30000)
            _assert_no_crash(page, "tab 1 (Colonnes maitres)")

            # Onglet "Import et Mapping"
            tabs.nth(1).click()
            page.wait_for_timeout(1000)
            page.locator('input[type="file"]').set_input_files(str(FIXTURE_CSV))
            page.wait_for_timeout(3000)

            body = _assert_no_crash(page, "tab 2 after import")
            assert "fichier(s) importés" in body, body
            assert "1 fichier" in body, body

            page.get_by_text("Auto-assigner TOUS les onglets", exact=False).click()
            page.wait_for_timeout(2000)
            _assert_no_crash(page, "tab 2 after auto-assign")

            page.get_by_text("Construire la base de travail fusionnee", exact=False).click()
            page.wait_for_timeout(3000)
            body = _assert_no_crash(page, "tab 2 after build")
            assert "Base construite" in body, body

            # [NAV] Le bouton "Passer au filtrage" doit reellement basculer
            # sur l'onglet 3 (clic JS sur l'onglet natif -- voir views/_nav.py).
            # Regression passee : le selecteur JS ne matchait plus rien sur
            # cette version de Streamlit et le bouton ne faisait rien.
            page.locator('button:visible', has_text="Passer au filtrage").click()
            page.wait_for_timeout(1000)
            body = _assert_no_crash(page, "tab 3 apres clic sur 'Passer au filtrage'")
            assert "lignes conservees" in body or "lignes conservées" in body, body

            # [NAV] Meme verification pour "Passer à l'export".
            page.locator('button:visible', has_text="Passer à l'export").click()
            page.wait_for_timeout(1000)
            body = _assert_no_crash(page, "tab 4 apres clic sur 'Passer à l'export'")
            assert "prêtes à l'export" in body or "pretes a l'export" in body, body

            # [SORTABLE] Regression passee : le widget de glisser-deposer des
            # colonnes (streamlit-sortables) restait invisible (iframe a
            # hauteur 0) quand les onglets n'etaient pas rendus par st.tabs()
            # natif. On verifie que son iframe a une hauteur reelle.
            page.get_by_text("Ordre et selection des colonnes", exact=False).click()
            page.wait_for_timeout(1500)
            sortable_iframe = page.locator('iframe[title="streamlit_sortables.sortable_items"]')
            sortable_iframe.wait_for(state="attached", timeout=10000)
            height = sortable_iframe.evaluate("el => getComputedStyle(el).height")
            assert height != "0px", f"widget de glisser-deposer invisible (hauteur iframe: {height})"

            # Navigation manuelle directe (clic sur un onglet) doit aussi
            # fonctionner independamment des boutons de raccourci.
            tabs.nth(0).click()
            page.wait_for_timeout(1000)
            body = _assert_no_crash(page, "tab 1 apres navigation manuelle")
            assert "Gerer vos colonnes maitres" in body, body
        finally:
            browser.close()


def test_master_columns_localstorage_fallback(streamlit_server):
    """[15] Si le fichier serveur des colonnes maitres est perdu (ex:
    redemarrage de conteneur) mais que le navigateur a une version enregistree
    dans le localStorage, elle doit etre restauree automatiquement, sans
    action de l'utilisateur -- voir views/_ls_sync.py."""
    master_config_path = REPO_ROOT / "user_master_columns.json"
    custom_cols = ["NOM", "PRENOM", "IBAN_TEST_LS", "TELEPHONE_TEST_LS"]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        try:
            # Premiere visite : simule un navigateur qui a deja une liste de
            # colonnes maitres enregistree (sauvegardee lors d'une session
            # precedente).
            page.goto(streamlit_server, wait_until="load", timeout=30000)
            page.get_by_role("tab").first.wait_for(state="visible", timeout=30000)
            page.evaluate(
                "(cols) => window.localStorage.setItem('trieur_master_columns', JSON.stringify(cols))",
                custom_cols,
            )

            # Simule un redemarrage de conteneur : le fichier serveur disparait.
            if master_config_path.exists():
                master_config_path.unlink()

            # Nouvelle session (nouvelle visite) : le serveur repart des
            # colonnes par defaut, mais le navigateur doit imposer sa version.
            page.goto(streamlit_server, wait_until="load", timeout=30000)
            page.get_by_role("tab").first.wait_for(state="visible", timeout=30000)

            # La restauration prend DEUX aller-retours serveur (le composant
            # localStorage renvoie sa valeur -> rerun automatique, puis
            # app.py appelle st.rerun() une deuxieme fois pour rafraichir le
            # widget texte) : un delai fixe (4s) passait en local mais
            # cassait par intermittence en CI des que le runner etait plus
            # lent que d'habitude (confirme flaky sur PR #35/#38/#40, jamais
            # reproduit en local malgre plusieurs essais). `expect(...)`
            # reinterroge le DOM en boucle jusqu'a la vraie valeur au lieu de
            # parier sur un delai unique -- attend moins quand c'est rapide,
            # plus longtemps quand c'est lent, sans jamais durer plus que le
            # temps reellement necessaire.
            textarea = page.locator("textarea").first
            expect(textarea).to_have_value("\n".join(custom_cols), timeout=15000)

            # La restauration doit aussi avoir ete re-ecrite sur le fichier
            # serveur, pour survivre aux reruns suivants de cette session.
            assert master_config_path.exists(), "le fichier serveur n'a pas ete re-ecrit apres restauration"
        finally:
            browser.close()
            if master_config_path.exists():
                master_config_path.unlink()
