"""Tests fuer das produktive Werkzeug-Gateway (bianca.controller.tool_gateway).

Alle kern.calendar-Aufrufe laufen gegen ein INJIZIERTES Fake-Modul — kein
Netz, keine echte Buchung. Geprueft wird die Uebersetzung ToolCommand ->
ToolOutcome und vor allem die Schreibsperre (nur_lesen).
"""

from __future__ import annotations

from bianca.controller.tool_gateway import ToolGateway
from bianca.controller.typen import OutcomeStatus, ToolCommand


# --------------------------------------------------------------------------- #
# Fake-kern.calendar: liefert die dokumentierten Rueckgabe-Dicts.
# --------------------------------------------------------------------------- #
class FakeKalender:
    def __init__(self, **rueck):
        self.rueck = rueck
        self.aufrufe: list[tuple[str, dict, dict]] = []

    def _log(self, name: str, tenant: dict, ctx: dict, extra: dict):
        self.aufrufe.append((name, dict(ctx), dict(extra)))

    def offer_slots(self, tenant, ctx, *, wish_text="", **kw):
        self._log("offer_slots", tenant, ctx, {"wish_text": wish_text})
        return self.rueck.get("offer_slots", {"ok": True, "slots": []})

    def find_patient_appointments(self, tenant, ctx):
        self._log("find_patient_appointments", tenant, ctx, {})
        return self.rueck.get("find", {"ok": True, "appointments": []})

    def book_slot(self, tenant, ctx, *, slot_iso=""):
        self._log("book_slot", tenant, ctx, {"slot_iso": slot_iso})
        return self.rueck.get("book_slot", {"ok": True, "booked": True})

    def cancel_by_id(self, tenant, ctx, appointment_id):
        self._log("cancel_by_id", tenant, ctx, {"appointment_id": appointment_id})
        return self.rueck.get("cancel", {"ok": True, "cancelled": True})

    def move_appointment(self, tenant, ctx, *, slot_iso="", **kw):
        self._log("move_appointment", tenant, ctx, {"slot_iso": slot_iso})
        return self.rueck.get("move", {"ok": True, "moved": True})

    def note_appointment(self, tenant, ctx, sit=None, *, note=""):
        self._log("note_appointment", tenant, ctx, {"note": note})
        return self.rueck.get("note", {"ok": True, "noted": True})


def _gw(nur_lesen=True, **rueck) -> tuple[ToolGateway, FakeKalender]:
    fake = FakeKalender(**rueck)
    gw = ToolGateway({"clientId": "c1", "locationId": "l1"},
                     nur_lesen=nur_lesen, kalender=fake)
    return gw, fake


# --------------------------------------------------------------------------- #
# offer_slots (read)
# --------------------------------------------------------------------------- #
def test_offer_ok_mit_slots():
    gw, _ = _gw(offer_slots={
        "ok": True,
        "slots": [{"iso": "2026-10-02T13:00", "spoken": "Freitag 09:00 Uhr"}],
    })
    oc = gw.ausfuehren(ToolCommand(name="offer_slots", args={"wish": "freitag"}))
    assert oc.status == OutcomeStatus.OK
    assert oc.payload["slots"] == ["Freitag 09:00 Uhr"]
    assert oc.committed is False


def test_offer_leer_ist_empty():
    gw, _ = _gw(offer_slots={"ok": True, "slots": []})
    oc = gw.ausfuehren(ToolCommand(name="offer_slots"))
    assert oc.status == OutcomeStatus.EMPTY


def test_offer_naechstbestes_setzt_exakt_false():
    gw, _ = _gw(offer_slots={
        "ok": True, "wishMatched": False, "wunsch": "montag",
        "slots": [{"iso": "x", "spoken": "Dienstag 14:30 Uhr"}],
    })
    oc = gw.ausfuehren(ToolCommand(name="offer_slots", args={"wish": "montag"}))
    assert oc.status == OutcomeStatus.OK
    assert oc.payload.get("exakt") is False
    assert oc.payload.get("wunsch") == "montag"


def test_offer_denied_bei_nicht_telefonisch():
    gw, _ = _gw(offer_slots={
        "ok": False, "motivNichtTelefonisch": True,
        "spoken": "Diese Terminart darf ich telefonisch nicht vergeben.",
    })
    oc = gw.ausfuehren(ToolCommand(name="offer_slots"))
    assert oc.status == OutcomeStatus.DENIED


def test_offer_binding_landet_im_ctx():
    gw, fake = _gw(offer_slots={"ok": True, "slots": [{"iso": "i", "spoken": "x"}]})
    gw.ausfuehren(ToolCommand(
        name="offer_slots",
        bindings={"calendarId": "cal-1", "visitMotiveId": "mot-1"},
    ))
    _, ctx, _ = fake.aufrufe[-1]
    assert ctx["calendarId"] == "cal-1"
    assert ctx["visitMotiveId"] == "mot-1"


# --------------------------------------------------------------------------- #
# list_appointments (read)
# --------------------------------------------------------------------------- #
def test_list_ok_normalisiert():
    gw, _ = _gw(find={
        "ok": True,
        "patient": {"id": "p1"},
        "appointments": [{
            "id": "A1", "iso": "2026-10-02T13:00", "date": "2026-10-02",
            "doctorName": "Dr. Petsas", "motivName": "Kontrolle",
            "calendarId": "cal-p", "spoken": "Freitag bei Dr. Petsas",
        }],
    })
    oc = gw.ausfuehren(ToolCommand(name="list_appointments", args={"lastName": "Meier"}))
    assert oc.status == OutcomeStatus.OK
    a = oc.payload["appointments"][0]
    assert a["id"] == "A1"
    assert a["arzt"] == "Dr. Petsas"
    assert a["grund"] == "Kontrolle"
    assert oc.payload["patientId"] == "p1"


def test_list_notfound():
    gw, _ = _gw(find={"ok": True, "notFound": True, "appointments": []})
    oc = gw.ausfuehren(ToolCommand(name="list_appointments", args={"lastName": "X"}))
    assert oc.status == OutcomeStatus.NOT_FOUND


def test_list_mehrdeutig_ist_ambiguous():
    gw, _ = _gw(find={"ok": True, "mehrdeutig": True, "appointments": []})
    oc = gw.ausfuehren(ToolCommand(name="list_appointments", args={"lastName": "X"}))
    assert oc.status == OutcomeStatus.AMBIGUOUS


def test_list_fehler_ist_calendar_error():
    gw, _ = _gw(find={"ok": False})
    oc = gw.ausfuehren(ToolCommand(name="list_appointments", args={"lastName": "X"}))
    assert oc.status == OutcomeStatus.CALENDAR_ERROR


# --------------------------------------------------------------------------- #
# Schreibsperre (nur_lesen=True) — der wichtigste Teil
# --------------------------------------------------------------------------- #
def test_schreibsperre_book_ist_inert():
    gw, fake = _gw(nur_lesen=True)
    oc = gw.ausfuehren(ToolCommand(name="book_slot", args={"slot_iso": "2026-10-02T13:00"}))
    assert oc.status == OutcomeStatus.ERROR
    assert oc.committed is False
    assert oc.payload.get("inert") is True
    # kern.calendar.book_slot wurde NIE gerufen:
    assert not any(a[0] == "book_slot" for a in fake.aufrufe)


def test_schreibsperre_cancel_move_notiz_inert():
    for name in ("cancel_appointment", "move_appointment", "praxis_notiz"):
        gw, fake = _gw(nur_lesen=True)
        oc = gw.ausfuehren(ToolCommand(name=name, args={"appointmentId": "A1"}))
        assert oc.committed is False
        assert oc.payload.get("inert") is True
        assert fake.aufrufe == []  # nichts an kern.calendar durchgereicht


def test_schreibsperre_laesst_lesen_zu():
    gw, fake = _gw(nur_lesen=True, offer_slots={"ok": True, "slots": [{"iso": "i", "spoken": "x"}]})
    oc = gw.ausfuehren(ToolCommand(name="offer_slots"))
    assert oc.status == OutcomeStatus.OK
    assert any(a[0] == "offer_slots" for a in fake.aufrufe)


# --------------------------------------------------------------------------- #
# Schreiben freigeschaltet (nur_lesen=False)
# --------------------------------------------------------------------------- #
def test_book_erfolg_ist_committed():
    gw, _ = _gw(nur_lesen=False, book_slot={
        "ok": True, "booked": True, "appointmentId": "NEU-1",
        "slotIso": "2026-10-02T13:00",
    })
    oc = gw.ausfuehren(ToolCommand(name="book_slot", args={"slot_iso": "2026-10-02T13:00"}))
    assert oc.status == OutcomeStatus.OK
    assert oc.committed is True
    assert oc.payload["appointmentId"] == "NEU-1"


def test_book_dryrun_nicht_committed():
    gw, _ = _gw(nur_lesen=False, book_slot={
        "ok": True, "booked": False, "dryRun": True, "slotIso": "2026-10-02T13:00",
    })
    oc = gw.ausfuehren(ToolCommand(name="book_slot", args={"slot_iso": "2026-10-02T13:00"}))
    assert oc.status == OutcomeStatus.OK
    assert oc.committed is False
    assert oc.payload.get("dryRun") is True


def test_book_slot_taken():
    gw, _ = _gw(nur_lesen=False, book_slot={"ok": False, "slotTaken": True})
    oc = gw.ausfuehren(ToolCommand(name="book_slot", args={"slot_iso": "i"}))
    assert oc.status == OutcomeStatus.SLOT_TAKEN
    assert oc.committed is False


def test_book_needs_phone_ueber_text():
    gw, _ = _gw(nur_lesen=False, book_slot={
        "ok": False, "spoken": "In Ihrer Akte fehlt noch eine Handynummer. Wie lautet sie?",
    })
    oc = gw.ausfuehren(ToolCommand(name="book_slot", args={"slot_iso": "i"}))
    assert oc.status == OutcomeStatus.NEEDS_PHONE


def test_book_patient_mismatch_ist_error():
    gw, _ = _gw(nur_lesen=False, book_slot={"ok": False, "patientMismatch": True})
    oc = gw.ausfuehren(ToolCommand(name="book_slot", args={"slot_iso": "i"}))
    assert oc.status == OutcomeStatus.ERROR
    assert oc.committed is False


def test_cancel_erfolg_committed():
    gw, _ = _gw(nur_lesen=False, cancel={"ok": True, "cancelled": True, "appointmentId": "A1"})
    oc = gw.ausfuehren(ToolCommand(name="cancel_appointment", args={"appointmentId": "A1"}))
    assert oc.status == OutcomeStatus.OK
    assert oc.committed is True


def test_cancel_dryrun_nicht_committed():
    gw, _ = _gw(nur_lesen=False, cancel={"ok": True, "cancelled": False, "dryRun": True})
    oc = gw.ausfuehren(ToolCommand(name="cancel_appointment", args={"appointmentId": "A1"}))
    assert oc.committed is False
    assert oc.payload.get("dryRun") is True


def test_move_erfolg_committed():
    gw, _ = _gw(nur_lesen=False, move={
        "ok": True, "moved": True, "appointmentId": "A1", "slotIso": "2026-10-03T09:00",
    })
    oc = gw.ausfuehren(ToolCommand(
        name="move_appointment", args={"appointmentId": "A1", "slot_iso": "2026-10-03T09:00"},
    ))
    assert oc.status == OutcomeStatus.OK
    assert oc.committed is True


def test_move_slot_taken():
    gw, _ = _gw(nur_lesen=False, move={"ok": False, "slotTaken": True})
    oc = gw.ausfuehren(ToolCommand(
        name="move_appointment", args={"appointmentId": "A1", "slot_iso": "i"},
    ))
    assert oc.status == OutcomeStatus.SLOT_TAKEN


def test_notiz_erfolg_committed():
    gw, _ = _gw(nur_lesen=False, note={"ok": True, "noted": True, "appointmentId": "A1"})
    oc = gw.ausfuehren(ToolCommand(name="praxis_notiz", args={"was": "Rueckruf", "appointmentId": "A1"}))
    assert oc.status == OutcomeStatus.OK
    assert oc.committed is True


def test_notiz_dryrun_nicht_committed():
    gw, _ = _gw(nur_lesen=False, note={"ok": True, "noted": False, "dryRun": True})
    oc = gw.ausfuehren(ToolCommand(name="praxis_notiz", args={"was": "x"}))
    assert oc.committed is False


# --------------------------------------------------------------------------- #
# Robustheit
# --------------------------------------------------------------------------- #
def test_ausnahme_wird_zu_calendar_error():
    class Kaputt:
        def offer_slots(self, *a, **k):
            raise RuntimeError("boom")
    gw = ToolGateway({}, nur_lesen=True, kalender=Kaputt())
    oc = gw.ausfuehren(ToolCommand(name="offer_slots"))
    assert oc.status == OutcomeStatus.CALENDAR_ERROR
    assert oc.committed is False


def test_unbekannter_befehl_ist_error():
    gw, _ = _gw()
    oc = gw.ausfuehren(ToolCommand(name="voodoo"))
    assert oc.status == OutcomeStatus.ERROR


def test_ctx_wird_ueber_zuege_gehalten():
    gw, fake = _gw(
        offer_slots={"ok": True, "slots": [{"iso": "i", "spoken": "x"}]},
    )
    gw.ausfuehren(ToolCommand(name="offer_slots", bindings={"calendarId": "cal-9"}))
    gw.ausfuehren(ToolCommand(name="offer_slots", args={"wish": "montag"}))
    # zweiter Aufruf traegt calendarId aus dem ersten noch im ctx
    _, ctx2, _ = fake.aufrufe[-1]
    assert ctx2["calendarId"] == "cal-9"


def test_default_ist_nur_lesen():
    gw = ToolGateway({})
    assert gw.nur_lesen is True
