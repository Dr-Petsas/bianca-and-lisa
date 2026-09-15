"""W-BUCHUNG-BEWEIS (15.09.2026) — Ruecklese ohne Namensraten.

Thaler-Anruf 831c8b6bd9044569962d20abdc9a5885: das Gespraech lief sauber,
`masBookAppointment` antwortete HTTP 200 mit `appointmentId
5JCHiVjknQCuVJDYj2l8` fuer die Akte `npZu3ptUmDODjsNkuzRE` — und die
Anruferin hoerte trotzdem "Die Buchungsantwort ist nicht eindeutig im
Kalender angekommen".

Ursache ist der Plattform-Vertrag: `agentFindPatientAppointments` loest den
Patienten ueber Namens-Aehnlichkeit auf und liest eine mitgeschickte
`patientId` NICHT (functions/src/controllers/agentAppointments.ts). In der
Praxis liegen drei Akten "Eva Thaler"; die Ruecklese traf
`3DsgqaItzZCbkPDI9wfd` samt deren PZR am 21.10., `found_pid != patient_id`
schlug zu.

Erreicht die Namensliste die richtige Akte NICHT, beweist seitdem ein
zweiter Weg ueber `masPatientLastDoctor` (der nimmt die patientId). Die
Gegenproben sind hier der wichtigere Teil: hat die Namensliste die Akte
erreicht und der Termin passte trotzdem nicht, ist das ein echter
Widerspruch und bleibt unbestaetigt (Tom-Schumann-Klasse, 11.09.2026).
"""

from __future__ import annotations

from kern import calendar

TENANT = {"clientId": "7tTnJZfJkb801r2rmYed", "locationId": "loc_m219jgfb"}

PID = "npZu3ptUmDODjsNkuzRE"          # Akte, auf die Bianca gebucht hat
PID_FREMD = "3DsgqaItzZCbkPDI9wfd"    # Dublette, die die Namenssuche traf
AID = "5JCHiVjknQCuVJDYj2l8"          # Termin-ID aus der Buchungsantwort
CAL = "QfAXRMiLpJVESMCFBLF6"          # Kalender Eva Thaler
SLOT = "2026-09-16T13:00:00+02:00"
MOTIV = "imp-besprechung-30min"


def _mit_cf(antworten: dict, calls: list):
    """_cf_post-Ersatz: zeichnet Aufrufe auf, liefert vorgegebene Antworten."""

    def fake(route: str, body: dict, **kw):
        calls.append((route, body))
        return antworten.get(
            route, (500, {"status": "error", "message": "unbekannte route"}))

    return fake


def _antwort_buchen(aid: str = AID) -> tuple[int, dict]:
    return 200, {
        "status": "success",
        "appointmentId": aid,
        "patient": {"id": PID, "firstName": "Eva", "lastName": "Thaler"},
        "calendarId": CAL,
    }


def _antwort_fremde_akte() -> tuple[int, dict]:
    """Wortgleich die Live-Antwort: fremde Dublette samt fremdem Termin."""
    return 200, {
        "status": "success",
        "patient": {"id": PID_FREMD, "firstName": "Eva", "lastName": "Thaler"},
        "appointments": [{
            "appointmentId": "rIkJkpHNcjuspOHV34zz",
            "start": "2026-10-21T10:30:00+02:00",
            "appointmentDate": "2026-10-21",
            "appointmentTime": "10:30",
            "calendarId": CAL,
            "doctorName": "Eva Thaler",
            "visitMotive": {
                "id": "pro-professionelle-zahnreinigung-recall-6m",
                "name": "PRO Professionelle Zahnreinigung",
                "duration": 60,
            },
        }],
    }


def _antwort_akte(
    *,
    aid: str = AID,
    start: str = "2026-09-16T13:00",
    cal: str = CAL,
    naechster: bool = True,
) -> tuple[int, dict]:
    """masPatientLastDoctor-Vertrag (masAgent.ts): startIso in Praxis-Zeit."""
    nxt = {
        "appointmentId": aid,
        "startIso": start,
        "calendarId": cal,
        "calendarName": "Eva Thaler",
        "doctorName": "Eva Thaler",
        "visitMotiveName": "IMP Besprechung",
    } if naechster else None
    return 200, {
        "status": "success",
        "found": bool(nxt),
        "lastAppointment": None,
        "nextAppointment": nxt,
        "pastCount": 0,
        "futureCount": 1 if nxt else 0,
    }


def _ctx(*, phone: str = "01516780764") -> dict:
    ctx = {
        "patientId": PID,
        "firstName": "Eva",
        "lastName": "Thaler",
        "patientName": "Eva Thaler",
        "calendarId": CAL,
        "visitMotiveId": MOTIV,
    }
    if phone:
        ctx["phone"] = phone
    calendar.patients.patient_id_bindung_setzen(ctx, PID, "Eva", "Thaler")
    return ctx


def _lauf(antworten: dict, *, ctx: dict | None = None, akte: bool = True):
    """book_slot mit gestellten CF-Antworten; gibt (ergebnis, ctx, calls)."""
    alt = (calendar._cf_post, calendar.WRITE_LIVE,
           calendar._BOOK_VERIFY_DELAYS, calendar.BOOK_VERIFY_AKTE)
    calls: list = []
    calendar._cf_post = _mit_cf(antworten, calls)
    calendar.WRITE_LIVE = True
    # Ein Durchgang reicht: die Replikations-Retries sind hier nicht der Punkt.
    calendar._BOOK_VERIFY_DELAYS = (0.0,)
    calendar.BOOK_VERIFY_AKTE = akte
    ctx = _ctx() if ctx is None else ctx
    try:
        return calendar.book_slot(TENANT, ctx, slot_iso=SLOT), ctx, calls
    finally:
        (calendar._cf_post, calendar.WRITE_LIVE,
         calendar._BOOK_VERIFY_DELAYS, calendar.BOOK_VERIFY_AKTE) = alt


def test_thaler_831c8b6b_dublette_wird_ueber_die_akte_bewiesen():
    r, ctx, calls = _lauf({
        "masBookAppointment": _antwort_buchen(),
        "agentFindPatientAppointments": _antwort_fremde_akte(),
        "masPatientLastDoctor": _antwort_akte(),
    })
    assert r["ok"] and r["booked"] and r["verified"]
    assert r["appointmentId"] == AID
    assert ctx["appointmentId"] == AID
    assert ctx["appointmentDate"] == "2026-09-16"
    assert "nicht eindeutig" not in r["spoken"]
    # Der zweite Weg lief erst NACH der Namensliste.
    assert [route for route, _ in calls] == [
        "masBookAppointment", "agentFindPatientAppointments",
        "masPatientLastDoctor"]
    # In der Gespraechsansicht muss sichtbar sein, WER den Termin bewiesen hat.
    pruefung = r["dispatch"]["verification"]
    assert pruefung["beweis"] == "akte"
    assert pruefung["namenslisteFehler"] == "Rücklese-Patient stimmt nicht"


def test_ruecklese_schickt_die_anrufernummer_mit():
    """Live fehlte die Nummer im Verify-Body — mit ihr kandidiert die CF
    zuerst ueber das Telefon und trifft die richtige der drei Akten."""
    _, _, calls = _lauf({
        "masBookAppointment": _antwort_buchen(),
        "agentFindPatientAppointments": _antwort_fremde_akte(),
        "masPatientLastDoctor": _antwort_akte(),
    })
    verify = [body for route, body in calls
              if route == "agentFindPatientAppointments"][0]
    assert verify["callerPhone"] == "01516780764"
    assert verify["patientId"] == PID  # bleibt drin, auch wenn die CF ihn ignoriert


def test_ohne_nummer_bleibt_der_verify_body_wie_vorher():
    _, _, calls = _lauf(
        {
            "masBookAppointment": _antwort_buchen(),
            "agentFindPatientAppointments": _antwort_fremde_akte(),
            "masPatientLastDoctor": _antwort_akte(),
        },
        ctx=_ctx(phone=""),
    )
    verify = [body for route, body in calls
              if route == "agentFindPatientAppointments"][0]
    assert "callerPhone" not in verify


def test_namensliste_traf_die_akte_kein_zweiter_weg():
    """Gegenprobe (Tom-Schumann-Klasse): richtige Akte, aber der Termin
    passt nicht — das ist ein Widerspruch, kein Evidenz-Loch. Der
    Akten-Weg darf so einen Befund nie ueberstimmen."""
    r, ctx, calls = _lauf({
        "masBookAppointment": _antwort_buchen(aid="CBGob-falsch"),
        "agentFindPatientAppointments": (200, {
            "status": "success",
            "patient": {"id": PID, "firstName": "Eva", "lastName": "Thaler"},
            "appointments": [{
                "appointmentId": "CBGob-falsch",
                "start": "2026-09-11T11:20:00+02:00",
                "calendarId": CAL,
            }],
        }),
        "masPatientLastDoctor": _antwort_akte(aid="CBGob-falsch"),
    })
    assert not r["ok"] and not r["booked"]
    assert r["verificationFailed"] and r["possiblyBooked"]
    assert "SMS" not in r["spoken"]
    assert "appointmentId" not in ctx
    assert "masPatientLastDoctor" not in [route for route, _ in calls]


def test_akte_beweis_verlangt_die_startminute():
    r, _, calls = _lauf({
        "masBookAppointment": _antwort_buchen(),
        "agentFindPatientAppointments": _antwort_fremde_akte(),
        "masPatientLastDoctor": _antwort_akte(start="2026-09-16T13:30"),
    })
    assert not r["ok"] and r["verificationFailed"]
    assert "masPatientLastDoctor" in [route for route, _ in calls]


def test_akte_beweis_verlangt_den_kalender():
    r, _, _ = _lauf({
        "masBookAppointment": _antwort_buchen(),
        "agentFindPatientAppointments": _antwort_fremde_akte(),
        "masPatientLastDoctor": _antwort_akte(cal="fremder-kalender"),
    })
    assert not r["ok"] and r["verificationFailed"]


def test_akte_ohne_kommenden_termin_bleibt_unbestaetigt():
    r, _, _ = _lauf({
        "masBookAppointment": _antwort_buchen(),
        "agentFindPatientAppointments": _antwort_fremde_akte(),
        "masPatientLastDoctor": _antwort_akte(naechster=False),
    })
    assert not r["ok"] and r["verificationFailed"]


def test_akte_beweis_auch_bei_mehrdeutiger_namenssuche():
    """409/ambiguous: die CF gibt gar keinen Patienten zurueck. Auch dann
    fehlt nur Evidenz — die patientId beweist den Termin."""
    r, ctx, _ = _lauf({
        "masBookAppointment": _antwort_buchen(),
        "agentFindPatientAppointments": (409, {
            "status": "ambiguous", "message": "multiple patients"}),
        "masPatientLastDoctor": _antwort_akte(),
    })
    assert r["ok"] and r["verified"]
    assert ctx["appointmentId"] == AID


def test_notaus_book_verify_akte_stellt_das_alte_verhalten_her():
    r, ctx, calls = _lauf(
        {
            "masBookAppointment": _antwort_buchen(),
            "agentFindPatientAppointments": _antwort_fremde_akte(),
            "masPatientLastDoctor": _antwort_akte(),
        },
        akte=False,
    )
    assert not r["ok"] and r["verificationFailed"]
    assert "appointmentId" not in ctx
    assert "masPatientLastDoctor" not in [route for route, _ in calls]


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok {name}")
    print("test_buchung_beweis: alle gruen")
