from __future__ import annotations

import json
from typing import Any

from lisa import calendar, llm, notes, session
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
    text = begruessung(_s(tenant.get("praxisName")), _s(session_doc.get("auftrag")))
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
    return {"text": text, "book": None}


def user_turn(session_doc: dict, spoken: str, melde=None) -> dict[str, Any]:
    text_in = _s(spoken)
    if not text_in:
        return {"text": "", "book": None}
    msgs = list(session_doc.get("messages") or [])
    if not msgs:
        return start_reply(session_doc)
    msgs.append({"role": "user", "content": text_in})
    out = llm.chat(msgs, TOOLS)
    if not out.get("ok"):
        return {
            "text": "Einen Moment, ich komme gerade nicht an den Kalender. Darf ich später noch einmal anrufen?",
            "error": out.get("error"),
            "book": None,
        }
    text, msgs, book = _apply_tools(session_doc, msgs, out, melde=melde)
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
    return _auto_notiz(session_doc, force=True)


def _run_tool(session_doc: dict, name: str, args: dict) -> dict[str, Any]:
    tenant = session_doc["tenant"]
    ctx = session_doc.get("booking") or {}
    if name == "list_appointments":
        return calendar.list_appointments(tenant, ctx, session_doc.get("upcoming") or [], sit=session_doc)
    if name == "offer_slots":
        result = calendar.offer_slots(tenant, ctx, wish_text=_s(args.get("wish")))
        if result.get("slots"):
            session_doc["offered"] = result["slots"]
        return result
    if name == "create_patient":
        return calendar.create_patient(
            tenant, ctx, session_doc,
            first=_s(args.get("first") or args.get("firstName")),
            last=_s(args.get("last") or args.get("lastName")),
            phone=_s(args.get("phone") or args.get("mobile") or args.get("handy")),
            birth=_s(args.get("birth") or args.get("birthDate")),
            gender=_s(args.get("gender")),
        )
    if name == "book_slot":
        return calendar.book_slot(tenant, ctx, slot_iso=_s(args.get("slot_iso")))
    if name == "cancel_appointment":
        return calendar.cancel_appointment(tenant, ctx, date=_s(args.get("date")))
    if name == "move_appointment":
        result = calendar.move_appointment(
            tenant, ctx,
            slot_iso=_s(args.get("slot_iso")),
            date=_s(args.get("date")),
            wish=_s(args.get("wish")),
        )
        if result.get("appointmentId"):
            ctx["appointmentId"] = result["appointmentId"]
        if result.get("slots"):
            session_doc["offered"] = result["slots"]
        return result
    if name == "note_appointment":
        return calendar.note_appointment(tenant, ctx, session_doc, note=_s(args.get("note")))
    return {"ok": False, "spoken": "Dieses Werkzeug kenne ich hier nicht."}


def _auto_notiz(session_doc: dict, *, force: bool = False) -> dict[str, Any]:
    if session_doc.get("noteWritten") and not force:
        return session_doc.get("lastNote") or {}
    if not notes.braucht_notiz(session_doc):
        return {}
    if session_doc.get("noteWritten") and force:
        extra = notes.zusammenfassung(session_doc)
        schon = _s((session_doc.get("lastNote") or {}).get("note"))
        if extra and extra.lower() in schon.lower():
            return session_doc.get("lastNote") or {}
    result = calendar.note_appointment(
        session_doc["tenant"],
        session_doc.get("booking") or {},
        session_doc,
        note=notes.zusammenfassung(session_doc),
    )
    if result.get("ok"):
        session.merke_tool(session_doc, "note_appointment", result)
    return result


def _apply_tools(session_doc: dict, msgs: list, first: dict, melde=None) -> tuple[str, list, dict | None]:
    calls = first.get("tool_calls") or []
    text = _s(first.get("text"))
    book = None
    if not calls:
        if text:
            msgs.append({"role": "assistant", "content": text})
        return text, msgs, None

    if melde:
        # Dem Anrufer JETZT einen Füller vorspielen — die Werkzeuge brauchen gleich Netz-Zeit.
        erster = _s(((calls[0].get("function") or {}).get("name")))
        try:
            melde(erster)
        except Exception:
            pass

    msgs.append({
        "role": "assistant",
        "content": text or None,
        "tool_calls": calls,
    })
    spoken = ""
    for call in calls:
        fn = (call.get("function") or {})
        name = _s(fn.get("name"))
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        result = _run_tool(session_doc, name, args)
        if name == "book_slot":
            book = {
                "booked": bool(result.get("booked")),
                "dryRun": bool(result.get("dryRun")),
                "slotIso": result.get("slotIso") or "",
                "spoken": result.get("spoken") or "",
            }
        session.merke_tool(session_doc, name, result)
        if name != "note_appointment":
            spoken = _s(result.get("spoken")) or spoken
        elif not spoken:
            spoken = "Gut, das merke ich für Ihren Termin."
        msgs.append({
            "role": "tool",
            "tool_call_id": call.get("id") or name,
            "content": json.dumps(result, ensure_ascii=False),
        })
    if spoken:
        msgs.append({"role": "assistant", "content": spoken})
        return spoken, msgs, book
    if text:
        return text, msgs, book
    follow = llm.chat(msgs, TOOLS, max_tokens=80)
    spoken = _s(follow.get("text"))
    if spoken:
        msgs.append({"role": "assistant", "content": spoken})
    return spoken, msgs, book
