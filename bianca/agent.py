"""Biancas Zug-Logik: Zustandsmaschine zuerst, Sprachmodell nur als Beifahrer.

Jeder Anrufer-Satz geht durch flow.zug() — deterministisch, ohne Modell-Latenz.
Nur wenn der Fluss abgibt (Zwischenfrage, Absage/Verschieben, Smalltalk),
übernimmt das Modell mit dem Buchungs-Stand im Prompt und denselben
Kalender-Werkzeugen wie Lisa (kern.zuege).
"""

from __future__ import annotations

from typing import Any

from bianca import flow, session
from bianca.greeting import begruessung
from bianca.prompt import TOOLS, system_prompt
from kern import llm, zuege
from kern.calendar import slots_zeile


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _termine_zeile(sit: dict) -> str:
    up = sit.get("upcoming") or []
    if not up:
        return ""
    return "Kommend: " + "; ".join(x.get("label") or "" for x in up[:4] if isinstance(x, dict))


def system_prompt_aktuell(sit: dict) -> str:
    tenant = sit["tenant"]
    return system_prompt(
        praxis=_s(tenant.get("praxisName")),
        behandler=_s(tenant.get("behandler")),
        sprache=_s(tenant.get("sprache")) or "de",
        status=flow.status_zeile(sit),
        termine_text=_termine_zeile(sit),
        slots_text=slots_zeile(sit.get("offered") or []),
    )


def start_reply(sit: dict) -> dict[str, Any]:
    tenant = sit["tenant"]
    text = begruessung(_s(tenant.get("praxisName")))
    sit["messages"] = [
        {"role": "system", "content": system_prompt_aktuell(sit)},
        {"role": "user", "content": "(Ein Anrufer ist in der Leitung. Du hast dich gerade gemeldet.)"},
        {"role": "assistant", "content": text},
    ]
    return {"text": text, "book": None}


def user_turn(sit: dict, spoken: str, melde=None) -> dict[str, Any]:
    text_in = _s(spoken)
    if not text_in:
        return {"text": "", "book": None}
    msgs = list(sit.get("messages") or [])
    if not msgs:
        return start_reply(sit)
    msgs.append({"role": "user", "content": text_in})

    # 1) Deterministischer Buchungsfluss — antwortet ohne Modell, also sofort.
    fl = flow.zug(sit, text_in, melde)
    if fl and _s(fl.get("text")):
        msgs.append({"role": "assistant", "content": fl["text"]})
        sit["messages"] = msgs
        return {"text": fl["text"], "book": fl.get("book")}

    # 2) Modell-Pfad: Stand der Buchung frisch in den Systemprompt.
    if msgs and msgs[0].get("role") == "system":
        msgs[0]["content"] = system_prompt_aktuell(sit)
    out = llm.chat(msgs, TOOLS)
    if not out.get("ok"):
        return {
            "text": "Entschuldigung, da ist mir gerade etwas dazwischengekommen. Was darf ich für Sie tun?",
            "error": out.get("error"),
            "book": None,
        }
    text, msgs, book = zuege.apply_tools(sit, msgs, out, melde=melde)
    sit["messages"] = msgs
    return {"text": text, "book": book}


def hangup(sit: dict) -> dict[str, Any]:
    return zuege.auto_notiz(sit, force=True)
