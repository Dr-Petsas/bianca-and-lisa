"""Thaler 08.09.2026 Leonid: Nachname nach der Buchung aendern.

Live: „mein Nachname hat sich geändert“ → Slot-Frage → fast Doppelbuchung.
Der Name muss in die Terminnotiz, nie wieder ins Angebot.
"""

from __future__ import annotations

from bianca import flow, gehirn
from kern.tenants import laden


def _sit_gebucht() -> dict:
    sit = {
        "tenant": laden("meddent"),
        "messages": [{"role": "system", "content": "x"}],
        "offered": [{"iso": "2026-09-10T17:00:00+02:00", "spoken": "übermorgen um siebzehn Uhr"}],
        "flussFrage": "Welcher davon passt Ihnen?",
        "booking": {"appointmentId": "appt-1"},
    }
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "phase": "gebucht",
        "frage": "",
        "vorname": "Leonid",
        "nachname": "Sarkaldeva",
        "buchstabiert": True,
        "patientId": "pat-1",
        "telefon": "01601874281",
        "telefonOk": True,
        "arzt": {"typ": "genannt", "calendarId": "cal-eva",
                 "calendarName": "Eva Thaler"},
        "grund": "akute Beschwerden/Notfall",
        "motivName": "KCH Akute Beschwerden / Notfall",
        "slotIso": "2026-09-10T17:00:00+02:00",
    })
    return sit


def _ohne_note(fn):
    echt = flow.kal.note_appointment
    notizen = []

    def fake(tenant, ctx, sit=None, *, note=""):
        notizen.append(note)
        return {"ok": True, "noted": True, "note": note, "spoken": "ok"}

    flow.kal.note_appointment = fake
    try:
        return fn(), notizen
    finally:
        flow.kal.note_appointment = echt


def test_gebucht_nachname_aendern_fragt_nicht_slots():
    sit = _sit_gebucht()

    def lauf():
        z1 = flow.zug(sit, "Ja, und mein Nachname hat sich geändert. Könnten Sie das auch noch umändern?")
        assert z1 and "buchstabieren" in z1["text"].lower()
        assert "passt" not in z1["text"].lower()
        assert gehirn.sammler(sit)["frage"] == "nachname_korr"
        assert sit.get("offered") == []
        z2 = flow.zug(sit, "D E H R A N I")
        return z1, z2

    (_, z2), notizen = _ohne_note(lauf)
    s = gehirn.sammler(sit)
    assert s["nachname"].lower() == "dehrani"
    assert s["phase"] == "gebucht"
    assert s["frage"] == ""
    assert z2 and "Dehrani" in z2["text"]
    assert "eintragen" not in z2["text"].lower()
    assert notizen and "Dehrani" in notizen[0] and "Sarkaldeva" in notizen[0]


def test_gebucht_ja_allein_bucht_nicht_nochmal():
    sit = _sit_gebucht()
    z = flow.zug(sit, "Ja.")
    assert z is None
    assert gehirn.sammler(sit)["phase"] == "gebucht"


def test_arzt_sprechname_eva_thaler_ist_frau():
    from kern.patients import arzt_sprechname
    t = {
        "calendars": [{"id": "c1", "name": "Eva Thaler"}],
    }
    assert arzt_sprechname("Thaler", t) == "Frau Thaler"
    assert arzt_sprechname("Eva Thaler") == "Frau Thaler"


def test_anrede_leonid_ist_herr():
    s = {"vorname": "Leonid", "nachname": "Sarkaldeva", "geschlecht": ""}
    assert gehirn.anrede(s) == "Herr Sarkaldeva"
