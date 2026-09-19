"""Hirn: freier Verstehensvorlauf. Keine Schublade, kein Bianca-Satz.

Das Modell sagt nur, was der Anrufer will. ``ordnen`` waehlt danach
die Fakten und die Aufgabe. Tests stummen den Haken; das Dock haengt
``deuten`` an vLLM.
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

from bianca.controller.typen import SemanticEvent, Verstand, replace

_JSON = re.compile(r"\{.*\}", re.S)

_SYSTEM = """\
Du verstehst den Anrufer. Du waehlst keine Aktion und keine Antwort.

Nur EIN JSON:
  verstanden: ein Satz in deinen Worten — was die Person JETZT will,
              bezogen auf die Lage (letzter Satz, letzter Vorgang)
  janein: true | false | null
  genannt: freie Schluessel fuer konkret Genanntes
           (wer, wann, warum, wieviele, kanal, … — keine Pflichtliste)

Kein intent. Kein Tool. Kein Bianca-Satz. Nichts erfinden.
Zwei Anliegen in einem Satz: beide in verstanden nennen, in genannt trennen.
"""


def lage_block(lage: Mapping[str, Any] | None) -> str:
    d = dict(lage or {})
    zeilen = [
        f"offene_frage: {d.get('offene_frage') or '—'}",
        f"erwartet_janein: {bool(d.get('erwartet_janein'))}",
        f"erwartet_wahl: {bool(d.get('erwartet_wahl'))}",
        f"aufgabe: {d.get('task') or '—'}",
        f"phase: {d.get('phase') or '—'}",
    ]
    slots = d.get("slots") or {}
    if isinstance(slots, dict) and slots:
        zeilen.append("bekannt: " + ", ".join(f"{k}={v}" for k, v in slots.items() if v))
    angebot = d.get("angebot") or []
    if angebot:
        zeilen.append("angebot: " + " | ".join(str(x) for x in angebot[:5]))
    letzter = (d.get("letzter_satz") or "").strip()
    if letzter:
        zeilen.append("letzter_assistentensatz: " + letzter[:240])
    n = d.get("termine_n")
    if n:
        zeilen.append(f"vorgelesene_termine: {n}")
    write = str(d.get("letzter_write") or "").strip()
    if write:
        zeilen.append(f"letzter_vorgang: {write}")
    return "\n".join(zeilen)


def verstand_aus_json(roh: str, *, anrufer: str = "") -> Verstand | None:
    m = _JSON.search(roh or "")
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    janein = data.get("janein", data.get("bestaetigung", None))
    if janein not in (True, False, None):
        janein = None
    genannt: dict[str, str] = {}
    roh_genannt = data.get("genannt")
    if not isinstance(roh_genannt, dict):
        roh_genannt = data.get("slots") or {}
    if isinstance(roh_genannt, dict):
        for k, v in roh_genannt.items():
            if str(v or "").strip():
                genannt[str(k).strip()] = str(v).strip()
    verstanden = str(
        data.get("verstanden") or data.get("bezug") or ""
    ).strip()
    return Verstand(
        verstanden=verstanden,
        janein=janein,
        genannt=genannt,
        korrektur_feld=str(data.get("korrektur_feld") or "").strip(),
        hint=str(data.get("intent") or data.get("hint") or "").strip().lower(),
        roh=(anrufer or "")[:120],
        llm=(roh or "")[:400],
    )


def event_aus_json(roh: str, *, anrufer: str = "", lage: Mapping[str, Any] | None = None) -> SemanticEvent | None:
    """Kompatibilitaet: JSON -> Verstand -> geordnetes Event."""
    v = verstand_aus_json(roh, anrufer=anrufer)
    if v is None:
        return None
    from bianca.controller.ordnen import zu_event
    return zu_event(v, lage=lage, anrufer=anrufer)


def ohne_alte_wiederholung(
    ev: SemanticEvent, lage: Mapping[str, Any] | None
) -> SemanticEvent:
    """Bekannten Slot-Wert zurueckkopieren ist kein neuer Inhalt."""
    bekannt = (lage or {}).get("slots") or {}
    if not ev.korrektur_feld or not isinstance(bekannt, dict):
        return ev
    sv = ev.slots.get(ev.korrektur_feld)
    alt = bekannt.get(ev.korrektur_feld)
    if not sv or not alt:
        return ev
    if str(sv.wert).strip().lower() != str(alt).strip().lower():
        return ev
    slots = dict(ev.slots)
    slots.pop(ev.korrektur_feld, None)
    return replace(ev, slots=slots)


def deuten(text: str, *, lage: Mapping[str, Any] | None = None, **_: Any) -> Verstand:
    """Freier Vorlauf gegen vLLM. Wirft bei Netz-/Parsefehler."""
    from kern import llm as _llm

    messages = [
        {"role": "system", "content": _SYSTEM},
        {
            "role": "user",
            "content": (
                "Lage:\n" + lage_block(lage) + "\n\nAnrufer: " + str(text or "").strip()
            ),
        },
    ]
    r = _llm.chat(messages, tools=None, temperature=0.0, max_tokens=220)
    roh_llm = str(r.get("text") or "").strip()
    if not r.get("ok"):
        raise RuntimeError(r.get("error") or "hirn_offline")
    v = verstand_aus_json(roh_llm, anrufer=text)
    if v is None:
        raise RuntimeError("hirn_kein_json: " + roh_llm[:180])
    return replace(v, llm=roh_llm)


__all__ = [
    "deuten", "event_aus_json", "verstand_aus_json",
    "lage_block", "ohne_alte_wiederholung",
]
