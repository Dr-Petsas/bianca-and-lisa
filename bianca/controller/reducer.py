"""Reiner, mandantenAGNOSTISCHER Dialog-Reducer: (State, Event, Policy) -> (State, Decision).

Der Reducer ist die EINZIGE Entscheidungsinstanz des Kerns. Er ist rein: keine
Uhr, kein Zufall, kein Netz, keine globale Variable. Gleicher Eingang ergibt
denselben Ausgang. Er mutiert den uebergebenen ``State`` nie, sondern gibt eine
Kopie zurueck.

Mandantenspezifik ist DATEN, nicht Code: alles Praxis-Abhaengige kommt ueber
``Policy`` herein (Slot-Reihenfolge, Retry-Grenzen, Ruecklese-Politik, Transfer-
Whitelist, Notfall-Regel). Der Reducer verzweigt NIE nach Mandanten-Namen. Ein
Mandanten-Fix aendert nur dessen Policy (siehe ``bianca/controller/policy.py``);
dieser Code und seine Invarianten bleiben unberuehrt.

Task-FAMILIEN (``TaskSpec.familie``) — jede eine kleine Zustandsmaschine, die
sich dieselben Invarianten teilt:

  BUCHEN     sammeln -> offer_slots -> Wahl -> Ruecklese -> book_slot (belegt)
  VERWALTEN  identify -> suchen -> waehlen -> Ruecklese -> (Ja) cancel/move (belegt)
  AUSKUNFT   identify -> suchen -> vorlesen (read-only, terminal)
  VERBINDEN  Policy-Whitelist -> Uebergabe ODER ehrlich "telefonisch nicht"
  DOKUMENT   ehrlich "nicht am Telefon" -> optional Rueckruf
  RUECKRUF   sammeln (Name/Telefon) -> praxis_notiz (belegt) -> terminal
  NOTFALL    Sofortregel (Policy) -> terminal

Strukturell garantierte Invarianten (tests/test_controller_reducer.py):

  I1  Nie eine Frage zu einem bereits gefuellten Pflicht-/Identify-Feld.
  I2  ``SprechAkt.ERFOLG`` nur mit ``committed``-Beleg im Ledger.
  I3  Hoechstens EIN Werkzeug UND hoechstens EINE Frage je Zug (Decision-Form).
  I4  Beschraenkte Retries -> jede Aufgabe erreicht in endlich vielen Zuegen
      einen terminalen Status (erledigt/gescheitert).
  I5  Determinismus/Idempotenz: dasselbe Event auf denselben State wirkt gleich;
      ein bereits gefuelltes Feld erneut zu setzen aendert die Phase nicht.

Fuehrt die Policy eine Aufgabe NICHT (``eigene_tasks``) oder fehlt ihre
``TaskSpec``, gibt der Reducer eine ``UEBERGEBEN``-Entscheidung zurueck (der
Orchestrator reicht sie an den Legacy-Pfad).
"""

from __future__ import annotations

from typing import Any, Mapping

from bianca.controller.typen import (
    Decision,
    Event,
    Familie,
    Intent,
    Naechste,
    OutcomeStatus,
    Phase,
    Policy,
    Quelle,
    SemanticEvent,
    SlotValue,
    SpeakSpec,
    SprechAkt,
    State,
    TaskSpec,
    TaskState,
    TaskStatus,
    ToolCommand,
    ToolOutcome,
    replace,
)

# Task-startende Intents -> Aufgabentyp (mandantenunabhaengig; ob der Kern die
# Aufgabe FUEHRT, entscheidet allein die Policy).
_INTENT_TASK: dict[Intent, str] = {
    Intent.BUCHEN: "buchen",
    Intent.ABSAGEN: "absagen",
    Intent.VERSCHIEBEN: "verschieben",
    Intent.AUSKUNFT: "auskunft",
    Intent.VERBINDEN: "verbinden",
    Intent.DOKUMENT: "dokument",
    Intent.RUECKRUF: "rueckruf",
}


# --------------------------------------------------------------------------- #
# Kleine, reine Helfer.
# --------------------------------------------------------------------------- #
def _merge_slots(task: TaskState, ev: SemanticEvent) -> None:
    """Neue Fakten uebernehmen. Idempotent: gleicher Wert aendert nichts."""
    for name, sv in ev.slots.items():
        if not isinstance(sv, SlotValue) or not sv.wert:
            continue
        alt = task.slots.get(name)
        if alt and alt.wert == sv.wert:
            if sv.bestaetigt and not alt.bestaetigt:
                task.slots[name] = sv
            continue
        task.slots[name] = sv


def _sammel_slots(spec: TaskSpec) -> tuple[str, ...]:
    """Welche Slots sind vor der ersten Werkzeugaktion zu sammeln?"""
    if spec.familie in (Familie.VERWALTEN, Familie.AUSKUNFT):
        return spec.identify
    return spec.pflicht


def _erste_luecke(task: TaskState, spec: TaskSpec) -> str:
    """Erstes unbefuelltes ODER unbestaetigtes (bei Ruecklese-Pflicht) Sammelfeld."""
    for slot in _sammel_slots(spec):
        if not task.gefuellt(slot):
            return slot
        if slot in spec.ruecklese_slots and not task.bestaetigt(slot):
            return slot
    return ""


def _ruecklese_check(task: TaskState, ev: SemanticEvent, spec: TaskSpec) -> str | None:
    """Ja/Nein auf eine offene Ruecklese in der Sammelphase verarbeiten.

    Rueckgabe: Slot-Name, wenn die Ruecklese verneint wurde (neu erfragen);
    sonst ``None`` (bestaetigt oder gar keine Ruecklese offen).
    """
    slot = task.zuletzt_gefragt
    if slot in spec.ruecklese_slots and task.gefuellt(slot) and not task.bestaetigt(slot):
        if ev.bestaetigung is True:
            task.slots[slot] = replace(task.slots[slot], bestaetigt=True)
            return None
        if ev.bestaetigung is False:
            task.slots.pop(slot, None)
            return slot
    return None


def _frage(ns: State, task: TaskState, slot: str, grund: str) -> tuple[State, Decision]:
    task.zuletzt_gefragt = slot
    return ns, Decision(
        naechste=Naechste.FRAGEN,
        speak=SpeakSpec(akt=SprechAkt.FRAGE, frage_id=slot),
        task=task.typ,
        grund=grund,
    )


def _ruecklesen(ns: State, task: TaskState, slot: str, grund: str) -> tuple[State, Decision]:
    task.zuletzt_gefragt = slot
    return ns, Decision(
        naechste=Naechste.SPRECHEN,
        speak=SpeakSpec(akt=SprechAkt.RUECKLESEN, fakten=_fakten(task, slot)),
        task=task.typ,
        grund=grund,
    )


def _fakten(task: TaskState, *slots: str) -> tuple[tuple[str, str], ...]:
    out: list[tuple[str, str]] = []
    for s in slots:
        v = task.slots.get(s)
        if v and v.wert:
            out.append((s, v.wert))
    return tuple(out)


def _bindings(task: TaskState) -> dict[str, str]:
    b: dict[str, str] = {}
    cal = task.slots.get("calendarId")
    mot = task.slots.get("motivId")
    if cal and cal.wert:
        b["calendarId"] = cal.wert
    if mot and mot.wert:
        b["visitMotiveId"] = mot.wert
    return b


def _offer_args(task: TaskState) -> dict[str, str]:
    w = task.slots.get("wunschzeit")
    return {"wish": w.wert} if (w and w.wert) else {}


def _such_args(task: TaskState) -> dict[str, str]:
    a: dict[str, str] = {}
    nn = task.slots.get("nachname")
    vn = task.slots.get("vorname")
    if nn and nn.wert:
        a["lastName"] = nn.wert
    if vn and vn.wert:
        a["firstName"] = vn.wert
    return a


def _set_gefunden(task: TaskState, appt: Mapping[str, Any]) -> None:
    """Belegte Termin-Fakten (Quelle KALENDER) aus einer Suchantwort in Slots legen."""
    def put(name: str, *keys: str) -> None:
        for k in keys:
            val = appt.get(k)
            if val:
                task.slots[name] = SlotValue(wert=str(val), quelle=Quelle.KALENDER)
                return
    put("gefunden_id", "id", "appointmentId")
    put("gefunden_iso", "iso", "start", "startIso")
    put("gefunden_arzt", "arzt", "calendarName", "behandler")
    put("gefunden_grund", "grund", "motivName", "besuchsgrund")
    put("calendarId", "calendarId", "kalenderId")


def _appt_kurz(appt: Mapping[str, Any]) -> str:
    iso = appt.get("iso") or appt.get("start") or appt.get("startIso") or ""
    arzt = appt.get("arzt") or appt.get("calendarName") or ""
    return " ".join(str(x) for x in (iso, arzt) if x).strip() or str(appt.get("id") or "")


def _neuer_task(ns: State, typ: str) -> TaskState:
    t = TaskState(typ=typ)
    ns.tasks.append(t)
    return t


def _terminal_task(
    ns: State,
    task: TaskState,
    status: TaskStatus,
    speak: SpeakSpec,
    *,
    grund: str,
    hangup: bool = False,
) -> tuple[State, Decision]:
    task.status = status
    task.phase = Phase.ABGESCHLOSSEN
    if hangup:
        ns.terminal = True
    naechste = Naechste.AUFLEGEN if hangup else Naechste.SPRECHEN
    return ns, Decision(naechste=naechste, speak=speak, task=task.typ, hangup=hangup, grund=grund)


def _uebergeben(ns: State, typ: str, grund: str) -> tuple[State, Decision]:
    return ns, Decision(naechste=Naechste.UEBERGEBEN, task=typ, grund=grund)


# --------------------------------------------------------------------------- #
# Einstieg.
# --------------------------------------------------------------------------- #
def reduce(state: State, event: Event, policy: Policy) -> tuple[State, Decision]:
    """Reine Zustandsfortschreibung. Gibt IMMER eine neue State-Kopie zurueck."""
    ns = state.kopie()
    ns.zug_nr += 1
    if ns.terminal:
        return ns, Decision(naechste=Naechste.WARTEN, grund="terminal")
    if isinstance(event, ToolOutcome):
        return _reduce_outcome(ns, event, policy)
    if isinstance(event, SemanticEvent):
        return _reduce_event(ns, event, policy)
    return ns, Decision(naechste=Naechste.WARTEN, grund="unbekanntes_event")


# --------------------------------------------------------------------------- #
# Anrufer-Zug.
# --------------------------------------------------------------------------- #
def _reduce_event(ns: State, ev: SemanticEvent, policy: Policy) -> tuple[State, Decision]:
    # Globale Sofortregeln.
    if ev.intent == Intent.NOTFALL:
        if not policy.notfall_sofort:
            return _uebergeben(ns, "notfall", grund="notfall_ohne_regel")
        active = ns.aktiv() or _neuer_task(ns, "notfall")
        return _terminal_task(
            ns, active, TaskStatus.ERLEDIGT,
            SpeakSpec(akt=SprechAkt.NOTFALL),
            grund="notfall_sofort", hangup=True,
        )
    if ev.intent == Intent.ABSCHIED:
        active = ns.aktiv() or _neuer_task(ns, "abschied")
        return _terminal_task(
            ns, active, TaskStatus.ERLEDIGT,
            SpeakSpec(akt=SprechAkt.ABSCHIED),
            grund="abschied", hangup=True,
        )

    active = ns.aktiv()

    # Aufgabenstart / -wechsel.
    if ev.intent in _INTENT_TASK:
        ziel = _INTENT_TASK[ev.intent]
        if active is None or ziel != active.typ:
            if active is not None:
                active.status = TaskStatus.GEPARKT
            active = _neuer_task(ns, ziel)
            if not policy.fuehrt(ziel) or policy.spec(ziel) is None:
                return _uebergeben(ns, ziel, grund=f"task_nicht_im_kern:{ziel}")

    if active is None:
        return _uebergeben(ns, "", grund=f"kein_task:{ev.intent.value}")

    spec = policy.spec(active.typ)
    if spec is None or not policy.fuehrt(active.typ):
        return _uebergeben(ns, active.typ, grund=f"task_nicht_im_kern:{active.typ}")

    # Korrektur (W-EINWAND): bestrittenes Feld leeren, gezielt neu fragen.
    if ev.intent == Intent.KORREKTUR and ev.korrektur_feld:
        feld = ev.korrektur_feld
        active.slots.pop(feld, None)
        _merge_slots(active, ev)  # Wert aus derselben Aeusserung darf sofort greifen.
        if active.phase in {Phase.ANGEBOT, Phase.BESTAETIGEN} and feld in _sammel_slots(spec):
            active.phase = Phase.SAMMELN
            active.merker.clear()
        if not active.gefuellt(feld) or (
            feld in spec.ruecklese_slots and not active.bestaetigt(feld)
        ):
            return _frage(ns, active, feld, grund=f"korrektur:{feld}")

    _merge_slots(active, ev)

    fam = spec.familie
    if fam == Familie.BUCHEN:
        return _adv_buchen(ns, active, ev, spec)
    if fam == Familie.VERWALTEN:
        return _adv_verwalten(ns, active, ev, spec)
    if fam == Familie.AUSKUNFT:
        return _adv_auskunft(ns, active, ev, spec)
    if fam == Familie.VERBINDEN:
        return _adv_verbinden(ns, active, ev, spec, policy)
    if fam == Familie.DOKUMENT:
        return _adv_dokument(ns, active, ev, spec, policy)
    if fam == Familie.RUECKRUF:
        return _adv_rueckruf(ns, active, ev, spec)
    return _uebergeben(ns, active.typ, grund=f"familie_unbekannt:{fam.value}")


# --------------------------------------------------------------------------- #
# Familie BUCHEN.
# --------------------------------------------------------------------------- #
def _adv_buchen(ns: State, task: TaskState, ev: SemanticEvent, spec: TaskSpec) -> tuple[State, Decision]:
    if task.phase == Phase.SAMMELN:
        wieder = _ruecklese_check(task, ev, spec)
        if wieder is not None:
            return _frage(ns, task, wieder, grund="ruecklese_nein")
        luecke = _erste_luecke(task, spec)
        if luecke:
            if luecke in spec.ruecklese_slots and task.gefuellt(luecke) and not task.bestaetigt(luecke):
                return _ruecklesen(ns, task, luecke, grund=f"ruecklese_pflicht:{luecke}")
            return _frage(ns, task, luecke, grund="pflicht_sammeln")
        task.phase = Phase.ANGEBOT
        task.merker.clear()
        return ns, Decision(
            naechste=Naechste.WERKZEUG,
            tool=ToolCommand(name=spec.offer_tool, args=_offer_args(task), bindings=_bindings(task)),
            task=task.typ,
            grund="slots_vollstaendig",
        )

    if task.phase == Phase.ANGEBOT:
        wahl = task.slots.get("terminwahl")
        if wahl and wahl.wert:
            task.phase = Phase.BESTAETIGEN
            task.merker["termin_gelesen"] = True
            return ns, Decision(
                naechste=Naechste.SPRECHEN,
                speak=SpeakSpec(
                    akt=SprechAkt.RUECKLESEN,
                    fakten=_fakten(task, "terminwahl", "behandler", "besuchsgrund"),
                ),
                task=task.typ,
                grund="ruecklese_termin",
            )
        return ns, Decision(naechste=Naechste.WARTEN, task=task.typ, grund="angebot_offen")

    if task.phase == Phase.BESTAETIGEN:
        return _bestaetigen_buchen(ns, task, ev, spec)

    return ns, Decision(naechste=Naechste.WARTEN, task=task.typ, grund="phase_ohne_zug")


def _bestaetigen_buchen(
    ns: State, task: TaskState, ev: SemanticEvent, spec: TaskSpec
) -> tuple[State, Decision]:
    # Telefon-Etappe (W-TELEFON-ZULETZT): erst nach Ja zum Termin.
    if task.zuletzt_gefragt == spec.telefon_slot:
        tel = task.slots.get(spec.telefon_slot)
        if tel and tel.wert and not tel.bestaetigt:
            if ev.bestaetigung is True:
                task.slots[spec.telefon_slot] = replace(tel, bestaetigt=True)
                return _commit_werkzeug(ns, task, spec, grund="telefon_bestaetigt")
            if ev.bestaetigung is False:
                task.slots.pop(spec.telefon_slot, None)
                return _frage(ns, task, spec.telefon_slot, grund="telefon_neu")
            return _ruecklesen(ns, task, spec.telefon_slot, grund="ruecklese_telefon")
        if tel and tel.bestaetigt:
            return _commit_werkzeug(ns, task, spec, grund="telefon_bestaetigt")
        return _frage(ns, task, spec.telefon_slot, grund="telefon_fehlt")

    if ev.bestaetigung is True:
        if not task.bestaetigt(spec.telefon_slot):
            return _frage(ns, task, spec.telefon_slot, grund="telefon_zuletzt")
        return _commit_werkzeug(ns, task, spec, grund="bestaetigt")

    if ev.bestaetigung is False:
        task.phase = Phase.ANGEBOT
        task.slots.pop("terminwahl", None)
        task.merker.pop("termin_gelesen", None)
        return _frage(ns, task, "aenderung", grund="ruecklese_nein")

    return ns, Decision(naechste=Naechste.WARTEN, task=task.typ, grund="bestaetigen_offen")


def _commit_werkzeug(
    ns: State, task: TaskState, spec: TaskSpec, *, grund: str
) -> tuple[State, Decision]:
    args: dict[str, str] = {}
    wahl = task.slots.get("terminwahl")
    if wahl and wahl.wert:
        args["slot_iso"] = wahl.wert
    return ns, Decision(
        naechste=Naechste.WERKZEUG,
        tool=ToolCommand(name=spec.commit_tool, args=args, bindings=_bindings(task)),
        task=task.typ,
        grund=grund,
    )


# --------------------------------------------------------------------------- #
# Familie VERWALTEN (absagen + verschieben).
# --------------------------------------------------------------------------- #
def _adv_verwalten(ns: State, task: TaskState, ev: SemanticEvent, spec: TaskSpec) -> tuple[State, Decision]:
    if task.phase == Phase.SAMMELN:
        wieder = _ruecklese_check(task, ev, spec)
        if wieder is not None:
            return _frage(ns, task, wieder, grund="ruecklese_nein")
        luecke = _erste_luecke(task, spec)
        if luecke:
            if luecke in spec.ruecklese_slots and task.gefuellt(luecke) and not task.bestaetigt(luecke):
                return _ruecklesen(ns, task, luecke, grund=f"ruecklese_pflicht:{luecke}")
            return _frage(ns, task, luecke, grund="identify_sammeln")
        task.phase = Phase.ANGEBOT
        task.merker["gesucht"] = True
        return ns, Decision(
            naechste=Naechste.WERKZEUG,
            tool=ToolCommand(name=spec.such_tool, args=_such_args(task), bindings=_bindings(task)),
            task=task.typ,
            grund="identify_vollstaendig",
        )

    if task.phase == Phase.ANGEBOT:
        # Auswahl unter mehreren Treffern: der Anrufer-Zug hat gefunden_id gesetzt.
        if task.gefuellt("gefunden_id") and not task.merker.get("bestand_gelesen"):
            task.merker["bestand_gelesen"] = True
            task.phase = Phase.BESTAETIGEN
            return ns, Decision(
                naechste=Naechste.SPRECHEN,
                speak=SpeakSpec(
                    akt=SprechAkt.RUECKLESEN,
                    fakten=_fakten(task, "gefunden_iso", "gefunden_arzt", "gefunden_grund"),
                ),
                task=task.typ,
                grund="ruecklese_bestand",
            )
        return ns, Decision(naechste=Naechste.WARTEN, task=task.typ, grund="suche_offen")

    if task.phase == Phase.BESTAETIGEN:
        return _bestaetigen_verwalten(ns, task, ev, spec)

    return ns, Decision(naechste=Naechste.WARTEN, task=task.typ, grund="phase_ohne_zug")


def _bestaetigen_verwalten(
    ns: State, task: TaskState, ev: SemanticEvent, spec: TaskSpec
) -> tuple[State, Decision]:
    if not spec.neue_zeit:
        # ABSAGEN: destruktive Bestaetigung.
        if ev.bestaetigung is True:
            return ns, Decision(
                naechste=Naechste.WERKZEUG,
                tool=ToolCommand(name=spec.commit_tool, args=_storno_args(task), bindings=_bindings(task)),
                task=task.typ,
                grund="storno_bestaetigt",
            )
        if ev.bestaetigung is False:
            return _terminal_task(
                ns, task, TaskStatus.ERLEDIGT,
                SpeakSpec(akt=SprechAkt.ABSCHIED, detail="nichts_geaendert"),
                grund="storno_abgelehnt",
            )
        return ns, Decision(naechste=Naechste.WARTEN, task=task.typ, grund="storno_offen")

    # VERSCHIEBEN: erst Bestand bestaetigen, dann neuen Slot, dann move.
    if not task.merker.get("bestand_bestaetigt"):
        if ev.bestaetigung is True:
            task.merker["bestand_bestaetigt"] = True
            return ns, Decision(
                naechste=Naechste.WERKZEUG,
                tool=ToolCommand(name=spec.offer_tool, args=_offer_args(task), bindings=_bindings(task)),
                task=task.typ,
                grund="verschieben_neue_slots",
            )
        if ev.bestaetigung is False:
            return _terminal_task(
                ns, task, TaskStatus.ERLEDIGT,
                SpeakSpec(akt=SprechAkt.ABSCHIED, detail="nichts_geaendert"),
                grund="verschieben_abgelehnt",
            )
        return ns, Decision(naechste=Naechste.WARTEN, task=task.typ, grund="verschieben_bestand_offen")

    if not task.merker.get("neu_gelesen"):
        wahl = task.slots.get("terminwahl")
        if wahl and wahl.wert:
            task.merker["neu_gelesen"] = True
            return ns, Decision(
                naechste=Naechste.SPRECHEN,
                speak=SpeakSpec(akt=SprechAkt.RUECKLESEN, fakten=_fakten(task, "terminwahl")),
                task=task.typ,
                grund="ruecklese_neu_termin",
            )
        return ns, Decision(naechste=Naechste.WARTEN, task=task.typ, grund="verschieben_neu_offen")

    if ev.bestaetigung is True:
        return ns, Decision(
            naechste=Naechste.WERKZEUG,
            tool=ToolCommand(name=spec.commit_tool, args=_move_args(task), bindings=_bindings(task)),
            task=task.typ,
            grund="verschieben_bestaetigt",
        )
    if ev.bestaetigung is False:
        task.merker.pop("neu_gelesen", None)
        task.slots.pop("terminwahl", None)
        task.retries["neu_offer"] = task.retries.get("neu_offer", 0) + 1
        if task.retries["neu_offer"] <= spec.max_commit_retries:
            return ns, Decision(
                naechste=Naechste.WERKZEUG,
                tool=ToolCommand(name=spec.offer_tool, args=_offer_args(task), bindings=_bindings(task)),
                task=task.typ,
                grund="verschieben_neu_wieder",
            )
        return _terminal_task(
            ns, task, TaskStatus.GESCHEITERT,
            SpeakSpec(akt=SprechAkt.RUECKRUF),
            grund="verschieben_unentschlossen",
        )
    return ns, Decision(naechste=Naechste.WARTEN, task=task.typ, grund="verschieben_neu_bestaetigen_offen")


def _storno_args(task: TaskState) -> dict[str, str]:
    a: dict[str, str] = {}
    gid = task.slots.get("gefunden_id")
    if gid and gid.wert:
        a["appointmentId"] = gid.wert
    return a


def _move_args(task: TaskState) -> dict[str, str]:
    a = _storno_args(task)
    wahl = task.slots.get("terminwahl")
    if wahl and wahl.wert:
        a["slot_iso"] = wahl.wert
    return a


# --------------------------------------------------------------------------- #
# Familie AUSKUNFT (read-only Terminauskunft).
# --------------------------------------------------------------------------- #
def _adv_auskunft(ns: State, task: TaskState, ev: SemanticEvent, spec: TaskSpec) -> tuple[State, Decision]:
    if task.phase == Phase.SAMMELN:
        wieder = _ruecklese_check(task, ev, spec)
        if wieder is not None:
            return _frage(ns, task, wieder, grund="ruecklese_nein")
        luecke = _erste_luecke(task, spec)
        if luecke:
            if luecke in spec.ruecklese_slots and task.gefuellt(luecke) and not task.bestaetigt(luecke):
                return _ruecklesen(ns, task, luecke, grund=f"ruecklese_pflicht:{luecke}")
            return _frage(ns, task, luecke, grund="identify_sammeln")
        task.phase = Phase.ANGEBOT
        return ns, Decision(
            naechste=Naechste.WERKZEUG,
            tool=ToolCommand(name=spec.such_tool, args=_such_args(task), bindings=_bindings(task)),
            task=task.typ,
            grund="identify_vollstaendig",
        )
    return ns, Decision(naechste=Naechste.WARTEN, task=task.typ, grund="auskunft_offen")


# --------------------------------------------------------------------------- #
# Familie VERBINDEN (Weiterleitung).
# --------------------------------------------------------------------------- #
def _adv_verbinden(
    ns: State, task: TaskState, ev: SemanticEvent, spec: TaskSpec, policy: Policy
) -> tuple[State, Decision]:
    wunsch = ""
    z = task.slots.get("ziel")
    if z and z.wert:
        wunsch = z.wert
    elif ev.roh:
        wunsch = ev.roh  # nur zum Whitelist-Abgleich, nie als Fakt gespeichert
    ziel = policy.transfer_ziel(wunsch)
    if ziel:
        task.status = TaskStatus.ERLEDIGT
        task.phase = Phase.ABGESCHLOSSEN
        ns.terminal = True
        return ns, Decision(
            naechste=Naechste.UEBERGEBEN,
            speak=SpeakSpec(akt=SprechAkt.UEBERGEBEN, fakten=(("ziel", ziel),), detail=ziel),
            task=task.typ,
            grund="transfer_erlaubt",
        )
    if not policy.transfer_erlaubt:
        return _terminal_task(
            ns, task, TaskStatus.ERLEDIGT,
            SpeakSpec(akt=SprechAkt.EHRLICH_KEIN, detail="kein_transfer"),
            grund="transfer_gesperrt",
        )
    if task.zuletzt_gefragt == "ziel":
        return _terminal_task(
            ns, task, TaskStatus.ERLEDIGT,
            SpeakSpec(akt=SprechAkt.EHRLICH_KEIN, detail="kein_transfer"),
            grund="transfer_ziel_unklar",
        )
    return _frage(ns, task, "ziel", grund="transfer_zu_wem")


# --------------------------------------------------------------------------- #
# Familie DOKUMENT (Rezept/Ueberweisung/Krankmeldung).
# --------------------------------------------------------------------------- #
def _adv_dokument(
    ns: State, task: TaskState, ev: SemanticEvent, spec: TaskSpec, policy: Policy
) -> tuple[State, Decision]:
    if not task.merker.get("erklaert"):
        task.merker["erklaert"] = True
        task.phase = Phase.BESTAETIGEN
        task.zuletzt_gefragt = "rueckruf_ja"
        return ns, Decision(
            naechste=Naechste.FRAGEN,
            speak=SpeakSpec(akt=SprechAkt.FRAGE, frage_id="rueckruf_ja", detail="dokument"),
            task=task.typ,
            grund="dokument_erklaert",
        )
    if ev.bestaetigung is True:
        task.status = TaskStatus.ERLEDIGT
        task.phase = Phase.ABGESCHLOSSEN
        rspec = policy.spec("rueckruf")
        if policy.fuehrt("rueckruf") and rspec is not None:
            rt = _neuer_task(ns, "rueckruf")
            nn = task.slots.get("nachname")
            if nn and nn.wert:
                rt.slots["nachname"] = nn
            return _adv_rueckruf(ns, rt, SemanticEvent(intent=Intent.RUECKRUF), rspec)
        return _uebergeben(ns, "rueckruf", grund="rueckruf_nicht_im_kern")
    if ev.bestaetigung is False:
        return _terminal_task(
            ns, task, TaskStatus.ERLEDIGT,
            SpeakSpec(akt=SprechAkt.ABSCHIED, detail="dokument_persoenlich"),
            grund="dokument_abgelehnt",
        )
    return ns, Decision(naechste=Naechste.WARTEN, task=task.typ, grund="dokument_offen")


# --------------------------------------------------------------------------- #
# Familie RUECKRUF (Notiz mit Name/Telefon).
# --------------------------------------------------------------------------- #
def _adv_rueckruf(ns: State, task: TaskState, ev: SemanticEvent, spec: TaskSpec) -> tuple[State, Decision]:
    if task.phase == Phase.SAMMELN:
        wieder = _ruecklese_check(task, ev, spec)
        if wieder is not None:
            return _frage(ns, task, wieder, grund="ruecklese_nein")
        luecke = _erste_luecke(task, spec)
        if luecke:
            if luecke in spec.ruecklese_slots and task.gefuellt(luecke) and not task.bestaetigt(luecke):
                return _ruecklesen(ns, task, luecke, grund=f"ruecklese_pflicht:{luecke}")
            return _frage(ns, task, luecke, grund="rueckruf_sammeln")
        task.phase = Phase.ANGEBOT
        args: dict[str, str] = {}
        nn = task.slots.get("nachname")
        tel = task.slots.get(spec.telefon_slot)
        if nn and nn.wert:
            args["name"] = nn.wert
        if tel and tel.wert:
            args["phone"] = tel.wert
        return ns, Decision(
            naechste=Naechste.WERKZEUG,
            tool=ToolCommand(name=spec.notiz_tool, args=args),
            task=task.typ,
            grund="rueckruf_notiz",
        )
    return ns, Decision(naechste=Naechste.WARTEN, task=task.typ, grund="rueckruf_offen")


# --------------------------------------------------------------------------- #
# Werkzeug-Ergebnis.
# --------------------------------------------------------------------------- #
def _reduce_outcome(ns: State, oc: ToolOutcome, policy: Policy) -> tuple[State, Decision]:
    ns.ledger.append(oc)
    task = ns.aktiv()
    if task is None:
        return ns, Decision(naechste=Naechste.WARTEN, grund="outcome_ohne_task")
    spec = policy.spec(task.typ)
    if spec is None or not policy.fuehrt(task.typ):
        return ns, Decision(naechste=Naechste.WARTEN, task=task.typ, grund="outcome_fremd")

    fam = spec.familie
    if fam == Familie.BUCHEN:
        if oc.name == spec.offer_tool:
            return _oc_offer(ns, task, oc)
        if oc.name == spec.commit_tool:
            return _oc_commit_buchen(ns, task, oc, spec)
    elif fam == Familie.VERWALTEN:
        if oc.name == spec.such_tool:
            return _oc_such(ns, task, oc, spec)
        if oc.name == spec.offer_tool:
            return _oc_offer_neu(ns, task, oc, spec)
        if oc.name == spec.commit_tool:
            return _oc_commit_verwalten(ns, task, oc, spec)
    elif fam == Familie.AUSKUNFT:
        if oc.name == spec.such_tool:
            return _oc_such_auskunft(ns, task, oc, spec)
    elif fam == Familie.RUECKRUF:
        if oc.name == spec.notiz_tool:
            return _oc_notiz(ns, task, oc)
    return ns, Decision(naechste=Naechste.WARTEN, task=task.typ, grund=f"outcome_ignoriert:{oc.name}")


def _payload_liste(oc: ToolOutcome, schluessel: str) -> list[Any]:
    val = oc.payload.get(schluessel) if isinstance(oc.payload, dict) else None
    return list(val) if isinstance(val, (list, tuple)) else []


def _oc_offer(ns: State, task: TaskState, oc: ToolOutcome) -> tuple[State, Decision]:
    slots = _payload_liste(oc, "slots")
    if oc.status == OutcomeStatus.OK and slots:
        task.phase = Phase.ANGEBOT
        fakten = tuple(("slot", str(s)) for s in slots[:3])
        return ns, Decision(
            naechste=Naechste.SPRECHEN,
            speak=SpeakSpec(akt=SprechAkt.ANGEBOT, fakten=fakten),
            task=task.typ,
            grund="angebot",
        )
    if oc.status == OutcomeStatus.DENIED:
        return _terminal_task(
            ns, task, TaskStatus.GESCHEITERT,
            SpeakSpec(akt=SprechAkt.EHRLICH_KEIN),
            grund="nicht_telefonisch",
        )
    return _terminal_task(
        ns, task, TaskStatus.GESCHEITERT,
        SpeakSpec(akt=SprechAkt.RUECKRUF),
        grund=f"keine_slots:{oc.status.value}",
    )


def _oc_commit_buchen(
    ns: State, task: TaskState, oc: ToolOutcome, spec: TaskSpec
) -> tuple[State, Decision]:
    if oc.committed:
        return _terminal_task(
            ns, task, TaskStatus.ERLEDIGT,
            SpeakSpec(akt=SprechAkt.ERFOLG, fakten=_erfolg_fakten(task, oc)),
            grund="gebucht_belegt",
        )

    if oc.status == OutcomeStatus.SLOT_TAKEN:
        task.retries["commit"] = task.retries.get("commit", 0) + 1
        if task.retries["commit"] <= spec.max_commit_retries:
            task.phase = Phase.ANGEBOT
            task.slots.pop("terminwahl", None)
            task.merker.pop("termin_gelesen", None)
            return ns, Decision(
                naechste=Naechste.WERKZEUG,
                tool=ToolCommand(name=spec.offer_tool, args=_offer_args(task), bindings=_bindings(task)),
                task=task.typ,
                grund="slot_weg_neu_suchen",
            )
        return _terminal_task(
            ns, task, TaskStatus.GESCHEITERT,
            SpeakSpec(akt=SprechAkt.RUECKRUF),
            grund="slot_wiederholt_weg",
        )

    if oc.status == OutcomeStatus.NEEDS_PHONE:
        if task.bestaetigt(spec.telefon_slot):
            task.retries["phone"] = task.retries.get("phone", 0) + 1
            if task.retries["phone"] <= spec.max_phone_retries:
                return _commit_werkzeug(ns, task, spec, grund="needs_phone_retry")
            return _terminal_task(
                ns, task, TaskStatus.GESCHEITERT,
                SpeakSpec(akt=SprechAkt.RUECKRUF),
                grund="needs_phone_wiederholt",
            )
        task.phase = Phase.BESTAETIGEN
        return _frage(ns, task, spec.telefon_slot, grund="needs_phone_frage")

    return _terminal_task(
        ns, task, TaskStatus.GESCHEITERT,
        SpeakSpec(akt=SprechAkt.RUECKRUF),
        grund=f"buchung_fehler:{oc.status.value}",
    )


def _oc_such(ns: State, task: TaskState, oc: ToolOutcome, spec: TaskSpec) -> tuple[State, Decision]:
    if oc.status == OutcomeStatus.OK:
        appts = _payload_liste(oc, "appointments")
        if len(appts) == 1:
            _set_gefunden(task, appts[0])
            task.merker["bestand_gelesen"] = True
            task.phase = Phase.BESTAETIGEN
            return ns, Decision(
                naechste=Naechste.SPRECHEN,
                speak=SpeakSpec(
                    akt=SprechAkt.RUECKLESEN,
                    fakten=_fakten(task, "gefunden_iso", "gefunden_arzt", "gefunden_grund"),
                ),
                task=task.typ,
                grund="einzel_termin",
            )
        if len(appts) > 1:
            task.merker["mehrere"] = True
            task.phase = Phase.ANGEBOT
            fakten = tuple(("option", _appt_kurz(a)) for a in appts[:3])
            task.zuletzt_gefragt = "auswahl"
            return ns, Decision(
                naechste=Naechste.FRAGEN,
                speak=SpeakSpec(akt=SprechAkt.FRAGE, frage_id="auswahl", fakten=fakten),
                task=task.typ,
                grund="mehrere_termine",
            )
        return _such_not_found(ns, task, spec)
    if oc.status == OutcomeStatus.AMBIGUOUS:
        if not task.gefuellt("vorname"):
            task.phase = Phase.SAMMELN
            return _frage(ns, task, "vorname", grund="mehrere_patienten")
        return _such_not_found(ns, task, spec)
    if oc.status == OutcomeStatus.NOT_FOUND:
        return _such_not_found(ns, task, spec)
    return _terminal_task(
        ns, task, TaskStatus.GESCHEITERT,
        SpeakSpec(akt=SprechAkt.RUECKRUF),
        grund=f"such_fehler:{oc.status.value}",
    )


def _such_not_found(ns: State, task: TaskState, spec: TaskSpec) -> tuple[State, Decision]:
    task.retries["such"] = task.retries.get("such", 0) + 1
    if task.retries["such"] <= spec.max_such_retries:
        task.phase = Phase.SAMMELN
        task.slots.pop("nachname", None)
        return _frage(ns, task, "nachname", grund="nicht_gefunden_korrektur")
    return _terminal_task(
        ns, task, TaskStatus.GESCHEITERT,
        SpeakSpec(akt=SprechAkt.RUECKRUF),
        grund="nicht_gefunden",
    )


def _oc_offer_neu(ns: State, task: TaskState, oc: ToolOutcome, spec: TaskSpec) -> tuple[State, Decision]:
    slots = _payload_liste(oc, "slots")
    if oc.status == OutcomeStatus.OK and slots:
        return ns, Decision(
            naechste=Naechste.SPRECHEN,
            speak=SpeakSpec(akt=SprechAkt.ANGEBOT, fakten=tuple(("slot", str(s)) for s in slots[:3])),
            task=task.typ,
            grund="neue_slots",
        )
    if oc.status == OutcomeStatus.DENIED:
        return _terminal_task(
            ns, task, TaskStatus.GESCHEITERT,
            SpeakSpec(akt=SprechAkt.EHRLICH_KEIN),
            grund="nicht_telefonisch",
        )
    return _terminal_task(
        ns, task, TaskStatus.GESCHEITERT,
        SpeakSpec(akt=SprechAkt.RUECKRUF),
        grund=f"keine_neuen_slots:{oc.status.value}",
    )


def _oc_commit_verwalten(
    ns: State, task: TaskState, oc: ToolOutcome, spec: TaskSpec
) -> tuple[State, Decision]:
    if oc.committed:
        fakten = _fakten(task, "terminwahl") if spec.neue_zeit else _fakten(task, "gefunden_iso")
        return _terminal_task(
            ns, task, TaskStatus.ERLEDIGT,
            SpeakSpec(akt=SprechAkt.ERFOLG, fakten=fakten),
            grund="verwaltung_belegt",
        )
    if oc.status == OutcomeStatus.SLOT_TAKEN and spec.neue_zeit:
        task.retries["commit"] = task.retries.get("commit", 0) + 1
        if task.retries["commit"] <= spec.max_commit_retries:
            task.merker.pop("neu_gelesen", None)
            task.slots.pop("terminwahl", None)
            return ns, Decision(
                naechste=Naechste.WERKZEUG,
                tool=ToolCommand(name=spec.offer_tool, args=_offer_args(task), bindings=_bindings(task)),
                task=task.typ,
                grund="verschieben_slot_weg",
            )
    return _terminal_task(
        ns, task, TaskStatus.GESCHEITERT,
        SpeakSpec(akt=SprechAkt.RUECKRUF),
        grund=f"verwaltung_fehler:{oc.status.value}",
    )


def _oc_such_auskunft(
    ns: State, task: TaskState, oc: ToolOutcome, spec: TaskSpec
) -> tuple[State, Decision]:
    if oc.status == OutcomeStatus.OK:
        appts = _payload_liste(oc, "appointments")
        if appts:
            fakten = tuple(("termin", _appt_kurz(a)) for a in appts[:3])
            return _terminal_task(
                ns, task, TaskStatus.ERLEDIGT,
                SpeakSpec(akt=SprechAkt.INFO, fakten=fakten),
                grund="auskunft",
            )
        return _terminal_task(
            ns, task, TaskStatus.ERLEDIGT,
            SpeakSpec(akt=SprechAkt.EHRLICH_KEIN, detail="kein_termin"),
            grund="kein_termin",
        )
    if oc.status == OutcomeStatus.AMBIGUOUS:
        if not task.gefuellt("vorname"):
            task.phase = Phase.SAMMELN
            return _frage(ns, task, "vorname", grund="mehrere_patienten")
        return _terminal_task(
            ns, task, TaskStatus.ERLEDIGT,
            SpeakSpec(akt=SprechAkt.EHRLICH_KEIN, detail="kein_termin"),
            grund="mehrdeutig",
        )
    if oc.status == OutcomeStatus.NOT_FOUND:
        return _terminal_task(
            ns, task, TaskStatus.ERLEDIGT,
            SpeakSpec(akt=SprechAkt.EHRLICH_KEIN, detail="kein_termin"),
            grund="nicht_gefunden",
        )
    return _terminal_task(
        ns, task, TaskStatus.GESCHEITERT,
        SpeakSpec(akt=SprechAkt.RUECKRUF),
        grund=f"such_fehler:{oc.status.value}",
    )


def _oc_notiz(ns: State, task: TaskState, oc: ToolOutcome) -> tuple[State, Decision]:
    if oc.committed:
        return _terminal_task(
            ns, task, TaskStatus.ERLEDIGT,
            SpeakSpec(akt=SprechAkt.RUECKRUF, fakten=_fakten(task, "nachname", "telefon")),
            grund="notiz_belegt",
        )
    return _terminal_task(
        ns, task, TaskStatus.GESCHEITERT,
        SpeakSpec(akt=SprechAkt.EHRLICH_KEIN, detail="notiz_fehler"),
        grund="notiz_fehler",
    )


def _erfolg_fakten(task: TaskState, oc: ToolOutcome) -> tuple[tuple[str, str], ...]:
    out: list[tuple[str, str]] = list(_fakten(task, "terminwahl", "behandler", "besuchsgrund"))
    aid = oc.payload.get("appointmentId") if isinstance(oc.payload, dict) else ""
    if aid:
        out.append(("appointmentId", str(aid)))
    return tuple(out)
