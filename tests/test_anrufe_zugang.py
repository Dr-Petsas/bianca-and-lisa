"""Öffentlicher, aber geschützter Zugang zu Biancas Anruftranskripten."""

from pathlib import Path

import inspect

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


def test_viewer_reicht_fragment_token_an_alle_api_wege():
    js = (Path(__file__).parents[1] / "bianca_web" / "anrufe.js").read_text(
        encoding="utf-8"
    )
    assert 'location.hash.slice(1)' in js
    assert 'function mitZugang(url)' in js
    assert 'fetch(mitZugang("api/anrufe")' in js
    assert 'return mitZugang(`api/anrufe/' in js
    route = inspect.getsource(server.bianca_durchreichen)
    assert "_bianca_transkript_auth(pfad)" in route
    assert "_remote_guard(request)" in route

