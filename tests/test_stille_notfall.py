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
    # Fueller-URLs vorbelegen (im Test laeuft kein TTS).
    nr = 0
    for gruppe in filler.GRUPPEN.values():
        for satz in gruppe:
            d.filler_urls[satz] = f"/api/audio/f{nr}"
            nr += 1
    return d


def _zeilen(d: Dienst, sit: dict, text: str = "Hallo") -> list[dict]:
    return [json.loads(z) for z in d.zug_stream(sit, art="turn", text_in=text)]


def test_schneller_zug_bleibt_ohne_fueller():
    d = _dienst()
    out = _zeilen(d, {})
    assert [z["type"] for z in out] == ["reply"]


def test_langsamer_zug_bekommt_fueller_und_nachschub():
    """Nur wenn wirklich Kalender erwartet wird — Plauder-Zuege bleiben
    ohne Server-Fueller (Dock-Watchdog deckt Haenger)."""
    alt = (dienst_mod.FILLER_VORAB_S, dienst_mod.FILLER_NACHSCHUB_S)
    dienst_mod.FILLER_VORAB_S = 0.05
    dienst_mod.FILLER_NACHSCHUB_S = 0.08
    try:
        d = _dienst(langsam_s=0.4)
        out = _zeilen(d, {}, "Haben Sie nächste Woche vormittags etwas frei?")
        arten = [z["type"] for z in out]
        assert arten[-1] == "reply"
        assert arten.count("filler") == dienst_mod.FILLER_MAX
        urls = [z["audioUrl"] for z in out if z["type"] == "filler"]
        assert len(set(urls)) == len(urls)  # rotierend, nie derselbe Satz
    finally:
        dienst_mod.FILLER_VORAB_S, dienst_mod.FILLER_NACHSCHUB_S = alt


def test_plauderzug_bekommt_keinen_server_fueller():
    """„Wie heißt du?" darf keinen Nachschau-Füller auslösen — die echte
    Antwort (P5) oder der neutrale Dock-Watchdog sprechen."""
    d = _dienst(langsam_s=0.25)
    out = _zeilen(d, {}, "Wie heißt du?")
    assert [z["type"] for z in out] == ["reply"]


def test_schnelle_phase_ohne_geratenen_fueller():
    """Maschine/Readback liefern den ersten Ton selbst — kein „ich schaue
    nach" in die Buchungsfragen hinein."""
    d = _dienst(langsam_s=0.25, schnell=True)
    out = _zeilen(d, {}, "Ja.")
    assert [z["type"] for z in out] == ["reply"]


def test_produktions_fristen_halten_die_regel():
    """Kalender-Vorab bleibt früh; Nachschub hält die 1,5-s-Lücke."""
    assert dienst_mod.FILLER_VORAB_S <= 0.3
    assert FILLER_NACHSCHUB_S <= 2.4
    assert FILLER_MAX >= 2


def test_notfall_ansagen_stehen_bereit():
    """Drei Eskalationsstufen; die letzte ist die ehrliche Dran-bleiben-Zeile
    (spielt das Dock auch im Fehlerfall, wenn Netz oder Server weg sind)."""
    assert len(NOTFALL_SAETZE) == 3
    assert "dran" in NOTFALL_SAETZE[-1]
