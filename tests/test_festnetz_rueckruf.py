"""W-FESTNETZ-RUECKRUF / W-KEIN-HANDY (07.10.2026, Anruf c449b685).

Live: eine Kollegenpraxis bat um Rückruf und diktierte ihre Festnetznummer
„0, 2, 1, 1, 3, 8 und 4, 6, 1, 0.“ — Bianca verlangte eine Handynummer
„für die Bestätigung“, auf „Hab keine.“ kam „Das habe ich akustisch nicht
sicher mitbekommen.“ Für eine Rückruf-Notiz gibt es keine SMS.
"""

import pytest

from bianca import flow, gehirn
from kern import namenslink
from kern.tenants import laden


def _abgeben_sit() -> dict:
    sit = {"id": "t-festnetz", "tenant": laden("meddent"), "messages": [],
           "callerPhone": "+492113846100"}
    sit["hirnAbgeben"] = {"offen": True, "was": "Rücksprache halten Bild anfordern"}
    s = gehirn.sammler(sit)
    s["nachname"] = "Stroll"
    s["frage"] = "telefon"
    return sit


@pytest.fixture
def notizen(monkeypatch):
    geschrieben = []

    def _notiz(sit, was=""):
        geschrieben.append({"was": was, "tel": gehirn.sammler(sit).get("telefon")})
        return True

    monkeypatch.setattr(flow.verwalten, "abgeben_notiz", _notiz)
    return geschrieben


def test_live_festnetz_gilt_als_rueckrufnummer(notizen):
    sit = _abgeben_sit()
    aus = flow._abgeben_zug(sit, "0, 2, 1, 1, 3, 8 und 4, 6, 1, 0.")
    assert aus and "Alles notiert" in aus["text"]
    assert "Handynummer" not in aus["text"] and "SMS" not in aus["text"]
    assert notizen and notizen[0]["tel"] == "0211384610"
    assert not sit.get("_festnetzStattHandy")


def test_festnetz_rueckruf_wird_nie_sms_ziel_der_geparkten_buchung(notizen, monkeypatch):
    sit = _abgeben_sit()
    erhalten = {}
    monkeypatch.setattr("kern.hirn.checkpoint_ergaenzen",
                        lambda sit, felder: erhalten.update(felder) or True)
    flow._abgeben_zug(sit, "0, 2, 1, 1, 3, 8 und 4, 6, 1, 0.")
    assert "telefonBekannt" not in erhalten


def test_buchung_verlangt_weiter_ein_handy():
    sit = {"id": "t-b", "tenant": laden("meddent"), "messages": []}
    s = gehirn.sammler(sit)
    s["frage"] = "telefon"
    gehirn.einsammeln(sit, "0, 2, 1, 1, 3, 8 und 4, 6, 1, 0.")
    assert not s.get("telefonOffen") and sit.get("_festnetzStattHandy") is True


def test_notaus_festnetz(monkeypatch, notizen):
    monkeypatch.setenv("FESTNETZ_RUECKRUF", "0")
    sit = _abgeben_sit()
    gehirn.einsammeln(sit, "0, 2, 1, 1, 3, 8 und 4, 6, 1, 0.")
    assert sit.get("_festnetzStattHandy") is True


@pytest.mark.parametrize("satz", [
    "Hab keine.", "Ich habe keins.", "Nein, hab ich leider keins.",
    "Ich habe kein Handy.", "Nur Festnetz.", "Ich hab nur das Festnetz.",
])
def test_kein_handy_erkannt(satz):
    assert flow._kein_handy(satz), satz


@pytest.mark.parametrize("satz", [
    "Ich habe keine andere Nummer.", "Hab keine Ahnung, wo das Handy ist, Moment.",
    "Ich habe keine Zeit am Montag.", "Null eins sieben sieben.",
])
def test_kein_handy_gegenproben(satz):
    assert not flow._kein_handy(satz), satz


def test_kein_handy_notaus(monkeypatch):
    monkeypatch.setenv("KEIN_HANDY", "0")
    assert not flow._kein_handy("Hab keine.")


def _buchungs_sit() -> dict:
    sit = {"id": "t-kh", "tenant": laden("meddent"), "messages": [],
           "callerPhone": "+492113846100"}
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen", "warSchonMal": False, "phase": "",
        "arzt": {"typ": "genannt", "calendarId": "c", "calendarName": "Petsas"},
        "grund": "Kontrolle", "motivId": "m1", "motivName": "Kontrolle",
        "wunsch": {}, "vorname": "Anna", "nachname": "Stroll",
        "slotIso": "2026-10-22T09:00:00+02:00",
        "versicherung": "gesetzlich", "versicherungOk": True,
        "pzr": "nein", "arztNotizFrage": "nein",
        "frage": "telefon", "telefonPflicht": True,
    })
    sit["buchIntent"] = True
    sit["frageLeer"] = {}
    return sit


def test_hab_keine_schliesst_buchung_sofort_ehrlich(notizen, monkeypatch):
    monkeypatch.setattr(flow.kal, "book_slot",
                        lambda *a, **k: pytest.fail("ohne Handy darf nichts gebucht werden"))
    sit = _buchungs_sit()
    aus = flow.zug(sit, "Hab keine.")
    assert aus and "Ohne Handynummer" in aus["text"]
    assert notizen and "keine Handynummer" in notizen[0]["was"]
    assert gehirn.sammler(sit)["phase"] == "fertig"


def test_namens_sms_hab_keine_fuehrt_ins_buchstabieren():
    sit = {"id": "t-n", "tenant": laden("meddent"), "messages": []}
    s = gehirn.sammler(sit)
    s["frage"] = "namens_handy"
    aus = namenslink.handy_zug(sit, "Hab keine.")
    assert aus and "buchstabieren" in aus["text"].lower()
    assert s["frage"] == "buchstabieren"


def test_namens_sms_keine_andere_nummer_ist_keine_ablehnung():
    sit = {"id": "t-n2", "tenant": laden("meddent"), "messages": []}
    gehirn.sammler(sit)["frage"] = "namens_handy"
    aus = namenslink.handy_zug(sit, "Ich habe keine andere Nummer.")
    assert gehirn.sammler(sit)["frage"] == "namens_handy"
    assert aus and "Ziffer für Ziffer" in aus["text"]
