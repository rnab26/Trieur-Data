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
from playwright.sync_api import sync_playwright  # noqa: E402

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
            # [14] Barre d'onglets "maison" (boutons, pas des st.tabs natifs --
            # necessaire pour piloter la navigation depuis le code Python).
            nav = lambda label: page.get_by_role("button", name=label, exact=True)  # noqa: E731
            nav("1. Colonnes maitres").wait_for(state="visible", timeout=30000)
            _assert_no_crash(page, "tab 1 (Colonnes maitres)")

            # Onglet "Import et Mapping"
            nav("2. Import et Mapping").click()
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

            # Onglet "Filtrage & Dedup" : c'est exactement le chemin qui a
            # declenche le crash width="stretch" en production (le tableau
            # filtre s'affiche sans condition des que la base existe, sur
            # CHAQUE rerun -- il faut verifier CE tab, pas seulement Export).
            nav("3. Filtrage & Dedup").click()
            page.wait_for_timeout(1500)
            body = _assert_no_crash(page, "tab 3 (Filtrage & Dedup)")
            assert "lignes conservees" in body or "lignes conservées" in body, body

            # Onglet "Export"
            nav("4. Export").click()
            page.wait_for_timeout(1500)
            body = _assert_no_crash(page, "tab 4 (Export)")
            assert "prêtes à l'export" in body or "pretes a l'export" in body, body
        finally:
            browser.close()
