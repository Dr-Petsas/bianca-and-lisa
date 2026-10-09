"""Anruf 205930f8 (Blessing, 06.10.2026): Namens-SMS kam beim Verschieben nie.

Live: Festnetz-Anrufer (+49 721 …), Termin am 15. Oktober um 16:20 Uhr
verschieben. Bianca fragte dreimal nach dem Behandler, der Nachname scheiterte
mehrmals („J, R, S, D, K, K.", „Falsch nein", „Termin.", „Blessing.") — der
Zähler stand aber nur bei 1, und ohne Handy gab es ohnehin kein SMS-Ziel.

Soll: jede gescheiterte Namensrunde zählt, ab der zweiten fragt Bianca beim
Festnetz-Anrufer nach einer Handynummer, liest sie vor und schickt nach dem Ja
die reine Namens-SMS (nie Reservierung, auch mit NAMENS_LINK=1). Der Behandler
wird im Verwaltungsweg nur einmal erfragt."""

import copy

import pytest

from bianca import flow, gehirn, verwalten
from kern import namenslink
from kern.tenants import laden

FESTNETZ = "+4972182518885"
RALF = {"id": "TphQRh53x8SToBSa8DdB", "name": "Doktor Ellen Ralf"}


def _termin(tid, kal, arzt, vor, nach):
    return {
        "id": tid,
        "iso": "2026-10-15T16:20+02:00",
        "date": "2026-10-15",
        "calendarId": kal,
        "doctorName": arzt,
        "motivId": "motiv-kontrolle",
        "motivName": "Kontrolle",
        "spoken": f"am Donnerstag, den fünfzehnten Oktober um sechzehn Uhr "
                  f"zwanzig bei {arzt}",
        "patientId": f"p-{tid}",
        "patientFirstName": vor,
        "patientLastName": nach,
        "patientName": f"{vor} {nach}",
        "patientPhone": "",
    }


TERMINE = [
    _termin("apt-a", "8krcWh7AuXEfgWc1blzQ", "Doktor Blessing", "Davide", "Jurisic"),
    _termin("apt-b", RALF["id"], "Doktor Ralf", "Maria", "Schulz"),
]


def _cf(aufrufe):
    def cf(route, body, timeout=None):
        aufrufe.append(dict(body))
        if body.get("action") == "create":
            return 200, {"status": "ok", "token": "tok-205930f8", "url": "u",
                         "sent": True}, {}
        return 200, {"status": "open"}, {}
    return cf


@pytest.fixture(params=["0", "1"], ids=["link-aus", "link-an"])
def umgebung(request, monkeypatch):
    monkeypatch.setenv("NAMENS_LINK", request.param)
    monkeypatch.delenv("NAMENS_SMS", raising=False)
    monkeypatch.setattr(flow.hintergrund, "anstossen", lambda sit: None)
    monkeypatch.setattr(
        verwalten.kal, "find_appointments_by_date",
        lambda tenant, day: {
            "ok": True, "appointments": copy.deepcopy(TERMINE),
            "dispatch": {"route": "firestoreAppointmentsByDate", "httpStatus": 200},
        },
    )
    monkeypatch.setattr(
        verwalten.kal, "find_patient_appointments",
        lambda *a, **k: {"ok": False, "notFound": True, "appointments": []},
    )
    aufrufe = []
    monkeypatch.setattr(namenslink, "_cf_call", _cf(aufrufe))
    return aufrufe


def _sit(caller=FESTNETZ):
    tenant = laden("blessing")
    tenant["calendars"] = list(tenant.get("calendars") or []) + [RALF]
    sit = {"tenant": tenant, "messages": [{"role": "system", "content": "x"}],
           "id": "sitzung-205930f8", "callerPhone": caller}
    s = gehirn.sammler(sit)
    s["modus"] = "verschieben"
    sit["verwAktiv"] = True
    verwalten._hinweis_merken(sit, "15. Oktober, 16.20 Uhr.", relativ=True)
    return sit, s


def _zug(sit, text):
    sit["_zugNr"] = int(sit.get("_zugNr") or 0) + 1
    aus = flow.zug(sit, text)
    return aus or {}


def test_behandler_nur_einmal_dann_der_name(umgebung):
    sit, s = _sit()
    handled, erst = verwalten._detail_dispatch(sit, None)
    assert handled and "Behandler" in erst["text"]
    assert s["frage"] == "arzt"
    aus = _zug(sit, "Weiss ich nicht, der Name ist Vorname Davide.")
    assert "behandler" not in aus["text"].lower()
    assert s["frage"] in {"buchstabieren", "nachname", "name"}


def test_festnetz_zweite_namensrunde_fragt_nach_handy_und_schickt_sms(umgebung):
    sit, s = _sit()
    verwalten._detail_dispatch(sit, None)
    _zug(sit, "Weiss ich nicht, der Name ist Vorname Davide.")
    assert s["frage"] in {"buchstabieren", "nachname", "name"}
    # „Davide" passt zu keinem Patienten am Termin (erste Runde), „Termin."
    # auf die Buchstabierfrage ist die zweite — wortgleich live.
    assert s["nameFehlversuche"] == 1
    aus = _zug(sit, "Termin.")
    assert s["nameFehlversuche"] == 2
    assert s["frage"] == "namens_handy", aus
    assert "festnetz" in aus["text"].lower()
    assert aus["text"].rstrip().endswith("?")
    assert not [a for a in umgebung if a.get("action") == "create"]

    # Handynummer in zwei Stücken: erst still weiterhören, dann vorlesen.
    teil = _zug(sit, "0177 600")
    assert teil.get("warte") and not teil.get("text")
    rb = _zug(sit, "4600")
    assert s["frage"] == "namens_handy_check"
    assert "stimmt das so" in rb["text"].lower()

    sms = _zug(sit, "Ja.")
    assert "sms" in sms["text"].lower()
    assert s["frage"] == "namenslink"
    create = [a for a in umgebung if a.get("action") == "create"]
    assert len(create) == 1
    assert create[0]["phone"] == "+491776004600"
    # Verschieben: nur der Name, nie Reservierung — auch mit NAMENS_LINK=1.
    assert create[0]["appointmentId"] == ""
    assert create[0]["patientId"] == ""
    assert create[0]["start"] == ""
    assert sit["namenslink"]["nurName"] is True


def test_handy_nein_fragt_einmal_neu(umgebung):
    sit, s = _sit()
    s["nameFehlversuche"] = 2
    aus = namenslink.rettung_starten(sit)
    assert s["frage"] == "namens_handy" and aus
    _zug(sit, "0 1 7 7 6 0 0 4 6 0 0")
    assert s["frage"] == "namens_handy_check"
    neu = _zug(sit, "Nein.")
    assert s["frage"] == "namens_handy"
    assert "noch einmal" in neu["text"].lower()
    _zug(sit, "0 1 5 2 5 3 0 4 7 5 6")
    _zug(sit, "Ja.")
    create = [a for a in umgebung if a.get("action") == "create"]
    assert create and create[0]["phone"] == "+491525304756"


def test_kein_handy_fuehrt_ins_langsame_buchstabieren(umgebung):
    sit, s = _sit()
    s["nameFehlversuche"] = 2
    namenslink.rettung_starten(sit)
    aus = _zug(sit, "Nein, ich habe kein Handy.")
    assert s["frage"] == "buchstabieren"
    assert "buchstabe für buchstabe" in aus["text"].lower()
    assert not [a for a in umgebung if a.get("action") == "create"]
    # Nur einmal je Anruf gefragt — nie eine Schleife.
    s["nameFehlversuche"] = 5
    assert namenslink.rettung_starten(sit) is None


def test_festnetz_als_handy_genannt_wird_nicht_genommen(umgebung):
    sit, s = _sit()
    s["nameFehlversuche"] = 2
    namenslink.rettung_starten(sit)
    aus = _zug(sit, "0 7 2 1 8 2 5 1 8 8 8 5")
    assert "keine handynummer" in aus["text"].lower()
    assert s["frage"] == "namens_handy"
    zweit = _zug(sit, "0 7 2 1 8 2 5 1 8 8 8 5")
    assert s["frage"] == "buchstabieren"
    assert "buchstab" in zweit["text"].lower()


def test_handy_anrufer_bekommt_die_sms_direkt(umgebung):
    sit, s = _sit(caller="+491776004600")
    verwalten._detail_dispatch(sit, None)
    _zug(sit, "Weiss ich nicht, der Name ist Vorname Davide.")
    aus = _zug(sit, "Termin.")
    assert s["frage"] == "namenslink", aus
    create = [a for a in umgebung if a.get("action") == "create"]
    assert len(create) == 1 and create[0]["phone"] == "+491776004600"
    assert create[0]["appointmentId"] == ""


def test_buchstaben_fragment_zaehlt_nicht(umgebung):
    sit, s = _sit()
    s["frage"] = "buchstabieren"
    vorher = int(s.get("nameFehlversuche") or 0)
    _zug(sit, "J, R,")
    assert int(s.get("nameFehlversuche") or 0) == vorher


def test_buchen_mit_link_an_bleibt_reservierungsmodus(monkeypatch):
    monkeypatch.setenv("NAMENS_LINK", "1")
    sit = {"sammler": {"modus": "buchen"}}
    assert namenslink._nur_name_fuer(sit) is False
    sit["sammler"]["modus"] = "verschieben"
    assert namenslink._nur_name_fuer(sit) is True
    monkeypatch.setenv("NAMENS_LINK", "0")
    sit["sammler"]["modus"] = "buchen"
    assert namenslink._nur_name_fuer(sit) is True


def test_namens_sms_verwaltung_schalter_aus(monkeypatch):
    """Stufe 1c: NAMENS_SMS_VERWALTUNG=0 schaltet die reine Namens-SMS in
    Absage/Verschieben/Auskunft ab — und ``starten`` legt dort keinen
    Reservierungs-Create ohne Slot an. Buchen bleibt unberührt."""
    def _nie_cf(*a, **k):  # ein CF-Aufruf wäre genau der Ghost-Termin-Weg
        raise AssertionError("starten() darf hier keinen CF-Create auslösen")
    monkeypatch.setattr(namenslink, "_cf_call", _nie_cf)
    monkeypatch.delenv("NAMENS_LINK", raising=False)
    monkeypatch.delenv("NAMENS_SMS", raising=False)
    monkeypatch.setenv("NAMENS_SMS_VERWALTUNG", "0")
    for modus in ("absagen", "verschieben", "auskunft"):
        sit = {"sammler": {"modus": modus}, "callerPhone": "+491776004600"}
        assert namenslink._nur_name_fuer(sit) is False, modus
        assert namenslink.starten(sit) is None, modus
    # Schalter an (Default) → Verwaltung bleibt reine Namens-SMS.
    monkeypatch.setenv("NAMENS_SMS_VERWALTUNG", "1")
    assert namenslink._nur_name_fuer(
        {"sammler": {"modus": "absagen"}, "callerPhone": "+491776004600"}
    ) is True
    # Buchen ist vom Schalter unberührt (NAMENS_LINK=1 → Reservierungsmodus).
    monkeypatch.setenv("NAMENS_LINK", "1")
    monkeypatch.setenv("NAMENS_SMS_VERWALTUNG", "0")
    assert namenslink._nur_name_fuer({"sammler": {"modus": "buchen"}}) is False
