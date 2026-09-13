"""Notiz landet im Termin (masAppointmentNote) und book_slot behaelt die ID."""

from lisa import calendar

TENANT = {"clientId": "c1", "locationId": "l1"}


def _mit_cf(antworten: dict, calls: list):
    """_cf_post-Ersatz: zeichnet Aufrufe auf, liefert vorgegebene Antworten."""

    def fake(route: str, body: dict, **kw):
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


def test_note_blockiert_fremde_patientenbindung():
    alt_cf, alt_live = calendar._cf_post, calendar.WRITE_LIVE
    calls = []
    calendar._cf_post = _mit_cf({}, calls)
    calendar.WRITE_LIVE = True
    try:
        ctx = {
            "appointmentId": "termin-kellner",
            "patientId": "6vCR-kellner",
            "firstName": "Den",
            "lastName": "Killnir",
        }
        calendar.patients.patient_id_bindung_setzen(
            ctx, "6vCR-kellner", "Phoebe Rose", "Kellner")
        r = calendar.note_appointment(
            TENANT, ctx, None, note="Anrufer möchte PZR.")
        assert not r["ok"]
        assert r["patientMismatch"]
        assert calls == []
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
    alt_delays = calendar._BOOK_VERIFY_DELAYS
    calls = []
    calendar._cf_post = _mit_cf(
        {
            "masBookAppointment": (
                200, {"status": "success", "appointmentId": "neu99"}),
            "agentFindPatientAppointments": (
                200,
                {
                    "status": "success",
                    "patient": {
                        "id": "p1", "firstName": "Tom", "lastName": "Schumann"},
                    "appointments": [{
                        "appointmentId": "neu99",
                        "start": "2026-08-31T09:15:00+02:00",
                        "calendarId": "cal1",
                    }],
                },
            ),
        },
        calls,
    )
    calendar.WRITE_LIVE = True
    calendar._BOOK_VERIFY_DELAYS = (0.0,)
    try:
        ctx = {
            "patientId": "p1",
            "firstName": "Tom",
            "lastName": "Schumann",
            "calendarId": "cal1",
            "visitMotiveId": "vm1",
        }
        calendar.patients.patient_id_bindung_setzen(
            ctx, "p1", "Tom", "Schumann")
        r = calendar.book_slot(TENANT, ctx, slot_iso="2026-08-31T09:15:00+02:00")
        assert r["ok"] and r["booked"]
        assert r["verified"]
        assert r["appointmentId"] == "neu99"
        assert ctx["appointmentId"] == "neu99"
        assert ctx["appointmentDate"] == "2026-08-31"
        assert [route for route, _ in calls] == [
            "masBookAppointment", "agentFindPatientAppointments"]
    finally:
        calendar._cf_post, calendar.WRITE_LIVE = alt_cf, alt_live
        calendar._BOOK_VERIFY_DELAYS = alt_delays


def test_book_slot_blockiert_killnir_mit_kellner_patient_id():
    alt_cf, alt_live = calendar._cf_post, calendar.WRITE_LIVE
    calls = []
    calendar._cf_post = _mit_cf({}, calls)
    calendar.WRITE_LIVE = True
    try:
        ctx = {
            "patientId": "6vCR-kellner",
            "firstName": "Den",
            "lastName": "Killnir",
            "calendarId": "cal1",
            "visitMotiveId": "vm1",
        }
        calendar.patients.patient_id_bindung_setzen(
            ctx, "6vCR-kellner", "Phoebe Rose", "Kellner")
        r = calendar.book_slot(
            TENANT, ctx, slot_iso="2026-10-07T11:30:00+02:00")
        assert not r["ok"]
        assert r["patientMismatch"]
        assert calls == []
    finally:
        calendar._cf_post, calendar.WRITE_LIVE = alt_cf, alt_live


def test_book_slot_http_200_ohne_passenden_readback_bleibt_unbestaetigt():
    """Tom-Schumann-Klasse: Eine fremde/recycelte appointmentId darf trotz
    HTTP 200 weder Buchung noch SMS-Evidenz erzeugen."""
    alt_cf, alt_live = calendar._cf_post, calendar.WRITE_LIVE
    alt_delays = calendar._BOOK_VERIFY_DELAYS
    calls = []
    calendar._cf_post = _mit_cf(
        {
            "masBookAppointment": (
                200, {"status": "success", "appointmentId": "CBGob-falsch"}),
            "agentFindPatientAppointments": (
                200,
                {
                    "status": "success",
                    "patient": {
                        "id": "p-tom", "firstName": "Tom", "lastName": "Schumann"},
                    "appointments": [{
                        "appointmentId": "CBGob-falsch",
                        "start": "2026-09-11T11:20:00+02:00",
                        "calendarId": "cal1",
                    }],
                },
            ),
        },
        calls,
    )
    calendar.WRITE_LIVE = True
    calendar._BOOK_VERIFY_DELAYS = (0.0,)
    try:
        ctx = {
            "patientId": "p-tom",
            "firstName": "Tom",
            "lastName": "Schumann",
            "calendarId": "cal1",
            "visitMotiveId": "vm1",
        }
        calendar.patients.patient_id_bindung_setzen(
            ctx, "p-tom", "Tom", "Schumann")
        r = calendar.book_slot(
            TENANT, ctx, slot_iso="2026-10-07T11:30:00+02:00")
        assert not r["ok"]
        assert not r["booked"]
        assert r["verificationFailed"]
        assert r["possiblyBooked"]
        assert "SMS" not in r["spoken"]
        assert "appointmentId" not in ctx
    finally:
        calendar._cf_post, calendar.WRITE_LIVE = alt_cf, alt_live
        calendar._BOOK_VERIFY_DELAYS = alt_delays


def test_readback_fehler_erzeugt_rueckruf_statt_sms_zusage():
    from bianca import flow, gehirn

    sit = {
        "tenant": {
            "clientId": "c1",
            "locationId": "l1",
            "calendars": [{"id": "cal1", "name": "Doktor Test"}],
            "visitMotives": [{"id": "vm1", "name": "Kontrolle"}],
        },
    }
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "phase": "bestaetigen",
        "frage": "bestaetigung",
        "vorname": "Tom",
        "nachname": "Schumann",
        "patientId": "p-tom",
        "bekannt": True,
        "warSchonMal": True,
        "telefon": "01776004600",
        "telefonOk": True,
        "slotIso": "2026-10-07T11:30:00+02:00",
        "motivId": "vm1",
        "motivName": "Kontrolle",
        "arzt": {
            "typ": "genannt",
            "calendarId": "cal1",
            "calendarName": "Doktor Test",
        },
    })
    sit["booking"] = {}
    gerufen = []
    alt_book = flow.kal.book_slot
    alt_notiz = flow.verwalten.buchung_pruefen_notiz
    flow.kal.book_slot = lambda *a, **k: {
        "ok": False,
        "booked": False,
        "verificationFailed": True,
        "possiblyBooked": True,
        "slotIso": s["slotIso"],
        "spoken": "Die Buchung ist nicht eindeutig. Die Praxis prüft das.",
    }
    flow.verwalten.buchung_pruefen_notiz = (
        lambda sit2, **kw: gerufen.append(kw))
    try:
        aus = flow._buchen(sit)
    finally:
        flow.kal.book_slot = alt_book
        flow.verwalten.buchung_pruefen_notiz = alt_notiz

    assert s["phase"] == "fertig"
    assert gerufen and gerufen[0]["slot_iso"].startswith("2026-10-07T11:30")
    assert not aus["book"]["booked"]
    assert "sms" not in aus["text"].lower()


if __name__ == "__main__":
    test_note_appointment_schreibt_in_termin()
    test_note_ohne_ziel_ehrlich()
    test_note_ziel_aus_upcoming()
    test_book_slot_behaelt_termin_id()
    print("test_notiz: alle gruen")
