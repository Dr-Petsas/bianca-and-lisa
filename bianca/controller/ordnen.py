"""Freies Verstehen -> Fakten ordnen und Schublade oeffnen.

Das Modell darf keine Intent-Liste sehen. Hier wird aus ``verstanden``
und ``genannt`` die Aufgabe gewaehlt. Der Renderer spricht den
Verstehenssatz nie — nur belegte Fakten.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from bianca.controller import anliegen as _anliegen
from bianca.controller import fuer_wen as _fw
from bianca.controller.typen import (
    Intent,
    Quelle,
    SemanticEvent,
    SlotValue,
    Verstand,
)

_ALIAS = {
    "zeit": "wunschzeit", "wanne": "wunschzeit", "wann": "wunschzeit",
    "datum": "wunschzeit", "zeitraum": "wunschzeit", "wunsch": "wunschzeit",
    "grund": "besuchsgrund", "motiv": "besuchsgrund", "besuch": "besuchsgrund",
    "arzt": "behandler", "doktor": "behandler",
    "name": "nachname", "handy": "telefon", "nummer": "telefon",
    "hinweis": "termin_hinweis", "tag": "termin_hinweis",
    "transfer": "uebertragen", "uebergabe": "uebertragen",
    "person": "fuer_wen", "rolle": "fuer_wen",
    "wer": "fuer_wen", "beziehung": "fuer_wen",
    "betroffene": "fuer_wen", "betroffene_person": "fuer_wen",
    "bezugsperson": "termin_zuordnung", "wessen": "termin_zuordnung",
    "zweites": "zweit_anliegen", "zweites_anliegen": "zweit_anliegen",
    "zweit_fuer": "zweit_fuer_wen", "zweite_person": "zweit_fuer_wen",
    "absagegrund": "absage_grund", "warum_absage": "absage_grund",
    "menge": "anzahl", "wieviele": "anzahl", "anzahl": "anzahl",
    "kanal": "sms", "sms": "sms",
}

_SLOTS = frozenset({
    "schonmal", "behandler", "besuchsgrund", "wunschzeit",
    "nachname", "vorname", "versicherung", "telefon",
    "fuer_wen", "terminwahl", "termin_hinweis", "termin_zuordnung",
    "uebertragen", "suche_weiter", "auskunft_art",
    "zweit_anliegen", "zweit_fuer_wen",
    "absage_grund", "anzahl", "sms",
})

_SMS_RE = re.compile(
    r"sms|best(?:ae|ä)tig\w*|nachricht\s+auf\s+s\s*handy",
    re.I,
)
_DOKUMENT_RE = re.compile(
    r"\brezept(?!ion)|ueberweis|überweis|krankmeldung|unterlagen|befund|"
    r"r(?:oe|ö)ntgen",
    re.I,
)
_NEU_RE = re.compile(r"\bneu(?:en)?\s+termin|vereinbaren|buchen\b", re.I)
_WISSEN_RE = re.compile(
    r"erfahr\w*|nachschau\w*|nachseh\w*|nachguck\w*|"
    r"wissen\s*(?:wann|ob|welchen|wie)|wissenwann|"
    r"genauen?\s+termin|"
    r"wann\s+(?:der|die|das|ihr|sein)\s+termin",
    re.I,
)
_WESSEN_RE = re.compile(
    r"welcher?\s+ist\s+(?:denn\s+)?von|"
    r"welcher?\s+.{0,48}gehoer|"
    r"von\s+(?:meinem|meiner|meinen|ihrem|ihren)\s+\w+\s+(?:ist|gehoer)|"
    r"gehoert?\s+zu\s+(?:meinem|meiner|ihrem|ihren)",
    re.I,
)


def _falt(s: str) -> str:
    return (
        (s or "")
        .lower()
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )


def _thema(v: Verstand) -> str:
    teile = [v.verstanden, v.roh]
    for k, val in (v.genannt or {}).items():
        teile.append(str(k))
        teile.append(str(val))
    return _falt(" ".join(teile))


def _slots_von_genannt(genannt: Mapping[str, Any]) -> dict[str, SlotValue]:
    slots: dict[str, SlotValue] = {}
    for k, raw in (genannt or {}).items():
        name = _ALIAS.get(str(k).strip().lower(), str(k).strip())
        wert = str(raw or "").strip()
        if name not in _SLOTS or not wert:
            continue
        if name == "sms" and wert.lower() not in ("nein", "0", "false"):
            wert = "ja"
        if name == "fuer_wen":
            wert = _fw.kanon(wert)
            if not wert or wert in ("anrufer", "selbst", "ich"):
                continue
        slots[name] = SlotValue(wert=wert, quelle=Quelle.GESAGT)
    return slots


def _will_sms(v: Verstand, lage: Mapping[str, Any] | None) -> bool:
    t = _thema(v)
    if _DOKUMENT_RE.search(t) and not _SMS_RE.search(t):
        return False
    if _SMS_RE.search(t):
        return True
    write = str((lage or {}).get("letzter_write") or "").strip()
    if write and _SMS_RE.search(t):
        return True
    if write and v.hint in ("bestaetigen", "dokument", "praxisinfo", "unklar"):
        return True
    if write and v.janein is True and not (lage or {}).get("erwartet_janein"):
        return True
    return False


def _intent_von_hint(hint: str) -> Intent | None:
    h = str(hint or "").strip().lower()
    if not h:
        return None
    for i in Intent:
        if i.value == h:
            return i
    return None


def zu_event(
    v: Verstand,
    *,
    lage: Mapping[str, Any] | None = None,
    anrufer: str = "",
) -> SemanticEvent:
    """Schublade aus dem freien Verstehen, nicht aus einer Prompt-Liste."""
    lage = dict(lage or {})
    task = str(lage.get("task") or "").strip()
    slots = _slots_von_genannt(v.genannt)
    verstanden = (v.verstanden or "").strip()
    text = " ".join(x for x in (verstanden, v.roh, anrufer) if x)
    janein = v.janein
    kf = v.korrektur_feld if v.korrektur_feld in _SLOTS else ""
    if "fuer_wen" not in slots:
        rolle = _fw.deute(text)
        if rolle and rolle != "selbst":
            slots["fuer_wen"] = SlotValue(wert=rolle, quelle=Quelle.ABGELEITET)

    if _will_sms(v, lage):
        slots["sms"] = SlotValue(wert="ja", quelle=Quelle.ABGELEITET)
        return SemanticEvent(
            intent=Intent.PRAXISINFO,
            slots=slots,
            bestaetigung=None,
            korrektur_feld="",
            roh=(v.roh or anrufer)[:120],
            llm=v.llm,
            verstanden=verstanden,
        )

    tz = slots.get("termin_zuordnung")
    if (tz and tz.wert) or _WESSEN_RE.search(_falt(text)):
        if not tz or not tz.wert:
            rolle = _fw.deute(text)
            if rolle:
                slots["termin_zuordnung"] = SlotValue(
                    wert=rolle, quelle=Quelle.ABGELEITET,
                )
        slots.pop("fuer_wen", None)
        keep = _intent_von_hint(task) if task in (
            "absagen", "verschieben", "auskunft",
        ) else None
        if keep is not None and slots.get("termin_zuordnung"):
            return SemanticEvent(
                intent=keep,
                slots=slots,
                bestaetigung=janein,
                korrektur_feld=kf,
                roh=(v.roh or anrufer)[:120],
                llm=v.llm,
                verstanden=verstanden,
            )

    hint = _intent_von_hint(v.hint)
    if kf or hint == Intent.KORREKTUR:
        return SemanticEvent(
            intent=Intent.KORREKTUR,
            slots=slots,
            bestaetigung=janein,
            korrektur_feld=kf,
            roh=(v.roh or anrufer)[:120],
            llm=v.llm,
            verstanden=verstanden,
        )

    # Altes JSON mit intent, ohne Verstehenssatz: Schublade bleibt Kompatibilitaet.
    if not verstanden and hint is not None:
        return SemanticEvent(
            intent=hint,
            slots=slots,
            bestaetigung=janein,
            korrektur_feld=kf,
            roh=(v.roh or anrufer)[:120],
            llm=v.llm,
            verstanden=verstanden,
        )

    prim, extra = _anliegen.deute(verstanden) if verstanden else (None, {})
    if prim is None:
        prim, extra = _anliegen.deute(v.roh or anrufer)
    for name, wert in extra.items():
        if name in _SLOTS and name not in slots:
            slots[name] = SlotValue(wert=wert, quelle=Quelle.ABGELEITET)

    intent = prim
    if _WISSEN_RE.search(_falt(verstanden or text)) and intent not in (
        Intent.ABSAGEN, Intent.VERSCHIEBEN, Intent.DOKUMENT, Intent.NOTFALL,
    ):
        intent = Intent.AUSKUNFT
        if "auskunft_art" not in slots:
            slots["auskunft_art"] = SlotValue(wert="bestand", quelle=Quelle.ABGELEITET)
    if intent is None and hint not in (None, Intent.DOKUMENT, Intent.BESTAETIGEN):
        intent = hint
    if intent is None and janein is not None:
        intent = Intent.BESTAETIGEN
    if intent is None and task in ("absagen", "verschieben", "buchen") and not _NEU_RE.search(_falt(text)):
        intent = _intent_von_hint(task)
    if intent is None:
        intent = Intent.UNKLAR

    return SemanticEvent(
        intent=intent,
        slots=slots,
        bestaetigung=janein,
        korrektur_feld=kf,
        roh=(v.roh or anrufer)[:120],
        llm=v.llm,
        verstanden=verstanden,
    )


__all__ = ["zu_event"]
