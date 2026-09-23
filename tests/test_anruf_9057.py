"""Anruf 9057eb03 (Blessing, Jana Steinke) — offline.

Drei Brüche, bevor die Nummer in der Schleife landete:

1. „Wie lautet noch mal der zweite Termin?“ hat den zweiten Slot gewählt.
2. „Nein, … am 22.12. um 15.55“ hat das Angebot gelöscht und wieder
   vormittags/nachmittags gefragt. Angeboten war 15:50.
3. Nach needs_phone hat die Leitungsnummer die Frage still bestätigt und
   book_slot siebenmal ohne Akten-Update ausgelöst. „Wie lautet sie?“
   wurde als Wiederholung gestrichen.
"""

from __future__ import annotations

from bianca import flow, gehirn
from kern import reservierung, wiederholung
from kern.tenants import laden

ANGEBOT = [
    {"iso": "2026-12-22T15:50:00+01:00", "spoken": "Dienstag, der zweiundzwanzigste Dezember, um fünfzehn Uhr fünfzig"},
    {"iso": "2026-12-28T12:05:00+01:00", "spoken": "Montag, der achtundzwanzigste Dezember, um zwölf Uhr fünf"},
]


def test_zweiter_termin_noch_mal_ist_keine_wahl():
    assert flow._slot_wahl("Wie lautet noch mal der zweite Termin?", ANGEBOT) == ""
    assert flow._slot_wahl("den zweiten bitte", ANGEBOT) == ANGEBOT[1]["iso"]
    text = flow._slot_vorlesen("Wie lautet noch mal der zweite Termin?", ANGEBOT)
    assert "zwölf Uhr fünf" in text
    assert "fünfzehn Uhr fünfzig" not in text


def test_nein_mit_22_12_nimmt_15_50_nicht_die_tageszeitfrage():
    sit = {"tenant": laden("meddent"), "messages": [{"role": "system", "content": "x"}]}
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "phase": "bestaetigen",
        "frage": "bestaetigung",
        "vorname": "Jana",
        "nachname": "Steinke",
        "buchstabiert": True,
        "warSchonMal": True,
        "bekannt": True,
        "patientId": "p1",
        "grund": "Kontrolle",
        "motivId": "m1",
        "motivName": "Kontrolle",
        "arzt": {"typ": "genannt", "calendarId": "c1", "calendarName": "Doktor Blessing"},
        "slotIso": "2026-12-28T12:05:00+01:00",
        "telefon": "01624339906",
        "telefonOk": True,
    })
    sit["offered"] = list(ANGEBOT)

    def _kein_buch(*_a, **_k):
        raise AssertionError("book_slot")

    alt = flow.kal.book_slot
    flow.kal.book_slot = _kein_buch
    try:
        z = flow.zug(sit, "Nein, ich würde den Termin am 22.12. um 15.55 Uhr nehmen.")
    finally:
        flow.kal.book_slot = alt
    assert str(s.get("slotIso") or "").startswith("2026-12-22T15:50")
    gesagt = str((z or {}).get("text") or "").lower()
    assert "vormittags oder nachmittags" not in gesagt
    assert "eintragen" in gesagt


def test_needs_phone_setzt_leitungsnummer_nicht_still_erneut():
    sit = {
        "callerPhone": "+491624339906",
        "needsPhoneOffen": True,
        "sammler": {"telefonOk": False, "telefon": "", "telefonOffen": ""},
    }
    assert reservierung.nummer_still(sit) is False
    assert sit["sammler"].get("telefonOk") is not True

    offen = {
        "callerPhone": "+491624339906",
        "sammler": {"telefonOk": False},
    }
    assert reservierung.nummer_still(offen) is True
    assert offen["sammler"]["telefonOk"] is True


def test_wie_lautet_sie_bleibt_stehen():
    satz = "In Ihrer Akte fehlt noch eine Handynummer. Wie lautet sie?"
    sit = {"sammler": {"frage": "telefon"}, "messages": [], "waechterGesagt": []}
    aus = wiederholung.pruefen(
        sit, satz, frueher=[satz], frage_id="telefon",
    )
    assert "Wie lautet sie?" in aus
