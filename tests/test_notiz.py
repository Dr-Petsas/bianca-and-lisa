"""Notiz landet im Termin (masAppointmentNote) und book_slot behaelt die ID."""

from lisa import calendar

TENANT = {"clientId": "c1", "locationId": "l1"}


def _mit_cf(antworten: dict, calls: list):
    """_cf_post-Ersatz: zeichnet Aufrufe auf, liefert vorgegebene Antworten."""

    def fake(route: str, body: dict):
        calls.append((route, body))
        return antworten.get(route, (500, {"status": "error", "message": "unbekannte route"}))

    return fake


def test_note_appointment_schreibt_in_termin(monkeypatch_none=None):
    alt_cf, alt_live = calendar._cf_post, calendar.WRITE_LIVE
    calls = []
    calendar._cf_post = _mit_cf(
        {"masAppointmentNote": (200, {"status": "success", "changed": True})}, calls
    )
    calendar.WRITE_LIVE = True
    try:
        ctx = {"appointmentId": "termin42"}
        note = "Neuer Termin am Telefon. (Lisa)\n— Telefonprotokoll Lisa —\nLisa: Hallo\nPatient: Hallo zurück"
        r = calendar.note_appointment(TENANT, ctx, None, note=note)
        assert r["ok"] and r["noted"]
        assert r["appointmentId"] == "termin42"
        route, body = calls[0]
        assert route == "masAppointmentNote"
        assert body["appointmentId"] == "termin42"
        # Mehrzeilig bleibt mehrzeilig (Protokoll nicht plattgedrueckt).
        assert body["note"].count("\n") == 3
    finally:
        calendar._cf_post, calendar.WRITE_LIVE = alt_cf, alt_live


def test_note_ohne_ziel_ehrlich():
    alt_cf, alt_live = calendar._cf_post, calendar.WRITE_LIVE
    calls = []
    calendar._cf_post = _mit_cf({}, calls)
    calendar.WRITE_LIVE = True
    try:
        r = calendar.note_appointment(TENANT, {}, {"upcoming": []}, note="Patient hat Angst")
        assert not r["ok"]
        assert "keinen Termin" in r["spoken"]
        assert calls == []  # kein blinder CF-Aufruf
    finally:
        calendar._cf_post, calendar.WRITE_LIVE = alt_cf, alt_live


def test_note_ziel_aus_upcoming():
    alt_cf, alt_live = calendar._cf_post, calendar.WRITE_LIVE
    calls = []
    calendar._cf_post = _mit_cf(
        {"masAppointmentNote": (200, {"status": "success", "changed": True})}, calls
    )
    calendar.WRITE_LIVE = True
    try:
        sit = {"upcoming": [{"id": "bestehend7", "iso": "2026-09-01T10:00", "label": "…"}]}
        r = calendar.note_appointment(TENANT, {}, sit, note="Nur vormittags")
        assert r["ok"]
        assert calls[0][1]["appointmentId"] == "bestehend7"
    finally:
        calendar._cf_post, calendar.WRITE_LIVE = alt_cf, alt_live


def test_book_slot_behaelt_termin_id():
    alt_cf, alt_live = calendar._cf_post, calendar.WRITE_LIVE
    calls = []
    calendar._cf_post = _mit_cf(
        {"masBookAppointment": (200, {"status": "success", "appointmentId": "neu99"})}, calls
    )
    calendar.WRITE_LIVE = True
    try:
        ctx = {"patientId": "p1", "calendarId": "cal1", "visitMotiveId": "vm1"}
        r = calendar.book_slot(TENANT, ctx, slot_iso="2026-08-31T09:15:00+02:00")
        assert r["ok"] and r["booked"]
        assert r["appointmentId"] == "neu99"
        assert ctx["appointmentId"] == "neu99"
        assert ctx["appointmentDate"] == "2026-08-31"
    finally:
        calendar._cf_post, calendar.WRITE_LIVE = alt_cf, alt_live


if __name__ == "__main__":
    test_note_appointment_schreibt_in_termin()
    test_note_ohne_ziel_ehrlich()
    test_note_ziel_aus_upcoming()
    test_book_slot_behaelt_termin_id()
    print("test_notiz: alle gruen")
