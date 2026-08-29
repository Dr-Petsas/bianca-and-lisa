"""W-STILLE (Chef 29.08.2026): nie mehr als ~1,5 s Stille nach dem Sprechende.

Prueft die Server-Seite: die Fueller-Frist gilt fuer JEDEN Zug (auch die
schnelle Phase), und solange die Antwort aussteht, kommt NACHSCHUB — erst
Inhalt (Vorab-Satz/Antwort) beendet die Kette. Die Fristen werden fuer den
Test verkleinert (echte Werte: 0,9 s / 2,4 s), die Logik ist dieselbe.
Die Dock-Seite (1,4-s-Watchdog mit lokalen Blob-Ansagen) ist Browser-Code
und wird per Live-Probe abgenommen.
"""

import json
import time

import kern.dienst as dienst_mod
from kern import filler
from kern.dienst import (Dienst, FILLER_MAX, FILLER_NACHSCHUB_S,
                         FILLER_SPAET_S, NOTFALL_SAETZE)


def _dienst(*, langsam_s: float = 0.0, schnell: bool = False) -> Dienst:
    d = Dienst(name="t", start_fn=lambda sit: {}, turn_fn=lambda sit, t, **k: {},
               schnell_fn=(lambda sit: True) if schnell else None)

    def antwort(sit, **k):
        if langsam_s:
            time.sleep(langsam_s)
        return {"ok": True, "empty": False, "text": "Antwort.", "audioUrl": ""}

    d.json_antwort = antwort
    # Fueller-URLs vorbelegen (im Test laeuft kein TTS): jeder Satz der
    # Rotations-Gruppe "allgemein" bekommt eine eigene Fake-URL.
    for i, satz in enumerate(filler.GRUPPEN["allgemein"]):
        d.filler_urls[satz] = f"/api/audio/f{i}"
    return d


def _zeilen(d: Dienst, sit: dict) -> list[dict]:
    return [json.loads(z) for z in d.zug_stream(sit, art="turn", text_in="Hallo")]


def test_schneller_zug_bleibt_ohne_fueller():
    d = _dienst()
    out = _zeilen(d, {})
    assert [z["type"] for z in out] == ["reply"]


def test_langsamer_zug_bekommt_fueller_und_nachschub():
    alt = (dienst_mod.FILLER_SPAET_S, dienst_mod.FILLER_NACHSCHUB_S)
    dienst_mod.FILLER_SPAET_S = 0.05
    dienst_mod.FILLER_NACHSCHUB_S = 0.08
    try:
        d = _dienst(langsam_s=0.4)
        out = _zeilen(d, {})
        arten = [z["type"] for z in out]
        assert arten[-1] == "reply"
        # Erster Fueller frueh, danach Nachschub — bis zum Deckel.
        assert arten.count("filler") == dienst_mod.FILLER_MAX
        urls = [z["audioUrl"] for z in out if z["type"] == "filler"]
        assert len(set(urls)) == len(urls)  # rotierend, nie derselbe Satz
    finally:
        dienst_mod.FILLER_SPAET_S, dienst_mod.FILLER_NACHSCHUB_S = alt


def test_schnelle_phase_haengt_nicht_stumm():
    """Regression: die alte 3,2-s-Frist liess Readback-/Kalender-Haenger in
    der schnellen Phase sekundenlang stumm — jetzt gilt die kurze Frist
    ueberall, die Zustandsmaschine schlaegt sie im Normalfall ohnehin."""
    alt = (dienst_mod.FILLER_SPAET_S, dienst_mod.FILLER_NACHSCHUB_S)
    dienst_mod.FILLER_SPAET_S = 0.05
    dienst_mod.FILLER_NACHSCHUB_S = 5.0
    try:
        d = _dienst(langsam_s=0.25, schnell=True)
        out = _zeilen(d, {})
        arten = [z["type"] for z in out]
        assert arten[0] == "filler"
        assert arten[-1] == "reply"
    finally:
        dienst_mod.FILLER_SPAET_S, dienst_mod.FILLER_NACHSCHUB_S = alt


def test_produktions_fristen_halten_die_regel():
    """0,9 s Frist + Dock-Vorlauf (~0,5-0,8 s) bleibt beim ersten Ton unter
    1,5 s; der Nachschub laesst zwischen zwei Fuellern nie mehr als ~1,5 s
    Stille (Fueller-Audio ~1,2 s + 2,4er-Frist ab Fueller-BEGINN)."""
    assert FILLER_SPAET_S <= 0.9
    assert FILLER_NACHSCHUB_S <= 2.4
    assert FILLER_MAX >= 2


def test_notfall_ansagen_stehen_bereit():
    """Drei Eskalationsstufen; die letzte ist die ehrliche Dran-bleiben-Zeile
    (spielt das Dock auch im Fehlerfall, wenn Netz oder Server weg sind)."""
    assert len(NOTFALL_SAETZE) == 3
    assert "dran" in NOTFALL_SAETZE[-1]
