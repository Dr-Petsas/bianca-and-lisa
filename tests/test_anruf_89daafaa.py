"""Regressionen aus Blessings Live-Anruf 89daafaa vom 15.09.2026.

Der Kalender-Write war erfolgreich. Fehlerhaft waren der Gesprächsweg davor
und danach:
- "den frühestmöglichen" wurde zunächst richtig gewählt, nach der Korrektur
  des gesprochenen Besuchsgrunds aber wieder verworfen;
- "Hautkrebs-Screening" wurde als "Kontrolle" vorgelesen und provozierte
  genau diese Korrektur;
- die Vorbereitungsnachricht für die Ärztin war abgeschaltet;
- der ausdrückliche Notizwunsch nach der Buchung lief in einer
  "Kann ich sonst noch etwas tun?"-Schleife.
"""

from __future__ import annotations

import copy

import pytest

from bianca import agent, flow, gehirn, session
from kern import hirn, sprech
from kern.tenants import laden


SCREENING_ID = "d8gQBR3fJiE0tAAR5c7t"
KALENDER_ID = "8krcWh7AuXEfgWc1blzQ"
FRUEH = "2026-10-19T12:30:00+02:00"
SPAET = "2026-12-07T11:30:00+01:00"
ANGEBOT = [
    {"iso": FRUEH, "spoken": "am Montag, den neunzehnten Oktober um zwölf Uhr dreißig",
     "calendarId": KALENDER_ID},
    {"iso": SPAET, "spoken": "am Montag, den siebten Dezember um elf Uhr dreißig",
     "calendarId": KALENDER_ID},
]


@pytest.fixture(autouse=True)
def _ohne_nachzug(monkeypatch):
    monkeypatch.setenv("INTENT_NACHZUG", "0")


def _tenant() -> dict:
    tenant = copy.deepcopy(laden("blessing"))
    tenant["_testNoWrite"] = True
    return tenant


def _angebot_sit(*, phase: str = "bestaetigen") -> dict:
    sit = {
        "tenant": _tenant(),
        "messages": [],
        "offered": copy.deepcopy(ANGEBOT),
        "angebotKalender": {
            "calendarId": KALENDER_ID,
            "calendarName": "Doktor Charlotte Blessing",
        },
        "slotVorrat": [x["iso"] for x in ANGEBOT],
        "vorratKey": "screening",
        "vorratFuer": f"{KALENDER_ID}|{SCREENING_ID}",
        "vorratGemerkt": True,
    }
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "phase": phase,
        "frage": "bestaetigung" if phase == "bestaetigen" else "slotwahl",
        "warSchonMal": True,
        "arzt": {
            "typ": "einzig",
            "calendarId": KALENDER_ID,
            "calendarName": "Doktor Charlotte Blessing",
        },
        "grund": "Kontrolle",
        "grundWortlaut": "Hautkrebsscreening.",
        "motivId": SCREENING_ID,
        "motivName": "Hautkrebs-Screening",
        "wunsch": {},
        "slotIso": FRUEH if phase == "bestaetigen" else "",
        "vorname": "Peter",
        "nachname": "Mayer",
        "buchstabiert": True,
        "versicherung": "gesetzlich",
        "versicherungOk": True,
        "telefon": "01776004600",
        "telefonOk": True,
        "pzr": "nein",
        "bleaching": "nein",
    })
    return sit


def _gebucht_sit() -> dict:
    sit = {
        "tenant": _tenant(),
        "messages": [],
        "lastBook": {
            "ok": True,
            "booked": True,
            "appointmentId": "7JedjkT8xBOCO23mpqwa",
            "slotIso": FRUEH,
            "spoken": "Der Termin ist fest eingetragen.",
        },
        "booking": {
            "appointmentId": "7JedjkT8xBOCO23mpqwa",
            "slotIso": FRUEH,
            "calendarId": KALENDER_ID,
            "visitMotiveId": SCREENING_ID,
        },
        "sonstNochGefragt": True,
        "flussFrage": "Kann ich sonst noch etwas für Sie tun?",
    }
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "phase": "gebucht",
        "frage": "sonst_noch",
        "grund": "Hautkrebs-Screening",
        "motivId": SCREENING_ID,
        "motivName": "Hautkrebs-Screening",
        "slotIso": FRUEH,
        "vorname": "Peter",
        "nachname": "Mayer",
        "telefon": "01776004600",
        "telefonOk": True,
    })
    return sit


def test_live_fruehestmoeglichen_waehlt_den_zeitlich_fruehesten_slot():
    # Nicht "erstes Array-Element", sondern wirklich die früheste ISO-Zeit.
    assert flow._slot_wahl("Den Frühestmöglichen, bitte.", list(reversed(ANGEBOT))) == FRUEH


def test_motivkorrektur_darf_die_relative_auswahl_nicht_verwerfen(monkeypatch):
    sit = _angebot_sit()
    s = gehirn.sammler(sit)
    monkeypatch.setattr(flow.hintergrund, "anstossen", lambda *a, **k: None)
    monkeypatch.setattr(
        flow,
        "_angebot",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("gleiches Motiv darf weder neu suchen noch neu auswählen")
        ),
    )

    aus = flow._aenderung_zug(
        sit,
        "Nee, keine Kontrolle, Hautkrebs-Screening.",
    )

    assert s["motivId"] == SCREENING_ID
    assert s["slotIso"] == FRUEH
    assert s["phase"] == "bestaetigen"
    assert sit["offered"] == ANGEBOT
    mund = sprech.sanitize(aus["text"])
    assert "Hautscreening" in mund
    assert "Kontrolle" not in mund
    assert "neunzehnten Oktober" in mund


def test_echter_motivwechsel_verwirft_den_alten_slot_weiterhin(monkeypatch):
    sit = _angebot_sit()
    s = gehirn.sammler(sit)
    aufrufe = []
    monkeypatch.setattr(flow.hintergrund, "anstossen", lambda *a, **k: None)
    monkeypatch.setattr(
        flow,
        "_angebot",
        lambda *a, **k: aufrufe.append(True) or {"text": "NEUES ANGEBOT"},
    )

    aus = flow._aenderung_zug(sit, "Nein, es geht um Rosacea.", feld="grund")

    assert s["motivId"] != SCREENING_ID
    assert s["slotIso"] == ""
    assert sit["offered"] == []
    assert aufrufe == [True]
    assert "NEUES ANGEBOT" in aus["text"]


def test_screening_wird_spezifisch_aber_ohne_krebs_vorgelesen():
    assert sprech.ohne_krebs("Hautkrebs-Screening") == "Hautscreening"
    assert sprech.ohne_krebs("Hautkrebsvorsorge") == "Hautvorsorge"
    assert sprech.ohne_krebs("Krebs") == "Kontrolle"


def test_blessing_fragt_vor_buchung_einmal_nach_doktor_nachricht(monkeypatch):
    sit = _angebot_sit()
    s = gehirn.sammler(sit)
    s.update({"pzr": "nein", "arztNotizFrage": "", "frage": "bestaetigung"})
    monkeypatch.setattr(gehirn, "pzr_noch_fragen", lambda *a, **k: False)
    monkeypatch.setattr(
        flow,
        "_buchen",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("vor der Nachricht darf noch nicht gebucht werden")
        ),
    )

    aus = flow._nach_ok_buchen(sit, "Ja.")

    assert aus["text"].count("?") == 1
    assert "Ärztin" in aus["text"]
    assert "Vorbereitung" in aus["text"]
    assert s["frage"] == "arzt_notiz"
    assert s["arztNotizFrage"] == "gefragt"


def test_blessing_buchungsabschluss_ist_kurz_und_beendet_den_anruf(monkeypatch):
    sit = _angebot_sit()
    s = gehirn.sammler(sit)
    s.update({
        "grund": "Hautkrebs-Screening",
        "grundWortlaut": "Hautkrebsscreening",
        "arztNotizFrage": "nein",
        "phase": "bestaetigen",
        "aktePhone": "01776004600",
        "telefonAlt": "",
    })
    monkeypatch.setattr(
        flow.kal,
        "book_slot",
        lambda *a, **k: {
            "ok": True,
            "booked": True,
            "dryRun": False,
            "slotIso": FRUEH,
            "appointmentId": "7JedjkT8xBOCO23mpqwa",
            "spoken": (
                "Der Termin am Montag, den neunzehnten Oktober um zwölf Uhr "
                "dreißig ist fest eingetragen."
            ),
        },
    )

    aus = flow._buchen(sit)

    assert aus.get("hangup") is True
    assert "sonst noch" not in aus["text"].casefold()
    assert "Anamnese" not in aus["text"]
    assert "Datenschutz" not in aus["text"]
    assert "Bestätigung" in aus["text"]
    assert "Unterlagen" in aus["text"]
    assert "Auf Wiederhören" in aus["text"]
    assert "?" not in aus["text"]
    assert len(sprech.tts_saetze(aus["text"])) <= 3
    assert s["frage"] == ""


def test_notizwunsch_nach_buchung_wird_geklaert_bestaetigt_und_geschrieben():
    sit = _gebucht_sit()
    s = gehirn.sammler(sit)

    eins = flow.zug(sit, "Kannst du noch eine Notiz dazu schreiben?")
    assert "welche" in eins["text"].casefold()
    assert "Nachricht" in eins["text"]
    assert "sonst noch" not in eins["text"].casefold()
    assert s["frage"] == "termin_notiz"

    zwei = flow.zug(sit, "Ja, eine Notiz noch in den Termin eintragen, geht das?")
    assert "Nachricht" in zwei["text"]
    assert "sonst noch" not in zwei["text"].casefold()
    assert s["frage"] == "termin_notiz"

    drei = flow.zug(
        sit,
        "Bitte schreiben Sie: Ich nehme Marcumar und bringe den Medikamentenplan mit.",
    )
    assert "Marcumar" in drei["text"]
    assert "Soll ich" in drei["text"]
    assert s["frage"] == "termin_notiz_check"
    assert not sit.get("lastNote")

    vier = flow.zug(sit, "Ja.")
    assert sit["lastNote"]["ok"] is True
    assert "Marcumar" in sit["lastNote"]["note"]
    assert "sonst noch" not in vier["text"].casefold()
    assert vier.get("hangup") is True
    assert s["frage"] == ""


def test_notiz_readback_schreibt_ohne_ja_nichts():
    sit = _gebucht_sit()
    s = gehirn.sammler(sit)

    aus = flow.zug(
        sit,
        "Schreiben Sie als Nachricht: Bitte den Ausschlag am Rücken mit ansehen.",
    )

    assert "Ausschlag am Rücken" in aus["text"]
    assert s["frage"] == "termin_notiz_check"
    assert not sit.get("lastNote")
    assert not any(
        x.get("name") == "note_appointment" for x in (sit.get("tools") or [])
    )


def test_nein_auf_notiz_readback_fragt_nur_nach_dem_neuen_inhalt():
    sit = _gebucht_sit()
    flow.zug(
        sit,
        "Schreiben Sie als Nachricht: Bitte den Ausschlag am Rücken mit ansehen.",
    )

    aus = flow.zug(sit, "Nein.")

    assert "stattdessen" in aus["text"]
    assert aus["text"].count("?") == 1
    assert gehirn.sammler(sit)["frage"] == "termin_notiz"
    assert not sit.get("lastNote")


def test_hallo_mitten_in_slotwahl_bleibt_bei_der_offenen_terminfrage(monkeypatch):
    sit = session.neu(tenant=_tenant())
    agent.start_reply(sit)
    hirn.anliegen_hinzufuegen(
        sit,
        hirn._anliegen("ANLEGEN", "VORGANG", spiegel="Termin vereinbaren"),
        aktivieren=True,
    )
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "phase": "angebot",
        "frage": "slotwahl",
        "grund": "Hautkrebs-Screening",
        "motivId": SCREENING_ID,
        "motivName": "Hautkrebs-Screening",
        "wunsch": {},
    })
    sit["offered"] = copy.deepcopy(ANGEBOT)
    monkeypatch.setattr(
        agent.llm,
        "chat",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("Hallo bei offener Slotwahl braucht kein LLM")
        ),
    )

    aus = agent.user_turn(sit, "Hallo.")

    assert "Welcher" in aus["text"]
    assert "neunzehnten Oktober" in aus["text"]
    assert "Absage" not in aus["text"]
    assert s["frage"] == "slotwahl"


def test_task_auswahl_spricht_keinen_llm_vorsatz_vor_der_jobfrage(monkeypatch):
    sit = session.neu(tenant=_tenant())
    agent.start_reply(sit)
    vorab = []
    monkeypatch.setattr(
        agent.llm,
        "chat_stream",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("Task-Auswahl darf nie vorab aus dem LLM sprechen")
        ),
    )
    monkeypatch.setattr(
        agent.llm,
        "chat",
        lambda *a, **k: {
            "ok": True,
            "text": "Das klingt nach einer wichtigen Angelegenheit.",
            "tool_calls": [],
        },
    )

    aus = agent.user_turn(
        sit,
        "Ich mache meine Kampf eine Abfrage.",
        vorab=vorab.append,
    )

    assert vorab == []
    assert "wichtigen Angelegenheit" not in aus["text"]
    assert aus["text"].count("?") == 1


def test_task_auswahl_spricht_auch_bei_anderen_mandanten_keinen_vorsatz(monkeypatch):
    """W-RUHE (15.09.2026): die Vorsatz-Sperre während der semantischen
    Task-Auswahl gilt jetzt für JEDEN Mandanten (Chef: "ein Thema nach dem
    anderen") — nicht mehr nur Blessing. Für meddent lief früher noch ein
    Streaming-Vorsatz; das wirkte hektisch."""
    tenant = copy.deepcopy(laden("meddent"))
    tenant["_testNoWrite"] = True
    sit = session.neu(tenant=tenant)
    agent.start_reply(sit)
    vorab = []

    monkeypatch.setattr(
        agent.llm,
        "chat_stream",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("Task-Auswahl darf bei keinem Mandanten vorab sprechen")
        ),
    )
    monkeypatch.setattr(
        agent.llm,
        "chat",
        lambda *a, **k: {
            "ok": True,
            "text": "Das klingt nach einer wichtigen Angelegenheit.",
            "tool_calls": [],
        },
    )

    # Kein Streaming-Vorsatz während der Task-Auswahl (chat_stream würfe);
    # der nicht-streamende chat-Pfad wird genutzt.
    agent.user_turn(
        sit,
        "Ich mache meine Kampf eine Abfrage.",
        vorab=vorab.append,
    )

    assert vorab == [], "meddent streamt während der Task-Auswahl keinen Vorsatz mehr"
