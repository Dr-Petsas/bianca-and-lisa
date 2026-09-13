"""bianca-and-lisa.pickadoc-tunnel.com: globale Navigation und Bianca-Proxy."""

from __future__ import annotations

import inspect

from lisa import server


def test_bianca_ziel_default_ist_localhost(monkeypatch):
    monkeypatch.delenv("LISA_BIANCA_URL", raising=False)
    assert server.bianca_ziel() == "http://127.0.0.1:8096"


def test_bianca_ziel_kommt_aus_env(monkeypatch):
    monkeypatch.setenv("LISA_BIANCA_URL", "http://bianca:8096/")
    assert server.bianca_ziel() == "http://bianca:8096"


def test_compose_setzt_bianca_auf_geschwister():
    text = open("compose.yml", encoding="utf-8").read()
    assert "LISA_BIANCA_URL: ${LISA_BIANCA_URL:-http://bianca:8096}" in text


def test_demo_praxis_kommt_aus_keiner_globalen_kundenauswahl():
    from bianca import server as bianca_server
    from tests.baukasten import editor

    for antwort in (server.api_tenants(), bianca_server.api_tenants(), editor.api_tenants()):
        assert "demo" not in {str(t.get("id") or "") for t in antwort["tenants"]}


def test_kampagne_route_und_dateien_existieren():
    src = inspect.getsource(server)
    assert '@app.get("/kampagne")' in src
    assert "kampagnen_store.liste" in src
    assert (server.WEB_DIR / "kampagne.html").is_file()
    assert (server.WEB_DIR / "kampagne.js").is_file()


def test_globale_navigation_und_anruf_unterseiten_existieren():
    html = (server.WEB_DIR / "index.html").read_text(encoding="utf-8")
    shell = (server.WEB_DIR / "shell.js").read_text(encoding="utf-8")
    assert 'data-tab="bianca"' in html
    assert 'data-tab="lisa"' in html
    assert 'data-tab="studio"' in html
    assert "bianca-anrufe" in html
    assert "lisa-anrufe" in html
    assert '"/bianca/anrufe"' in shell
    assert '"/lisa-anrufe"' in shell
    assert "Bianca ? Patiententelefon" not in html
    src = inspect.getsource(server)
    assert '@app.get("/anrufe")' in src
    assert '@app.get("/lisa-anrufe")' in src
    assert "content-disposition" in inspect.getsource(server.bianca_durchreichen)
    dock = open("bianca_web/index.html", encoding="utf-8").read()
    assert 'id="tenant" hidden' in dock
    assert 'id="studioBtn"' not in dock
    assert "Bianca — Patiententelefon" in dock
    assert "Schließen" in dock
    assert "Können" in dock
    from pathlib import Path

    from bianca import server as bianca_server

    antwort = bianca_server.web_file("anrufe.js")
    assert Path(antwort.path).name == "anrufe.js"
    html_anrufe = open("bianca_web/anrufe.html", encoding="utf-8").read()
    js_anrufe = open("bianca_web/anrufe.js", encoding="utf-8").read()
    assert "anrufe.js?v=a14" in html_anrufe
    assert "praxis.js?v=5" in html_anrufe
    assert "Testanrufe" in html_anrufe
    assert "Praxis-Live" in html_anrufe
    assert "function istTest" in js_anrufe
    assert "art-filter" in html_anrufe
    assert 'raus.setdefault("cache-control", "no-store")' in inspect.getsource(
        server.bianca_durchreichen
    )
    src_proxy = inspect.getsource(server.bianca_durchreichen)
    assert "x-forwarded-prefix" in src_proxy
    assert "location_hinter_prefix" in src_proxy
    assert "html_studio_pfade" in src_proxy
