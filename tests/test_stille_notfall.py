"""W-STILLE / W-FUELLER-EINER: erster Ton unter 2 s, genau EIN Warte-Satz.

Die Fristen werden fuer den Test verkleinert; die Logik ist dieselbe.
Die Dock-Seite (Watchdog, max. 1 lokale Ansage) ist Browser-Code.
"""

import json
import time

import kern.dienst as dienst_mod
from kern import filler
from kern.dienst import Dienst, FILLER_MAX, FILLER_SPAET_S, NOTFALL_SAETZE


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


def test_langsamer_zug_bekommt_genau_einen_fueller():
    """Kalender-Haenger: EIN kurzer Satz, kein Nachschub-Sermon
    (Chef 08.09.: nie dreimal „ich schaue nach")."""
    alt = (dienst_mod.FILLER_SPAET_S, dienst_mod.FILLER_NACHSCHUB_S)
    dienst_mod.FILLER_SPAET_S = 0.05
    dienst_mod.FILLER_NACHSCHUB_S = 0.05
    try:
        d = _dienst(langsam_s=0.4)
        out = _zeilen(d, {}, "Haben Sie nächste Woche vormittags etwas frei?")
        arten = [z["type"] for z in out]
        assert arten[-1] == "reply"
        assert arten.count("filler") == 1
    finally:
        dienst_mod.FILLER_SPAET_S, dienst_mod.FILLER_NACHSCHUB_S = alt


def test_ja_ohne_schnellphase_bekommt_keinen_fueller():
    """Live 08.09.: bei jedem Satz „Einen Moment bitte." — Ja/Arzt ohne
    Slot/Confirm darf keinen allgemeinen Warte-Satz mehr auslösen."""
    alt = (dienst_mod.FILLER_SPAET_S, dienst_mod.FILLER_NACHSCHUB_S)
    dienst_mod.FILLER_SPAET_S = 0.05
    dienst_mod.FILLER_NACHSCHUB_S = 0.05
    try:
        d = _dienst(langsam_s=0.35, schnell=False)
        out = _zeilen(d, {}, "Ja?")
        assert [z["type"] for z in out] == ["reply"]
    finally:
        dienst_mod.FILLER_SPAET_S, dienst_mod.FILLER_NACHSCHUB_S = alt


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


def test_schnelle_phase_bekommt_neutralen_fueller_bei_haenger():
    """Chef 08.09.: 7–32 s Totenstille in der Buchung — nach 0,8 s
    ein neutrales „Einen Moment.", nie Kalender behaupten, nie drei."""
    alt = (dienst_mod.FILLER_SPAET_S, dienst_mod.FILLER_NACHSCHUB_S)
    dienst_mod.FILLER_SPAET_S = 0.05
    dienst_mod.FILLER_NACHSCHUB_S = 0.05
    try:
        d = _dienst(langsam_s=0.35, schnell=True)
        out = _zeilen(d, {}, "Ja.")
        arten = [z["type"] for z in out]
        assert arten[-1] == "reply"
        assert arten.count("filler") == 1
        urls = [z["audioUrl"] for z in out if z["type"] == "filler"]
        allgemein = set(filler.GRUPPEN["allgemein"])
        for url in urls:
            satz = next((s for s, u in d.filler_urls.items() if u == url), "")
            assert satz in allgemein, satz
    finally:
        dienst_mod.FILLER_SPAET_S, dienst_mod.FILLER_NACHSCHUB_S = alt


def test_kartei_fueller_statt_allgemein_wenn_fakt_liegt():
    """Chef 08.09.: Totzeit mit letztem Besuch, ohne Frage, einmal."""
    alt = (dienst_mod.FILLER_SPAET_S, dienst_mod.FILLER_NACHSCHUB_S)
    dienst_mod.FILLER_SPAET_S = 0.05
    dienst_mod.FILLER_NACHSCHUB_S = 0.05
    satz = "Letztes Mal die Kontrolle — einen Moment."
    try:
        d = _dienst(langsam_s=0.35, schnell=True)
        d.filler_urls[satz] = "/api/audio/kartei"
        sit = {
            "karteiFillerText": satz,
            "sammler": {"modus": "buchen", "phase": ""},
        }
        out = _zeilen(d, sit, "Nächste Woche vormittags.")
        urls = [z["audioUrl"] for z in out if z["type"] == "filler"]
        assert urls == ["/api/audio/kartei"]
        assert sit["karteiFillerGesagt"] is True
        assert sit["sammler"]["karteiFuellerGesagt"] is True
        # Zweiter Zug: kein zweiter Kartei-Satz.
        out2 = _zeilen(d, sit, "Der erste bitte.")
        urls2 = [z["audioUrl"] for z in out2 if z["type"] == "filler"]
        assert "/api/audio/kartei" not in urls2
    finally:
        dienst_mod.FILLER_SPAET_S, dienst_mod.FILLER_NACHSCHUB_S = alt


def test_produktions_fristen_halten_die_regel():
    """Erster Ton unter 2 s; genau ein Warte-Satz, kein Sermon."""
    assert FILLER_SPAET_S <= 2.0
    assert FILLER_MAX == 1


def test_notfall_ansagen_stehen_bereit():
    """Drei Eskalationsstufen; die letzte ist die ehrliche Dran-bleiben-Zeile
    (spielt das Dock auch im Fehlerfall, wenn Netz oder Server weg sind)."""
    assert len(NOTFALL_SAETZE) == 3
    assert "dran" in NOTFALL_SAETZE[-1]
