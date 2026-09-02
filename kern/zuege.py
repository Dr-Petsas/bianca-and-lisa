"""Werkzeug-Schleife des Sprachmodells + Wachen — geteilt von Lisa und Bianca.

Hierhin gezogen aus lisa/agent.py (27.08.2026), unverändert in der Sache:
  - run_tool:        ein Werkzeug-Aufruf gegen kern.calendar
  - apply_tools:     Tool-Calls des Modells ausführen, Antwort bauen
  - buchungs_wache:  Zusage ohne Werkzeug abfangen (Vorfall 27.08.2026)
  - auto_notiz:      Gesprächsnotiz/Protokoll in den Termin schreiben

Die Stimme (Lisa/Bianca) steckt in sit["stimme"] — nur für Log-Präfixe.
"""

from __future__ import annotations

import json
import re
from typing import Any

from kern import calendar, llm, notes
from kern.sitzung import merke_tool
from kern.werkzeuge import TOOLS


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _wer(sit: dict) -> str:
    return (_s(sit.get("stimme")) or "Lisa").lower()


def run_tool(sit: dict, name: str, args: dict) -> dict[str, Any]:
    tenant = sit["tenant"]
    ctx = sit.get("booking") or {}
    if name == "list_appointments":
        return calendar.list_appointments(tenant, ctx, sit.get("upcoming") or [], sit=sit)
    if name == "offer_slots":
        result = calendar.offer_slots(tenant, ctx, wish_text=_s(args.get("wish")))
        if result.get("slots"):
            sit["offered"] = result["slots"]
        return result
    if name == "create_patient":
        return calendar.create_patient(
            tenant, ctx, sit,
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
            sit["offered"] = result["slots"]
        return result
    if name == "note_appointment":
        return calendar.note_appointment(tenant, ctx, sit, note=_s(args.get("note")))
    return {"ok": False, "spoken": "Dieses Werkzeug kenne ich hier nicht."}


def auto_notiz(sit: dict, *, force: bool = False) -> dict[str, Any]:
    if sit.get("noteWritten") and not force:
        return sit.get("lastNote") or {}
    if force and sit.get("hangupNotiert"):
        # Doppelter Auflege-Aufruf (Client-Retry/Reload) schrieb live am
        # 27.08.2026 die Notiz ZWEIMAL in den Termin — einmal reicht.
        return sit.get("lastNote") or {}
    if not notes.braucht_notiz(sit):
        return {}
    if force:
        sit["hangupNotiert"] = True
    # Minimale, deterministische Notiz (Chef 27.08.2026) — identische Zeilen
    # filtert masAppointmentNote serverseitig (zeilen-idempotent) zusätzlich.
    text = notes.termin_notiz(sit) if force else notes.zusammenfassung(sit)
    if not _s(text):
        return {}
    result = calendar.note_appointment(
        sit["tenant"],
        sit.get("booking") or {},
        sit,
        note=text,
    )
    if result.get("ok"):
        merke_tool(sit, "note_appointment", result)
    return result


def apply_tools(sit: dict, msgs: list, first: dict, melde=None) -> tuple[str, list, dict | None]:
    calls = first.get("tool_calls") or []
    text = _s(first.get("text"))
    book = None
    if not calls:
        gerettet, book = buchungs_wache(sit, text, melde=melde)
        if gerettet:
            msgs.append({"role": "assistant", "content": gerettet})
            return gerettet, msgs, book
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
        result = run_tool(sit, name, args)
        if name == "book_slot":
            book = {
                "booked": bool(result.get("booked")),
                "dryRun": bool(result.get("dryRun")),
                "slotIso": result.get("slotIso") or "",
                "spoken": result.get("spoken") or "",
            }
        merke_tool(sit, name, result, args=args if isinstance(args, dict) else None)
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


# Vorfall 27.08.2026: Das Modell sagte "dann buche ich Ihnen heute um neun Uhr
# fünfzehn" OHNE book_slot aufzurufen — der Kalender blieb leer, der Patient
# haette sich auf einen Termin verlassen, den es nicht gibt. Eine Zusage ohne
# Werkzeug darf den Mund nie erreichen.
_BUCH_ZUSAGE = re.compile(
    r"(buche\s+ich|ich\s+buche|reserviere\s+ich|ich\s+reserviere|"
    r"(?:ich\s+trage|trage\s+ich)\s+(?:Sie|das|ihn|den|Ihren)\b|"
    r"habe\s+ich\s+eingetragen|"
    r"ist\s+(?:gebucht|eingetragen|reserviert|fest\s+eingetragen))",
    re.I,
)


def zusage_ohne_werkzeug(text: str) -> bool:
    for satz in re.split(r"(?<=[.!?])\s+", _s(text)):
        s = _s(satz)
        if s and not s.endswith("?") and _BUCH_ZUSAGE.search(s):
            return True
    return False


def gemeinter_slot(text: str, offered: list) -> str:
    """Welchen der angebotenen Termine meint der Satz?"""
    t = _s(text).lower()
    for x in offered:
        gesagt = _s(x.get("spoken")).lower()
        if gesagt and gesagt in t:
            return _s(x.get("iso"))
    if len(offered) == 1:
        return _s(offered[0].get("iso"))
    return ""


def buchungs_wache(sit: dict, text: str, melde=None) -> tuple[str, dict | None]:
    """Zusage ohne Werkzeug: entweder wirklich buchen oder nachfragen."""
    if not zusage_ohne_werkzeug(text):
        return "", None
    offered = [x for x in (sit.get("offered") or []) if isinstance(x, dict)]
    iso = gemeinter_slot(text, offered)
    print(f"{_wer(sit)}-buchwache: Zusage ohne Werkzeug, iso={iso or '-'} text={text!r}", flush=True)
    if not iso:
        return (
            "Einen Moment — welchen Termin darf ich fest eintragen?",
            None,
        )
    if melde:
        try:
            melde("book_slot")
        except Exception:
            pass
    result = run_tool(sit, "book_slot", {"slot_iso": iso})
    merke_tool(sit, "book_slot", result)
    book = {
        "booked": bool(result.get("booked")),
        "dryRun": bool(result.get("dryRun")),
        "slotIso": result.get("slotIso") or iso,
        "spoken": result.get("spoken") or "",
    }
    return _s(result.get("spoken")), book
