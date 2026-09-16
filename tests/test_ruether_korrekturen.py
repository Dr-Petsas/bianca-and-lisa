"""Rüther-Liveanrufe 008a9f2c / 1dc0a04a vom 16.09.2026.

Regressionen für zwei konkrete Gesprächsfehler:
- ein klar genannter neuer Besuchsgrund muss den alten Terminrahmen ersetzen;
- Ben fordert die Nachnamen-Schreibweise direkt an und bestätigt sie, bevor
  er zum Vornamen weitergeht.
"""

from __future__ import annotations

import copy

import pytest

from bianca import flow, gehirn
from kern import gespraechsruhe
from kern.tenants import laden
from stt_serve.postcorrect import correct_transcript


KALENDER = "6enqS7xObw02u3S1pfXM"
ALT_SLOT = "2026-09-16T11:30:00+02:00"
HORMON = {
    "id": "gyn-hormonstatus",
    "name": "GYN Hormonstatus Besprechung",
    "allowOnlineBooking": True,
    "calendarIds": [KALENDER],
}
VORSORGE = {
    "id": "gyn-krebsvorsorge",
    "name": "GYN Krebsvorsorge",
    "allowOnlineBooking": True,
    "calendarIds": [KALENDER],
}


@pytest.fixture(autouse=True)
def _kein_hintergrund(monkeypatch):
    monkeypatch.setattr(flow.hintergrund, "anstossen", lambda *a, **k: None)


def _tenant() -> dict:
    t = copy.deepcopy(laden("ruether"))
    t["visitMotives"] = [copy.deepcopy(HORMON), copy.deepcopy(VORSORGE)]
    return t


def _vollstaendige_buchung() -> dict:
    sit = {
        "tenant": _tenant(),
        "motivKatalog": [copy.deepcopy(HORMON), copy.deepcopy(VORSORGE)],
        "messages": [],
        "offered": [{"iso": ALT_SLOT, "calendarId": KALENDER}],
        "slotVorrat": [ALT_SLOT],
        "vorratKey": "hormon",
        "vorratFuer": f"{KALENDER}|{HORMON['id']}",
        "vorratGemerkt": True,
        "angebotKalender": {
            "calendarId": KALENDER,
            "calendarName": "Doktor Denise Rüther",
        },
    }
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "phase": "bestaetigen",
        "frage": "bestaetigung",
        "warSchonMal": False,
        "arzt": {
            "typ": "genannt",
            "calendarId": KALENDER,
            "calendarName": "Doktor Denise Rüther",
        },
        "grund": "Hormonstatus Besprechung",
        "grundWortlaut": "Forsabe.",
        "motivId": HORMON["id"],
        "motivName": HORMON["name"],
        "wunsch": {"hourMin": 0, "hourMax": 12},
        "slotIso": ALT_SLOT,
        "vorname": "Kiriakos",
        "nachname": "Tannis",
        "buchstabiert": True,
        "versicherung": "gesetzlich",
        "versicherungOk": True,
    })
    return sit


def _namen_sitzung(mandant: str = "ruether") -> dict:
    sit = {"tenant": copy.deepcopy(laden(mandant)), "messages": []}
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "warSchonMal": False,
        "arzt": {
            "typ": "genannt",
            "calendarId": KALENDER,
            "calendarName": "Doktor Denise Rüther",
        },
        "grund": "Kontrolluntersuchung",
        "motivId": VORSORGE["id"],
        "motivName": VORSORGE["name"],
        "wunsch": {},
    })
    return sit


def test_live_einwand_wechselt_hormonstatus_sofort_auf_vorsorge(monkeypatch):
    sit = _vollstaendige_buchung()
    s = gehirn.sammler(sit)
    gesehen = []

    def neues_angebot(*_args, **_kwargs):
        gesehen.append({
            "motivId": s["motivId"],
            "grund": s["grund"],
            "slotIso": s["slotIso"],
            "offered": list(sit.get("offered") or []),
        })
        return {"text": "NEUES VORSORGE-ANGEBOT"}

    monkeypatch.setattr(flow, "_angebot", neues_angebot)
    aus = flow.zug(
        sit,
        "Nein, keine Hormonstase zu besprechen, einfach eine Vorsorge.",
    )

    assert s["motivId"] == VORSORGE["id"]
    assert "vorsorge" in s["motivName"].casefold()
    assert s["grundWortlaut"] == "eine Vorsorge."
    assert s["slotIso"] == ""
    assert sit["offered"] == []
    assert gesehen == [{
        "motivId": VORSORGE["id"],
        "grund": "Kontrolluntersuchung",
        "slotIso": "",
        "offered": [],
    }]
    assert aus and "NEUES VORSORGE-ANGEBOT" in aus["text"]


def test_reine_feldwahl_besuchsgrund_bestaetigt_nie_das_alte_motiv(monkeypatch):
    sit = _vollstaendige_buchung()
    s = gehirn.sammler(sit)
    s["phase"] = ""
    s["frage"] = "aenderung"
    monkeypatch.setattr(
        flow,
        "_angebot",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("ohne neuen Grund darf keine Slotsuche starten")
        ),
    )

    aus = flow.zug(sit, "Besuchsgrund.")

    assert s["grund"] == ""
    assert s["motivId"] == ""
    assert s["slotIso"] == ""
    assert sit["offered"] == []
    assert "Worum geht es" in aus["text"]
    assert "Hormonstatus" not in aus["text"]
    assert "Soll ich das so eintragen" not in aus["text"]


def test_ruether_forsabe_wird_nur_mit_vorsorge_hotword_korrigiert():
    assert correct_transcript("Forsabe.", ["Vorsorge"]) == (
        "Vorsorge.",
        [("Forsabe", "Vorsorge")],
    )
    assert correct_transcript("Forsabe.", ["Rüther"])[0] == "Forsabe."


def test_ruether_fragt_nachnamen_direkt_buchstabe_fuer_buchstabe():
    sit = _namen_sitzung()
    fid, frage = gehirn.naechste_frage(sit)

    assert fid == "nachname"
    assert "Buchstabe für Buchstabe" in frage
    assert frage.endswith("?")
    assert gespraechsruhe.saeubern(frage) == (frage, [])
    gehirn.sammler(sit)["frage"] = fid
    assert gehirn.stille_ms(gehirn.sammler(sit)) == 1500


def test_ruether_geht_erst_nach_buchstabierung_und_readback_zum_vornamen():
    sit = _namen_sitzung()
    s = gehirn.sammler(sit)
    s["frage"], _ = gehirn.naechste_frage(sit)

    nur_gesprochen = flow.zug(sit, "Tannis.")
    assert s["nachname"] == "Tannis"
    assert s["buchstabiert"] is False
    assert s["frage"] == "buchstabieren"
    assert "Buchstabe für Buchstabe" in nur_gesprochen["text"]
    assert "Vorname" not in nur_gesprochen["text"]

    buchstabiert = flow.zug(sit, "T-A-N-N-I-S, fertig.")
    assert s["nachname"] == "Tannis"
    assert s["buchstabiert"] is True
    assert s["frage"] == "nachname_check"
    assert "T wie Theodor" in buchstabiert["text"]
    assert "Ist das richtig?" in buchstabiert["text"]
    assert "Vorname" not in buchstabiert["text"]

    bestaetigt = flow.zug(sit, "Ja.")
    assert s["frage"] == "vorname"
    assert "Vorname" in bestaetigt["text"]


@pytest.mark.parametrize("mandant", ["meddent", "thaler", "blessing"])
def test_andere_mandanten_behalten_ihre_bisherige_nachnamenfrage(mandant):
    sit = _namen_sitzung(mandant)
    fid, frage = gehirn.naechste_frage(sit)
    assert fid == "buchstabieren"
    assert "Wie lautet der Nachname?" in frage
    assert "Buchstabe für Buchstabe" not in frage
