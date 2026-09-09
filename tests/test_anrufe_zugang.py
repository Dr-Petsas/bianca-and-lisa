"""Öffentlicher, aber geschützter Zugang zu Biancas Anruftranskripten."""

from pathlib import Path

import inspect

from bianca import server as bianca_server
from lisa import server
from lisa.server import _bianca_transkript_auth


def test_nur_patientenhaltige_anruf_api_ist_tokenpflichtig():
    assert _bianca_transkript_auth("api/anrufe")
    assert _bianca_transkript_auth("/api/anrufe/abc")
    assert _bianca_transkript_auth("api/anrufe/abc/audio/z001.wav")
    assert not _bianca_transkript_auth("")
    assert not _bianca_transkript_auth("anrufe")
    assert not _bianca_transkript_auth("anrufe.js")
    assert not _bianca_transkript_auth("api/start")


def test_viewer_tauscht_fragment_token_gegen_pfad_cookie():
    js = (Path(__file__).parents[1] / "bianca_web" / "anrufe.js").read_text(
        encoding="utf-8"
    )
    assert 'location.hash.slice(1)' in js
    assert 'fetch("transkript-zugang"' in js
    assert '"x-remote-token": zugangToken' in js
    assert '?token=' not in js
    route = inspect.getsource(server.bianca_durchreichen)
    assert "_bianca_transkript_auth(pfad)" in route
    assert "_bianca_transkript_guard(request)" in route
    handschlag = inspect.getsource(server.bianca_transkript_zugang)
    assert "_remote_guard(request)" in handschlag
    assert "httponly=True" in handschlag
    assert 'path="/bianca"' in handschlag


def test_anrufe_javascript_wird_vom_bianca_server_ausgeliefert():
    antwort = bianca_server.web_file("anrufe.js")
    assert Path(antwort.path).name == "anrufe.js"

