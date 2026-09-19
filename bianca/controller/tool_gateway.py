"""Produktives Werkzeug-Gateway fuer den Dialogkern.

Dieses Modul ist das Gegenstueck zu ``gateway_sim.ToolGatewaySim``: es
uebersetzt einen ``ToolCommand`` des Reducers 1:1 in ein normalisiertes
``ToolOutcome`` — aber gegen die ECHTEN, bewaehrten Kalenderfunktionen in
``kern/calendar.py`` (offer_slots / book_slot / find_patient_appointments /
cancel_by_id / move_appointment / note_appointment). Nichts wird hier neu
erfunden: die Read-after-write-Beweise, WRITE_LIVE-/Testmodus-Gates und
Patient-Bindungswachen leben schon in ``kern.calendar`` und bleiben die
einzige Wahrheit.

DREI Sicherheiten, bewusst konservativ (der Dialogkern laeuft noch NICHT im
Enforce-Modus live — er ist Shadow):

1. **Schreibsperre per Default** (``nur_lesen=True``). Solange die Praxis
   nicht ausdruecklich auf Enforce steht, fuehrt dieses Gateway KEINE
   schreibenden Befehle aus (book/cancel/move/notiz). Es liefert dann ein
   ehrliches ``ERROR``-Outcome mit ``payload={"inert": True}`` zurueck —
   nie einen erfundenen Erfolg. Lesebefehle (offer/list) laufen immer.
2. **Kein Roh-Audio, kein neuer Netzpfad.** Es werden ausschliesslich die
   vorhandenen ``kern.calendar``-Funktionen gerufen; deren eigene
   ``WRITE_LIVE``/``_test_no_write``-Gates greifen zusaetzlich (Testmodus =
   Trockenlauf, auch wenn ``nur_lesen=False`` gesetzt waere).
3. **Nie werfend.** Jede Ausnahme aus ``kern.calendar`` wird gefangen und zu
   ``OutcomeStatus.CALENDAR_ERROR`` — der Anruf-Pfad darf nie an einem
   Tool-Fehler zerschellen.

Der ``ctx`` (Buchungskontext) wird ueber die Zuege HINWEG gehalten: Bindungen
(Kalender/Motiv), aufgeloeste ``patientId`` und der ``slotVorrat`` sammeln
sich an wie im Live-``booking``-Dict. Args des einzelnen Befehls werden
oben drauf gemappt.

Dieses Gateway ist derzeit NICHT in den Live-Zug (``user_turn``) verdrahtet.
Es ist der fertige Baustein fuer den spaeteren, mandantenscharfen
Enforce-Cutover (eigene To-do ``shadow-cutover``).
"""

from __future__ import annotations

from typing import Any, Callable

from bianca.controller.typen import OutcomeStatus, ToolCommand, ToolOutcome


# --------------------------------------------------------------------------- #
# Hilfen
# --------------------------------------------------------------------------- #
def _s(v: Any) -> str:
    return str(v).strip() if v is not None else ""


_SCHREIB_BEFEHLE = frozenset(
    {"book_slot", "cancel_appointment", "move_appointment", "praxis_notiz"}
)


def _denied(payload: dict) -> bool:
    """Telefonisch-nicht-buchbar erkennen (kern liefert Marker/Spoken)."""
    if payload.get("motivNichtTelefonisch") or payload.get("denied"):
        return True
    txt = f"{_s(payload.get('spoken'))} {_s(payload.get('regie'))}".lower()
    return "telefonisch" in txt and "nicht" in txt and (
        "buchbar" in txt or "vergeben" in txt
    )


def _needs_phone(payload: dict) -> bool:
    """book_slot meldet fehlende Handynummer nur ueber Text/Regie."""
    if payload.get("needsPhone") or payload.get("needs_phone"):
        return True
    txt = f"{_s(payload.get('spoken'))} {_s(payload.get('regie'))}".lower()
    return "handynummer" in txt or ("nummer erfragen" in txt)


# --------------------------------------------------------------------------- #
# Gateway
# --------------------------------------------------------------------------- #
class ToolGateway:
    """Produktiver Uebersetzer ToolCommand -> ToolOutcome gegen kern.calendar.

    Parameter
    ---------
    tenant     : aufgeloester Mandant (clientId/locationId/Kalender/Motive).
    nur_lesen  : Default True. True = schreibende Befehle werden NICHT
                 ausgefuehrt (inertes ERROR-Outcome). Erst der Enforce-Cutover
                 setzt das je Mandant/Anliegen auf False.
    sit        : optionale Live-Sitzung (fuer list_appointments/note, damit
                 kern.calendar Patient/upcoming aus dem Sammler ziehen kann).
    kalender   : Injektionspunkt fuer Tests. Default: lazy ``kern.calendar``.
    """

    def __init__(
        self,
        tenant: dict | None = None,
        *,
        nur_lesen: bool = True,
        sit: dict | None = None,
        kalender: Any | None = None,
    ) -> None:
        self.tenant = tenant or {}
        self.nur_lesen = bool(nur_lesen)
        self.sit = sit
        self._cal = kalender
        # Buchungskontext, ueber die Zuege hinweg gehalten (wie booking-Dict).
        self.ctx: dict[str, Any] = {}

    # ------------------------------------------------------------------ #
    def _kal(self) -> Any:
        """kern.calendar erst bei Bedarf importieren (keine schwere Top-Dep)."""
        if self._cal is None:
            from kern import calendar as _cal  # lazy
            self._cal = _cal
        return self._cal

    def _ctx_fuer(self, cmd: ToolCommand) -> dict[str, Any]:
        """Bindungen + Args in den fortlaufenden ctx spiegeln."""
        for k, v in (cmd.bindings or {}).items():
            if _s(v):
                self.ctx[k] = v
        a = cmd.args or {}
        # Suche/Anlage-relevante Felder in den ctx ziehen (kern liest sie dort).
        for quelle, ziel in (
            ("lastName", "lastName"),
            ("firstName", "firstName"),
            ("visitMotiveId", "visitMotiveId"),
            ("calendarId", "calendarId"),
        ):
            if _s(a.get(quelle)):
                self.ctx[ziel] = a[quelle]
        return self.ctx

    # ------------------------------------------------------------------ #
    def ausfuehren(self, cmd: ToolCommand) -> ToolOutcome:
        """Einen Befehl ausfuehren. Nie werfend."""
        name = cmd.name
        try:
            if name == "offer_slots":
                return self._offer(cmd)
            if name == "list_appointments":
                return self._list(cmd)
            if name in _SCHREIB_BEFEHLE:
                if self.nur_lesen:
                    return self._inert(name)
                if name == "book_slot":
                    return self._book(cmd)
                if name == "cancel_appointment":
                    return self._cancel(cmd)
                if name == "move_appointment":
                    return self._move(cmd)
                if name == "praxis_notiz":
                    return self._notiz(cmd)
            return ToolOutcome(name=name, status=OutcomeStatus.ERROR)
        except Exception as exc:  # noqa: BLE001 — Tool-Fehler nie werfen lassen
            return ToolOutcome(
                name=name,
                status=OutcomeStatus.CALENDAR_ERROR,
                payload={"fehler": type(exc).__name__},
            )

    # ------------------------------------------------------------------ #
    def _inert(self, name: str) -> ToolOutcome:
        """Schreibsperre: ehrlich NICHTS getan, kein erfundener Erfolg."""
        return ToolOutcome(
            name=name,
            status=OutcomeStatus.ERROR,
            committed=False,
            payload={"inert": True, "grund": "gateway_read_only"},
        )

    # ------------------------------- READ ------------------------------ #
    def _offer(self, cmd: ToolCommand) -> ToolOutcome:
        ctx = self._ctx_fuer(cmd)
        wish = _s((cmd.args or {}).get("wish"))
        res = self._kal().offer_slots(self.tenant, ctx, wish_text=wish)
        if not isinstance(res, dict):
            return ToolOutcome(name="offer_slots", status=OutcomeStatus.CALENDAR_ERROR)
        roh = res.get("slots") or []
        slots = [
            _s(s.get("spoken")) if isinstance(s, dict) else _s(s)
            for s in roh
        ]
        slots = [s for s in slots if s]
        if res.get("ok") and slots:
            payload: dict[str, Any] = {"slots": slots}
            if res.get("exakt") is False or res.get("wishMatched") is False:
                payload["exakt"] = False
                if _s(res.get("wunsch")) or wish:
                    payload["wunsch"] = _s(res.get("wunsch")) or wish
            return ToolOutcome(
                name="offer_slots", status=OutcomeStatus.OK, payload=payload
            )
        if _denied(res):
            return ToolOutcome(name="offer_slots", status=OutcomeStatus.DENIED)
        return ToolOutcome(name="offer_slots", status=OutcomeStatus.EMPTY)

    def _list(self, cmd: ToolCommand) -> ToolOutcome:
        ctx = self._ctx_fuer(cmd)
        res = self._kal().find_patient_appointments(self.tenant, ctx)
        if not isinstance(res, dict):
            return ToolOutcome(
                name="list_appointments", status=OutcomeStatus.CALENDAR_ERROR
            )
        if not res.get("ok"):
            return ToolOutcome(
                name="list_appointments", status=OutcomeStatus.CALENDAR_ERROR
            )
        if res.get("mehrdeutig"):
            return ToolOutcome(
                name="list_appointments", status=OutcomeStatus.AMBIGUOUS,
                payload={"vornameVerworfen": bool(res.get("vornameVerworfen"))},
            )
        appts = res.get("appointments") or []
        if res.get("notFound") or not appts:
            return ToolOutcome(
                name="list_appointments", status=OutcomeStatus.NOT_FOUND
            )
        norm: list[dict[str, str]] = []
        for a in appts:
            if not isinstance(a, dict):
                continue
            iso = _s(a.get("iso"))
            norm.append({
                "id": _s(a.get("id")),
                "iso": iso,
                "date": _s(a.get("date")) or (iso[:10] if len(iso) >= 10 else ""),
                "arzt": _s(a.get("doctorName")) or _s(a.get("arzt")),
                "grund": _s(a.get("motivName")) or _s(a.get("grund")),
                "calendarId": _s(a.get("calendarId")),
                "spoken": _s(a.get("spoken")),
            })
        payload = {"appointments": norm}
        if _s(res.get("patient", {}).get("id") if isinstance(res.get("patient"), dict) else ""):
            payload["patientId"] = res["patient"]["id"]
        return ToolOutcome(
            name="list_appointments", status=OutcomeStatus.OK, payload=payload
        )

    # ------------------------------ WRITE ------------------------------ #
    def _book(self, cmd: ToolCommand) -> ToolOutcome:
        ctx = self._ctx_fuer(cmd)
        iso = _s((cmd.args or {}).get("slot_iso"))
        if iso:
            ctx["slotIso"] = iso
        res = self._kal().book_slot(self.tenant, ctx, slot_iso=iso)
        if not isinstance(res, dict):
            return ToolOutcome(name="book_slot", status=OutcomeStatus.CALENDAR_ERROR)
        if res.get("booked"):
            return ToolOutcome(
                name="book_slot", status=OutcomeStatus.OK, committed=True,
                payload={
                    "appointmentId": _s(res.get("appointmentId")),
                    "iso": _s(res.get("slotIso")) or iso,
                },
            )
        if res.get("dryRun"):
            # Testmodus/WRITE_LIVE=0: bewusst NICHT committed.
            return ToolOutcome(
                name="book_slot", status=OutcomeStatus.OK, committed=False,
                payload={"dryRun": True, "iso": _s(res.get("slotIso")) or iso},
            )
        if res.get("slotTaken"):
            return ToolOutcome(name="book_slot", status=OutcomeStatus.SLOT_TAKEN)
        if _needs_phone(res):
            return ToolOutcome(name="book_slot", status=OutcomeStatus.NEEDS_PHONE)
        if res.get("patientMismatch"):
            return ToolOutcome(
                name="book_slot", status=OutcomeStatus.ERROR,
                payload={"patientMismatch": True},
            )
        return ToolOutcome(name="book_slot", status=OutcomeStatus.CALENDAR_ERROR)

    def _cancel(self, cmd: ToolCommand) -> ToolOutcome:
        ctx = self._ctx_fuer(cmd)
        aid = _s((cmd.args or {}).get("appointmentId"))
        res = self._kal().cancel_by_id(self.tenant, ctx, aid)
        if not isinstance(res, dict):
            return ToolOutcome(
                name="cancel_appointment", status=OutcomeStatus.CALENDAR_ERROR
            )
        if res.get("cancelled"):
            return ToolOutcome(
                name="cancel_appointment", status=OutcomeStatus.OK, committed=True,
                payload={"appointmentId": _s(res.get("appointmentId")) or aid},
            )
        if res.get("dryRun"):
            return ToolOutcome(
                name="cancel_appointment", status=OutcomeStatus.OK, committed=False,
                payload={"dryRun": True, "appointmentId": aid},
            )
        return ToolOutcome(
            name="cancel_appointment", status=OutcomeStatus.CALENDAR_ERROR
        )

    def _move(self, cmd: ToolCommand) -> ToolOutcome:
        ctx = self._ctx_fuer(cmd)
        a = cmd.args or {}
        aid = _s(a.get("appointmentId"))
        if aid:
            ctx["appointmentId"] = aid
        iso = _s(a.get("slot_iso"))
        res = self._kal().move_appointment(self.tenant, ctx, slot_iso=iso)
        if not isinstance(res, dict):
            return ToolOutcome(
                name="move_appointment", status=OutcomeStatus.CALENDAR_ERROR
            )
        if res.get("moved"):
            return ToolOutcome(
                name="move_appointment", status=OutcomeStatus.OK, committed=True,
                payload={
                    "appointmentId": _s(res.get("appointmentId")) or aid,
                    "iso": _s(res.get("slotIso")) or iso,
                },
            )
        if res.get("dryRun"):
            return ToolOutcome(
                name="move_appointment", status=OutcomeStatus.OK, committed=False,
                payload={"dryRun": True, "iso": _s(res.get("slotIso")) or iso},
            )
        if res.get("slotTaken"):
            return ToolOutcome(name="move_appointment", status=OutcomeStatus.SLOT_TAKEN)
        return ToolOutcome(
            name="move_appointment", status=OutcomeStatus.CALENDAR_ERROR
        )

    def _notiz(self, cmd: ToolCommand) -> ToolOutcome:
        ctx = self._ctx_fuer(cmd)
        a = cmd.args or {}
        aid = _s(a.get("appointmentId"))
        if aid:
            ctx["appointmentId"] = aid
        note = _s(a.get("was")) or _s(a.get("note"))
        res = self._kal().note_appointment(self.tenant, ctx, self.sit, note=note)
        if not isinstance(res, dict):
            return ToolOutcome(name="praxis_notiz", status=OutcomeStatus.CALENDAR_ERROR)
        if res.get("noted"):
            return ToolOutcome(
                name="praxis_notiz", status=OutcomeStatus.OK, committed=True,
                payload={"appointmentId": _s(res.get("appointmentId")) or aid},
            )
        if res.get("dryRun"):
            return ToolOutcome(
                name="praxis_notiz", status=OutcomeStatus.OK, committed=False,
                payload={"dryRun": True},
            )
        return ToolOutcome(name="praxis_notiz", status=OutcomeStatus.CALENDAR_ERROR)


__all__ = ["ToolGateway"]
