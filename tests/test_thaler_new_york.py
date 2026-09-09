"""Thaler-Livefälle 08./09.09.2026: Datenaufnahme und New-York-Abzweig.

Die kritischen Formularschritte bleiben deterministisch. Ein vermeintliches
Nebenthema darf weder Patientendaten erfinden noch die offene Zeitfrage
verlieren.
"""

from bianca import agent, flow, gehirn
from kern import hirn, intent, zimmer_map


def _tenant() -> dict:
    return {
        "clientId": zimmer_map.THALER_CLIENT,
        "locationId": "loc",
        "praxisName": "Zahnarztpraxis Eva Thaler",
        "defaultCalendarId": "cal-eva",
        "zimmerMap": dict(zimmer_map.DEFAULT_MAP),
        "calendars": [
            {"id": "cal-eva", "name": "Dr. Eva Thaler"},
            {"id": "cal-pro", "name": "Prophylaxe"},
        ],
    }


def _sit() -> dict:
    return {
        "stimme": "Bianca",
        "tenant": _tenant(),
        "messages": [{"role": "system", "content": "x"}],
        "motivKatalog": [],
    }


def test_kein_aktueller_termin_aber_nicht_neu_ist_bestand():
    """Live New York: Kein bestehender Termin bedeutet nicht Neupatient."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "frage": "schonmal"})

    neu = gehirn.einsammeln(
        sit,
        "Nee, ich hab noch keinen Termin bei Ihnen, aber ich bin auch nicht neu.",
    )

    assert s["warSchonMal"] is True
    assert "warSchonMal" in neu
    assert not s["vorname"] and not s["nachname"]


def test_fuellung_startet_den_sicheren_flow_ohne_llm(monkeypatch):
    """Wurzelfehler der Live-Session: Schon Turn eins muss den Job öffnen."""
    sit = _sit()
    hirn.init(sit)

    def niemals_llm(*_a, **_k):
        raise AssertionError("Der sichere Thaler-Handoff darf kein LLM brauchen")

    monkeypatch.setattr(agent.llm, "chat", niemals_llm)
    monkeypatch.setattr(agent.llm, "chat_stream", niemals_llm)
    monkeypatch.setattr(agent.flow.hintergrund, "anstossen", lambda _sit: None)
    monkeypatch.setenv("INTENT_NACHZUG", "0")

    aus = agent.user_turn(sit, "Hallo, ich brauche eine Füllung.")

    s = gehirn.sammler(sit)
    assert aus
    assert s["modus"] == "buchen"
    assert s["frage"] == "schonmal"
    assert s["grund"] == "Zahnersatz-Beratung"
    assert "schon einmal" in aus["text"]
    aktiv = next(a for a in sit["hirn"]["anliegen"] if a["id"] == sit["hirn"]["aktiv"])
    assert aktiv["handlung"] == "ANLEGEN"
    assert aktiv["quelle"] == "entdeckt"


def test_fuellungsfrage_und_verneinung_starten_keine_buchung():
    for text in (
        "Was kostet eine Füllung?",
        "Ich möchte keine Füllung.",
    ):
        deutung = intent.erkennen(_sit(), text)
        assert deutung.get("handlung") != "ANLEGEN", (text, deutung)


def test_buchstabier_rueckfrage_bestaetigt_den_sicheren_weg():
    """Live New York: „Soll ich … buchstabieren?“ darf nie mit Nein enden."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "frage": "buchstabieren",
        "warSchonMal": True,
        "arzt": {"typ": "genannt", "calendarId": "cal-eva", "calendarName": "Dr. Eva Thaler"},
        "grund": "Zahnersatz-Beratung",
    })

    aus = flow.zug(sit, "Soll ich meinen Namen buchstabieren?")

    assert aus
    assert "ja" in aus["text"].lower()
    assert "buchstab" in aus["text"].lower()
    assert s["frage"] == "buchstabieren"


def test_new_york_verliert_die_offene_zeitfrage_nicht():
    """Live New York: Reiseort kurz würdigen, dann konkrete Verfügbarkeit."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "frage": "wunsch",
        "warSchonMal": True,
        "arzt": {"typ": "genannt", "calendarId": "cal-eva", "calendarName": "Dr. Eva Thaler"},
        "grund": "Zahnersatz-Beratung",
        "vorname": "Michael",
        "nachname": "Petsas",
        "buchstabiert": True,
        "pzr": "nein",
    })

    aus = flow.zug(sit, "aus New York.")

    assert aus
    assert "new york" not in aus["text"].lower() or "verstanden" in aus["text"].lower()
    assert "tag" in aus["text"].lower() or "vormittag" in aus["text"].lower()
    assert s["frage"] == "wunsch"
    assert s["wunsch"] is None
    assert not sit.get("lastBook")


def test_new_york_bestaetigt_keine_unvollstaendige_nummer_und_keine_akte():
    """Live New York: Reiseort ist kein Ja auf den Nummern-Readback."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "frage": "telefon_check",
        "warSchonMal": True,
        "arzt": {"typ": "genannt", "calendarId": "cal-eva", "calendarName": "Dr. Eva Thaler"},
        "grund": "Zahnersatz-Beratung",
        "vorname": "Michael",
        "nachname": "Petsas",
        "buchstabiert": True,
        "telefonOffen": "01776004600",
    })

    aus = flow.zug(sit, "aus New York.")

    assert aus
    assert "ja oder nein" in aus["text"].lower()
    assert s["frage"] == "telefon_check"
    assert s["telefon"] == ""
    assert s["telefonOffen"] == "01776004600"
    assert not sit.get("lastCreate")
    assert "angelegt" not in aus["text"].lower()


def test_nach_erfolgloser_slotsuche_danke_beendet_statt_zu_wiederholen(monkeypatch):
    """Live Andrejevic: Nach echter Rückrufnotiz keine Slot-Suche in Schleife."""
    sit = _sit()
    sit["praxisNotiz"] = "Marija Andrejevic wollte neu buchen — kein freier Termin."
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "phase": "fertig",
        "frage": "",
        "warSchonMal": True,
        "arzt": {"typ": "genannt", "calendarId": "cal-eva", "calendarName": "Dr. Eva Thaler"},
        "grund": "Kontrolle",
        "wunsch": {},
        "vorname": "Marija",
        "nachname": "Andrejevic",
    })
    monkeypatch.setattr(
        flow,
        "_angebot",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("keine neue Slotsuche")),
    )

    aus = flow.zug(sit, "Okay, vielen Dank")

    assert aus
    assert "wiederhören" in aus["text"].lower()
    assert "kein freier termin" not in aus["text"].lower()
