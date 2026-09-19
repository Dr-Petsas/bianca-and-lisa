"""Werkzeug-Gateway-SIMULATION fuer das isolierte Test-Dock des Dialogkerns.

Uebersetzt einen ``ToolCommand`` des Reducers in ein normalisiertes
``ToolOutcome`` — OHNE MAS, OHNE Cloud Function, OHNE Firestore. Rein
deterministisch und im Speicher, damit man den kompletten Fluss
(offer_slots -> book_slot, list_appointments -> cancel/move, praxis_notiz)
im Browser/CLI durchspielen kann.

Ueber ``Szenario`` lassen sich die interessanten Faelle gezielt ausloesen:
freie Slots (Anzahl/leer/denied), Terminsuche (0/1/mehrere), Buchung
(ok/needs_phone/slot_taken). So kann man Retry-, Ruecklese- und
Ehrlich-nein-Pfade testen, ohne echte Systeme zu beruehren.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from bianca.controller import wuensche as _wuensche
from bianca.controller.typen import OutcomeStatus, ToolCommand, ToolOutcome


@dataclass
class Szenario:
    """Stellschrauben fuer den Simulator (Default: der 'glueckliche' Pfad)."""

    freie_slots: int = 3            # offer_slots: Anzahl (0 -> EMPTY)
    slots_denied: bool = False      # offer_slots: telefonisch nicht buchbar
    termine: int = 1                # list_appointments: 0/1/mehrere
    buchung: str = "ok"             # ok | needs_phone | slot_taken | error
    anrufer_anrede: str = ""
    anrufer_nachname: str = ""
    anrufer_vorname: str = ""
    letzter_arzt: str = ""
    letzter_grund: str = ""
    letzter_wann: str = ""
    anrufer_telefon: str = ""
    anrufer_versicherung: str = ""
    _needs_phone_einmal: bool = True  # needs_phone nur beim ersten Versuch
    _slot_taken_einmal: bool = True   # slot_taken nur beim ersten Versuch


_WOCHENTAG = (
    "montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag",
)

# Ohne Wunsch bleiben die ersten drei wie bisher Montag/Dienstag/Mittwoch.
_KALENDER: tuple[tuple[str, str, str], ...] = (
    ("montag", "vormittag", "Montag 22.09. 09:00 Uhr"),
    ("dienstag", "nachmittag", "Dienstag 23.09. 14:30 Uhr"),
    ("mittwoch", "vormittag", "Mittwoch 24.09. 11:15 Uhr"),
    ("mittwoch", "nachmittag", "Mittwoch 24.09. 15:00 Uhr"),
    ("mittwoch", "nachmittag", "Mittwoch 01.10. 14:30 Uhr"),
    ("donnerstag", "vormittag", "Donnerstag 25.09. 09:00 Uhr"),
    ("donnerstag", "nachmittag", "Donnerstag 02.10. 14:30 Uhr"),
    ("donnerstag", "vormittag", "Donnerstag 09.10. 11:15 Uhr"),
    ("dienstag", "nachmittag", "Dienstag 30.09. 15:00 Uhr"),
    ("dienstag", "vormittag", "Dienstag 23.09. 09:30 Uhr"),
    ("freitag", "nachmittag", "Freitag 26.09. 15:30 Uhr"),
    ("freitag", "vormittag", "Freitag 26.09. 10:00 Uhr"),
    ("freitag", "vormittag", "Freitag 03.10. 10:00 Uhr"),
    ("montag", "vormittag", "Montag 05.10. 09:00 Uhr"),
    ("dienstag", "nachmittag", "Dienstag 06.10. 14:30 Uhr"),
    ("mittwoch", "vormittag", "Mittwoch 08.10. 11:15 Uhr"),
)


def _slot_suche(n: int, wish: str) -> tuple[list[str], bool]:
    """(Slots, exakt). Fenster aus dem Wunsch; sonst naechstbestes ab Fenstertag."""
    if n <= 0:
        return [], True
    if not (wish or "").strip():
        return [s[2] for s in _KALENDER[:n]], True
    treffer = [s for s in _KALENDER if _wuensche.passt_slot(s[2], wish)]
    treffer.sort(key=lambda s: _wuensche.slot_datum(s[2]) or date.max)
    if treffer:
        return [s[2] for s in treffer[:n]], True
    rest = list(_KALENDER)
    rest.sort(key=lambda s: _wuensche.slot_datum(s[2]) or date.max)
    von, _bis = _wuensche.fenster(wish)
    if von:
        nach = [s for s in rest if (_wuensche.slot_datum(s[2]) or date.min) >= von]
        if nach:
            rest = nach
    return [s[2] for s in rest[:n]], False


def _slot_texte(n: int, wish: str) -> list[str]:
    """Nur Zeiten, die zum Wunsch passen — nie Montag, wenn Dienstag gesagt wurde."""
    slots, _exakt = _slot_suche(n, wish)
    return slots


def _appt_passt(appt: dict, wish: str, grund: str) -> bool:
    from bianca.controller import wuensche as _w
    if grund:
        g = _w.falt(appt.get("grund") or "")
        such = _w.falt(grund)
        if such not in g and g not in such:
            return False
    if not (wish or "").strip():
        return True
    iso = str(appt.get("iso") or "")
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", iso)
    if not m:
        return True
    d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    teile = _w.teile(wish)
    tage = ("montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag")
    if teile["wochentag"] and tage[d.weekday()] != _w.falt(teile["wochentag"]):
        return False
    von, bis = _w.fenster(wish)
    if von and bis and (d < von or d > bis):
        return False
    return True


def _appt(i: int) -> dict[str, str]:
    daten = [
        {"id": "APPT-1", "iso": "2026-10-02 13:00", "arzt": "Dr. Petsas",
         "grund": "Kontrolle", "calendarId": "cal-petsas"},
        {"id": "APPT-2", "iso": "2026-10-21 10:30", "arzt": "Dr. Patrikis",
         "grund": "Zahnreinigung", "calendarId": "cal-patrikis"},
        {"id": "APPT-3", "iso": "2026-11-05 08:45", "arzt": "Dr. Petsas",
         "grund": "Besprechung", "calendarId": "cal-petsas"},
    ]
    return daten[i % len(daten)]


class ToolGatewaySim:
    """Zustandsbehafteter Simulator (zaehlt Versuche fuer Retry-Pfade)."""

    def __init__(self, szenario: Szenario | None = None) -> None:
        self.sz = szenario or Szenario()
        self._book_versuche = 0
        self._cancelled: set[str] = set()

    # ------------------------------------------------------------------ #
    def ausfuehren(self, cmd: ToolCommand) -> ToolOutcome:
        name = cmd.name
        if name == "offer_slots":
            return self._offer(cmd)
        if name == "book_slot":
            return self._book(cmd)
        if name == "list_appointments":
            return self._list(cmd)
        if name in ("cancel_appointment", "move_appointment"):
            return self._commit_verwalten(name, cmd)
        if name == "praxis_notiz":
            return ToolOutcome(name=name, status=OutcomeStatus.OK, committed=True)
        return ToolOutcome(name=name, status=OutcomeStatus.ERROR)

    # ------------------------------------------------------------------ #
    def _offer(self, cmd: ToolCommand) -> ToolOutcome:
        if self.sz.slots_denied:
            return ToolOutcome(name="offer_slots", status=OutcomeStatus.DENIED)
        wish = str(cmd.args.get("wish") or "")
        slots, exakt = _slot_suche(self.sz.freie_slots, wish)
        if not slots:
            return ToolOutcome(name="offer_slots", status=OutcomeStatus.EMPTY)
        payload: dict = {"slots": slots}
        if not exakt:
            payload["exakt"] = False
            payload["wunsch"] = wish
        return ToolOutcome(
            name="offer_slots", status=OutcomeStatus.OK, payload=payload
        )

    def _book(self, cmd: ToolCommand) -> ToolOutcome:
        self._book_versuche += 1
        modus = self.sz.buchung
        if modus == "needs_phone" and (
            self._book_versuche == 1 or not self.sz._needs_phone_einmal
        ):
            return ToolOutcome(name="book_slot", status=OutcomeStatus.NEEDS_PHONE)
        if modus == "slot_taken" and (
            self._book_versuche == 1 or not self.sz._slot_taken_einmal
        ):
            return ToolOutcome(name="book_slot", status=OutcomeStatus.SLOT_TAKEN)
        if modus == "error":
            return ToolOutcome(name="book_slot", status=OutcomeStatus.ERROR)
        iso = str(cmd.args.get("slot_iso") or "")
        return ToolOutcome(
            name="book_slot", status=OutcomeStatus.OK, committed=True,
            payload={"appointmentId": "NEU-1", "iso": iso},
        )

    def _list(self, cmd: ToolCommand) -> ToolOutcome:
        if not str(cmd.args.get("lastName") or "").strip():
            return ToolOutcome(name="list_appointments", status=OutcomeStatus.ERROR)
        n = self.sz.termine
        if n <= 0:
            return ToolOutcome(name="list_appointments", status=OutcomeStatus.NOT_FOUND)
        person = str(cmd.args.get("fuer_wen") or "").lower()
        start = 0
        if person in ("sohn", "son"):
            start = 2
        elif person in ("tochter", "nachbar", "nachbarin"):
            start = 1
        ohne = {x.strip() for x in str(cmd.args.get("ohne") or "").split(",") if x.strip()}
        ohne |= self._cancelled
        appts = [_appt(start + i) for i in range(max(n, 1))]
        appts = [a for a in appts if a["id"] not in ohne]
        if not appts:
            return ToolOutcome(name="list_appointments", status=OutcomeStatus.NOT_FOUND)
        wish = str(cmd.args.get("wish") or "")
        grund = str(cmd.args.get("grund") or "")
        if wish or grund:
            treffer = [a for a in appts if _appt_passt(a, wish, grund)]
            if treffer:
                return ToolOutcome(
                    name="list_appointments", status=OutcomeStatus.OK,
                    payload={"appointments": treffer[: max(1, n)]},
                )
            return ToolOutcome(
                name="list_appointments", status=OutcomeStatus.OK,
                payload={"appointments": appts[: max(1, n)], "exakt": False, "wunsch": wish or grund},
            )
        return ToolOutcome(
            name="list_appointments", status=OutcomeStatus.OK,
            payload={"appointments": appts[: max(1, n)]},
        )

    def _commit_verwalten(self, name: str, cmd: ToolCommand) -> ToolOutcome:
        if name == "cancel_appointment":
            for aid in str(cmd.args.get("appointmentId") or "").split(","):
                aid = aid.strip()
                if aid:
                    self._cancelled.add(aid)
        return ToolOutcome(name=name, status=OutcomeStatus.OK, committed=True)


__all__ = ["Szenario", "ToolGatewaySim"]
