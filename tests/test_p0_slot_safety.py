"""V5.6 P0-Wachen fuer Slots, Schreibdeckel und Vergangenheitsgrenzen."""

from __future__ import annotations

from datetime import datetime, timedelta

from bianca import gehirn, verwalten
from kern import calendar as kal
from kern import patients
from kern.tenants import laden


def _future(days: int, hour: int = 10) -> str:
    return (
        datetime.now(kal.TZ)
        .replace(hour=hour, minute=0, second=0, microsecond=0)
        + timedelta(days=days)
    ).isoformat(timespec="seconds")


def _tenant() -> dict:
    return {
        "clientId": "client-1",
        "locationId": "location-1",
        "calendars": [{"id": "cal-1", "name": "Doktor Test"}],
    }


def _existing_ctx() -> dict:
    ctx = {
        "patientId": "patient-1",
        "patientName": "Anna Test",
        "firstName": "Anna",
        "lastName": "Test",
        "calendarId": "cal-1",
        "calendarName": "Doktor Test",
        "visitMotiveId": "mot-1",
        "visitMotiveName": "Kontrolle",
        "phone": "01771234567",
        "phoneConfirmed": "01771234567",
        "phoneInChartKnown": True,
        "phoneInChart": "01771234567",
    }
    patients.patient_id_bindung_setzen(ctx, "patient-1", "Anna", "Test")
    return ctx


def test_gesperrter_slot_loest_keinen_schreibaufruf_aus(monkeypatch):
    iso = _future(2)
    ctx = _existing_ctx()
    ctx["slotGesperrt"] = [iso]
    rufe: list[str] = []
    monkeypatch.setattr(kal, "WRITE_LIVE", True)
    monkeypatch.setattr(
        kal,
        "_cf_call",
        lambda route, body, timeout=None: rufe.append(route) or (
            500,
            {"status": "error"},
            {"route": route},
        ),
    )

    res = kal.book_slot(_tenant(), ctx, slot_iso=iso)

    assert not res["ok"] and res["slotTaken"]
    assert res["writeAttempted"] is False
    assert res["blockedIso"] == iso
    # Eine reine Alternativsuche ist erlaubt; der gesperrte Slot darf aber
    # niemals erneut an eine Schreibroute gehen.
    assert "masBookAppointment" not in rufe


def test_konflikt_verwirft_stale_vorrat_und_nimmt_nur_frische_slots(monkeypatch):
    iso = _future(2)
    stale = _future(3, 11)
    fresh = _future(4, 14)
    ctx = _existing_ctx()
    ctx["slotVorrat"] = [stale]
    ctx["offered"] = [{"iso": stale, "spoken": "stale"}]
    rufe: list[tuple[str, dict]] = []
    monkeypatch.setattr(kal, "WRITE_LIVE", True)

    def _cf(route, body, timeout=None):
        rufe.append((route, dict(body)))
        if route == "masBookAppointment":
            return (
                400,
                {
                    "status": "error",
                    "message": "The slot is not available.",
                    "slots": [stale],
                },
                {"route": route},
            )
        if route == "getFreeTimeSlots":
            return (
                200,
                {
                    "status": "success",
                    "data": {
                        "free_time_slots": [fresh],
                        "doctor_name": "Doktor Test",
                    },
                },
                {"route": route},
            )
        raise AssertionError(route)

    monkeypatch.setattr(kal, "_cf_call", _cf)

    res = kal.book_slot(_tenant(), ctx, slot_iso=iso)

    assert not res["ok"] and res["slotTaken"]
    assert [route for route, _ in rufe] == [
        "masBookAppointment",
        "getFreeTimeSlots",
    ]
    assert [x["iso"] for x in res["slots"]] == [fresh]
    assert stale not in {x["iso"] for x in res["slots"]}
    assert iso in ctx["slotGesperrt"]


def test_letzte_cloud_grenze_klemmt_jeden_start_auf_heute(monkeypatch):
    """Diese Grenze liegt unmittelbar vor getFreeTimeSlots und schuetzt
    direkte, Hintergrund-, Konflikt- und Verschiebe-Aufrufer gemeinsam."""
    bodies: list[dict] = []

    def _cf(route, body, timeout=None):
        assert route == "getFreeTimeSlots"
        bodies.append(dict(body))
        return (
            200,
            {
                "status": "success",
                "data": {"free_time_slots": [], "doctor_name": "Doktor Test"},
            },
            {"route": route},
        )

    monkeypatch.setattr(kal, "_cf_call", _cf)
    res = kal._find_slots_seite(
        _tenant(),
        _existing_ctx(),
        start_date="2020-01-01",
        source="p0-test",
    )

    assert res["ok"]
    assert bodies
    assert all(body["startDate"] == datetime.now(kal.TZ).date().isoformat()
               for body in bodies)


def test_verschiebe_angebot_klemmt_startsearchdate_auf_heute(monkeypatch):
    """Die ältere find-for-postpone-Route hat ein eigenes Datumsfeld und
    muss deshalb direkt vor ihrem CF-Aufruf dieselbe Heute-Grenze haben."""
    bodies: list[dict] = []

    def _cf(route, body, timeout=None):
        assert route == "updateOrCancelAppointment"
        bodies.append(dict(body))
        return 404, {"status": "not_found"}, {"route": route}

    monkeypatch.setattr(kal, "_cf_call", _cf)
    monkeypatch.setattr(
        kal,
        "parse_slot_wish",
        lambda _text: {"date": "2020-01-01"},
    )
    # Der 404-Rückfall ruft offer_slots auf; für diese Wache ist nur der
    # unmittelbar vorher gesendete find-for-postpone-Body relevant.
    monkeypatch.setattr(
        kal,
        "offer_slots",
        lambda *a, **k: {"ok": False, "spoken": "kein Termin"},
    )

    kal.offer_move(
        _tenant(),
        _existing_ctx(),
        date=_future(7)[:10],
        wish="am ersten Januar zweitausendzwanzig",
    )

    assert bodies
    assert bodies[0]["action"] == "find-for-postpone"
    assert bodies[0]["startSearchDate"] == datetime.now(kal.TZ).date().isoformat()


def test_leere_erste_seite_darf_in_spaetes_fenster_weiterblaettern(monkeypatch):
    heute = datetime.now(kal.TZ).date()
    spaet = (heute + timedelta(days=121)).isoformat() + "T10:00:00+02:00"
    starts: list[str] = []

    def _cf(route, body, timeout=None):
        assert route == "getFreeTimeSlots"
        starts.append(body["startDate"])
        slots = [] if len(starts) == 1 else [spaet]
        return (
            200,
            {
                "status": "success",
                "data": {
                    "free_time_slots": slots,
                    "doctor_name": "Doktor Test",
                },
            },
            {"route": route},
        )

    monkeypatch.setattr(kal, "_cf_call", _cf)
    res = kal.find_slots(
        _tenant(),
        _existing_ctx(),
        wish={"von": spaet[:10], "bis": spaet[:10]},
    )

    assert res["ok"]
    assert starts == [heute.isoformat(), (heute + timedelta(days=120)).isoformat()]
    assert spaet in res["slots"]


def _move_sit() -> dict:
    tenant = laden("meddent")
    alt = _future(7)
    neu = _future(8)
    termin = {
        "id": "appointment-1",
        "iso": alt,
        "calendarId": "cal-1",
        "calendarName": "Doktor Petsas",
        "motivId": "mot-1",
        "motivName": "Kontrolle",
        "patientName": "Anna Test",
    }
    sit = {
        "tenant": tenant,
        "messages": [{"role": "system", "content": "test"}],
        "stimme": "Bianca",
        "verwaltenTermin": "appointment-1",
        "gefunden": [termin],
        "verwaltenNeuIso": neu,
    }
    s = gehirn.sammler(sit)
    s.update(
        {
            "modus": "verschieben",
            "phase": "verschieb_bestaetigen",
            "frage": "verschieb_bestaetigen",
            "vorname": "Anna",
            "nachname": "Test",
            "patientId": "patient-1",
            "telefon": "01771234567",
            "telefonOk": True,
            "wunsch": {},
        }
    )
    return sit


def test_verschieben_hat_harten_deckel_von_zwei_schreibversuchen(monkeypatch):
    sit = _move_sit()
    schreibversuche: list[str] = []
    notizen: list[dict] = []

    def _fail(tenant, ctx, *, slot_iso=""):
        schreibversuche.append(slot_iso)
        return {
            "ok": False,
            "slotTaken": True,
            "writeAttempted": True,
            "blockedIso": slot_iso,
            "slots": [{"iso": _future(9 + len(schreibversuche))}],
            "spoken": "Verschieben fehlgeschlagen.",
        }

    monkeypatch.setattr(verwalten.kal, "move_appointment", _fail)
    monkeypatch.setattr(
        verwalten,
        "_notiz_schreiben",
        lambda sit, **kwargs: notizen.append(kwargs) or True,
    )

    s = gehirn.sammler(sit)
    s["slotIso"] = _future(8)
    first = verwalten._verschieben(sit, None)
    s["slotIso"] = _future(9)
    second = verwalten._verschieben(sit, None)
    third = verwalten._verschieben(sit, None)

    assert first and second and third
    assert len(schreibversuche) == 2
    assert sit["moveFails"] == 2
    assert notizen
    assert gehirn.sammler(sit)["phase"] == "fertig"
