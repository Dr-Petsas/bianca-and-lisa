"""list_appointments nutzt Anrufer/Sammler und CF-Fallback (Petsas 06.09.2026)."""

from __future__ import annotations

from kern import calendar


TENANT = {"clientId": "c1", "locationId": "l1"}


def test_list_appointments_anrufer_fallback_zur_cf(monkeypatch=None):
    """Ohne sit.patient/upcoming — aber mit sit.anrufer — darf das Tool
    nicht 'keinen Termin' sagen, wenn die CF Treffer liefert."""
    sit = {
        "anrufer": {
            "vorname": "Michael", "nachname": "Petsas",
            "patientId": "pat-m", "telefon": "+491776004600",
        },
        "sammler": {},
        "upcoming": [],
        "patient": {},
        "booking": {},
        "tenant": TENANT,
    }
    calls = []

    def fake_find(tenant, ctx):
        calls.append(dict(ctx))
        return {
            "ok": True,
            "patient": {"id": "pat-m", "firstName": "Michael", "lastName": "Petsas"},
            "appointments": [{
                "id": "apt-1",
                "iso": "2026-09-07T09:00",
                "date": "2026-09-07",
                "doctorName": "Dr. Petsas",
                "motivName": "KFO Besprechung",
                "spoken": "morgen um neun Uhr bei Dr. Petsas",
            }],
        }

    alt_find = calendar.find_patient_appointments
    alt_termine = calendar.patients.termine_fuer
    calendar.find_patient_appointments = fake_find
    calendar.patients.termine_fuer = lambda t, p: {"past": [], "upcoming": []}
    try:
        r = calendar.list_appointments(TENANT, {}, [], sit=sit)
        assert r["ok"]
        assert "keinen kommenden Termin" not in r["spoken"]
        assert "neun Uhr" in r["spoken"]
        assert sit.get("upcoming") and sit["upcoming"][0]["id"] == "apt-1"
        assert calls and calls[0].get("lastName") == "Petsas"
        assert calls[0].get("patientId") == "pat-m"
        assert sit.get("patient", {}).get("id") == "pat-m"
    finally:
        calendar.find_patient_appointments = alt_find
        calendar.patients.termine_fuer = alt_termine


def test_find_patient_appointments_sendet_patient_id():
    bodies = []

    def fake_cf(route, body, timeout=None):
        bodies.append((route, dict(body)))
        return 200, {
            "status": "success",
            "patient": {"id": "p1", "firstName": "A", "lastName": "B"},
            "appointments": [],
        }, {}

    alt = calendar._cf_call
    calendar._cf_call = fake_cf
    try:
        calendar.find_patient_appointments(
            TENANT, {"firstName": "A", "lastName": "B", "patientId": "p1"},
        )
        assert bodies and bodies[0][0] == "agentFindPatientAppointments"
        assert bodies[0][1].get("patientId") == "p1"
    finally:
        calendar._cf_call = alt


def test_list_appointments_ignoriert_abgelehnten_anrufer():
    """Nach anruferCheck=nein darf der alte Match die Tool-Suche nicht fuettern."""
    sit = {
        "anrufer": {
            "vorname": "Falsch", "nachname": "Match",
            "patientId": "pat-x", "telefon": "+491771",
        },
        "sammler": {"anruferCheck": "nein"},
        "upcoming": [],
        "patient": {},
        "booking": {},
        "tenant": TENANT,
    }
    calls = []

    def fake_find(tenant, ctx):
        calls.append(dict(ctx))
        return {"ok": True, "notFound": True, "patient": {}, "appointments": []}

    alt_find = calendar.find_patient_appointments
    alt_termine = calendar.patients.termine_fuer
    calendar.find_patient_appointments = fake_find
    calendar.patients.termine_fuer = lambda t, p: {"past": [], "upcoming": []}
    try:
        r = calendar.list_appointments(TENANT, {}, [], sit=sit)
        assert "keinen kommenden Termin" in r["spoken"]
        # Kein CF-Call mit dem abgelehnten Nachnamen — lastName bleibt leer.
        assert not calls or not calls[0].get("lastName")
        assert not (sit.get("booking") or {}).get("patientId")
    finally:
        calendar.find_patient_appointments = alt_find
        calendar.patients.termine_fuer = alt_termine
