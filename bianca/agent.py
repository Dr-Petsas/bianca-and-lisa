"""Biancas Zug-Logik: Zustandsmaschine zuerst, Sprachmodell nur als Beifahrer.

Jeder Anrufer-Satz geht durch flow.zug() — deterministisch, ohne Modell-Latenz.
Nur wenn der Fluss abgibt (Zwischenfrage, Absage/Verschieben, Smalltalk),
übernimmt das Modell mit dem Buchungs-Stand im Prompt und denselben
Kalender-Werkzeugen wie Lisa (kern.zuege).
"""

from __future__ import annotations

import re
from typing import Any

from bianca import flow, gehirn, session
from bianca.greeting import begruessung
from bianca.prompt import TOOLS, system_prompt
from kern import llm, zuege
from kern.calendar import slots_zeile


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


# --- Wachen für den LLM-Pfad -------------------------------------------------
# Live 27.08.2026: Das Modell ERFAND Terminangebote ("Mittwoch, den 24. Juli,
# um 09:30 Uhr" — in der Vergangenheit!), obwohl kein einziger echter Slot
# geladen war, und stellte eigene Fragen statt der offenen Sammler-Frage.

_ANGEBOT_VERB_RE = re.compile(
    r"\bbiete|\banbieten|\bhätte\b|\bhaette\b|\bfrei\b|\bvorschlag|\bschlage\b|\bpasst\s+ihnen",
    re.I,
)
_ANGEBOT_ZEIT_RE = re.compile(
    r"\b(montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)\b|"
    r"\b\d{1,2}\.\s?(?:\d{1,2}\.|januar|februar|märz|maerz|april|mai|juni|juli|"
    r"august|september|oktober|november|dezember)|"
    r"\b(?:um|gegen)\s+\S{1,18}\s*uhr\b",
    re.I,
)
_FRAGE_KERN = {
    "schonmal": r"schon\s+(?:ein)?mal|bereits\s+bei\s+uns",
    "arzt": r"behandler|arzt|ärztin|aerztin|doktor",
    "name": r"\bname\b|\bnamen\b",
    "vorname": r"vorname",
    "nachname": r"nachname",
    "grund": r"worum|grund|anliegen|kontrolle",
    "wunsch": r"\bwann\b|vormittag|nachmittag|uhrzeit",
    "buchstabieren": r"buchstabier",
    "telefon": r"nummer|handy|telefon",
    "telefon_check": r"nummer|stimmt",
    "slotwahl": r"\buhr\b|termin.{0,30}passt|welcher",
    "bestaetigung": r"eintragen|so\s+buchen|festhalten",
}
_SATZ_ENDE_RE = re.compile(r"(?<=[.!?…])\s+")

# Behauptet das Modell eine Absage/Verschiebung, ohne dass ein Werkzeug lief?
# "sage ... ab" darf einen kompletten gesprochenen Termin ueberspannen
# ("ich sage den Termin morgen um zehn Uhr dreissig bei Doktor Petsas ab").
_ERLEDIGT_RE = re.compile(
    r"\b(abgesagt|storniert|verschoben|verlegt)\b|"
    r"\bsage\b[^.!?]{0,90}\bab\b|\bstorniere\b|\bverschiebe\b|\bverlege\b",
    re.I,
)


def _kanonische_frage(sit: dict, fid: str) -> str:
    if fid == "slotwahl":
        angebote = "; ".join(_s(x.get("spoken")) for x in (sit.get("offered") or [])[:3])
        return f"Im Angebot sind: {angebote}. Welcher passt Ihnen?" if angebote else "Welcher der genannten Termine passt Ihnen?"
    if fid == "bestaetigung":
        return "Soll ich den Termin so fest eintragen?"
    fid2, frage = gehirn.naechste_frage(sit)
    return frage if fid2 == fid else ""


def _nachbessern(sit: dict, text: str, melde=None, werkzeug_lief: bool = False) -> str:
    """LLM-Antworten auf dem Buchungspfad absichern: erfundene Angebote
    durch echte ersetzen, danach die offene Sammler-Frage wieder verankern."""
    s = sit.get("sammler") or {}
    t = _s(text)
    if not t:
        return text

    # 0) Erledigt-Wache: "ich sage den Termin ab" / "ist verschoben" ohne
    #    Werkzeuglauf ist eine leere Behauptung (live 27.08.: beide Termine
    #    standen noch im Kalender). Zurueck zur letzten offenen Fluss-Frage.
    if s.get("modus") in {"absagen", "verschieben"} and not werkzeug_lief and _ERLEDIGT_RE.search(t):
        zurueck = _s(sit.get("flussFrage")) or "Um welchen Termin geht es denn genau?"
        return "Da will ich nichts falsch machen — das mache ich erst nach Ihrer Bestätigung. " + zurueck

    if s.get("modus") != "buchen" or s.get("phase") in {"gebucht", "fertig"}:
        return text

    # 1) Angebots-Wache: konkrete Tag/Uhrzeit-Angebote ohne echte Slots.
    if not sit.get("offered") and _ANGEBOT_ZEIT_RE.search(t) and _ANGEBOT_VERB_RE.search(t):
        fid, frage = gehirn.naechste_frage(sit)
        if fid:
            s["frage"] = fid
            return "Einen Moment — Termine schaue ich lieber direkt im Kalender nach. " + frage
        ang = flow._angebot(sit, melde)
        if ang and _s(ang.get("text")):
            return ang["text"]
        return "Einen Moment, ich schaue in den Kalender."

    # 2) Frage-Anker: die offene Pflichtfrage muss am Zugende stehen.
    fid = _s(s.get("frage"))
    kern = _FRAGE_KERN.get(fid)
    if fid and kern and not re.search(kern, t, re.I):
        saetze = _SATZ_ENDE_RE.split(t)
        if saetze and saetze[-1].rstrip().endswith("?"):
            saetze = saetze[:-1]  # fremde Frage weicht der offenen Frage
        frage = _kanonische_frage(sit, fid)
        if frage:
            t = " ".join([x for x in saetze if x] + [frage]).strip()
    return t


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


def user_turn(sit: dict, spoken: str, melde=None, vorab=None) -> dict[str, Any]:
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
        if "?" in fl["text"]:
            sit["flussFrage"] = fl["text"].rsplit("?", 1)[0].split(". ")[-1].strip() + "?"
        msgs.append({"role": "assistant", "content": fl["text"]})
        sit["messages"] = msgs
        return {"text": fl["text"], "book": fl.get("book")}

    # 2) Modell-Pfad: Stand der Buchung frisch in den Systemprompt.
    if msgs and msgs[0].get("role") == "system":
        msgs[0]["content"] = system_prompt_aktuell(sit)
    # Kein Stream-Vorab, solange Buchung ODER Verwaltung offen ist: die Wachen
    # unten (_nachbessern) duerfen den Text noch umbauen — ein schon
    # gesprochener erster Satz waere dann falsch. Nur freies Geplauder streamt.
    s = sit.get("sammler") or {}
    mitten_drin = s.get("modus") in {"buchen", "absagen", "verschieben"} and s.get("phase") not in {"gebucht", "fertig"}
    darf_vorab = vorab is not None and not mitten_drin
    werkzeuge_vorher = len(sit.get("tools") or [])
    if darf_vorab:
        out = llm.chat_stream(msgs, TOOLS, erster_satz=vorab)
    else:
        out = llm.chat(msgs, TOOLS)
    if not out.get("ok"):
        return {
            "text": "Entschuldigung, da ist mir gerade etwas dazwischengekommen. Was darf ich für Sie tun?",
            "error": out.get("error"),
            "book": None,
        }
    text, msgs, book = zuege.apply_tools(sit, msgs, out, melde=melde)
    werkzeug_lief = len(sit.get("tools") or []) > werkzeuge_vorher
    bewacht = _nachbessern(sit, text, melde, werkzeug_lief=werkzeug_lief)
    if bewacht != text:
        if msgs and msgs[-1].get("role") == "assistant":
            msgs[-1]["content"] = bewacht
        text = bewacht
    sit["messages"] = msgs
    return {"text": text, "book": book}


def hangup(sit: dict) -> dict[str, Any]:
    return zuege.auto_notiz(sit, force=True)
