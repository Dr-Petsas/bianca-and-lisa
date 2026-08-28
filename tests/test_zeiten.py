"""Sperrzeiten: Feiertage, Wochenende, Sprechzeiten — offline, ohne Netz."""

from datetime import date

from kern import zeiten
from kern.calendar import book_slot
from kern.slots import pick_slots
from kern.tenants import laden


def test_ostern_2026_nrw():
    assert zeiten.ostersonntag(2026) == date(2026, 4, 5)
    assert zeiten.feiertag_name("2026-04-03") == "Karfreitag"
    assert zeiten.feiertag_name("2026-04-06") == "Ostermontag"
    assert zeiten.feiertag_name("2026-05-14") == "Christi Himmelfahrt"
    assert zeiten.feiertag_name("2026-06-04") == "Fronleichnam"
    assert zeiten.feiertag_name("2026-10-03") == "Tag der Deutschen Einheit"
    assert zeiten.feiertag_name("2026-08-28") == ""


def test_wochenende_und_werktag():
    assert zeiten.ist_wochenende("2026-08-29")  # Samstag
    assert zeiten.ist_wochenende("2026-08-30")  # Sonntag
    assert not zeiten.ist_wochenende("2026-08-28")  # Freitag
    assert zeiten.tag_grund("2026-08-29") == "Samstag"
    assert not zeiten.tag_grund("2026-08-28")


def test_sprechfenster_meddent():
    t = laden("meddent")
    assert zeiten.slot_frei("2026-08-28T15:45", t)  # Freitag vor 16
    assert not zeiten.slot_frei("2026-08-28T16:00", t)  # Freitag ab 16 zu
    assert zeiten.slot_frei("2026-08-27T17:30", t)  # Donnerstag bis 18
    assert not zeiten.slot_frei("2026-08-27T18:00", t)
    assert not zeiten.slot_frei("2026-08-29T10:00", t)  # Samstag
    assert not zeiten.slot_frei("2026-04-03T10:00", t)  # Karfreitag


def test_pick_slots_wirft_wochenende_und_spaet():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    jetzt = datetime(2026, 8, 27, 8, 0, tzinfo=ZoneInfo("Europe/Berlin"))
    res = pick_slots(
        [
            "2026-08-28T15:00:00+02:00",
            "2026-08-28T17:00:00+02:00",
            "2026-08-29T10:00:00+02:00",
            "2026-08-31T09:15:00+02:00",
        ],
        now_ms=int(jetzt.timestamp() * 1000),
        tenant=laden("meddent"),
    )
    isos = [s["iso"] for s in res["slots"]]
    assert any(x.startswith("2026-08-28T15:00") for x in isos)
    assert any(x.startswith("2026-08-31T09:15") for x in isos)
    assert not any("2026-08-29" in x for x in isos)
    assert not any("T17:00" in x for x in isos)


def test_wunsch_samstag_wird_auf_werktag_geschoben():
    t = laden("meddent")
    w, vor = zeiten.wunsch_richten(
        {"weekday": 6, "date": None, "hour": None, "minDaysAhead": 0},
        t, heute=date(2026, 8, 28),
    )
    assert "Samstag" in vor and "geschlossen" in vor
    assert w.get("weekday") is None
    assert w.get("date") == "2026-08-31"  # nächster Montag


def test_wunsch_karfreitag_wird_geschoben():
    t = laden("meddent")
    w, vor = zeiten.wunsch_richten(
        {"date": "2026-04-03", "weekday": None, "hour": None, "minDaysAhead": 0},
        t, heute=date(2026, 3, 30),
    )
    assert "Karfreitag" in vor or "Feiertag" in vor
    assert w["date"] == "2026-04-07"  # Dienstag nach Ostern (Mo ist Ostermontag)


def test_book_slot_lehnt_sonntag_ab():
    r = book_slot(laden("meddent"), {}, slot_iso="2026-08-30T10:00:00+02:00")
    assert r.get("closed") and r.get("ok") is False
    assert "geschlossen" in (r.get("spoken") or "").lower()


def test_book_slot_lehnt_freitag_abend_ab():
    r = book_slot(laden("meddent"), {}, slot_iso="2026-08-28T17:00:00+02:00")
    assert r.get("closed") and r.get("ok") is False


def test_offen_frage_samstag():
    t = laden("meddent")
    assert zeiten.ist_offen_frage("Habt ihr samstags auch auf?")
    a = zeiten.offen_antwort("Habt ihr samstags auch auf?", t)
    assert "Samstag" in a and "geschlossen" in a
    assert not zeiten.ist_offen_frage("Ich hätte gern einen Termin.")


def test_agent_antwortet_oeffnungszeiten_ohne_llm():
    from bianca.agent import user_turn
    sit = {
        "tenant": laden("meddent"),
        "sammler": {},
        "messages": [
            {"role": "system", "content": "x"},
            {"role": "assistant", "content": "Was kann ich für Sie tun?"},
        ],
    }
    r = user_turn(sit, "Wie sind denn Ihre Öffnungszeiten?")
    assert "achtzehn" in r["text"] and "Samstag" in r["text"]
    r2 = user_turn(sit, "Habt ihr samstags auf?")
    assert "geschlossen" in r2["text"].lower()
