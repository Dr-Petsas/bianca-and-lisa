"""Semantische Task-Auswahl im bestehenden Haupt-LLM-Lauf.

Das Modell bekommt keine direkten Kalender-Aktionswerkzeuge. Es darf eine
Aufgabe an den FlowManager übergeben oder ein Nebenthema natürlich beantworten.
So bleibt die Bedeutung beim LLM, während Modus, Pflichtfragen und sämtliche
Kalenderaktionen weiter deterministisch laufen.

Kein zusätzlicher LLM-Aufruf: ``select_task`` wird im ohnehin nötigen
Antwortlauf angeboten. Praxisinfo und Smalltalk beantwortet das Modell ohne
Tool. Kalender lesen/schreiben ist vor einer Task-Zuordnung unmöglich.
"""

from __future__ import annotations

import json
import os
from typing import Any

from kern import hirn, werkzeuge

OPERATIONEN = {
    "buchen", "absagen", "verschieben", "terminauskunft", "verbinden", "rueckruf",
}

PROMPT = """TASK-AUSWAHL
Erkennst du ein neues Termin-, Weiterleitungs- oder Rückrufanliegen, rufe
select_task auf. Das ist nur eine Übergabe an den sicheren FlowManager, niemals
eine Erledigung. „Ich möchte zur Kontrolle/Zahnreinigung“ bedeutet buchen, auch
ohne das Wort Termin. Bestehende Termine darfst du nur bei einer ausdrücklichen
Auskunfts-, Absage- oder Verschiebeanfrage erwähnen. Antworten auf die laufende
Pflichtfrage sind KEIN neuer Task. Praxiswissen, Rückfragen und Smalltalk
beantwortest du direkt ohne Tool; der Gesprächsplan führt danach zur laufenden
Aufgabe zurück. Du behauptest keine Kalenderaktion selbst."""

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

_MODUS_OPERATION = {
    "buchen": "buchen",
    "absagen": "absagen",
    "verschieben": "verschieben",
    "auskunft": "terminauskunft",
}


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def enabled() -> bool:
    return os.environ.get("TASK_ROUTER", "1").strip().lower() not in {
        "0", "false", "no",
    }


def braucht_auswahl(sit: dict[str, Any]) -> bool:
    """Kompatibilitätsname: Router gilt jetzt auch während laufender Tasks."""
    return enabled()


def prompt(sit: dict[str, Any]) -> str:
    s = sit.get("sammler") if isinstance(sit.get("sammler"), dict) else {}
    modus = _s(s.get("modus"))
    frage = _s(s.get("frage"))
    if not modus:
        stand = "Aktuell läuft noch keine sichere Fachaufgabe."
    else:
        op = _MODUS_OPERATION.get(modus, modus)
        stand = f"Aktuell läuft die Aufgabe {op}."
        if frage:
            stand += f" Offener Dialogschritt: {frage}."
        stand += (
            " Nur bei einem klar anderen Anliegen select_task aufrufen; "
            "die bisherige Aufgabe wird dann geparkt."
        )
    return f"{PROMPT}\n{stand}"


def _hat_gebuchten_termin(sit: dict[str, Any]) -> bool:
    s = sit.get("sammler") if isinstance(sit.get("sammler"), dict) else {}
    booking = sit.get("booking") if isinstance(sit.get("booking"), dict) else {}
    last = sit.get("lastBook") if isinstance(sit.get("lastBook"), dict) else {}
    return bool(
        _s(s.get("phase")) == "gebucht"
        or _s(booking.get("appointmentId"))
        or _s(last.get("appointmentId"))
    )


def werkzeuge_fuer(sit: dict[str, Any]) -> list[dict[str, Any]]:
    """Nur Task-Handoff; nach echter Buchung zusätzlich sichere Terminnotiz."""
    out = list(TOOLS)
    if _hat_gebuchten_termin(sit):
        note = next(
            (
                tool for tool in werkzeuge.TOOLS
                if _s((tool.get("function") or {}).get("name")) == "note_appointment"
            ),
            None,
        )
        if note:
            out.append(note)
    return out


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
    if op == "buchen":
        # Der Satz wurde vor der semantischen Zuordnung bereits einmal vom
        # Sammler gelesen. Beim zweiten Durchlauf direkt zur ersten fehlenden
        # Pflichtfrage gehen, nicht als Zwischenfrage oder Upsell behandeln.
        sit["taskHandoff"] = "buchen"
    sit.setdefault("taskRouter", []).append({
        "operation": op,
        "reason": spiegel[:180],
        "anliegenId": _s((ergebnis.get("anliegen") or {}).get("id")),
        "quelle": "haupt_llm",
    })
    sit["taskRouter"] = sit["taskRouter"][-12:]
    return True
