"""Semantische Task-Auswahl im bestehenden Haupt-LLM-Lauf.

Wenn noch keine deterministische Maschine zuständig ist, bekommt das Modell
keine Kalender-Aktionswerkzeuge. Es darf stattdessen genau eine Aufgabe an
den FlowManager übergeben. So bleibt die Bedeutung beim LLM, während Modus,
Pflichtfragen und alle Schreibaktionen weiter deterministisch laufen.

Kein zusätzlicher LLM-Aufruf: ``select_task`` wird im ohnehin nötigen
Antwortlauf angeboten. Praxisinfo und Smalltalk beantwortet das Modell ohne
Tool. Kalender lesen/schreiben ist vor einer Task-Zuordnung unmöglich.
"""

from __future__ import annotations

import json
from typing import Any

from kern import hirn

OPERATIONEN = {
    "buchen", "absagen", "verschieben", "terminauskunft", "verbinden", "rueckruf",
}

PROMPT = """TASK-AUSWAHL
Es läuft noch keine sichere Fachaufgabe. Erkennst du ein Termin-, Weiterleitungs-
oder Rückrufanliegen, rufe select_task auf. Das ist eine Übergabe, keine
Erledigung. „Ich möchte zur Kontrolle/Zahnreinigung“ bedeutet buchen, auch ohne
das Wort Termin. Bestehende Termine darfst du nur bei einer ausdrücklichen
Auskunfts-, Absage- oder Verschiebeanfrage erwähnen. Praxiswissen und Smalltalk
beantwortest du direkt ohne Tool."""

TOOLS = [{
    "type": "function",
    "function": {
        "name": "select_task",
        "description": (
            "Übergibt ein erkanntes Anliegen an den sicheren FlowManager. "
            "Nutze buchen auch für natürliche Formulierungen ohne das Wort Termin, "
            "zum Beispiel 'ich möchte zur Kontrolle', 'ich muss zur Zahnreinigung' "
            "oder 'ich brauche etwas wegen Schmerzen'. terminauskunft gilt nur, "
            "wenn nach einem bereits bestehenden Termin gefragt wird. Praxisfragen "
            "und Smalltalk beantwortest du direkt ohne Tool."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": sorted(OPERATIONEN),
                    "description": "Die fachfreie Aufgabe des Anrufers.",
                },
                "reason": {
                    "type": "string",
                    "description": "Kurze Paraphrase des Gesagten, keine erfundenen Fakten.",
                },
            },
            "required": ["operation", "reason"],
        },
    },
}]

_HIRN = {
    "buchen": ("ANLEGEN", "VORGANG", None),
    "absagen": ("AENDERN", "VORGANG", False),
    "verschieben": ("AENDERN", "VORGANG", True),
    "terminauskunft": ("WISSEN", "VORGANG", None),
    "verbinden": ("ERREICHEN", "PERSON", None),
    "rueckruf": ("ABGEBEN", "SACHE", None),
}


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def braucht_auswahl(sit: dict[str, Any]) -> bool:
    s = sit.get("sammler") if isinstance(sit.get("sammler"), dict) else {}
    return not _s(s.get("modus")) and not sit.get("hirnVerbinden") and not sit.get("hirnAbgeben")


def auswahl(llm_out: dict[str, Any] | None) -> dict[str, str]:
    """Validierten select_task-Call aus einem normalen LLM-Ergebnis lesen."""
    for call in (llm_out or {}).get("tool_calls") or []:
        fn = call.get("function") if isinstance(call, dict) else {}
        if not isinstance(fn, dict) or _s(fn.get("name")) != "select_task":
            continue
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except (TypeError, ValueError):
            return {}
        op = _s(args.get("operation")).lower()
        reason = _s(args.get("reason"))
        if op in OPERATIONEN and reason:
            return {"operation": op, "reason": reason[:180]}
    return {}


def anwenden(sit: dict[str, Any], wahl: dict[str, str], *, original: str = "") -> bool:
    """Task ins Session-Hirn übergeben; führt selbst kein Werkzeug aus."""
    op = _s(wahl.get("operation")).lower()
    if op not in _HIRN:
        return False
    handlung, gegenstand, ersatz = _HIRN[op]
    spiegel = _s(wahl.get("reason")) or _s(original)
    deutung: dict[str, Any] = {
        "kanal": "ok",
        "zug": "wechseln",
        "handlung": handlung,
        "gegenstand": gegenstand,
        "spiegel": spiegel,
        "quelle": "llm_task_router",
    }
    if isinstance(ersatz, bool):
        deutung["ersatz"] = ersatz
    ergebnis = hirn.anwenden(sit, deutung)
    sit.setdefault("taskRouter", []).append({
        "operation": op,
        "reason": spiegel[:180],
        "anliegenId": _s((ergebnis.get("anliegen") or {}).get("id")),
        "quelle": "haupt_llm",
    })
    sit["taskRouter"] = sit["taskRouter"][-12:]
    return True
