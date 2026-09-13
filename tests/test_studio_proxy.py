"""Studio-Tabs hinter Tunnel UND direkt: nie wieder hartes /studio/."""

from __future__ import annotations

from types import SimpleNamespace

from bianca import server as bianca_server
from kern import webpfad


def _headers(prefix: str | None):
    if prefix is None:
        return None
    return {"x-forwarded-prefix": prefix}


def test_studio_basis_direkt_und_tunnel():
    assert webpfad.studio_basis(None) == "/studio/"
    assert webpfad.studio_basis({}) == "/studio/"
    assert webpfad.studio_basis(_headers("/bianca")) == "/bianca/studio/"
    assert webpfad.studio_basis(_headers("/bianca/")) == "/bianca/studio/"
    assert webpfad.studio_basis(_headers("/evil")) == "/studio/"


def test_html_bekommt_prefix_im_base():
    html = "<html><head><title>x</title></head></html>"
    direkt = webpfad.html_base_setzen(html, "/studio/")
    assert '<base href="/studio/">' in direkt
    tunnel = webpfad.html_base_setzen(html, "/bianca/studio/")
    assert '<base href="/bianca/studio/">' in tunnel
    assert tunnel.count("<base ") == 1


def test_altes_hartes_base_wird_ersetzt():
    html = '<head>\n<base href="/studio/">\n<title>x</title></head>'
    neu = webpfad.html_base_setzen(html, "/bianca/studio/")
    assert '<base href="/bianca/studio/">' in neu
    assert '<base href="/studio/">' not in neu


def test_lisa_zieht_location_und_html_hinter_prefix():
    assert webpfad.location_hinter_prefix("/studio/", "/bianca") == "/bianca/studio/"
    assert webpfad.location_hinter_prefix("/bianca/studio/", "/bianca") == "/bianca/studio/"
    assert webpfad.location_hinter_prefix("https://x/studio/", "/bianca") == "https://x/studio/"
    html = '<base href="/studio/"><link href="/studio/web/stil.css">'
    neu = webpfad.html_studio_pfade(html, "/bianca")
    assert 'href="/bianca/studio/"' in neu
    assert 'href="/bianca/studio/web/stil.css"' in neu
    assert 'href="/studio/"' not in neu


def test_bianca_seite_direkt_ohne_prefix():
    html = bianca_server._studio_seite("index.html").body.decode("utf-8")
    assert '<base href="/studio/">' in html
    assert '<base href="/bianca/studio/">' not in html


def test_bianca_seite_hinter_lisa_prefix():
    req = SimpleNamespace(headers=_headers("/bianca"))
    html = bianca_server._studio_seite("index.html", req).body.decode("utf-8")
    assert '<base href="/bianca/studio/">' in html
    assert '<base href="/studio/">' not in html
    erg = bianca_server._studio_seite("ergebnisse.html", req).body.decode("utf-8")
    assert '<base href="/bianca/studio/">' in erg


def test_lisa_proxy_setzt_prefix_und_laesst_head_zu():
    src = open("lisa/server.py", encoding="utf-8").read()
    assert 'x-forwarded-prefix' in src
    assert '"HEAD"' in src or "HEAD" in src
    assert "location_hinter_prefix" in src
    assert "html_studio_pfade" in src
