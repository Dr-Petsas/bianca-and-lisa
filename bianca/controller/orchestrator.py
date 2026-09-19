"""Orchestrator NUR fuers isolierte Test-Dock des Dialogkerns.

Verdrahtet die reinen Bausteine zu einem spielbaren Gespraech, OHNE Telefon,
MAS oder Cloud Function:

    getippter Text
      -> verstehen.deuten(...)           (Text -> SemanticEvent)
      -> reducer.reduce(state, ev, pol)  (reine Entscheidung)
      -> [Naechste.WERKZEUG]?            (Werkzeug-Schleife)
           gateway_sim.ausfuehren(cmd)   (ToolCommand -> ToolOutcome, simuliert)
           -> reducer.reduce(state, oc)  (bis eine Sprech-/Frage-Entscheidung faellt)
      -> renderer.rendern(decision.speak) (SpeakSpec -> deutscher Satz)

Der Orchestrator haelt NUR Sitzungszustand fuer den Test (State, zuletzt
angebotene Slots/Termine, offene Erwartung fuer die NLU). Fuehrt der Kern eine
Aufgabe nicht (``Naechste.UEBERGEBEN``), zeigt das Dock den Uebergabe-Hinweis —
so ist sichtbar, wo der Legacy-Pfad uebernehmen wuerde.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from bianca.controller import renderer, verstehen
from bianca.controller.gateway_sim import Szenario, ToolGatewaySim
from bianca.controller.reducer import reduce
from bianca.controller.typen import (
    Decision,
    Naechste,
    Policy,
    Quelle,
    SemanticEvent,
    SlotValue,
    SprechAkt,
    State,
    replace,
)

_MAX_WERKZEUG_SCHRITTE = 8  # Sicherung gegen eine haengende Werkzeug-Schleife


def _llm_zeile(ev: SemanticEvent) -> str:
    """Kleine Dock-Zeile: freies Verstehen, dann das Roh-JSON."""
    teile = []
    if ev.verstanden:
        teile.append(ev.verstanden)
    if ev.llm and ev.llm != ev.verstanden:
        teile.append(ev.llm)
    if teile:
        return "\n".join(teile)
    slots = {k: v.wert for k, v in ev.slots.items() if v and v.wert}
    teile = [ev.deutung or "?", ev.intent.value]
    if ev.bestaetigung is True:
        teile.append("ja")
    elif ev.bestaetigung is False:
        teile.append("nein")
    if ev.korrektur_feld:
        teile.append("feld=" + ev.korrektur_feld)
    if slots:
        teile.append(str(slots))
    return " ".join(teile) or "— kein LLM-Text —"


@dataclass
class _Erwartung:
    """Was der letzte Zug erfragt hat — steuert die Deutung der Kurzantwort."""

    offene_frage: str = ""
    janein: bool = False
    wahl: bool = False


@dataclass
class Zugantwort:
    """Ergebnis EINES Test-Zugs (fuer Browser/CLI)."""

    antwort: str
    grund: str = ""
    naechste: str = ""
    tool: str = ""
    uebergeben: bool = False
    hangup: bool = False
    llm: str = ""
    debug: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "antwort": self.antwort,
            "grund": self.grund,
            "naechste": self.naechste,
            "tool": self.tool,
            "uebergeben": self.uebergeben,
            "hangup": self.hangup,
            "llm": self.llm,
            "debug": self.debug,
        }


class TestGespraech:
    """Ein spielbares Gespraech gegen den reinen Kern (isoliert, deterministisch)."""

    def __init__(
        self,
        policy: Policy,
        szenario: Szenario | None = None,
        llm: Any = None,
    ) -> None:
        self.policy = policy
        self.llm = llm
        self.state = State()
        self.gateway = ToolGatewaySim(szenario)
        self._erw = _Erwartung()
        self._slots_angebot: list[str] = []
        self._appt_angebot: list[dict[str, Any]] = []
        self.verlauf: list[dict[str, str]] = []
        sz = szenario or Szenario()
        if sz.anrufer_nachname or sz.anrufer_anrede:
            self.state.anrufer = {
                "anrede": sz.anrufer_anrede,
                "nachname": sz.anrufer_nachname,
                "vorname": sz.anrufer_vorname,
            }
            if sz.anrufer_telefon:
                self.state.anrufer["telefon"] = sz.anrufer_telefon
            if sz.anrufer_versicherung:
                self.state.anrufer["versicherung"] = sz.anrufer_versicherung
        if sz.letzter_arzt or sz.letzter_grund or sz.letzter_wann:
            self.state.letzter_besuch = {
                "arzt": sz.letzter_arzt,
                "grund": sz.letzter_grund,
                "wann": sz.letzter_wann,
            }

    def _lage(self) -> dict[str, Any]:
        aktiv = self.state.aktiv()
        slots = {}
        if aktiv is not None:
            slots = {k: v.wert for k, v in aktiv.slots.items() if v and v.wert}
        letzter = self.verlauf[-1]["bianca"] if self.verlauf else ""
        return {
            "offene_frage": self._erw.offene_frage,
            "erwartet_janein": self._erw.janein,
            "erwartet_wahl": self._erw.wahl,
            "task": aktiv.typ if aktiv is not None else "",
            "phase": aktiv.phase.value if aktiv is not None else "",
            "slots": slots,
            "angebot": list(self._slots_angebot),
            "letzter_satz": letzter,
            "termine_n": len(self.state.letzte_termine),
            "letzter_write": self.state.letzter_write(),
        }

    # ------------------------------------------------------------------ #
    def eingabe(self, text: str) -> Zugantwort:
        ev = verstehen.deuten(
            text,
            offene_frage=self._erw.offene_frage,
            erwartet_janein=self._erw.janein,
            erwartet_wahl=self._erw.wahl,
            lage=self._lage(),
            llm=self.llm,
        )
        ev = self._wahl_aufloesen(ev)

        state, decision = reduce(self.state, ev, self.policy)
        state, decision = self._werkzeug_schleife(state, decision)
        self.state = state

        antwort = renderer.rendern(decision.speak)
        antwort = self._uebergabe_text(decision, antwort)
        self._erwartung_setzen(decision)

        self.verlauf.append({"anrufer": text, "bianca": antwort})
        return Zugantwort(
            antwort=antwort,
            grund=decision.grund,
            naechste=decision.naechste.value,
            tool=decision.tool.name if decision.tool else "",
            uebergeben=decision.naechste == Naechste.UEBERGEBEN,
            hangup=bool(decision.hangup),
            llm=_llm_zeile(ev),
            debug=self._debug(ev, decision),
        )

    def start(self) -> str:
        """Begruessung fuers Dock (der Kern reagiert erst auf einen Anrufer-Zug)."""
        return "Guten Tag, hier ist Bianca. Wie kann ich Ihnen helfen?"

    # ------------------------------------------------------------------ #
    def _werkzeug_schleife(
        self, state: State, decision: Decision
    ) -> tuple[State, Decision]:
        schritte = 0
        while decision.naechste == Naechste.WERKZEUG and decision.tool is not None:
            schritte += 1
            if schritte > _MAX_WERKZEUG_SCHRITTE:
                break
            outcome = self.gateway.ausfuehren(decision.tool)
            self._merke_angebot(outcome)
            state, decision = reduce(state, outcome, self.policy)
        return state, decision

    def _merke_angebot(self, outcome: Any) -> None:
        payload = getattr(outcome, "payload", {}) or {}
        if outcome.name == "offer_slots":
            slots = payload.get("slots")
            if isinstance(slots, (list, tuple)):
                self._slots_angebot = [str(s) for s in slots]
        elif outcome.name == "list_appointments":
            appts = payload.get("appointments")
            if isinstance(appts, (list, tuple)):
                self._appt_angebot = [dict(a) for a in appts if isinstance(a, dict)]

    # ------------------------------------------------------------------ #
    def _wahl_aufloesen(self, ev: SemanticEvent) -> SemanticEvent:
        """Ordinalwahl ('der erste') auf den echten Slot/Termin abbilden."""
        tw = ev.slots.get("terminwahl")
        if not tw or not tw.wert:
            return ev

        # Auswahl unter mehreren Bestandsterminen (Familie VERWALTEN).
        if self._erw.offene_frage == "auswahl" and self._appt_angebot:
            if str(tw.wert).strip().lower() in {"alle", "beide"}:
                return ev
            idx = self._ordinal_index(tw.wert, len(self._appt_angebot))
            if idx is None:
                return ev
            appt = self._appt_angebot[idx]
            neu = dict(ev.slots)
            neu.pop("terminwahl", None)
            for slot, *keys in (
                ("gefunden_id", "id", "appointmentId"),
                ("gefunden_iso", "iso", "start"),
                ("gefunden_arzt", "arzt", "calendarName"),
                ("gefunden_grund", "grund", "motivName"),
                ("calendarId", "calendarId"),
            ):
                for k in keys:
                    if appt.get(k):
                        neu[slot] = SlotValue(wert=str(appt[k]), quelle=Quelle.KALENDER)
                        break
            return replace(ev, slots=neu)

        # Slot-Angebot (Familie BUCHEN / Verschieben-neu).
        if self._slots_angebot:
            idx = self._ordinal_index(tw.wert, len(self._slots_angebot))
            if idx is not None:
                neu = dict(ev.slots)
                neu["terminwahl"] = SlotValue(
                    wert=self._slots_angebot[idx], quelle=Quelle.GESAGT
                )
                return replace(ev, slots=neu)
        return ev

    @staticmethod
    def _ordinal_index(wert: str, n: int) -> int | None:
        if n <= 0:
            return None
        w = str(wert).strip()
        if w == "-1":
            return n - 1
        try:
            i = int(w)
        except ValueError:
            return None
        if 1 <= i <= n:
            return i - 1
        return None

    # ------------------------------------------------------------------ #
    def _uebergabe_text(self, decision: Decision, antwort: str) -> str:
        if decision.naechste == Naechste.UEBERGEBEN and not antwort:
            return f"[UEBERGABE an den Legacy-Pfad — Grund: {decision.grund}]"
        return antwort

    def _erwartung_setzen(self, decision: Decision) -> None:
        sp = decision.speak
        # Kein neuer Satz (z. B. 'angebot_offen' -> WARTEN): die vorige
        # Erwartung steht weiter. Sonst verloere die naechste Kurzantwort
        # ('der erste') ihren Wahl-Kontext.
        if sp is None:
            return
        self._erw = _Erwartung()
        if sp.akt == SprechAkt.FRAGE:
            self._erw.offene_frage = sp.frage_id
            if sp.frage_id == "auswahl":
                self._erw.wahl = True
            elif sp.frage_id in (
                "rueckruf_ja", "anmeldung_rueckruf", "schonmal",
                "anrufer_check", "fach_weiter", "arzt_notiz",
                "mehrfach_ok",
            ):
                self._erw.janein = True
        elif sp.akt == SprechAkt.RUECKLESEN:
            self._erw.janein = True
        elif sp.akt == SprechAkt.ANGEBOT:
            self._erw.wahl = True
            self._erw.janein = True

    def _debug(self, ev: SemanticEvent, decision: Decision) -> dict[str, Any]:
        aktiv = self.state.aktiv()
        return {
            "intent": ev.intent.value,
            "event_slots": {k: v.wert for k, v in ev.slots.items()},
            "bestaetigung": ev.bestaetigung,
            "task": decision.task,
            "phase": aktiv.phase.value if aktiv else "",
            "speak_akt": decision.speak.akt.value if decision.speak else "",
            "frage_id": decision.speak.frage_id if decision.speak else "",
            "korrektur_feld": ev.korrektur_feld,
            "deutung": ev.deutung,
            "hirn": self.llm is not None,
            "llm": ev.llm,
            "verstanden": ev.verstanden,
            "wunsch": (aktiv.slots.get("wunschzeit").wert
                       if aktiv and aktiv.slots.get("wunschzeit") else ""),
        }


__all__ = ["TestGespraech", "Zugantwort", "Szenario"]
