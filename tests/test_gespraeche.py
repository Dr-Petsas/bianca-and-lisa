"""Gesprächskarte: eine Aufzeichnung, ein Gedächtnis-Eintrag."""

from __future__ import annotations

from lisa import gespraeche


def _sit(**kw):
    sit = {
        "id": "abc123",
        "startedAt": "2026-08-30T08:00:00+00:00",
        "auftrag": "Recall im September",
        "probe": False,
        "patient": {"id": "p1", "name": "Anna Berger", "phone": "01761110001"},
        "kampagne": {"campaignId": "c1"},
        "zuege": [
            {"art": "start", "textIn": "", "text": "Guten Tag, Spreche ich mit Anna Berger?",
             "audioUrl": "/api/audio/a.wav"},
            {"art": "listen", "textIn": "Ja.", "text": "Wir rufen zur Kontrolle an.",
             "audioUrl": "/api/audio/b.wav"},
        ],
        "tools": [],
    }
    sit.update(kw)
    return sit


def test_gedaechtnis_id_ist_stabil():
    assert gespraeche.gedaechtnis_id(_sit()) == "telefonki:lisa_call:abc123"
    assert gespraeche.gedaechtnis_id(_sit(gedaechtnisId="x")) == "x"


def test_karte_hat_transkript_und_keine_zweite_id():
    k = gespraeche.karte(_sit())
    assert k["sessionId"] == "abc123"
    assert k["gedaechtnisId"] == "telefonki:lisa_call:abc123"
    assert k["hasAudio"]
    assert [x["role"] for x in k["transcript"]] == ["agent", "user", "agent"]
    assert k["campaignId"] == "c1"
    assert k["patientId"] == "p1"


def test_probe_wird_in_liste_ausgeblendet(monkey=None):
    from lisa import session
    echt = dict(session._STORE)
    session._STORE.clear()
    session._STORE["p"] = _sit(id="probe1", probe=True)
    session._STORE["e"] = _sit(id="echt1", probe=False)
    try:
        ids = [c["sessionId"] for c in gespraeche.liste()]
        assert "echt1" in ids
        assert "probe1" not in ids
        assert any(c["sessionId"] == "probe1" for c in gespraeche.liste(auch_probe=True))
    finally:
        session._STORE.clear()
        session._STORE.update(echt)
