"""Pfadvertrag des Bianca-Teststudios: direkt und hinter /bianca/."""

import inspect
from pathlib import Path
from urllib.parse import urljoin

from bianca import server as bianca_server
from lisa import server as lisa_server


ROOT = Path(__file__).parents[1]
WEB = ROOT / "tests" / "baukasten" / "editor_web"


def _basis(html: str) -> str:
    marker = '<base href="'
    assert marker in html
    return html.split(marker, 1)[1].split('"', 1)[0]


def test_studio_index_bleibt_hinter_bianca_prefix():
    html = bianca_server._studio_seite("index.html").body.decode("utf-8")
    basis = urljoin(
        "https://lisa-live.pickadoc-tunnel.com/bianca/studio/",
        _basis(html),
    )
    assert basis == "https://lisa-live.pickadoc-tunnel.com/bianca/studio/"
    assert urljoin(basis, "web/stil.css?v=7").startswith(
        "https://lisa-live.pickadoc-tunnel.com/bianca/studio/web/stil.css"
    )
    assert urljoin(basis, "web/app.js?v=7").startswith(
        "https://lisa-live.pickadoc-tunnel.com/bianca/studio/web/app.js"
    )
    assert urljoin(basis, "api/katalog") == (
        "https://lisa-live.pickadoc-tunnel.com/bianca/studio/api/katalog"
    )


def test_ergebnisse_nutzen_dieselbe_studiowurzel():
    html = bianca_server._studio_seite("ergebnisse.html").body.decode("utf-8")
    basis = urljoin(
        "https://lisa-live.pickadoc-tunnel.com/bianca/studio/ergebnisse/",
        _basis(html),
    )
    assert basis == "https://lisa-live.pickadoc-tunnel.com/bianca/studio/"
    assert urljoin(basis, "web/ergebnisse.js?v=7").startswith(
        "https://lisa-live.pickadoc-tunnel.com/bianca/studio/web/ergebnisse.js"
    )
    assert urljoin(basis, "api/laeufe") == (
        "https://lisa-live.pickadoc-tunnel.com/bianca/studio/api/laeufe"
    )
    assert urljoin(basis, "./") == (
        "https://lisa-live.pickadoc-tunnel.com/bianca/studio/"
    )


def test_slash_redirects_sind_relativ_und_proxy_reicht_location_durch():
    assert bianca_server.studio_index_redirect().headers["location"] == "studio/"
    assert (
        bianca_server.studio_ergebnisse_redirect().headers["location"]
        == "ergebnisse/"
    )
    proxy = inspect.getsource(lisa_server.bianca_durchreichen)
    assert '"location"' in proxy


def test_alle_sichtbaren_studio_assets_existieren():
    for name in ("index.html", "app.js", "stil.css", "ergebnisse.html", "ergebnisse.js"):
        assert (WEB / name).is_file(), name

