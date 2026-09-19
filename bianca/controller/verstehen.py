"""Verstehen: Satz + Lage -> SemanticEvent. Der Reducer liest keinen Rohtext.

Eine Schicht fuer ALLE Biancas. Mandanten schaerfen nicht das Verstehen,
sondern die Policy (welche Aufgabe, welche Pflichtfelder, Transfer, Notfall).

Reihenfolge (Chef 19.09.2026): erst Verstehen, dann die Schublade.

  1. Formular-Taste (0 ms): nacktes Ja/Nein, reine Ordinalwahl, Power-#…
     Das ist keine Semantik.
  2. Hirn ZUERST: jeder andere Satz geht an das Modell MIT der Lage.
     Das Modell liefert ausschliesslich ein SemanticEvent. Die Maschine
     feuert DANACH aus dieser Schublade — NLU fuellt und korrigiert nicht.
  3. NLU nur wenn kein Modell da ist oder das Modell wirft.

``llm`` ist ein Callable ``(text, *, lage) -> SemanticEvent``.
Dock haengt ``hirn.deuten`` (vLLM) an; Tests geben einen Stub.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any

from bianca.controller import anliegen as _anliegen
from bianca.controller import fuer_wen as _fuer_wen
from bianca.controller import hirn as _hirn
from bianca.controller import nlu_test
from bianca.controller import ordnen as _ordnen
from bianca.controller import wuensche as _wuensche
from bianca.controller.typen import Intent, Quelle, SemanticEvent, SlotValue, Verstand, replace

_VERWALTUNG = {Intent.VERSCHIEBEN, Intent.ABSAGEN}

LlmVerstehen = Callable[..., SemanticEvent | Verstand]

_NUR_JA = re.compile(
    r"^\s*(ja|genau|richtig|stimmt|jup|gerne|ok|okay|jawohl|klar|yes)\s*[.!]?\s*$",
    re.I,
)
_NUR_NEIN = re.compile(
    r"^\s*(nein|ne|n[oö]e?|nee|nicht|falsch|no)\s*[.!]?\s*$",
    re.I,
)
_NUR_WAHL = re.compile(
    r"^\s*(?:der\s+|die\s+|das\s+)?"
    r"(?:erste|zweite|dritte|letzte|1|2|3|alle|beide)\s*[.!]?\s*$",
    re.I,
)
_ALLE_RE = re.compile(
    r"\b(?:alle|beide|s(?:ae|ä)mtliche|die\s+ganzen?)\b",
    re.I,
)
_ABSAGE_RE = re.compile(r"absag|stornier|cancel|streichen|loeschen|löschen", re.I)
_UMZUG_RE = re.compile(r"umgezogen|umzug|wohnortwechsel|weggezogen", re.I)
_ANZAHL_RE = re.compile(
    r"(?:habe|haben)\s+ich\s+(?:jetzt\s+|also\s+)*(\d+|zwei|drei|vier|fuenf|fünf)\s+termine"
    r"|ich\s+habe\s+(\d+|zwei|drei|vier|fuenf|fünf)\s+termine"
    r"|(\d+|zwei|drei|vier)\s+termine\s*\?",
    re.I,
)
_ZAHL = {
    "zwei": "2", "drei": "3", "vier": "4", "fuenf": "5", "fünf": "5",
}
_ALLE_WERTE = frozenset({"alle", "beide", "saemtliche", "sämtliche"})
_WESSEN_RE = re.compile(
    r"welcher?\s+ist\s+(?:denn\s+)?von|"
    r"welcher?\s+.{0,48}gehoer|"
    r"von\s+(?:meinem|meiner|meinen|ihrem|ihren)\s+\w+\s+(?:ist|gehoer)|"
    r"gehoert?\s+zu\s+(?:meinem|meiner|ihrem|ihren)",
    re.I,
)


def _ist_formular(text: str, *, janein: bool, wahl: bool) -> bool:
    t = str(text or "").strip()
    if not t:
        return True
    if t.startswith("#"):
        return True
    if janein and (_NUR_JA.match(t) or _NUR_NEIN.match(t)):
        return True
    if wahl and _NUR_WAHL.match(t):
        return True
    return False


def _kanon_slots(ev: SemanticEvent) -> SemanticEvent:
    """Hirn-Werte in die Form bringen, die Reducer und Suche wirklich lesen."""
    slots: dict[str, SlotValue] = dict(ev.slots)
    wz = slots.get("wunschzeit")
    if wz and wz.wert:
        kanon = _wuensche.wunschzeit(wz.wert)
        if kanon:
            slots["wunschzeit"] = replace(wz, wert=kanon)
    th = slots.get("termin_hinweis")
    if th and th.wert:
        kanon = _wuensche.wunschzeit(th.wert)
        if kanon:
            slots["termin_hinweis"] = replace(th, wert=kanon)
    bg = slots.get("besuchsgrund")
    if bg and bg.wert:
        kanon = _wuensche.besuchsgrund(bg.wert)
        if kanon:
            slots["besuchsgrund"] = replace(bg, wert=kanon)
    return replace(ev, slots=slots)


def _zweit_sichern(ev: SemanticEvent, text: str) -> SemanticEvent:
    """Zwei Verben im Satz: zweite Haelfte darf nie verloren gehen.

    Fuellt nur fehlende zweit_* und holt ein irres buchen/unklar
    zurueck auf das erste Verwaltungsanliegen. Andere Hirn-Slots bleiben.
    """
    extra = _anliegen.zwei_anliegen_slots(text)
    if not extra:
        extra = _anliegen.zwei_anliegen_slots(ev.verstanden or "")
    if not extra:
        return ev
    slots = dict(ev.slots)
    for name, wert in extra.items():
        cur = slots.get(name)
        if cur is None or not cur.wert:
            slots[name] = SlotValue(wert=wert, quelle=Quelle.ABGELEITET)
    zweit_person = slots.get("zweit_fuer_wen")
    fw = slots.get("fuer_wen")
    if zweit_person and zweit_person.wert and fw and fw.wert == zweit_person.wert:
        slots.pop("fuer_wen", None)
    intent = ev.intent
    if extra.get("zweit_anliegen") and intent not in _VERWALTUNG:
        prim, _ = _anliegen.deute(text)
        if prim in _VERWALTUNG:
            intent = prim
    return replace(ev, intent=intent, slots=slots)


def _zahl(wort: str) -> str:
    w = str(wort or "").strip().lower()
    return _ZAHL.get(w, w)


def ist_umzug_wert(wert: str) -> bool:
    return bool(wert) and bool(_UMZUG_RE.search(str(wert)))


def ist_alle_wert(wert: str) -> bool:
    return str(wert or "").strip().lower() in _ALLE_WERTE


def _verwaltung_sichern(ev: SemanticEvent, text: str) -> SemanticEvent:
    """Hirn-JSON darf Alle-Absage, Umzug und Anzahlfrage nicht verlieren.

    Der Reducer oeffnet nur Schubladen, die im Event stehen. Live hat das
    Modell 'Umzug' als Besuchsgrund und 'alle' als suche_weiter geliefert —
    dann feuert die Maschine wieder 'Welchen meinen Sie?'. Hier wird das
    Gesagte festgehalten, bevor eine Schublade aufgeht.
    """
    t = str(text or "")
    slots = dict(ev.slots)
    intent = ev.intent

    bg = slots.get("besuchsgrund")
    if bg and ist_umzug_wert(bg.wert):
        slots["absage_grund"] = SlotValue(wert="umzug", quelle=Quelle.ABGELEITET)
        slots.pop("besuchsgrund", None)
    elif _UMZUG_RE.search(t):
        cur = slots.get("absage_grund")
        if cur is None or not cur.wert:
            slots["absage_grund"] = SlotValue(wert="umzug", quelle=Quelle.ABGELEITET)

    tw = slots.get("terminwahl")
    alle = bool(tw and ist_alle_wert(tw.wert))
    if tw and alle:
        slots["terminwahl"] = SlotValue(wert="alle", quelle=tw.quelle)
    elif _ALLE_RE.search(t) and (
        intent == Intent.ABSAGEN
        or _ABSAGE_RE.search(t)
        or re.fullmatch(r"\s*(?:bitte\s+)?(?:alle|beide)\s*[.!]?\s*", t, re.I)
    ):
        alle = True
        slots["terminwahl"] = SlotValue(wert="alle", quelle=Quelle.ABGELEITET)
        if intent in (Intent.UNKLAR, Intent.AUSKUNFT, Intent.SMALLTALK, Intent.BUCHEN):
            intent = Intent.ABSAGEN
    if alle:
        slots.pop("suche_weiter", None)
        if intent in (Intent.UNKLAR, Intent.AUSKUNFT, Intent.SMALLTALK):
            intent = Intent.ABSAGEN

    m = _ANZAHL_RE.search(t)
    if m and not _ABSAGE_RE.search(t) and not alle:
        n = next((g for g in m.groups() if g), "")
        n = _zahl(n)
        if n:
            slots["anzahl"] = SlotValue(wert=n, quelle=Quelle.ABGELEITET)
            if intent in (Intent.AUSKUNFT, Intent.UNKLAR, Intent.SMALLTALK, Intent.BUCHEN):
                intent = Intent.BESTAETIGEN

    return replace(ev, intent=intent, slots=slots)


def _zuordnung_sichern(ev: SemanticEvent, text: str) -> SemanticEvent:
    """„Welcher ist von meinem Mann?“ oeffnet die Zuordnungs-Schublade."""
    t = " ".join(x for x in (text, ev.verstanden) if x)
    cur = ev.slots.get("termin_zuordnung")
    if cur and cur.wert:
        slots = dict(ev.slots)
        slots.pop("fuer_wen", None)
        return replace(ev, slots=slots)
    if not _WESSEN_RE.search(t):
        return ev
    rolle = _fuer_wen.deute(t)
    if not rolle:
        return ev
    slots = dict(ev.slots)
    slots["termin_zuordnung"] = SlotValue(wert=rolle, quelle=Quelle.ABGELEITET)
    slots.pop("fuer_wen", None)
    return replace(ev, slots=slots)


def _sichern(ev: SemanticEvent, text: str) -> SemanticEvent:
    return _zuordnung_sichern(
        _verwaltung_sichern(_zweit_sichern(ev, text), text),
        text,
    )


def _nlu(
    text: str,
    *,
    offene_frage: str,
    erwartet_janein: bool,
    erwartet_wahl: bool,
    llm_notiz: str = "",
) -> SemanticEvent:
    ev = nlu_test.deuten(
        text,
        offene_frage=offene_frage,
        erwartet_janein=erwartet_janein,
        erwartet_wahl=erwartet_wahl,
    )
    return _sichern(
        replace(_kanon_slots(ev), deutung="nlu", llm=llm_notiz),
        text,
    )


def deuten(
    text: str,
    *,
    offene_frage: str = "",
    erwartet_janein: bool = False,
    erwartet_wahl: bool = False,
    lage: Mapping[str, Any] | None = None,
    llm: LlmVerstehen | None = None,
) -> SemanticEvent:
    if _ist_formular(text, janein=erwartet_janein, wahl=erwartet_wahl):
        ev = nlu_test.deuten(
            text,
            offene_frage=offene_frage,
            erwartet_janein=erwartet_janein,
            erwartet_wahl=erwartet_wahl,
        )
        return _sichern(
            replace(ev, deutung="formular", llm="— Formular, kein LLM —"),
            text,
        )
    if llm is None:
        return _nlu(
            text,
            offene_frage=offene_frage,
            erwartet_janein=erwartet_janein,
            erwartet_wahl=erwartet_wahl,
            llm_notiz="— Hirn nicht angeschlossen, NLU —",
        )
    ctx = dict(lage or {})
    ctx.setdefault("offene_frage", offene_frage)
    ctx.setdefault("erwartet_janein", erwartet_janein)
    ctx.setdefault("erwartet_wahl", erwartet_wahl)
    try:
        hirn = llm(text, lage=ctx)
    except Exception as exc:
        return _nlu(
            text,
            offene_frage=offene_frage,
            erwartet_janein=erwartet_janein,
            erwartet_wahl=erwartet_wahl,
            llm_notiz=f"— Hirn-Fehler, NLU — {exc}",
        )
    if isinstance(hirn, Verstand):
        ev = _ordnen.zu_event(hirn, lage=ctx, anrufer=text)
        ev = replace(ev, deutung="hirn", llm=hirn.llm or ev.llm, verstanden=hirn.verstanden)
    elif isinstance(hirn, SemanticEvent):
        ev = hirn
        if not ev.verstanden and ev.roh:
            ev = replace(ev, verstanden="")
    else:
        return _nlu(
            text,
            offene_frage=offene_frage,
            erwartet_janein=erwartet_janein,
            erwartet_wahl=erwartet_wahl,
            llm_notiz="— Hirn lieferte kein Verstehen, NLU —",
        )
    ev = _hirn.ohne_alte_wiederholung(ev, ctx)
    return _sichern(_kanon_slots(replace(ev, deutung=ev.deutung or "hirn")), text)


__all__ = ["deuten", "LlmVerstehen", "ist_umzug_wert", "ist_alle_wert"]
