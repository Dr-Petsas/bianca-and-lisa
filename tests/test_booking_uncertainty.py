"""P0: Ein unklarer Buchungs-Write darf nie zu einer Dublette führen."""

from __future__ import annotations

import json
import time

import pytest

from kern import calendar, patients


TENANT = {"clientId": "client-1", "locationId": "location-1"}
SLOT = "2026-10-21T09:30:00+02:00"


def _ctx() -> dict:
    ctx = {
        "patientId": "patient-1",
        "firstName": "Anna",
        "lastName": "Muster",
        "patientName": "Anna Muster",
        "calendarId": "calendar-1",
        "visitMotiveId": "motive-1",
        "phone": "+491701234567",
        "phoneConfirmed": "+491701234567",
        "phoneInChart": "+491701234567",
    }
    patients.patient_id_bindung_setzen(ctx, "patient-1", "Anna", "Muster")
    return ctx


@pytest.mark.parametrize(
    ("status", "data"),
    [
        (0, {"status": "error", "message": "timeout"}),
        (500, {"status": "error", "message": "internal"}),
        (204, {"status": "accepted"}),
    ],
)
def test_unklare_schreibantwort_verriegelt_jeden_folgeversuch(
    monkeypatch,
    status,
    data,
):
    writes = []
    monkeypatch.setattr(calendar, "WRITE_LIVE", True)
    monkeypatch.setattr(calendar, "BOOK_FIX_PHONE", False)
    monkeypatch.setattr(
        calendar,
        "_cf_call",
        lambda route, body, **kwargs: (
            writes.append((route, dict(body))) or
            (status, data, {"route": route})
        ),
    )
    monkeypatch.setattr(
        calendar,
        "_buchung_verifizieren",
        lambda *args, **kwargs: {"ok": False, "error": "kein Beweis"},
    )
    ctx = _ctx()

    first = calendar.book_slot(TENANT, ctx, slot_iso=SLOT)
    second = calendar.book_slot(TENANT, ctx, slot_iso=SLOT)

    assert first["verificationFailed"] is True
    assert first["possiblyBooked"] is True
    assert first["writeAttempted"] is True
    assert second["possiblyBooked"] is True
    assert second["writeAttempted"] is False
    assert len(writes) == 1


def test_erfolgsantwort_ohne_exakten_readback_wird_nicht_als_buchung_gesprochen(
    monkeypatch,
):
    monkeypatch.setattr(calendar, "WRITE_LIVE", True)
    monkeypatch.setattr(calendar, "BOOK_FIX_PHONE", False)
    monkeypatch.setattr(
        calendar,
        "_cf_call",
        lambda route, body, **kwargs: (
            200,
            {"status": "success", "appointmentId": "appointment-1"},
            {"route": route},
        ),
    )
    monkeypatch.setattr(
        calendar,
        "_buchung_verifizieren",
        lambda *args, **kwargs: {"ok": False, "error": "Termin nicht sichtbar"},
    )

    result = calendar.book_slot(TENANT, _ctx(), slot_iso=SLOT)

    assert not result["ok"] and not result["booked"]
    assert result["possiblyBooked"] and result["verificationFailed"]
    assert "fest eingetragen" not in result["spoken"].lower()


def test_direktanlage_unklar_sperrt_auch_direkten_wiederholungsaufruf(
    monkeypatch,
):
    writes = []
    monkeypatch.setattr(
        calendar,
        "_cf_call",
        lambda route, body, **kwargs: (
            writes.append((route, dict(body))) or
            (200, {
                "status": "success",
                "patientId": "patient-new",
                "appointmentId": "appointment-new",
                "createdPatient": True,
            }, {"route": route})
        ),
    )
    monkeypatch.setattr(
        calendar,
        "_buchung_verifizieren",
        lambda *args, **kwargs: {"ok": False, "error": "kein exakter Termin"},
    )
    ctx = {"calendarId": "calendar-1", "visitMotiveId": "motive-1"}

    first = calendar._buch_und_akte(
        TENANT, ctx, SLOT, "Anna", "Muster", "+491701234567")
    second = calendar._buch_und_akte(
        TENANT, ctx, SLOT, "Anna", "Muster", "+491701234567")

    assert first["possiblyBooked"] and first["writeAttempted"]
    assert second["possiblyBooked"] and not second["writeAttempted"]
    assert len(writes) == 1


def test_gehaltene_direktbuchung_traegt_token_und_sitzungsbindung(
    monkeypatch,
):
    writes = []
    token = "0123456789abcdef0123456789abcdef"
    monkeypatch.setattr(
        calendar,
        "_cf_call",
        lambda route, body, **kwargs: (
            writes.append((route, dict(body)))
            or (200, {
                "status": "success",
                "patientId": "patient-held",
                "appointmentId": "appointment-held",
                "createdPatient": True,
            }, {"route": route})
        ),
    )
    monkeypatch.setattr(
        calendar,
        "_held_booking_readback",
        lambda *args, **kwargs: {
            "ok": True,
            "patientId": "patient-held",
            "appointmentId": "appointment-held",
            "beweis": "deterministic_firestore_id",
        },
    )
    ctx = {
        "calendarId": "calendar-1",
        "visitMotiveId": "motive-1",
        "skipConfirmation": True,
        "nameConfirmToken": token,
        "nameConfirmSessionId": "session-held",
    }

    result = calendar._buch_und_akte(
        TENANT, ctx, SLOT, "Reservierung", "SMS", "+491701234567")

    assert result["ok"] and result["verified"]
    assert len(writes) == 1
    route, body = writes[0]
    assert route == "createAppointment"
    assert body["skipConfirmation"] is True
    assert body["nameConfirmToken"] == token
    assert body["nameConfirmSessionId"] == "session-held"


def test_gehaltene_direktbuchung_ohne_sitzungsbindung_schreibt_nicht(
    monkeypatch,
):
    monkeypatch.setattr(
        calendar,
        "_cf_call",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("ohne Sitzungsbindung kein Write")),
    )
    result = calendar._buch_und_akte(
        TENANT,
        {
            "calendarId": "calendar-1",
            "visitMotiveId": "motive-1",
            "skipConfirmation": True,
            "nameConfirmToken": "0" * 32,
        },
        SLOT,
        "Reservierung",
        "SMS",
        "+491701234567",
    )

    assert not result["ok"]
    assert result["writeAttempted"] is False


def test_dispatch_enthaelt_keinen_rohen_reservierungstoken(monkeypatch):
    raw = "0123456789abcdef0123456789abcdef"
    monkeypatch.setattr(
        calendar,
        "_cf_post",
        lambda route, body, **kwargs: (
            200,
            {
                "status": "ok",
                "token": raw,
                "url": f"https://example.test/agentNameConfirm?t={raw}",
                "nested": {"signature": raw},
            },
        ),
    )

    _, _, dispatch = calendar._cf_call(
        "agentNameConfirm",
        {
            "action": "create",
            "nameConfirmToken": raw,
            "nested": {"token": raw},
        },
    )
    encoded = json.dumps(dispatch)

    assert raw not in encoded
    assert encoded.count("[REDACTED]") >= 5


def test_gesamtbudget_begrenzt_schreibversuch_und_readback(monkeypatch):
    monkeypatch.setattr(calendar, "WRITE_LIVE", True)
    monkeypatch.setattr(calendar, "BOOK_FIX_PHONE", False)
    monkeypatch.setattr(calendar, "_BOOK_TOTAL_BUDGET_S", 0.25)
    monkeypatch.setattr(calendar, "_BOOK_VERIFY_DELAYS", (0.0, 1.0, 1.0))
    monkeypatch.setattr(calendar, "BOOK_VERIFY_AKTE", False)
    monkeypatch.setattr(
        calendar,
        "_cf_call",
        lambda route, body, **kwargs: (
            500, {"status": "error"}, {"route": route}),
    )
    monkeypatch.setattr(
        calendar,
        "find_patient_appointments",
        lambda *args, **kwargs: {
            "ok": True,
            "patient": {},
            "appointments": [],
        },
    )

    start = time.monotonic()
    result = calendar.book_slot(TENANT, _ctx(), slot_iso=SLOT)
    elapsed = time.monotonic() - start

    assert result["possiblyBooked"]
    assert elapsed < 0.5


def test_deterministische_reservierungs_ids_sind_token_und_mandantenscharf():
    token_a = "a" * 32
    token_b = "b" * 32

    patient_a = calendar._name_confirm_scoped_id("ncp", TENANT, token_a)
    patient_b = calendar._name_confirm_scoped_id("ncp", TENANT, token_b)
    other_tenant = calendar._name_confirm_scoped_id(
        "ncp", {**TENANT, "clientId": "client-2"}, token_a)

    assert patient_a.startswith("ncp_")
    assert len(patient_a) == 44
    assert len({patient_a, patient_b, other_tenant}) == 3
