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
  I6  Werkzeug nie mit fehlenden Pflichtfeldern: fehlende Slots werden
      nachgesammelt, die Function startet nicht.

Fuehrt die Policy eine Aufgabe NICHT (``eigene_tasks``) oder fehlt ihre
``TaskSpec``, gibt der Reducer eine ``UEBERGEBEN``-Entscheidung zurueck (der
Orchestrator reicht sie an den Legacy-Pfad).
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from bianca.controller import aufsicht as _aufsicht
from bianca.controller import verstehen as _verstehen
from bianca.controller import wuensche as _wuensche
from bianca.controller.typen import (
    STEUER_FRAGEN as T_STEUER_FRAGEN,
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
# Session-Hirn: nur Anrufer-Identitaet gilt fuer jedes Anliegen.
# Behandler/Grund/Wunsch/fuer_wen bleiben aufgabe-lokal (Drittperson!).
_SESSION_SLOTS = frozenset({
    "nachname", "vorname", "telefon", "versicherung", "schonmal",
})
_PATIENT_SLOTS = ("schonmal", "nachname", "vorname", "versicherung")
# Einzige Quelle: bianca.controller.typen.STEUER_FRAGEN (auch von der Aufsicht
# gelesen). Alias hier, damit der bestehende Reducer-Code unveraendert bleibt.
_STEUER_FRAGEN = T_STEUER_FRAGEN


_STEUER_SLOTS = frozenset({
    "fuer_wen", "fuer_wen_mehr", "weiterer_task",
    "zweit_anliegen", "zweit_fuer_wen", "anstand", "angebot_nein",
    "termin_zuordnung",
})


def _merge_slots(task: TaskState, ev: SemanticEvent, ns: State | None = None) -> None:
    """Neue Fakten uebernehmen. Idempotent: gleicher Wert aendert nichts."""
    for name, sv in ev.slots.items():
        if name in _STEUER_SLOTS:
            continue
        if not isinstance(sv, SlotValue) or not sv.wert:
            continue
        alt = task.slots.get(name)
        if alt and alt.wert == sv.wert:
            if sv.bestaetigt and not alt.bestaetigt:
                task.slots[name] = sv
            continue
        if name == "wunschzeit" and alt and alt.wert:
            gemischt = _wuensche.wunsch_mischen(alt.wert, sv.wert)
            task.slots[name] = SlotValue(
                wert=gemischt, quelle=sv.quelle, bestaetigt=sv.bestaetigt,
            )
            continue
        task.slots[name] = sv
    if ns is not None:
        _merke_bekannt(ns, task)


def _merke_bekannt(ns: State, task: TaskState) -> None:
    for name, sv in task.slots.items():
        if name in _SESSION_SLOTS and sv.wert:
            ns.bekannt[name] = sv


def _person_key(sv: SlotValue | None) -> str:
    if sv is None or not sv.wert or sv.wert == "selbst":
        return ""
    return sv.wert


def _task_person(task: TaskState) -> str:
    return _person_key(task.slots.get("fuer_wen"))


def _fuelle_letzter_arzt(ns: State, task: TaskState) -> None:
    """Erkannter Anrufer: wieder beim letzten Behandler, ohne neu zu fragen."""
    if task.typ != "buchen":
        return
    if _task_person(task) or ns.anrufer_ok is not True:
        return
    arzt = (ns.letzter_besuch.get("arzt") or "").strip()
    if arzt and not task.gefuellt("behandler"):
        task.slots["behandler"] = SlotValue(wert=arzt, quelle=Quelle.AKTE, bestaetigt=True)
    grund = (ns.letzter_besuch.get("grund") or "").strip()
    if grund and not task.gefuellt("besuchsgrund"):
        task.slots["besuchsgrund"] = SlotValue(wert=grund, quelle=Quelle.AKTE, bestaetigt=True)


def _fuelle_aus_bekannt(ns: State, task: TaskState) -> None:
    dritter = _task_person(task)
    for name, sv in ns.bekannt.items():
        if name not in _SESSION_SLOTS or not sv.wert:
            continue
        if dritter and name in _PATIENT_SLOTS:
            if not (name == "nachname" and task.typ in ("auskunft", "absagen", "verschieben")):
                continue
        if not task.gefuellt(name):
            task.slots[name] = sv
    _fuelle_letzter_arzt(ns, task)


def _fuer_wen_wechseln(
    ns: State, task: TaskState, ev: SemanticEvent, alt: SlotValue | None
) -> TaskState:
    """Anderer Patient: laufende Aufgabe parken, neue anlegen — Slots behalten."""
    neu = ev.slots.get("fuer_wen")
    if neu is None or not neu.wert:
        return task
    if _truthy(ev.slots.get("uebertragen")) or _truthy(task.slots.get("uebertragen")):
        if ev.slots.get("uebertragen"):
            task.slots["uebertragen"] = ev.slots["uebertragen"]
        if neu and neu.wert:
            task.slots["fuer_wen"] = neu
        vn = ev.slots.get("vorname")
        if vn and vn.wert:
            task.slots["vorname"] = vn
        return task
    if _person_key(alt) == _person_key(neu):
        return task
    task.status = TaskStatus.GEPARKT
    neu_task = _aktiviere_task(ns, task.typ, person=_person_key(neu))
    neu_task.slots["fuer_wen"] = neu
    if _person_key(neu):
        for name in _PATIENT_SLOTS:
            neu_task.slots.pop(name, None)
            ns.gefragt.discard(name)
    else:
        _fuelle_aus_bekannt(ns, neu_task)
    return neu_task


def _weitere_personen_parken(ns: State, typ: str, ev: SemanticEvent) -> None:
    mehr = ev.slots.get("fuer_wen_mehr")
    if mehr is None or not mehr.wert:
        return
    vorhanden = {_task_person(t) for t in ns.tasks if t.typ == typ}
    for rolle in mehr.wert.split(","):
        rolle = rolle.strip()
        if not rolle or rolle in vorhanden:
            continue
        t = TaskState(typ=typ, status=TaskStatus.GEPARKT)
        t.slots["fuer_wen"] = SlotValue(wert=rolle, quelle=Quelle.GESAGT)
        ns.tasks.append(t)
        vorhanden.add(rolle)


def _park_zweit_anliegen(ns: State, ev: SemanticEvent, active: TaskState | None) -> None:
    """Zweites Anliegen (neuer Termin fuer X) parken — zuerst die laufende Aufgabe."""
    z = ev.slots.get("zweit_anliegen")
    if z is None or not z.wert or active is None:
        return
    person = ""
    zp = ev.slots.get("zweit_fuer_wen")
    if zp is not None and zp.wert:
        person = zp.wert
    for t in ns.tasks:
        if t.typ == z.wert and _task_person(t) == person and t.status == TaskStatus.GEPARKT:
            return
    t = TaskState(typ=z.wert, status=TaskStatus.GEPARKT)
    if person:
        t.slots["fuer_wen"] = SlotValue(wert=person, quelle=Quelle.GESAGT)
    ns.tasks.append(t)
    active.merker["plan_rolle"] = person
    active.merker["plan_typ"] = z.wert


def _plan_fakten(task: TaskState) -> list[tuple[str, str]]:
    rolle = task.merker.get("plan_rolle")
    if not rolle or task.merker.get("plan_gesagt"):
        return []
    task.merker["plan_gesagt"] = True
    out = [("plan_rolle", str(rolle)), ("plan_erst", task.typ)]
    typ = task.merker.get("plan_typ")
    if typ:
        out.append(("plan_typ", str(typ)))
    return out


_SMS_THEMA = re.compile(r"sms|best(?:ae|ä)tig", re.I)
_REZEPT_THEMA = re.compile(r"\brezept(?!ion)|ueberweis|überweis|krankmeldung", re.I)


def _klingt_sms(ev: SemanticEvent) -> bool:
    sm = ev.slots.get("sms")
    if sm and sm.wert and str(sm.wert).lower() not in ("nein", "0", "false"):
        return True
    t = " ".join(x for x in (ev.verstanden, ev.roh) if x)
    if _REZEPT_THEMA.search(t) and not _SMS_THEMA.search(t):
        return False
    return bool(_SMS_THEMA.search(t))


def _sms_antwort(ns: State, ev: SemanticEvent) -> tuple[State, Decision]:
    art = ns.letzter_write()
    fakten: list[tuple[str, str]] = [("sms", "ja"), ("write_art", art)]
    tel = ""
    tsv = ns.bekannt.get("telefon")
    if tsv and tsv.wert:
        tel = tsv.wert
    elif ns.anrufer.get("telefon"):
        tel = ns.anrufer["telefon"]
    if tel:
        fakten.append(("telefon", tel))
    if art == "absagen" and ns.letzte_termine:
        fakten.append(("anzahl", str(len(ns.letzte_termine))))
    return ns, Decision(
        naechste=Naechste.SPRECHEN,
        speak=SpeakSpec(akt=SprechAkt.INFO, detail="sms", fakten=tuple(fakten)),
        grund="sms_auskunft",
    )


def _sms_folge(ns: State, ev: SemanticEvent) -> tuple[State, Decision] | None:
    if ev.intent in (
        Intent.BUCHEN, Intent.ABSAGEN, Intent.VERSCHIEBEN, Intent.AUSKUNFT,
        Intent.VERBINDEN, Intent.RUECKRUF, Intent.NOTFALL, Intent.ABSCHIED,
        Intent.ANMELDUNG, Intent.KORREKTUR,
    ):
        return None
    if _klingt_sms(ev):
        return _sms_antwort(ns, ev)
    if ns.letzter_write() and ns.aktiv() is None and ev.intent in (
        Intent.BESTAETIGEN, Intent.DOKUMENT,
    ):
        art = ev.slots.get("dokumentart")
        if art and art.wert:
            return None
        return _sms_antwort(ns, ev)
    return None


def _slotwahl_oder_erstes(task: TaskState, ev: SemanticEvent) -> SlotValue | None:
    """Gewaehlter Slot oder Ja/Okay auf das erste Angebot."""
    wahl = task.slots.get("terminwahl")
    if wahl and wahl.wert and not _verstehen.ist_alle_wert(wahl.wert):
        return wahl
    if ev.bestaetigung is True:
        erstes = task.slots.get("angebot_erstes")
        if erstes and erstes.wert:
            task.slots["terminwahl"] = SlotValue(wert=erstes.wert, quelle=Quelle.GESAGT)
            return task.slots["terminwahl"]
    return None


def _merke_angebot_slots(task: TaskState, slots: list[Any]) -> None:
    if not slots:
        return
    task.slots["angebot_erstes"] = SlotValue(wert=str(slots[0]), quelle=Quelle.KALENDER)
    task.merker["angebot_csv"] = "||".join(str(s) for s in slots[:3])


def _angebot_fakten(task: TaskState) -> list[tuple[str, str]]:
    csv = task.merker.get("angebot_csv")
    if not csv:
        erstes = task.slots.get("angebot_erstes")
        return [("slot", erstes.wert)] if erstes and erstes.wert else []
    return [("slot", s) for s in str(csv).split("||") if s]


def _sammel_slots(spec: TaskSpec) -> tuple[str, ...]:
    """Welche Slots sind vor der ersten Werkzeugaktion zu sammeln?"""
    if spec.familie in (Familie.VERWALTEN, Familie.AUSKUNFT):
        return spec.identify
    return spec.pflicht


def _erste_luecke(task: TaskState, spec: TaskSpec, ns: State | None = None) -> str:
    """Erstes noch nicht gestelltes Sammelfeld. Schon gefragte, leere Slots
    werden hier uebersprungen (kein Nachbohren nach Themenwechsel).
    Bevor ein Werkzeug startet, holt ``_werkzeug`` fehlende Pflichtfelder
    trotzdem nach (I6)."""
    for slot in _sammel_slots(spec):
        if not task.gefuellt(slot):
            if ns is not None and slot in ns.gefragt:
                continue
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


def _anrufer_check_noetig(ns: State) -> bool:
    return bool(ns.anrufer.get("nachname") or ns.anrufer.get("anrede")) and ns.anrufer_ok is None


def _anrufer_in_hirn(ns: State) -> None:
    nn = (ns.anrufer.get("nachname") or "").strip()
    if nn:
        ns.bekannt["nachname"] = SlotValue(wert=nn, quelle=Quelle.ANRUFER_CF, bestaetigt=True)
    ns.bekannt["schonmal"] = SlotValue(wert="ja", quelle=Quelle.ANRUFER_CF, bestaetigt=True)
    vn = (ns.anrufer.get("vorname") or "").strip()
    if vn:
        ns.bekannt["vorname"] = SlotValue(wert=vn, quelle=Quelle.ANRUFER_CF, bestaetigt=True)
    tel = (ns.anrufer.get("telefon") or "").strip()
    if tel:
        ns.bekannt["telefon"] = SlotValue(wert=tel, quelle=Quelle.ANRUFER_CF, bestaetigt=True)
    vers = (ns.anrufer.get("versicherung") or "").strip()
    if vers:
        ns.bekannt["versicherung"] = SlotValue(wert=vers, quelle=Quelle.ANRUFER_CF, bestaetigt=True)


def _kontext_fakten(ns: State, slot: str) -> tuple[tuple[str, str], ...]:
    out: list[tuple[str, str]] = [("zug", str(ns.zug_nr))]
    if slot == "anrufer_check":
        if ns.anrufer.get("anrede"):
            out.append(("anrede", ns.anrufer["anrede"]))
        if ns.anrufer.get("nachname"):
            out.append(("name", ns.anrufer["nachname"]))
        return tuple(out)
    if slot == "fach_weiter" and ns.fach_thema:
        out.append(("thema", ns.fach_thema))
        return tuple(out)
    if slot in ("schonmal", "behandler", "besuchsgrund", "wunschzeit", "nachname"):
        out.extend(_letzter_besuch_fakten(ns))
    return tuple(out)


def _letzter_besuch_fakten(ns: State) -> list[tuple[str, str]]:
    """Letzter Besuch einmal vorsprechen — auch am Slotangebot, nicht nur an der Frage."""
    if ns.bezug_gesagt or ns.anrufer_ok is not True:
        return []
    if not (ns.letzter_besuch.get("arzt") or ns.letzter_besuch.get("grund")):
        return []
    out: list[tuple[str, str]] = []
    if ns.letzter_besuch.get("arzt"):
        out.append(("letzter_arzt", ns.letzter_besuch["arzt"]))
    if ns.letzter_besuch.get("grund"):
        out.append(("letzter_grund", ns.letzter_besuch["grund"]))
    if ns.letzter_besuch.get("wann"):
        out.append(("letzter_wann", ns.letzter_besuch["wann"]))
    ns.bezug_gesagt = True
    return out


def _frage(ns: State, task: TaskState, slot: str, grund: str) -> tuple[State, Decision]:
    task.zuletzt_gefragt = slot
    if slot not in _STEUER_FRAGEN:
        ns.gefragt.add(slot)
    fakten = list(_fakten(task, "fuer_wen"))
    fakten.extend(_kontext_fakten(ns, slot))
    vf = task.merker.get("wunsch_verfehlt")
    if slot == "wunschzeit" and vf:
        fakten.append(("wunsch_verfehlt", vf))
    fakten.extend(_plan_fakten(task))
    return ns, Decision(
        naechste=Naechste.FRAGEN,
        speak=SpeakSpec(
            akt=SprechAkt.FRAGE,
            frage_id=slot,
            fakten=tuple(fakten),
        ),
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


def _slots_neu_laden(
    ns: State, task: TaskState, spec: TaskSpec, *, grund: str
) -> tuple[State, Decision]:
    """Angebot passt nicht — mit dem neuen Zeitwunsch erneut suchen."""
    task.slots.pop("terminwahl", None)
    task.slots.pop("angebot_erstes", None)
    task.merker.pop("neu_gelesen", None)
    if spec.familie == Familie.BUCHEN:
        task.phase = Phase.ANGEBOT
    return _werkzeug(
        ns, task, spec,
        ToolCommand(name=spec.offer_tool, args=_offer_args(task), bindings=_bindings(task)),
        grund=grund,
    )


def _such_args(task: TaskState) -> dict[str, str]:
    a: dict[str, str] = {}
    nn = task.slots.get("nachname")
    vn = task.slots.get("vorname")
    if nn and nn.wert:
        a["lastName"] = nn.wert
    if vn and vn.wert:
        a["firstName"] = vn.wert
    fw = task.slots.get("fuer_wen")
    if fw and fw.wert and fw.wert != "selbst" and not _truthy(task.slots.get("uebertragen")):
        a["fuer_wen"] = fw.wert
    ohne = (task.merker.get("abgelehnt_ids") or "").strip()
    if ohne:
        a["ohne"] = ohne
    th = task.slots.get("termin_hinweis") or task.slots.get("wunschzeit")
    if th and th.wert:
        a["wish"] = th.wert
    bg = task.slots.get("besuchsgrund")
    if bg and bg.wert and not _verstehen.ist_umzug_wert(bg.wert):
        a["grund"] = bg.wert
    return a


def _truthy(sv: SlotValue | None) -> bool:
    if sv is None or not sv.wert:
        return False
    return str(sv.wert).strip().lower() not in {"nein", "0", "false", "nein."}


def _wahl_alle(sv: SlotValue | None) -> bool:
    return bool(sv and _verstehen.ist_alle_wert(sv.wert))


def _ist_alle(ev: SemanticEvent | None = None, task: TaskState | None = None) -> bool:
    if ev is not None and _wahl_alle(ev.slots.get("terminwahl")):
        return True
    if task is not None and _wahl_alle(task.slots.get("terminwahl")):
        return True
    return False


def _verwalten_filter(ev: SemanticEvent) -> bool:
    """Hinweis filtert WELCHEN Termin — nie 'alle' und nie ein Absagegrund."""
    if _ist_alle(ev):
        return False
    for name in ("termin_hinweis", "wunschzeit", "behandler", "suche_weiter"):
        sv = ev.slots.get(name)
        if sv and sv.wert:
            return True
    bg = ev.slots.get("besuchsgrund")
    if bg and bg.wert and not _verstehen.ist_umzug_wert(bg.wert):
        return True
    return False


def _ist_uebertragen(ev: SemanticEvent, task: TaskState | None = None) -> bool:
    if _truthy(ev.slots.get("uebertragen")):
        return True
    if task is not None and _truthy(task.slots.get("uebertragen")):
        return True
    fw = ev.slots.get("fuer_wen")
    return bool(
        fw and fw.wert and fw.wert not in ("", "selbst")
        and ev.bestaetigung is True
        and task is not None
        and task.gefuellt("gefunden_id")
        and _truthy(ev.slots.get("uebertragen"))
    )


def _verwalten_neu_suchen(
    ns: State, task: TaskState, spec: TaskSpec, *, grund: str
) -> tuple[State, Decision]:
    """Hinweise aus dem Hirn-Event in die Bestandssuche, nie neue Aufgabe."""
    task.phase = Phase.ANGEBOT
    task.merker.pop("bestand_gelesen", None)
    task.merker.pop("mehrere", None)
    for k in ("gefunden_id", "gefunden_iso", "gefunden_arzt", "gefunden_grund"):
        task.slots.pop(k, None)
    task.merker["gesucht"] = True
    return _werkzeug(
        ns, task, spec,
        ToolCommand(name=spec.such_tool, args=_such_args(task), bindings=_bindings(task)),
        grund=grund,
    )


def _restore_letzte_anzeige(task: TaskState) -> None:
    if task.gefuellt("gefunden_id"):
        return
    lid = task.merker.get("letzte_id")
    if not lid:
        return
    task.slots["gefunden_id"] = SlotValue(wert=str(lid), quelle=Quelle.KALENDER)
    if task.merker.get("letzte_iso"):
        task.slots["gefunden_iso"] = SlotValue(
            wert=str(task.merker["letzte_iso"]), quelle=Quelle.KALENDER,
        )
    if task.merker.get("letzte_arzt"):
        task.slots["gefunden_arzt"] = SlotValue(
            wert=str(task.merker["letzte_arzt"]), quelle=Quelle.KALENDER,
        )


def _verwalten_uebertragen(
    ns: State, task: TaskState, spec: TaskSpec
) -> tuple[State, Decision]:
    _restore_letzte_anzeige(task)
    rolle = task.slots.get("fuer_wen")
    vn = task.slots.get("vorname")
    iso = task.slots.get("gefunden_iso")
    gid = task.slots.get("gefunden_id")
    was = "Termin"
    if iso and iso.wert:
        was += f" {iso.wert}"
    was += " uebertragen"
    if rolle and rolle.wert:
        was += f" auf {rolle.wert}"
    if vn and vn.wert:
        was += f" {vn.wert}"
    args = {"was": was}
    if gid and gid.wert:
        args["appointmentId"] = gid.wert
    return _werkzeug(
        ns, task, spec,
        ToolCommand(name="praxis_notiz", args=args),
        grund="termin_uebertragen",
    )


def _slot_fuer_tool_bereit(task: TaskState, spec: TaskSpec, slot: str) -> bool:
    if not task.gefuellt(slot):
        return False
    if slot in spec.ruecklese_slots and not task.bestaetigt(slot):
        return False
    return True


def _tool_pflicht(spec: TaskSpec, name: str) -> tuple[str, ...]:
    """Welche Task-Slots muss dieses Werkzeug schon haben?"""
    if not name:
        return ()
    if name == spec.such_tool:
        return spec.identify
    if name == spec.offer_tool:
        if spec.familie == Familie.BUCHEN:
            return spec.pflicht
        if spec.neue_zeit:
            return ("gefunden_id",)
        return ()
    if name == spec.commit_tool:
        if spec.familie == Familie.BUCHEN:
            return ("terminwahl", spec.telefon_slot)
        if spec.neue_zeit:
            return ("gefunden_id", "terminwahl")
        return ("gefunden_id",)
    if name == spec.notiz_tool:
        return spec.pflicht
    return ()


def _fehlende_tool_slots(task: TaskState, spec: TaskSpec, name: str) -> tuple[str, ...]:
    return tuple(
        s for s in _tool_pflicht(spec, name)
        if s and not _slot_fuer_tool_bereit(task, spec, s)
    )


def _tool_luecke_sammeln(
    ns: State, task: TaskState, spec: TaskSpec, fehl: tuple[str, ...], *, grund: str
) -> tuple[State, Decision]:
    """Function unvollstaendig: restliche Felder einsammeln, nicht ausfuehren."""
    task.phase = Phase.SAMMELN
    erste = fehl[0]
    ns.gefragt.discard(erste)
    if erste in spec.ruecklese_slots and task.gefuellt(erste) and not task.bestaetigt(erste):
        return _ruecklesen(ns, task, erste, grund=grund)
    return _frage(ns, task, erste, grund=grund)


def _werkzeug(
    ns: State, task: TaskState, spec: TaskSpec, cmd: ToolCommand, *, grund: str
) -> tuple[State, Decision]:
    """Einzige Stelle, die WERKZEUG entscheidet — oder nachsammelt (I6)."""
    fehl = _fehlende_tool_slots(task, spec, cmd.name)
    if fehl:
        return _tool_luecke_sammeln(
            ns, task, spec, fehl, grund=f"tool_luecke:{cmd.name}:{fehl[0]}"
        )
    return ns, Decision(
        naechste=Naechste.WERKZEUG,
        tool=cmd,
        task=task.typ,
        grund=grund,
    )


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
    gid = task.slots.get("gefunden_id")
    if gid and gid.wert:
        task.merker["letzte_id"] = gid.wert
    iso = task.slots.get("gefunden_iso")
    if iso and iso.wert:
        task.merker["letzte_iso"] = iso.wert
    arzt = task.slots.get("gefunden_arzt")
    if arzt and arzt.wert:
        task.merker["letzte_arzt"] = arzt.wert


def _appt_kurz(appt: Mapping[str, Any]) -> str:
    iso = appt.get("iso") or appt.get("start") or appt.get("startIso") or ""
    arzt = appt.get("arzt") or appt.get("calendarName") or ""
    grund = appt.get("grund") or appt.get("motivName") or ""
    return " ".join(str(x) for x in (iso, arzt, grund) if x).strip() or str(appt.get("id") or "")


def _merke_termine(ns: State, appts: list[Any]) -> None:
    ns.letzte_termine = [dict(a) for a in appts if isinstance(a, dict)]


def _lage_termine(ns: State) -> list[dict[str, Any]]:
    return [dict(a) for a in ns.letzte_termine if isinstance(a, dict)]


def _termin_ids(appts: list[Mapping[str, Any]]) -> list[str]:
    out: list[str] = []
    for a in appts:
        aid = a.get("id") or a.get("appointmentId")
        if aid:
            out.append(str(aid))
    return out


def _option_fakten(appts: list[Mapping[str, Any]]) -> list[tuple[str, str]]:
    return [("option", _appt_kurz(a)) for a in appts[:3]]


def _zuordnung_rolle(ev: SemanticEvent) -> str:
    sv = ev.slots.get("termin_zuordnung")
    if sv and sv.wert:
        return sv.wert
    from bianca.controller import fuer_wen as _fw
    return _fw.deute(" ".join(x for x in (ev.verstanden, ev.roh) if x))


def _appt_person(appt: Mapping[str, Any]) -> str:
    return str(
        appt.get("person") or appt.get("fuer_wen") or appt.get("rolle") or ""
    ).strip().lower()


def _zuordnung_antworten(
    ns: State, task: TaskState, ev: SemanticEvent
) -> tuple[State, Decision]:
    rolle = _zuordnung_rolle(ev)
    liste = _lage_termine(ns)
    if not rolle or not liste:
        return _auswahl_aus_cache(ns, task)
    treffer = [a for a in liste if _appt_person(a) == rolle]
    fakten: list[tuple[str, str]] = [
        ("zuordnung_rolle", rolle),
        ("zuordnung", "treffer" if treffer else "leer"),
    ]
    fakten.extend(_option_fakten(treffer or liste))
    task.zuletzt_gefragt = "auswahl"
    task.phase = Phase.ANGEBOT
    return ns, Decision(
        naechste=Naechste.FRAGEN,
        speak=SpeakSpec(akt=SprechAkt.FRAGE, frage_id="auswahl", fakten=tuple(fakten)),
        task=task.typ,
        grund="termin_zuordnung" if treffer else "termin_zuordnung_leer",
    )


def _gehoert_fakten(ev: SemanticEvent, ns: State) -> list[tuple[str, str]]:
    """Was der Anrufer GERADE gesagt hat — der Renderer muss das aufgreifen."""
    out: list[tuple[str, str]] = [("gehoert_intent", ev.intent.value)]
    tw = ev.slots.get("terminwahl")
    if tw and tw.wert:
        out.append(("gehoert_terminwahl", tw.wert))
        if _verstehen.ist_alle_wert(tw.wert) and ns.letzte_termine:
            out.append(("anzahl", str(len(ns.letzte_termine))))
    ag = ev.slots.get("absage_grund")
    if ag and ag.wert:
        out.append(("gehoert_absage_grund", ag.wert))
        out.append(("absage_grund", ag.wert))
    az = ev.slots.get("anzahl")
    if az and az.wert:
        out.append(("gehoert_anzahl", az.wert))
        out.append(("anzahl", az.wert))
    if ev.verstanden:
        out.append(("gehoert_verstanden", ev.verstanden))
    sm = ev.slots.get("sms")
    if sm and sm.wert:
        out.append(("gehoert_sms", sm.wert))
        out.append(("sms", sm.wert))
    wz = ev.slots.get("wunschzeit") or ev.slots.get("termin_hinweis")
    if wz and wz.wert:
        out.append(("gehoert_wunsch", wz.wert))
    bg = ev.slots.get("besuchsgrund")
    if bg and bg.wert and not _verstehen.ist_umzug_wert(bg.wert):
        out.append(("gehoert_grund", bg.wert))
    fw = ev.slots.get("fuer_wen") or ev.slots.get("zweit_fuer_wen")
    if fw and fw.wert:
        out.append(("gehoert_rolle", fw.wert))
    return out


def _mit_gehoert(
    ns: State, decision: Decision, ev: SemanticEvent
) -> tuple[State, Decision]:
    if decision.speak is None:
        return ns, decision
    extra = _gehoert_fakten(ev, ns)
    haben = {k for k, _ in decision.speak.fakten}
    neu = list(decision.speak.fakten)
    for k, v in extra:
        if k not in haben:
            neu.append((k, v))
    return ns, replace(decision, speak=replace(decision.speak, fakten=tuple(neu)))


def _mehrfach_fragen(
    ns: State, task: TaskState, appts: list[Mapping[str, Any]] | None = None
) -> tuple[State, Decision]:
    liste = list(appts) if appts is not None else _lage_termine(ns)
    ids = _termin_ids(liste)
    if not ids:
        return ns, Decision(naechste=Naechste.WARTEN, task=task.typ, grund="keine_ids")
    _merke_termine(ns, liste)
    task.phase = Phase.BESTAETIGEN
    task.merker["mehrfach_ok"] = True
    task.merker["mehrfach_ids"] = ",".join(ids)
    task.slots["gefunden_id"] = SlotValue(wert=",".join(ids), quelle=Quelle.KALENDER)
    task.zuletzt_gefragt = "mehrfach_ok"
    fakten: list[tuple[str, str]] = [("anzahl", str(len(ids)))]
    ag = task.slots.get("absage_grund")
    if ag and ag.wert:
        fakten.append(("absage_grund", ag.wert))
    fakten.extend(_option_fakten(liste))
    return ns, Decision(
        naechste=Naechste.FRAGEN,
        speak=SpeakSpec(akt=SprechAkt.FRAGE, frage_id="mehrfach_ok", fakten=tuple(fakten)),
        task=task.typ,
        grund="mehrfach_ok",
    )


def _auswahl_aus_cache(ns: State, task: TaskState) -> tuple[State, Decision]:
    liste = _lage_termine(ns)
    if not liste:
        return ns, Decision(naechste=Naechste.WARTEN, task=task.typ, grund="suche_offen")
    task.phase = Phase.ANGEBOT
    task.merker["mehrere"] = True
    task.zuletzt_gefragt = "auswahl"
    return ns, Decision(
        naechste=Naechste.FRAGEN,
        speak=SpeakSpec(
            akt=SprechAkt.FRAGE, frage_id="auswahl", fakten=tuple(_option_fakten(liste)),
        ),
        task=task.typ,
        grund="auswahl_liste",
    )


def _neuer_task(ns: State, typ: str) -> TaskState:
    t = TaskState(typ=typ)
    _fuelle_aus_bekannt(ns, t)
    ns.tasks.append(t)
    return t


def _aktiviere_task(ns: State, typ: str, person: str = "") -> TaskState:
    """Geparkte Aufgabe derselben Art UND Person fortsetzen — sonst neu."""
    for t in reversed(ns.tasks):
        if t.typ == typ and t.status == TaskStatus.GEPARKT and _task_person(t) == person:
            t.status = TaskStatus.AKTIV
            _fuelle_aus_bekannt(ns, t)
            return t
    t = _neuer_task(ns, typ)
    if person:
        t.slots["fuer_wen"] = SlotValue(wert=person, quelle=Quelle.GESAGT)
        for name in _PATIENT_SLOTS:
            t.slots.pop(name, None)
    return t


def _naechste_geparkte(ns: State) -> TaskState | None:
    for t in reversed(ns.tasks):
        if t.status == TaskStatus.GEPARKT:
            return t
    return None


def _dispatch_familie(
    ns: State, task: TaskState, ev: SemanticEvent, spec: TaskSpec, policy: Policy
) -> tuple[State, Decision]:
    fam = spec.familie
    if fam == Familie.BUCHEN:
        return _adv_buchen(ns, task, ev, spec)
    if fam == Familie.VERWALTEN:
        return _adv_verwalten(ns, task, ev, spec)
    if fam == Familie.AUSKUNFT:
        return _adv_auskunft(ns, task, ev, spec)
    if fam == Familie.VERBINDEN:
        return _adv_verbinden(ns, task, ev, spec, policy)
    if fam == Familie.DOKUMENT:
        return _adv_dokument(ns, task, ev, spec, policy)
    if fam == Familie.RUECKRUF:
        return _adv_rueckruf(ns, task, ev, spec)
    return _uebergeben(ns, task.typ, grund=f"familie_unbekannt:{fam.value}")


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
        if isinstance(event, SemanticEvent) and event.intent != Intent.ABSCHIED:
            # Dock: nach Auflegen weiter tippen = neues Gespraech. Live waere tot.
            ns.tasks.clear()
            ns.ledger.clear()
            ns.terminal = False
            ns.anmeldung_gesagt = 0
            ns.anmeldung_rueckruf_offen = False
            ns.bekannt.clear()
            ns.gefragt.clear()
            ns.anrufer_ok = None
            ns.anrufer_gefragt = False
            ns.anrufer_fragen = 0
            ns.bezug_gesagt = False
            ns.auskunft_klar_offen = False
            ns.fach_thema = ""
            ns.fach_weiter_offen = False
            ns.letzte_termine = []
        else:
            return ns, Decision(
                naechste=Naechste.WARTEN,
                speak=SpeakSpec(akt=SprechAkt.ABSCHIED) if isinstance(event, SemanticEvent) else None,
                grund="terminal",
            )
    if isinstance(event, ToolOutcome):
        ns, decision = _nie_stumm(*_reduce_outcome(ns, event, policy), policy)
        return _aufsicht.ueberwachen(ns, decision, policy)
    if isinstance(event, SemanticEvent):
        ns, decision = _nie_stumm(*_reduce_event(ns, event, policy), policy)
        ns, decision = _mit_gehoert(ns, decision, event)
        return _aufsicht.ueberwachen(ns, decision, policy)
    return ns, Decision(
        naechste=Naechste.SPRECHEN,
        speak=SpeakSpec(akt=SprechAkt.INFO, detail="unklar"),
        grund="unbekanntes_event",
    )


def _nie_stumm(
    ns: State, decision: Decision, policy: Policy
) -> tuple[State, Decision]:
    """Kein leerer Zug: offene Frage wiederholen oder nach dem Anliegen fragen."""
    if decision.speak is not None or decision.hangup:
        return ns, decision
    if decision.naechste in (Naechste.WERKZEUG, Naechste.UEBERGEBEN, Naechste.AUFLEGEN):
        return ns, decision
    active = ns.aktiv()
    if active is not None:
        angebot = _angebot_fakten(active)
        wartet_wahl = bool(angebot) and (
            decision.grund in (
                "verschieben_neu_offen", "angebot_offen", "suche_offen",
            )
            or (
                bool(active.merker.get("bestand_bestaetigt"))
                and not active.merker.get("neu_gelesen")
                and not active.gefuellt("terminwahl")
            )
        )
        if wartet_wahl:
            return ns, Decision(
                naechste=Naechste.SPRECHEN,
                speak=SpeakSpec(akt=SprechAkt.ANGEBOT, fakten=tuple(angebot)),
                task=active.typ,
                grund=f"wiederholen:{decision.grund}",
            )
        if active.zuletzt_gefragt:
            spec = policy.spec(active.typ)
            schon = (
                active.zuletzt_gefragt in ns.gefragt
                and active.zuletzt_gefragt not in _STEUER_FRAGEN
                and not active.gefuellt(active.zuletzt_gefragt)
            )
            if schon and spec is not None:
                luecke = _erste_luecke(active, spec, ns)
                if luecke:
                    return _frage(ns, active, luecke, grund=f"hirn:{decision.grund}")
            elif not schon and not active.gefuellt(active.zuletzt_gefragt):
                return _frage(ns, active, active.zuletzt_gefragt, grund=f"wiederholen:{decision.grund}")
            elif not schon and spec is not None:
                luecke = _erste_luecke(active, spec, ns)
                if luecke:
                    return _frage(ns, active, luecke, grund=f"hirn:{decision.grund}")
        if active.phase == Phase.ANGEBOT:
            if _ist_alle(task=active) and ns.letzte_termine:
                return _mehrfach_fragen(ns, active)
            if ns.letzte_termine:
                return _auswahl_aus_cache(ns, active)
            return ns, Decision(
                naechste=Naechste.FRAGEN,
                speak=SpeakSpec(akt=SprechAkt.FRAGE, frage_id="auswahl"),
                task=active.typ,
                grund=f"wiederholen:{decision.grund}",
            )
    return ns, Decision(
        naechste=Naechste.SPRECHEN,
        speak=SpeakSpec(akt=SprechAkt.INFO, detail="unklar"),
        task=decision.task,
        grund=f"nie_stumm:{decision.grund}",
    )


# --------------------------------------------------------------------------- #
# Anrufer-Zug.
# --------------------------------------------------------------------------- #
def _reduce_event(ns: State, ev: SemanticEvent, policy: Policy) -> tuple[State, Decision]:
    # Globale Sofortregeln.
    anstand = ev.slots.get("anstand")
    if anstand and anstand.wert:
        return ns, Decision(
            naechste=Naechste.SPRECHEN,
            speak=SpeakSpec(akt=SprechAkt.INFO, detail=f"anstand_{anstand.wert}"),
            grund="anstand",
        )
    if (
        ev.intent == Intent.BESTAETIGEN
        and ev.bestaetigung is None
        and ns.letzte_termine
        and not ev.slots.get("sms")
    ):
        az = ev.slots.get("anzahl")
        n = (az.wert if az and az.wert else "") or str(len(ns.letzte_termine))
        return ns, Decision(
            naechste=Naechste.SPRECHEN,
            speak=SpeakSpec(akt=SprechAkt.INFO, detail="anzahl", fakten=(("anzahl", n),)),
            grund="anzahl_bestaetigt",
        )
    sms = _sms_folge(ns, ev)
    if sms is not None:
        return sms
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
        nxt = _naechste_geparkte(ns)
        if nxt is not None:
            cur = ns.aktiv()
            if cur is not None:
                if cur.phase == Phase.ABGESCHLOSSEN:
                    cur.status = TaskStatus.ERLEDIGT
                else:
                    cur.status = TaskStatus.GEPARKT
            nxt.status = TaskStatus.AKTIV
            spec = policy.spec(nxt.typ)
            if spec is None or not policy.fuehrt(nxt.typ):
                return _uebergeben(ns, nxt.typ, grund=f"task_nicht_im_kern:{nxt.typ}")
            return _dispatch_familie(ns, nxt, ev, spec, policy)
        active = ns.aktiv() or _neuer_task(ns, "abschied")
        return _terminal_task(
            ns, active, TaskStatus.ERLEDIGT,
            SpeakSpec(akt=SprechAkt.ABSCHIED),
            grund="abschied", hangup=True,
        )
    if ev.intent == Intent.ANMELDUNG:
        active = ns.aktiv()
        # Rolle erklaeren und zuhoeren — eine laufende Aufgabe (inkl. Falschstart
        # "Rezept" aus Rezeption) darf das nicht weiterfuehren.
        if active is not None:
            active.status = TaskStatus.GEPARKT
        ns.anmeldung_gesagt += 1
        if ns.anmeldung_gesagt >= 2:
            ns.anmeldung_rueckruf_offen = True
            return ns, Decision(
                naechste=Naechste.FRAGEN,
                speak=SpeakSpec(akt=SprechAkt.FRAGE, frage_id="anmeldung_rueckruf"),
                grund="anmeldung_besteht",
            )
        ns.anmeldung_rueckruf_offen = False
        return ns, Decision(
            naechste=Naechste.SPRECHEN,
            speak=SpeakSpec(akt=SprechAkt.INFO, detail="anmeldung", fakten=(("zug", str(ns.zug_nr)),)),
            grund="anmeldung_rolle",
        )
    if ev.intent == Intent.PRAXISINFO:
        thema = ""
        ts = ev.slots.get("thema")
        if ts and ts.wert:
            thema = ts.wert
        ns.fach_thema = thema or ns.fach_thema or "Ihre Frage"
        ns.fach_weiter_offen = True
        active = ns.aktiv()
        if active is None:
            active = _neuer_task(ns, "rueckruf")
            active.status = TaskStatus.GEPARKT
        return ns, Decision(
            naechste=Naechste.FRAGEN,
            speak=SpeakSpec(
                akt=SprechAkt.FRAGE,
                frage_id="fach_weiter",
                fakten=(("thema", ns.fach_thema), ("zug", str(ns.zug_nr))),
            ),
            grund="fachfrage",
        )
    if ns.fach_weiter_offen and ev.intent not in _INTENT_TASK:
        if ev.bestaetigung is True or ev.intent == Intent.RUECKRUF:
            ns.fach_weiter_offen = False
            active = _aktiviere_task(ns, "rueckruf")
            spec = policy.spec("rueckruf")
            if spec is None or not policy.fuehrt("rueckruf"):
                return _uebergeben(ns, "rueckruf", grund="rueckruf_nicht_im_kern")
            _merge_slots(active, ev, ns)
            return _adv_rueckruf(ns, active, ev, spec)
        if ev.bestaetigung is False:
            ns.fach_weiter_offen = False
            return ns, Decision(
                naechste=Naechste.SPRECHEN,
                speak=SpeakSpec(akt=SprechAkt.INFO, detail="anmeldung_nein", fakten=(("zug", str(ns.zug_nr)),)),
                grund="fachfrage_nein",
            )

    # Zweites Bestehen auf einen Menschen: Ja startet den Rueckruf (W-ANMELDUNG).
    if ns.anmeldung_rueckruf_offen and ev.intent not in _INTENT_TASK:
        if ev.bestaetigung is True or ev.intent == Intent.RUECKRUF:
            ns.anmeldung_rueckruf_offen = False
            active = _neuer_task(ns, "rueckruf")
            spec = policy.spec("rueckruf")
            if spec is None or not policy.fuehrt("rueckruf"):
                return _uebergeben(ns, "rueckruf", grund="rueckruf_nicht_im_kern")
            _merge_slots(active, ev, ns)
            return _adv_rueckruf(ns, active, ev, spec)
        if ev.bestaetigung is False:
            ns.anmeldung_rueckruf_offen = False
            return ns, Decision(
                naechste=Naechste.SPRECHEN,
                speak=SpeakSpec(akt=SprechAkt.INFO, detail="anmeldung_nein"),
                grund="anmeldung_rueckruf_nein",
            )
    if ev.intent == Intent.SMALLTALK:
        active = ns.aktiv()
        if active is not None and active.typ == "dokument":
            active.status = TaskStatus.GEPARKT
            return ns, Decision(
                naechste=Naechste.SPRECHEN,
                speak=SpeakSpec(akt=SprechAkt.INFO, detail="hallo"),
                grund="hallo",
            )
        if active is not None and active.zuletzt_gefragt:
            return _frage(ns, active, active.zuletzt_gefragt, grund="hallo_offen")
        roh = (ev.roh or "").lower()
        hilfe = any(w in roh for w in ("hilfe", "help", "helfen"))
        return ns, Decision(
            naechste=Naechste.SPRECHEN,
            speak=SpeakSpec(akt=SprechAkt.INFO, detail="hilfe" if hilfe else "hallo"),
            task=active.typ if active is not None else "",
            grund="hilfe" if hilfe else "hallo",
        )

    active = ns.aktiv()

    # Aufgabenstart / -wechsel.
    if ev.intent in _INTENT_TASK:
        ns.anmeldung_rueckruf_offen = False
        ziel = _INTENT_TASK[ev.intent]
        person = _person_key(ev.slots.get("fuer_wen"))
        bleibt = (
            active is not None
            and active.typ in ("absagen", "verschieben")
            and (
                ziel == "auskunft"
                or _ist_uebertragen(ev, active)
                or _verwalten_filter(ev)
                or ev.slots.get("termin_zuordnung")
                or _truthy(ev.slots.get("suche_weiter"))
                or (
                    ziel == "buchen"
                    and active.zuletzt_gefragt in ("termin_hinweis", "auswahl")
                )
            )
        )
        if bleibt:
            person = _task_person(active)
        if not bleibt and (active is None or ziel != active.typ):
            if active is not None:
                active.status = TaskStatus.GEPARKT
            active = _aktiviere_task(ns, ziel, person=person)
            if not policy.fuehrt(ziel) or policy.spec(ziel) is None:
                return _uebergeben(ns, ziel, grund=f"task_nicht_im_kern:{ziel}")
        if not bleibt and ziel == "buchen" and ns.fach_thema and active is not None and not active.gefuellt("besuchsgrund"):
            active.slots["besuchsgrund"] = SlotValue(wert=ns.fach_thema, quelle=Quelle.GESAGT)
            ns.fach_weiter_offen = False
        asv = ev.slots.get("auskunft_art")
        if not bleibt and asv and asv.wert and active is not None:
            active.slots["auskunft_art"] = asv
        if active is not None:
            # Wunsch/Grund aus dem Erstsatz behalten, auch wenn danach
            # erst die Identitaet geklaert wird.
            _merge_slots(active, ev, ns)
            _park_zweit_anliegen(ns, ev, active)

    weiter = ev.slots.get("weiterer_task")
    if weiter and weiter.wert:
        nxt = _naechste_geparkte(ns)
        if nxt is not None:
            if active is not None and active is not nxt:
                active.status = TaskStatus.GEPARKT
            nxt.status = TaskStatus.AKTIV
            active = nxt

    # Anrufer-Kennung: erst Ja/Nein, dann weiter (W-ANRUFER-CHECK).
    if _anrufer_check_noetig(ns) and ev.intent not in (Intent.NOTFALL, Intent.ABSCHIED, Intent.ANMELDUNG):
        dritter = ev.slots.get("fuer_wen")
        art = ev.slots.get("auskunft_art")
        if ev.bestaetigung is True or (
            ns.anrufer_gefragt
            and dritter
            and dritter.wert
            and dritter.wert != "selbst"
            and not ev.slots.get("zweit_anliegen")
        ):
            ns.anrufer_ok = True
            _anrufer_in_hirn(ns)
            if active is not None:
                _fuelle_aus_bekannt(ns, active)
        elif ev.bestaetigung is False:
            ns.anrufer_ok = False
            ns.anrufer = {}
            ns.letzter_besuch = {}
        elif ns.anrufer_gefragt and (ev.intent in _INTENT_TASK or (art and art.wert)):
            # Wer nach der Kennung schon das Anliegen nennt, bestaetigt mit.
            ns.anrufer_ok = True
            _anrufer_in_hirn(ns)
            if active is not None:
                _fuelle_aus_bekannt(ns, active)
        elif ns.anrufer_fragen >= (policy.max_rueckfragen if policy.max_rueckfragen > 0 else 1):
            # Deckel statt Schleife: der Anrufer-Check ist eine STEUER_FRAGE, die
            # Loop-Aufsicht zaehlt ihn nicht. Bleibt die Antwort mehrfach unklar,
            # wird der Treffer VERWORFEN und klassisch gefragt (W-ANRUFER-CHECK)
            # — nie dieselbe Kontrollfrage in Endlos-Umformulierungen.
            ns.anrufer_ok = False
            ns.anrufer = {}
            ns.letzter_besuch = {}
        else:
            if active is not None and ev.slots.get("auskunft_art"):
                active.slots["auskunft_art"] = ev.slots["auskunft_art"]
            typ = _INTENT_TASK.get(ev.intent) or "auskunft"
            if typ == "buchen" and ev.slots.get("auskunft_art") and ev.slots["auskunft_art"].wert == "bestand":
                typ = "auskunft"
            frage_task = active or _neuer_task(ns, typ)
            _merge_slots(frage_task, ev, ns)
            fw = ev.slots.get("fuer_wen")
            if fw and fw.wert and fw.wert != "selbst":
                frage_task.slots["fuer_wen"] = fw
            ns.anrufer_gefragt = True
            ns.anrufer_fragen += 1
            return _frage(ns, frage_task, "anrufer_check", grund="anrufer_check")

    # Terminauskunft ist doppeldeutig — erst klaeren, nie sofort buchen.
    # Andere Anliegen (Befunde, Unterlagen, Absage …) duerfen hier nie
    # in derselben Klaerungsfrage festkleben.
    if active is not None and active.typ == "auskunft":
        art = ""
        asv = ev.slots.get("auskunft_art") or active.slots.get("auskunft_art")
        if asv and asv.wert:
            art = asv.wert
        if ev.intent in _INTENT_TASK and ev.intent != Intent.AUSKUNFT:
            ns.auskunft_klar_offen = False
        elif ev.intent == Intent.PRAXISINFO:
            ns.auskunft_klar_offen = False
            active.status = TaskStatus.GEPARKT
            ns.fach_thema = (ev.slots.get("thema").wert if ev.slots.get("thema") else "") or ns.fach_thema
            ns.fach_weiter_offen = True
            return _frage(ns, active, "fach_weiter", grund="fach_statt_auskunft")
        elif art == "neu":
            active.status = TaskStatus.GEPARKT
            active = _aktiviere_task(ns, "buchen")
            ns.auskunft_klar_offen = False
        elif art == "bestand":
            ns.auskunft_klar_offen = False
            if asv:
                active.slots["auskunft_art"] = asv
        elif art == "unklar" or ns.auskunft_klar_offen:
            if ev.intent == Intent.BUCHEN:
                active.status = TaskStatus.GEPARKT
                active = _aktiviere_task(ns, "buchen")
                ns.auskunft_klar_offen = False
            elif ns.auskunft_klar_offen:
                ns.auskunft_klar_offen = False
                active.status = TaskStatus.GEPARKT
                return ns, Decision(
                    naechste=Naechste.SPRECHEN,
                    speak=SpeakSpec(akt=SprechAkt.INFO, detail="unklar"),
                    grund="auskunft_kein_termin",
                )
            else:
                ns.auskunft_klar_offen = True
                return _frage(ns, active, "auskunft_klar", grund="auskunft_klar")

    if active is None:
        nxt = _naechste_geparkte(ns)
        if nxt is not None and ev.intent not in (Intent.ABSCHIED, Intent.NOTFALL):
            nxt.status = TaskStatus.AKTIV
            active = nxt
            _merge_slots(active, ev, ns)
        else:
            return ns, Decision(
                naechste=Naechste.SPRECHEN,
                # Zug-Nummer mitgeben: der Renderer waehlt daran die Variante —
                # ohne sie kaeme wortgleich dieselbe Zeile (die Aufsicht deckelt
                # die Serie zusaetzlich).
                speak=SpeakSpec(
                    akt=SprechAkt.INFO, detail="unklar", fakten=(("zug", str(ns.zug_nr)),),
                ),
                grund=f"kein_task:{ev.intent.value}",
            )

    spec = policy.spec(active.typ)
    if spec is None or not policy.fuehrt(active.typ):
        return _uebergeben(ns, active.typ, grund=f"task_nicht_im_kern:{active.typ}")

    # Korrektur (W-EINWAND): bestrittenes Feld leeren, gezielt neu fragen.
    if ev.intent == Intent.KORREKTUR and ev.korrektur_feld:
        feld = ev.korrektur_feld
        active.slots.pop(feld, None)
        ns.bekannt.pop(feld, None)
        ns.gefragt.discard(feld)
        _merge_slots(active, ev, ns)  # Wert aus derselben Aeusserung darf sofort greifen.
        if active.phase in {Phase.ANGEBOT, Phase.BESTAETIGEN} and feld in _sammel_slots(spec):
            active.phase = Phase.SAMMELN
            active.merker.clear()
        if not active.gefuellt(feld) or (
            feld in spec.ruecklese_slots and not active.bestaetigt(feld)
        ):
            return _frage(ns, active, feld, grund=f"korrektur:{feld}")

    alt_person = active.slots.get("fuer_wen")
    _merge_slots(active, ev, ns)
    active = _fuer_wen_wechseln(ns, active, ev, alt_person)
    if not _truthy(ev.slots.get("uebertragen")):
        _weitere_personen_parken(ns, active.typ, ev)
    _fuelle_aus_bekannt(ns, active)
    spec = policy.spec(active.typ)
    if spec is None or not policy.fuehrt(active.typ):
        return _uebergeben(ns, active.typ, grund=f"task_nicht_im_kern:{active.typ}")
    return _dispatch_familie(ns, active, ev, spec, policy)


# --------------------------------------------------------------------------- #
# Familie BUCHEN.
# --------------------------------------------------------------------------- #
def _adv_buchen(ns: State, task: TaskState, ev: SemanticEvent, spec: TaskSpec) -> tuple[State, Decision]:
    if task.merker.get("warte_arzt_notiz"):
        return _arzt_notiz_zug(ns, task, ev)

    if task.phase == Phase.SAMMELN:
        wieder = _ruecklese_check(task, ev, spec)
        _merke_bekannt(ns, task)
        if wieder is not None:
            ns.bekannt.pop(wieder, None)
            ns.gefragt.discard(wieder)
            return _frage(ns, task, wieder, grund="ruecklese_nein")
        luecke = _erste_luecke(task, spec, ns)
        if luecke:
            if luecke in spec.ruecklese_slots and task.gefuellt(luecke) and not task.bestaetigt(luecke):
                return _ruecklesen(ns, task, luecke, grund=f"ruecklese_pflicht:{luecke}")
            return _frage(ns, task, luecke, grund="pflicht_sammeln")
        task.phase = Phase.ANGEBOT
        task.merker.clear()
        return _werkzeug(
            ns, task, spec,
            ToolCommand(name=spec.offer_tool, args=_offer_args(task), bindings=_bindings(task)),
            grund="slots_vollstaendig",
        )

    if task.phase == Phase.ANGEBOT:
        wahl = _slotwahl_oder_erstes(task, ev)
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
        if ev.slots.get("wunschzeit") and ev.slots["wunschzeit"].wert:
            return _slots_neu_laden(ns, task, spec, grund="angebot_neuer_wunsch")
        if ev.slots.get("angebot_nein") and ev.slots["angebot_nein"].wert:
            return _frage(ns, task, "wunschzeit", grund="angebot_keiner")
        return ns, Decision(naechste=Naechste.WARTEN, task=task.typ, grund="angebot_offen")

    if task.phase == Phase.BESTAETIGEN:
        return _bestaetigen_buchen(ns, task, ev, spec)

    return ns, Decision(naechste=Naechste.WARTEN, task=task.typ, grund="phase_ohne_zug")


def _arzt_notiz_zug(ns: State, task: TaskState, ev: SemanticEvent) -> tuple[State, Decision]:
    if ev.bestaetigung is True:
        task.merker["arzt_notiz"] = True
        task.merker.pop("warte_arzt_notiz", None)
        fakten = list(_fakten(task, "terminwahl", "behandler", "besuchsgrund"))
        fakten.append(("notiz", "ja"))
        return _terminal_task(
            ns, task, TaskStatus.ERLEDIGT,
            SpeakSpec(akt=SprechAkt.ERFOLG, detail="buchen", fakten=tuple(fakten)),
            grund="gebucht_mit_notiz",
        )
    if ev.bestaetigung is False:
        task.merker.pop("warte_arzt_notiz", None)
        return _terminal_task(
            ns, task, TaskStatus.ERLEDIGT,
            SpeakSpec(akt=SprechAkt.ERFOLG, detail="buchen", fakten=_fakten(task, "terminwahl", "behandler", "besuchsgrund")),
            grund="gebucht_belegt",
        )
    return _frage(ns, task, "arzt_notiz", grund="arzt_notiz")


def _bestaetigen_buchen(
    ns: State, task: TaskState, ev: SemanticEvent, spec: TaskSpec
) -> tuple[State, Decision]:
    if task.merker.get("warte_arzt_notiz"):
        return _arzt_notiz_zug(ns, task, ev)
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
        _fuelle_aus_bekannt(ns, task)
        tel = task.slots.get(spec.telefon_slot)
        if tel and tel.wert and (tel.bestaetigt or spec.telefon_slot in ns.gefragt):
            if not tel.bestaetigt:
                task.slots[spec.telefon_slot] = replace(tel, bestaetigt=True)
            return _commit_werkzeug(ns, task, spec, grund="telefon_aus_hirn")
        if not task.bestaetigt(spec.telefon_slot):
            return _frage(ns, task, spec.telefon_slot, grund="telefon_zuletzt")
        return _commit_werkzeug(ns, task, spec, grund="bestaetigt")

    hat_inhalt = any(
        (ev.slots.get(s) and ev.slots[s].wert)
        for s in ("wunschzeit", "besuchsgrund", "behandler", "nachname")
    )
    if ev.bestaetigung is False or hat_inhalt:
        task.slots.pop("terminwahl", None)
        task.merker.pop("termin_gelesen", None)
        if ev.slots.get("wunschzeit") and ev.slots["wunschzeit"].wert:
            return _slots_neu_laden(ns, task, spec, grund="bestaetigen_neue_zeit")
        if ev.slots.get("besuchsgrund") or ev.slots.get("behandler"):
            task.phase = Phase.SAMMELN
            return _adv_buchen(ns, task, replace(ev, bestaetigung=None), spec)
        if ev.bestaetigung is False:
            task.phase = Phase.ANGEBOT
            return _frage(ns, task, "aenderung", grund="ruecklese_nein")

    return ns, Decision(naechste=Naechste.WARTEN, task=task.typ, grund="bestaetigen_offen")


def _commit_werkzeug(
    ns: State, task: TaskState, spec: TaskSpec, *, grund: str
) -> tuple[State, Decision]:
    args: dict[str, str] = {}
    wahl = task.slots.get("terminwahl")
    if wahl and wahl.wert:
        args["slot_iso"] = wahl.wert
    return _werkzeug(
        ns, task, spec,
        ToolCommand(name=spec.commit_tool, args=args, bindings=_bindings(task)),
        grund=grund,
    )


# --------------------------------------------------------------------------- #
# Familie VERWALTEN (absagen + verschieben).
# --------------------------------------------------------------------------- #
def _adv_verwalten(ns: State, task: TaskState, ev: SemanticEvent, spec: TaskSpec) -> tuple[State, Decision]:
    if task.phase == Phase.SAMMELN:
        wieder = _ruecklese_check(task, ev, spec)
        _merke_bekannt(ns, task)
        if wieder is not None:
            ns.bekannt.pop(wieder, None)
            ns.gefragt.discard(wieder)
            return _frage(ns, task, wieder, grund="ruecklese_nein")
        luecke = _erste_luecke(task, spec, ns)
        if luecke:
            if luecke in spec.ruecklese_slots and task.gefuellt(luecke) and not task.bestaetigt(luecke):
                return _ruecklesen(ns, task, luecke, grund=f"ruecklese_pflicht:{luecke}")
            return _frage(ns, task, luecke, grund="identify_sammeln")
        if ns.letzte_termine:
            if _ist_alle(ev, task):
                return _mehrfach_fragen(ns, task)
            return _auswahl_aus_cache(ns, task)
        task.phase = Phase.ANGEBOT
        task.merker["gesucht"] = True
        return _werkzeug(
            ns, task, spec,
            ToolCommand(name=spec.such_tool, args=_such_args(task), bindings=_bindings(task)),
            grund="identify_vollstaendig",
        )

    if task.phase == Phase.ANGEBOT:
        if ev.slots.get("termin_zuordnung") and ns.letzte_termine:
            return _zuordnung_antworten(ns, task, ev)
        if _ist_uebertragen(ev, task):
            return _verwalten_uebertragen(ns, task, spec)
        if _ist_alle(ev, task):
            return _mehrfach_fragen(ns, task)
        if _verwalten_filter(ev):
            return _verwalten_neu_suchen(ns, task, spec, grund="verwalten_filter")
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
        if ns.letzte_termine:
            return _auswahl_aus_cache(ns, task)
        return ns, Decision(naechste=Naechste.WARTEN, task=task.typ, grund="suche_offen")

    if task.phase == Phase.BESTAETIGEN:
        return _bestaetigen_verwalten(ns, task, ev, spec)

    return ns, Decision(naechste=Naechste.WARTEN, task=task.typ, grund="phase_ohne_zug")


def _bestaetigen_verwalten(
    ns: State, task: TaskState, ev: SemanticEvent, spec: TaskSpec
) -> tuple[State, Decision]:
    if _ist_uebertragen(ev, task):
        return _verwalten_uebertragen(ns, task, spec)
    if task.merker.get("mehrfach_ok"):
        if ev.bestaetigung is False and not _ist_alle(ev, task):
            task.merker.pop("mehrfach_ok", None)
            task.merker.pop("mehrfach_ids", None)
            task.slots.pop("gefunden_id", None)
            return _auswahl_aus_cache(ns, task)
        if ev.bestaetigung is True or _ist_alle(ev, task):
            return _werkzeug(
                ns, task, spec,
                ToolCommand(name=spec.commit_tool, args=_storno_args(task), bindings=_bindings(task)),
                grund="storno_alle_bestaetigt",
            )
        return ns, Decision(naechste=Naechste.WARTEN, task=task.typ, grund="mehrfach_offen")
    if _verwalten_filter(ev):
        return _verwalten_neu_suchen(ns, task, spec, grund="verwalten_filter")

    if not spec.neue_zeit:
        # ABSAGEN: destruktive Bestaetigung.
        if ev.bestaetigung is True:
            return _werkzeug(
                ns, task, spec,
                ToolCommand(name=spec.commit_tool, args=_storno_args(task), bindings=_bindings(task)),
                grund="storno_bestaetigt",
            )
        if ev.bestaetigung is False:
            gid = task.slots.get("gefunden_id")
            if gid and gid.wert:
                alt = (task.merker.get("abgelehnt_ids") or "").strip()
                task.merker["abgelehnt_ids"] = f"{alt},{gid.wert}".strip(",")
                task.merker["letzte_id"] = gid.wert
                iso = task.slots.get("gefunden_iso")
                if iso and iso.wert:
                    task.merker["letzte_iso"] = iso.wert
                arzt = task.slots.get("gefunden_arzt")
                if arzt and arzt.wert:
                    task.merker["letzte_arzt"] = arzt.wert
            task.phase = Phase.SAMMELN
            task.merker.pop("bestand_gelesen", None)
            task.merker.pop("mehrere", None)
            for k in ("gefunden_id", "gefunden_iso", "gefunden_arzt", "gefunden_grund"):
                task.slots.pop(k, None)
            if task.gefuellt("nachname"):
                task.phase = Phase.ANGEBOT
                task.merker["gesucht"] = True
                return _werkzeug(
                    ns, task, spec,
                    ToolCommand(name=spec.such_tool, args=_such_args(task), bindings=_bindings(task)),
                    grund="storno_nicht_dieser",
                )
            return _frage(ns, task, "termin_hinweis", grund="storno_nicht_dieser")
        return ns, Decision(naechste=Naechste.WARTEN, task=task.typ, grund="storno_offen")

    # VERSCHIEBEN: erst Bestand bestaetigen, dann neuen Slot, dann move.
    if not task.merker.get("bestand_bestaetigt"):
        if ev.bestaetigung is True:
            task.merker["bestand_bestaetigt"] = True
            return _werkzeug(
                ns, task, spec,
                ToolCommand(name=spec.offer_tool, args=_offer_args(task), bindings=_bindings(task)),
                grund="verschieben_neue_slots",
            )
        if ev.bestaetigung is False:
            task.phase = Phase.SAMMELN
            task.merker.pop("bestand_gelesen", None)
            task.merker.pop("bestand_bestaetigt", None)
            for k in ("gefunden_id", "gefunden_iso", "gefunden_arzt", "gefunden_grund"):
                task.slots.pop(k, None)
            if task.gefuellt("nachname"):
                task.phase = Phase.ANGEBOT
                task.merker["gesucht"] = True
                return _werkzeug(
                    ns, task, spec,
                    ToolCommand(name=spec.such_tool, args=_such_args(task), bindings=_bindings(task)),
                    grund="verschieben_nicht_dieser",
                )
            return _frage(ns, task, "termin_hinweis", grund="verschieben_nicht_dieser")
        return ns, Decision(naechste=Naechste.WARTEN, task=task.typ, grund="verschieben_bestand_offen")

    if not task.merker.get("neu_gelesen"):
        wahl = _slotwahl_oder_erstes(task, ev)
        if wahl and wahl.wert:
            task.merker["neu_gelesen"] = True
            return ns, Decision(
                naechste=Naechste.SPRECHEN,
                speak=SpeakSpec(akt=SprechAkt.RUECKLESEN, fakten=_fakten(task, "terminwahl")),
                task=task.typ,
                grund="ruecklese_neu_termin",
            )
        if ev.slots.get("wunschzeit") and ev.slots["wunschzeit"].wert:
            return _slots_neu_laden(ns, task, spec, grund="verschieben_neuer_wunsch")
        if ev.slots.get("angebot_nein") and ev.slots["angebot_nein"].wert:
            return _frage(ns, task, "wunschzeit", grund="verschieben_keiner")
        return ns, Decision(naechste=Naechste.WARTEN, task=task.typ, grund="verschieben_neu_offen")

    if ev.bestaetigung is True:
        return _werkzeug(
            ns, task, spec,
            ToolCommand(name=spec.commit_tool, args=_move_args(task), bindings=_bindings(task)),
            grund="verschieben_bestaetigt",
        )
    if ev.bestaetigung is False:
        task.merker.pop("neu_gelesen", None)
        task.slots.pop("terminwahl", None)
        task.retries["neu_offer"] = task.retries.get("neu_offer", 0) + 1
        if task.retries["neu_offer"] <= spec.max_commit_retries:
            return _werkzeug(
                ns, task, spec,
                ToolCommand(name=spec.offer_tool, args=_offer_args(task), bindings=_bindings(task)),
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
    mehr = (task.merker.get("mehrfach_ids") or "").strip()
    if mehr:
        a["appointmentId"] = mehr
        return a
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
        _merke_bekannt(ns, task)
        if wieder is not None:
            ns.bekannt.pop(wieder, None)
            ns.gefragt.discard(wieder)
            return _frage(ns, task, wieder, grund="ruecklese_nein")
        luecke = _erste_luecke(task, spec, ns)
        if luecke:
            if luecke in spec.ruecklese_slots and task.gefuellt(luecke) and not task.bestaetigt(luecke):
                return _ruecklesen(ns, task, luecke, grund=f"ruecklese_pflicht:{luecke}")
            return _frage(ns, task, luecke, grund="identify_sammeln")
        task.phase = Phase.ANGEBOT
        return _werkzeug(
            ns, task, spec,
            ToolCommand(name=spec.such_tool, args=_such_args(task), bindings=_bindings(task)),
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
        art = task.slots.get("dokumentart")
        detail = "unterlagen" if art and art.wert == "unterlagen" else "dokument"
        return ns, Decision(
            naechste=Naechste.FRAGEN,
            speak=SpeakSpec(akt=SprechAkt.FRAGE, frage_id="rueckruf_ja", detail=detail),
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
    return _frage(ns, task, "rueckruf_ja", grund="dokument_offen")


# --------------------------------------------------------------------------- #
# Familie RUECKRUF (Notiz mit Name/Telefon).
# --------------------------------------------------------------------------- #
def _adv_rueckruf(ns: State, task: TaskState, ev: SemanticEvent, spec: TaskSpec) -> tuple[State, Decision]:
    if task.phase == Phase.SAMMELN:
        wieder = _ruecklese_check(task, ev, spec)
        _merke_bekannt(ns, task)
        if wieder is not None:
            ns.bekannt.pop(wieder, None)
            ns.gefragt.discard(wieder)
            return _frage(ns, task, wieder, grund="ruecklese_nein")
        luecke = _erste_luecke(task, spec, ns)
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
        return _werkzeug(
            ns, task, spec,
            ToolCommand(name=spec.notiz_tool, args=args),
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

    fehl = _fehlende_tool_slots(task, spec, oc.name)
    if fehl:
        return _tool_luecke_sammeln(
            ns, task, spec, fehl, grund=f"tool_luecke_outcome:{oc.name}:{fehl[0]}"
        )

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
        if oc.name == "praxis_notiz":
            return _oc_uebertragen(ns, task, oc)
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
        _merke_angebot_slots(task, slots)
        fakten: list[tuple[str, str]] = [("slot", str(s)) for s in slots[:3]]
        if ns.anrufer_ok is True and not _task_person(task):
            if ns.anrufer.get("anrede"):
                fakten.append(("anrede", ns.anrufer["anrede"]))
            if ns.anrufer.get("nachname"):
                fakten.append(("name", ns.anrufer["nachname"]))
        w = task.slots.get("wunschzeit")
        if w and w.wert:
            fakten.append(("wunsch", w.wert))
        if isinstance(oc.payload, dict) and oc.payload.get("exakt") is False:
            fakten.append(("naechstbestes", "1"))
        fakten.extend(_letzter_besuch_fakten(ns))
        fakten.append(("zug", str(ns.zug_nr)))
        return ns, Decision(
            naechste=Naechste.SPRECHEN,
            speak=SpeakSpec(akt=SprechAkt.ANGEBOT, fakten=tuple(fakten)),
            task=task.typ,
            grund="angebot",
        )
    if oc.status == OutcomeStatus.DENIED:
        return _terminal_task(
            ns, task, TaskStatus.GESCHEITERT,
            SpeakSpec(akt=SprechAkt.EHRLICH_KEIN),
            grund="nicht_telefonisch",
        )
    # Zeitwunsch: nie Praxisnotiz. Wunsch fallen lassen, neu fragen.
    alt = ""
    w = task.slots.get("wunschzeit")
    if w and w.wert:
        alt = w.wert
        task.merker["wunsch_verfehlt"] = alt
    task.slots.pop("wunschzeit", None)
    task.slots.pop("terminwahl", None)
    task.phase = Phase.SAMMELN
    return _frage(ns, task, "wunschzeit", grund="kein_slot_neuer_wunsch")


def _oc_commit_buchen(
    ns: State, task: TaskState, oc: ToolOutcome, spec: TaskSpec
) -> tuple[State, Decision]:
    if oc.committed:
        task.merker["warte_arzt_notiz"] = True
        task.phase = Phase.BESTAETIGEN
        return _frage(ns, task, "arzt_notiz", grund="arzt_notiz")

    if oc.status == OutcomeStatus.SLOT_TAKEN:
        task.retries["commit"] = task.retries.get("commit", 0) + 1
        if task.retries["commit"] <= spec.max_commit_retries:
            task.phase = Phase.ANGEBOT
            task.slots.pop("terminwahl", None)
            task.merker.pop("termin_gelesen", None)
            return _werkzeug(
                ns, task, spec,
                ToolCommand(name=spec.offer_tool, args=_offer_args(task), bindings=_bindings(task)),
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
        exakt = True
        if isinstance(oc.payload, dict) and oc.payload.get("exakt") is False:
            exakt = False
        if len(appts) == 1 and exakt:
            _merke_termine(ns, appts)
            _set_gefunden(task, appts[0])
            task.merker["bestand_gelesen"] = True
            task.phase = Phase.BESTAETIGEN
            fakten = list(_fakten(task, "gefunden_iso", "gefunden_arzt", "gefunden_grund"))
            fakten.extend(_plan_fakten(task))
            return ns, Decision(
                naechste=Naechste.SPRECHEN,
                speak=SpeakSpec(
                    akt=SprechAkt.RUECKLESEN,
                    fakten=tuple(fakten),
                ),
                task=task.typ,
                grund="einzel_termin",
            )
        if len(appts) > 1 or (len(appts) == 1 and not exakt):
            _merke_termine(ns, appts)
            if _ist_alle(task=task) and len(appts) > 1:
                return _mehrfach_fragen(ns, task, appts)
            task.merker["mehrere"] = True
            task.phase = Phase.ANGEBOT
            fakten = list(("option", _appt_kurz(a)) for a in appts[:3])
            w = task.slots.get("termin_hinweis") or task.slots.get("wunschzeit")
            if not exakt and w and w.wert:
                fakten.append(("wunsch_verfehlt", w.wert))
            task.zuletzt_gefragt = "auswahl"
            return ns, Decision(
                naechste=Naechste.FRAGEN,
                speak=SpeakSpec(akt=SprechAkt.FRAGE, frage_id="auswahl", fakten=tuple(fakten)),
                task=task.typ,
                grund="mehrere_termine" if exakt else "filter_naechstbestes",
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
    if task.gefuellt("besuchsgrund") or task.gefuellt("termin_hinweis") or task.gefuellt("wunschzeit"):
        task.phase = Phase.SAMMELN
        task.zuletzt_gefragt = "termin_hinweis"
        return ns, Decision(
            naechste=Naechste.SPRECHEN,
            speak=SpeakSpec(
                akt=SprechAkt.EHRLICH_KEIN,
                detail="kein_termin",
                fakten=_fakten(task, "termin_hinweis", "wunschzeit", "besuchsgrund"),
            ),
            task=task.typ,
            grund="filter_kein_termin",
        )
    if task.merker.get("abgelehnt_ids"):
        task.phase = Phase.SAMMELN
        return _frage(ns, task, "termin_hinweis", grund="nicht_dieser_hinweis")
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
        _merke_angebot_slots(task, slots)
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
    alt = ""
    w = task.slots.get("wunschzeit")
    if w and w.wert:
        alt = w.wert
        task.merker["wunsch_verfehlt"] = alt
    task.slots.pop("wunschzeit", None)
    task.slots.pop("terminwahl", None)
    return _frage(ns, task, "wunschzeit", grund="kein_neuer_slot")


def _oc_commit_verwalten(
    ns: State, task: TaskState, oc: ToolOutcome, spec: TaskSpec
) -> tuple[State, Decision]:
    if oc.committed:
        fakten = list(_fakten(task, "terminwahl") if spec.neue_zeit else _fakten(task, "gefunden_iso"))
        mehr = (task.merker.get("mehrfach_ids") or "").strip()
        if mehr:
            n = str(len([x for x in mehr.split(",") if x.strip()]))
            fakten.append(("anzahl", n))
            ag = task.slots.get("absage_grund")
            if ag and ag.wert:
                fakten.append(("absage_grund", ag.wert))
        art = "verschieben" if spec.neue_zeit else "absagen"
        nxt = None
        task.status = TaskStatus.ERLEDIGT
        task.phase = Phase.ABGESCHLOSSEN
        nxt = _naechste_geparkte(ns)
        if nxt is not None:
            nxt.status = TaskStatus.AKTIV
            _fuelle_aus_bekannt(ns, nxt)
            rolle = _task_person(nxt)
            if rolle:
                fakten.append(("weiter_rolle", rolle))
                fakten.append(("weiter_typ", nxt.typ))
        return ns, Decision(
            naechste=Naechste.SPRECHEN,
            speak=SpeakSpec(akt=SprechAkt.ERFOLG, detail=art, fakten=tuple(fakten)),
            task=task.typ,
            grund="verwaltung_belegt",
        )
    if oc.status == OutcomeStatus.SLOT_TAKEN and spec.neue_zeit:
        task.retries["commit"] = task.retries.get("commit", 0) + 1
        if task.retries["commit"] <= spec.max_commit_retries:
            task.merker.pop("neu_gelesen", None)
            task.slots.pop("terminwahl", None)
            return _werkzeug(
                ns, task, spec,
                ToolCommand(name=spec.offer_tool, args=_offer_args(task), bindings=_bindings(task)),
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
            _merke_termine(ns, appts)
            fakten = list(("termin", _appt_kurz(a)) for a in appts[:3])
            fw = task.slots.get("fuer_wen")
            if fw and fw.wert and fw.wert != "selbst":
                fakten.append(("fuer_wen", fw.wert))
                fakten.append(("gehoert_rolle", fw.wert))
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


def _oc_uebertragen(ns: State, task: TaskState, oc: ToolOutcome) -> tuple[State, Decision]:
    if oc.committed or oc.status == OutcomeStatus.OK:
        fakten = list(_fakten(task, "gefunden_iso", "gefunden_arzt", "fuer_wen", "vorname"))
        return _terminal_task(
            ns, task, TaskStatus.ERLEDIGT,
            SpeakSpec(akt=SprechAkt.ERFOLG, detail="uebertragen", fakten=tuple(fakten)),
            grund="termin_uebertragen_belegt",
        )
    return _terminal_task(
        ns, task, TaskStatus.GESCHEITERT,
        SpeakSpec(akt=SprechAkt.EHRLICH_KEIN, detail="notiz_fehler"),
        grund="uebertragen_fehler",
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
