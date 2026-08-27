from __future__ import annotations

from typing import Any

from kern import zuege
from lisa import calendar, identitaet, llm, session
from lisa.greeting import begruessung
from lisa.prompt import TOOLS, system_prompt


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _termine_zeile(past: list, upcoming: list) -> str:
    teile = []
    if upcoming:
        teile.append("Kommend: " + "; ".join(x.get("label") or "" for x in upcoming[:4]))
    if past:
        teile.append("Zuletzt: " + "; ".join(x.get("label") or "" for x in past[-3:]))
    return " | ".join(teile)


def start_reply(session_doc: dict) -> dict[str, Any]:
    tenant = session_doc["tenant"]
    patient = session_doc.get("patient") or {}
    text = begruessung(
        _s(tenant.get("praxisName")),
        _s(session_doc.get("auftrag")),
        patient=patient,
        behandler=_s(tenant.get("behandler")),
    )
    msgs = [
        {
            "role": "system",
            "content": system_prompt(
                praxis=_s(tenant.get("praxisName")),
                behandler=_s(tenant.get("behandler")),
                auftrag=_s(session_doc.get("auftrag")),
                patient=_s(patient.get("name")),
                sprache=_s(tenant.get("sprache")) or "de",
                termine_text=_termine_zeile(session_doc.get("past") or [], session_doc.get("upcoming") or []),
                slots_text=calendar.slots_zeile(session_doc.get("offered") or []),
            ),
        },
        {
            "role": "user",
            "content": "(Der Angerufene hat abgehoben. Beginne jetzt mit Begrüßung und Auftrag.)",
        },
        {"role": "assistant", "content": text},
    ]
    session_doc["messages"] = msgs
    # Identitaetscheck laeuft deterministisch, bevor das Modell dran ist.
    session_doc["idCheck"] = (
        identitaet.FRAGE if identitaet.moeglich(patient) else identitaet.FERTIG
    )
    return {"text": text, "book": None}


def user_turn(session_doc: dict, spoken: str, melde=None) -> dict[str, Any]:
    text_in = _s(spoken)
    if not text_in:
        return {"text": "", "book": None}
    msgs = list(session_doc.get("messages") or [])
    if not msgs:
        return start_reply(session_doc)
    msgs.append({"role": "user", "content": text_in})
    # Solange nicht geklaert ist, WER am Telefon sitzt, antwortet die
    # Zustandsmaschine — ohne Modell, also ohne Wartezeit und ohne Abweichen.
    id_zug = identitaet.naechster_zug(session_doc, text_in)
    if id_zug:
        msgs.append({"role": "assistant", "content": id_zug["text"]})
        session_doc["messages"] = msgs
        return {"text": id_zug["text"], "book": None}
    out = llm.chat(msgs, TOOLS)
    if not out.get("ok"):
        return {
            "text": "Einen Moment, ich komme gerade nicht an den Kalender. Darf ich später noch einmal anrufen?",
            "error": out.get("error"),
            "book": None,
        }
    # Werkzeug-Schleife und Wachen liegen im gemeinsamen Kern (kern.zuege) —
    # dieselbe Mechanik traegt auch Bianca.
    text, msgs, book = zuege.apply_tools(session_doc, msgs, out, melde=melde)
    session_doc["messages"] = msgs
    return {"text": text, "book": book}


def system_prompt_aktuell(session_doc: dict) -> str:
    tenant = session_doc["tenant"]
    patient = session_doc.get("patient") or {}
    return system_prompt(
        praxis=_s(tenant.get("praxisName")),
        behandler=_s(tenant.get("behandler")),
        auftrag=_s(session_doc.get("auftrag")),
        patient=_s(patient.get("name")),
        sprache=_s(tenant.get("sprache")) or "de",
        termine_text=_termine_zeile(session_doc.get("past") or [], session_doc.get("upcoming") or []),
        slots_text=calendar.slots_zeile(session_doc.get("offered") or []),
    )


def hangup(session_doc: dict) -> dict[str, Any]:
    return zuege.auto_notiz(session_doc, force=True)
