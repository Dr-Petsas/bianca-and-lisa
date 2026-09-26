"""Unklare Absage-/Verschiebeantworten werden per exakter Termin-ID gelesen.

Der Write selbst wird nie wiederholt. Nur der starke Firestore-Readback
derselben ID darf einen Timeout als ausgeführte Kalenderaktion bestätigen.
"""

from bianca import gehirn, verwalten
from kern import calendar


TENANT = {"clientId": "client-1", "locationId": "location-1"}
AID = "appointment-1"
OLD = "2026-10-12T09:00:00+02:00"
NEW = "2026-10-19T11:30:00+02:00"


def test_patient_status_vertrag_nur_vier_und_fuenf_sind_inaktiv():
    for status in (0, 1, 2, 3, "1", "2", "3"):
        assert calendar._management_appointment_active({
            "id": AID,
            "patientStatus": status,
        })
    for status in (4, 5, "4", "5"):
        assert not calendar._management_appointment_active({
            "id": AID,
            "patientStatus": status,
        })


def test_absagebestaetigung_endet_ohne_ja_und_ohne_write(monkeypatch):
    sit = {"tenant": TENANT}
    s = gehirn.sammler(sit)
    s.update({
        "modus": "absagen",
        "phase": "absage_bestaetigen",
        "frage": "bestaetigung",
    })
    sit["verwaltenTermin"] = AID
    sit["gefunden"] = [{"id": AID, "iso": OLD, "spoken": "Montag um neun"}]
    writes = []
    monkeypatch.setattr(
        verwalten,
        "_absagen",
        lambda *_a, **_k: writes.append("write") or {"text": "unerwartet"},
    )

    eins = verwalten.zug(sit, "Vielleicht.", set())
    zwei = verwalten.zug(sit, "Das weiß ich nicht.", set())

    assert "ja oder nein" in eins["text"].casefold()
    assert "ändere ich keinen termin" in zwei["text"].casefold()
    assert s["phase"] == "fertig"
    assert s["frage"] == "sonst_noch"
    assert not writes


def _aktiv(monkeypatch):
    monkeypatch.setattr(calendar, "WRITE_LIVE", True)
    monkeypatch.setattr(calendar, "MANAGEMENT_WRITE_RECOVERY", True)
    monkeypatch.setattr(calendar, "_MANAGEMENT_RECOVERY_DELAYS", (0.0,))


def test_management_recovery_bleibt_kurz_und_begrenzt():
    assert calendar._MANAGEMENT_RECOVERY_DELAYS == (0.0, 0.4)
    assert sum(calendar._MANAGEMENT_RECOVERY_DELAYS) <= 0.5


def test_machine_secret_schuetzt_nur_name_confirm_reservierungen(monkeypatch):
    calls = []

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"status": "ok"}

    class Client:
        @staticmethod
        def post(url, **kwargs):
            calls.append((url, kwargs))
            return Response()

    monkeypatch.setattr(calendar, "PHONE_CALL_TOKEN", "maschinen-secret")
    monkeypatch.setattr(calendar, "_CF_CLIENT", Client())

    calendar._cf_post("agentNameConfirm", {"action": "bind"})
    calendar._cf_post(
        "masBookAppointment",
        {"patientId": "p", "skipConfirmation": True},
    )
    calendar._cf_post(
        "createAppointment",
        {"patientId": "p", "skipConfirmation": True},
    )
    calendar._cf_post("masBookAppointment", {"patientId": "p"})

    expected = {
        "Authorization": "Bearer maschinen-secret",
        "x-pickadoc-phone-call-token": "maschinen-secret",
    }
    assert calls[0][1]["headers"] == expected
    assert calls[1][1]["headers"] == expected
    assert calls[2][1]["headers"] == expected
    assert calls[3][1]["headers"] is None


def test_absage_timeout_aber_termin_weg_gilt_als_erfolg(monkeypatch):
    _aktiv(monkeypatch)
    writes = []
    monkeypatch.setattr(
        calendar,
        "_cf_call",
        lambda route, body, **kwargs: (
            writes.append((route, body)) or
            (0, {"status": "error", "message": "timeout"}, {"route": route})
        ),
    )
    monkeypatch.setattr(
        calendar,
        "_firestore_appointment_by_id",
        lambda tenant, aid, **kwargs: {
            "ok": True, "missing": True, "appointmentId": aid,
        },
    )

    ctx = {"appointmentDate": OLD}
    result = calendar.cancel_by_id(TENANT, ctx, AID)

    assert result["ok"] is True
    assert result["cancelled"] is True
    assert result["recoveredBy"] == "calendar_readback"
    assert len(writes) == 1
    assert "managementUncertain" not in ctx


def test_absage_http_200_braucht_trotzdem_exakten_kalenderbeweis(monkeypatch):
    _aktiv(monkeypatch)
    monkeypatch.setattr(
        calendar,
        "_cf_call",
        lambda route, body, **kwargs: (
            200, {"status": "success"}, {"route": route}),
    )
    monkeypatch.setattr(
        calendar,
        "_firestore_appointment_by_id",
        lambda tenant, aid, **kwargs: {
            "ok": True,
            "deleted": False,
            "appointment": {"id": aid, "iso": OLD},
        },
    )

    ctx = {"appointmentDate": OLD}
    result = calendar.cancel_by_id(TENANT, ctx, AID)

    assert result["ok"] is False
    assert result["cancelled"] is False
    assert result["writeAttempted"] is True
    assert result["verificationFailed"] is True
    assert result["possiblyChanged"] is True
    assert result["manualCheckRequired"] is True
    assert result["error"] == "cancel_verification_inconclusive"
    assert ctx["managementUncertain"]["operation"] == "cancel"
    assert "abgesagt" not in result["spoken"].lower()


def test_absage_http_200_und_exakte_ruecklese_gilt_als_erfolg(monkeypatch):
    _aktiv(monkeypatch)
    monkeypatch.setattr(
        calendar,
        "_cf_call",
        lambda route, body, **kwargs: (
            200, {"status": "success"}, {"route": route}),
    )
    monkeypatch.setattr(
        calendar,
        "_firestore_appointment_by_id",
        lambda tenant, aid, **kwargs: {
            "ok": True, "missing": True, "appointmentId": aid,
        },
    )

    ctx = {"appointmentDate": OLD}
    result = calendar.cancel_by_id(TENANT, ctx, AID)

    assert result["ok"] is True
    assert result["cancelled"] is True
    assert result["verified"] is True
    assert "managementUncertain" not in ctx


def test_absage_nachlese_wartet_auf_eventual_consistency(monkeypatch):
    _aktiv(monkeypatch)
    monkeypatch.setattr(
        calendar, "_MANAGEMENT_RECOVERY_DELAYS", (0.0, 0.0))
    writes = []
    reads = iter([
        {
            "ok": True, "deleted": False,
            "appointment": {"id": AID, "iso": OLD},
        },
        {"ok": True, "deleted": True, "appointment": {"id": AID}},
    ])
    monkeypatch.setattr(
        calendar,
        "_cf_call",
        lambda route, body, **kwargs: (
            writes.append((route, body)) or
            (0, {"status": "error", "message": "timeout"}, {"route": route})
        ),
    )
    monkeypatch.setattr(
        calendar,
        "_firestore_appointment_by_id",
        lambda tenant, aid, **kwargs: next(reads),
    )

    result = calendar.cancel_by_id(
        TENANT, {"appointmentDate": OLD}, AID)

    assert result["ok"] is True
    assert result["recoveredBy"] == "calendar_readback"
    assert len(writes) == 1


def test_absage_5xx_aktiver_termin_latcht_und_blockiert_folgeschreiben(
    monkeypatch,
):
    _aktiv(monkeypatch)
    writes = []
    reads = []
    monkeypatch.setattr(
        calendar,
        "_cf_call",
        lambda route, body, **kwargs: (
            writes.append((route, body)) or
            (500, {"status": "error", "message": "intern"}, {"route": route})
        ),
    )
    monkeypatch.setattr(
        calendar,
        "_firestore_appointment_by_id",
        lambda tenant, aid, **kwargs: (
            reads.append((aid, kwargs)) or {
                "ok": True,
                "deleted": False,
                "appointment": {"id": aid, "iso": OLD},
            }
        ),
    )

    ctx = {"appointmentDate": OLD}
    result = calendar.cancel_by_id(TENANT, ctx, AID)
    blocked = calendar.cancel_by_id(TENANT, ctx, AID)

    assert result["ok"] is False
    assert result["cancelled"] is False
    assert result["writeAttempted"] is True
    assert result["verificationFailed"] is True
    assert result["possiblyChanged"] is True
    assert result["manualCheckRequired"] is True
    assert result["error"] == "cancel_verification_inconclusive"
    assert result.get("recoveredBy") is None
    assert ctx["managementUncertain"]["appointmentId"] == AID
    assert ctx["managementUncertain"]["reason"] == "readback_active"

    assert blocked["ok"] is False
    assert blocked["cancelled"] is False
    assert blocked["writeAttempted"] is False
    assert blocked["verificationFailed"] is True
    assert blocked["possiblyChanged"] is True
    assert blocked["manualCheckRequired"] is True
    assert blocked["error"] == "management_write_blocked_by_uncertainty"
    assert len(writes) == 1
    assert len(reads) == 1


def test_verschieben_http_500_aber_zielslot_belegt_durch_id_gilt_als_erfolg(
    monkeypatch,
):
    _aktiv(monkeypatch)
    writes = []
    monkeypatch.setattr(
        calendar,
        "_cf_update",
        lambda action, body: (
            writes.append((action, body)) or
            (500, {"success": False, "message": "sms failed"}, {
                "action": action,
            })
        ),
    )
    monkeypatch.setattr(
        calendar,
        "_firestore_appointment_by_id",
        lambda tenant, aid, **kwargs: {
            "ok": True,
            "deleted": False,
            "appointment": {"id": aid, "iso": NEW},
        },
    )

    ctx = {"appointmentId": AID}
    result = calendar.move_appointment(TENANT, ctx, slot_iso=NEW)

    assert result["ok"] is True
    assert result["moved"] is True
    assert result["recoveredBy"] == "calendar_readback"
    assert len(writes) == 1
    assert "managementUncertain" not in ctx


def test_verschieben_http_200_braucht_trotzdem_exakten_zielslot(monkeypatch):
    _aktiv(monkeypatch)
    monkeypatch.setattr(
        calendar,
        "_cf_update",
        lambda action, body: (
            200, {"success": True}, {"action": action}),
    )
    monkeypatch.setattr(
        calendar,
        "_firestore_appointment_by_id",
        lambda tenant, aid, **kwargs: {
            "ok": True,
            "deleted": False,
            "appointment": {"id": aid, "iso": OLD},
        },
    )

    ctx = {"appointmentId": AID}
    result = calendar.move_appointment(TENANT, ctx, slot_iso=NEW)

    assert result["ok"] is False
    assert result["moved"] is False
    assert result["writeAttempted"] is True
    assert result["verificationFailed"] is True
    assert result["possiblyChanged"] is True
    assert result["manualCheckRequired"] is True
    assert result["error"] == "move_verification_inconclusive"
    assert ctx["managementUncertain"]["operation"] == "move"
    assert "liegt jetzt" not in result["spoken"].lower()


def test_verschieben_http_200_und_exakte_ruecklese_gilt_als_erfolg(monkeypatch):
    _aktiv(monkeypatch)
    monkeypatch.setattr(
        calendar,
        "_cf_update",
        lambda action, body: (
            200, {"success": True}, {"action": action}),
    )
    monkeypatch.setattr(
        calendar,
        "_firestore_appointment_by_id",
        lambda tenant, aid, **kwargs: {
            "ok": True,
            "deleted": False,
            "appointment": {"id": aid, "iso": NEW},
        },
    )

    ctx = {"appointmentId": AID}
    result = calendar.move_appointment(TENANT, ctx, slot_iso=NEW)

    assert result["ok"] is True
    assert result["moved"] is True
    assert result["verified"] is True
    assert "managementUncertain" not in ctx


def test_verschieben_nachlese_wartet_bis_zielslot_sichtbar_ist(monkeypatch):
    _aktiv(monkeypatch)
    monkeypatch.setattr(
        calendar, "_MANAGEMENT_RECOVERY_DELAYS", (0.0, 0.0))
    writes = []
    reads = iter([
        {
            "ok": True,
            "deleted": False,
            "appointment": {"id": AID, "iso": OLD},
        },
        {
            "ok": True,
            "deleted": False,
            "appointment": {"id": AID, "iso": NEW},
        },
    ])
    monkeypatch.setattr(
        calendar,
        "_cf_update",
        lambda action, body: (
            writes.append((action, body)) or
            (0, {"success": False, "message": "timeout"}, {"action": action})
        ),
    )
    monkeypatch.setattr(
        calendar,
        "_firestore_appointment_by_id",
        lambda tenant, aid, **kwargs: next(reads),
    )

    result = calendar.move_appointment(
        TENANT, {"appointmentId": AID}, slot_iso=NEW)

    assert result["ok"] is True
    assert result["recoveredBy"] == "calendar_readback"
    assert len(writes) == 1


def test_verschieben_timeout_falscher_slot_latcht_und_blockiert_folgeschreiben(
    monkeypatch,
):
    _aktiv(monkeypatch)
    writes = []
    reads = []
    monkeypatch.setattr(
        calendar,
        "_cf_update",
        lambda action, body: (
            writes.append((action, body)) or
            (0, {"success": False, "message": "timeout"}, {"action": action})
        ),
    )
    monkeypatch.setattr(
        calendar,
        "_firestore_appointment_by_id",
        lambda tenant, aid, **kwargs: (
            reads.append((aid, kwargs)) or {
                "ok": True,
                "deleted": False,
                "appointment": {
                    "id": aid,
                    "iso": "2026-10-19T12:30:00+02:00",
                },
            }
        ),
    )

    ctx = {"appointmentId": AID}
    result = calendar.move_appointment(TENANT, ctx, slot_iso=NEW)
    blocked = calendar.move_appointment(TENANT, ctx, slot_iso=NEW)

    assert result["ok"] is False
    assert result["moved"] is False
    assert result["writeAttempted"] is True
    assert result["verificationFailed"] is True
    assert result["possiblyChanged"] is True
    assert result["manualCheckRequired"] is True
    assert result["error"] == "move_verification_inconclusive"
    assert result.get("recoveredBy") is None
    assert ctx["managementUncertain"]["appointmentId"] == AID
    assert ctx["managementUncertain"]["slotIso"] == NEW

    assert blocked["ok"] is False
    assert blocked["moved"] is False
    assert blocked["writeAttempted"] is False
    assert blocked["verificationFailed"] is True
    assert blocked["possiblyChanged"] is True
    assert blocked["manualCheckRequired"] is True
    assert blocked["error"] == "management_write_blocked_by_uncertainty"
    assert len(writes) == 1
    assert len(reads) == 1


def test_verschieben_patientenstatus_vier_oder_fuenf_beweist_keinen_erfolg(
    monkeypatch,
):
    _aktiv(monkeypatch)
    monkeypatch.setattr(
        calendar,
        "_cf_update",
        lambda action, body: (
            500, {"success": False, "message": "intern"}, {"action": action}),
    )
    for patient_status in (4, 5, "4", "5"):
        monkeypatch.setattr(
            calendar,
            "_firestore_appointment_by_id",
            lambda tenant, aid, patient_status=patient_status, **kwargs: {
                "ok": True,
                "deleted": False,
                "appointment": {
                    "id": aid,
                    "iso": NEW,
                    "patientStatus": patient_status,
                },
            },
        )

        result = calendar.move_appointment(
            TENANT, {"appointmentId": AID}, slot_iso=NEW)

        assert result["ok"] is False
        assert result.get("recoveredBy") is None


def test_firestore_readback_adressiert_exakte_id_mit_feldmaske(monkeypatch):
    from kern import anrufaudio, config, standort

    gesehen = {}

    class Response:
        status_code = 404

        @staticmethod
        def json():
            return {}

    def fake_get(url, **kwargs):
        gesehen["url"] = url
        gesehen.update(kwargs)
        return Response()

    monkeypatch.setattr(config, "FIREBASE_CREDENTIALS", "test-key.json")
    monkeypatch.setattr(anrufaudio, "_access_token", lambda scope: "oauth")
    monkeypatch.setattr(standort, "_projekt", lambda: "docgenda")
    monkeypatch.setattr(calendar.httpx, "get", fake_get)

    result = calendar._firestore_appointment_by_id(
        TENANT, AID, timeout=1.25)

    assert result == {
        "ok": True,
        "missing": True,
        "appointmentId": AID,
    }
    assert gesehen["url"].endswith(
        "/clients/client-1/locations/location-1/appointments/appointment-1")
    assert gesehen["headers"] == {"Authorization": "Bearer oauth"}
    assert gesehen["params"]["mask.fieldPaths"] == [
        "start", "status", "patientStatus", "isDeleted", "deletedAt",
        "patient", "calendar", "resourceId", "visitMotive",
        "nameConfirmToken", "nameConfirmPending", "confirmationHeld",
    ]
    assert gesehen["timeout"] == 1.25


def test_create_appointment_nutzt_zurueckgegebene_ids_ohne_namenssuche(
    monkeypatch,
):
    ctx = {
        "calendarId": "calendar-1",
        "visitMotiveId": "motive-1",
        "privateInsurance": None,
    }
    monkeypatch.setattr(
        calendar,
        "_cf_call",
        lambda route, body, **kwargs: (
            200,
            {
                "status": "success",
                "patientId": "patient-new",
                "appointmentId": "appointment-new",
                "createdPatient": True,
            },
            {"route": route},
        ),
    )
    monkeypatch.setattr(
        calendar.patients,
        "patient_aufloesen",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("keine namensbasierte Patientensuche")),
    )
    monkeypatch.setattr(
        calendar,
        "_buchung_verifizieren",
        lambda *args, **kwargs: {
            "ok": True,
            "patientId": "patient-new",
            "appointmentId": "appointment-new",
            "beweis": "namensliste",
        },
    )

    result = calendar._buch_und_akte(
        TENANT,
        ctx,
        NEW,
        "Anna",
        "Muster",
        "+491701234567",
    )

    assert result["ok"] is True
    assert result["patientId"] == "patient-new"
    assert result["appointmentId"] == "appointment-new"
    assert result["createdPatient"] is True
    assert ctx["patientId"] == "patient-new"
