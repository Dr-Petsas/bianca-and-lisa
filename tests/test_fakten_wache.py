"""W-FAKTEN-WACHE (09.09.2026): eine Erledigt-Behauptung darf nur raus, wenn
das passende Werkzeug erfolgreich lief (Tool-Ledger = Wahrheit). Shadow loggt
nur, enforce schreibt um. Notaus FAKTEN_WACHE=off. Offline, kein Netz.
"""

from bianca import agent
from kern import fakten_wache, spur
from kern.tenants import laden


def _sit() -> dict:
    return {
        "stimme": "Bianca",
        "tenant": laden("meddent"),
        "sammler": {"modus": "buchen", "phase": "sammeln", "grund": "Kontrolle"},
        "messages": [{"role": "system", "content": "x"}],
    }


# --- reine Erkennung ---------------------------------------------------------

def test_gebucht_ohne_evidenz_ist_unbelegt():
    sit = _sit()
    assert fakten_wache.unbelegte_behauptung(sit, "Ihr Termin ist gebucht.") == "buchen"


def test_gebucht_mit_evidenz_ist_ok():
    sit = _sit()
    sit["lastBook"] = {"ok": True, "booked": True}
    assert fakten_wache.unbelegte_behauptung(sit, "Ihr Termin ist gebucht.") == ""


def test_abgesagt_ohne_evidenz():
    sit = _sit()
    assert fakten_wache.unbelegte_behauptung(sit, "Der Termin ist abgesagt.") == "absagen"


def test_verschoben_mit_evidenz_ok():
    sit = _sit()
    sit["lastMove"] = {"ok": True}
    assert fakten_wache.unbelegte_behauptung(sit, "Ich habe den Termin verschoben.") == ""


def test_notiz_ohne_evidenz():
    sit = _sit()
    assert fakten_wache.unbelegte_behauptung(sit, "Ich habe eine Notiz gemacht.") == "notiz"


def test_notiz_mit_evidenz_ok():
    sit = _sit()
    sit["noteWritten"] = True
    assert fakten_wache.unbelegte_behauptung(sit, "Ich habe eine Notiz gemacht.") == ""


def test_frage_ist_keine_behauptung():
    sit = _sit()
    assert fakten_wache.unbelegte_behauptung(sit, "Soll ich den Termin so eintragen?") == ""


def test_angebot_ist_keine_behauptung():
    sit = _sit()
    assert fakten_wache.unbelegte_behauptung(
        sit, "Ich hätte am Montag um neun etwas frei. Passt Ihnen das?") == ""


# --- Agent-Umgang: off / shadow / enforce -----------------------------------

def test_off_laesst_text_stehen(monkeypatch):
    monkeypatch.setenv("FAKTEN_WACHE", "off")
    sit = _sit()
    aus = agent._fakten_wache_anwenden(sit, "Ihr Termin ist gebucht.")
    assert aus == "Ihr Termin ist gebucht."
    assert not sit.get("_spur")


def test_shadow_loggt_ohne_umschreiben(monkeypatch):
    monkeypatch.setenv("FAKTEN_WACHE", "shadow")
    sit = _sit()
    aus = agent._fakten_wache_anwenden(sit, "Ihr Termin ist gebucht.")
    assert aus == "Ihr Termin ist gebucht."
    spuren = [e["w"] for e in spur.abholen(sit)]
    assert "fakten-wache-shadow" in spuren


def test_enforce_schreibt_unbelegte_behauptung_um(monkeypatch):
    monkeypatch.setenv("FAKTEN_WACHE", "enforce")
    sit = _sit()
    aus = agent._fakten_wache_anwenden(sit, "Ihr Termin ist gebucht.")
    assert "gebucht" not in aus.lower()
    assert "nicht falsch machen" in aus.lower() or "noch nicht erledigt" in aus.lower()
    spuren = [e["w"] for e in spur.abholen(sit)]
    assert "fakten-wache" in spuren


def test_enforce_laesst_belegte_behauptung_stehen(monkeypatch):
    monkeypatch.setenv("FAKTEN_WACHE", "enforce")
    sit = _sit()
    sit["lastBook"] = {"ok": True, "booked": True}
    aus = agent._fakten_wache_anwenden(sit, "Ihr Termin ist gebucht.")
    assert aus == "Ihr Termin ist gebucht."
