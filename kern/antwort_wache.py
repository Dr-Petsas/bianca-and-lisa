"""Antwort-Wache: phone_agent-Gates vor dem Mund (W-REPEAT 01.09.2026).

Schlanke Portierung aus phone_agent/services/response_guard.py — nur die
Anti-Repeat-Teile: eine Identitätsfrage pro Äußerung, gestapelte
Name+Telefon-Fragen kollabieren, Mid-Call-Re-Greeting streichen.
Kein Netz, kein LLM. phone_agent bleibt unberührt.
"""

from __future__ import annotations

import re
from typing import Any

_SATZ_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")

_GREETING_STOPWORDS = frozenset({
    "hallo", "guten", "tag", "morgen", "abend", "hier", "ist", "die", "der",
    "das", "und", "sie", "mit", "ich", "bin", "wir", "ihnen", "bei", "willkommen",
    "einen", "schoenen", "schönen", "ihr",
})

_IDENTITY_FIELD_RES: dict[str, re.Pattern[str]] = {
    "vorname": re.compile(r"(?i)\bvorname[n]?\b"),
    "nachname": re.compile(r"(?i)\bnachname[n]?\b"),
    "phone": re.compile(
        r"(?i)\b(?:mobilnummer|telefonnummer|handy(?:nummer)?|"
        r"mobilfunknummer|festnetz(?:nummer)?)\b"
    ),
}

_IDENTITY_ALREADY_RE: dict[str, re.Pattern[str]] = {
    "vorname": re.compile(
        r"(?i)(?:habe\s+(?:ihren|den|ihr)\s+vornamen?|"
        r"vornamen?\s+(?:ist|notiert|verstanden|gespeichert))"
    ),
    "nachname": re.compile(
        r"(?i)(?:habe\s+(?:ihren|den|ihr)\s+nachnamen?|"
        r"nachnamen?\s+(?:ist|notiert|verstanden|gespeichert))"
    ),
    "phone": re.compile(
        r"(?i)(?:habe\s+(?:ihre|die|ihr)\s+(?:mobil|telefon)|"
        r"(?:mobilnummer|telefonnummer)\s+(?:ist|notiert|verstanden))"
    ),
}

_IDENTITY_COLLECTION_INTRO_RE = re.compile(
    r"(?i)(?:um|nach)\s+ihre[n]?\s+(?:daten|angaben)"
    r"|folgende[ns]?\s+(?:daten|angaben)"
)

_IDENTITY_CONFIRM_RE = re.compile(
    r"(?i)\b("
    r"ist das (?:so )?(?:richtig|korrekt|in ordnung)"
    r"|stimmt das"
    r"|soll ich (?:das |den termin )?(?:so )?buchen"
    r"|darf ich (?:das )?so buchen"
    r"|zusammengefasst"
    r"|habe ich (?:das )?richtig"
    r")"
)

_SINGLE_IDENTITY_ASK = {
    "vorname": "Wie lautet Ihr Vorname?",
    "nachname": "Bitte buchstabieren Sie Ihren Nachnamen.",
    "phone": "Wie lautet Ihre Handynummer?",
}


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _greeting_tokens(s: str) -> list[str]:
    return [t for t in re.findall(r"[A-Za-zÄÖÜäöüß]+", (s or "").lower()) if len(t) > 1]


def strip_repeated_greeting(text: str, greeting: str) -> str:
    """Mid-Call-Re-Greeting streichen (phone_agent strip_repeated_greeting)."""
    if not text or not greeting:
        return text
    g_distinct = {t for t in _greeting_tokens(greeting) if t not in _GREETING_STOPWORDS}
    if len(g_distinct) < 2:
        return text
    threshold = max(2, (len(g_distinct) + 1) // 2)
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    kept: list[str] = []
    dropped = False
    for p in parts:
        overlap = g_distinct & set(_greeting_tokens(p))
        if len(overlap) >= threshold:
            dropped = True
            continue
        kept.append(p)
    if not dropped:
        return text
    return " ".join(kept).strip()


def asked_identity_fields(text: str) -> list[str]:
    t = text or ""
    out: list[str] = []
    for key, pat in _IDENTITY_FIELD_RES.items():
        if not pat.search(t):
            continue
        if _IDENTITY_ALREADY_RE[key].search(t):
            continue
        out.append(key)
    return out


def looks_like_identity_collection_intro(text: str) -> bool:
    return bool(_IDENTITY_COLLECTION_INTRO_RE.search(text or ""))


def collapse_stacked_identity_ask(text: str) -> str:
    """Höchstens eine Identitätsfrage pro Äußerung."""
    if not text:
        return text
    if _IDENTITY_CONFIRM_RE.search(text):
        return text
    asked = asked_identity_fields(text)
    is_intro = looks_like_identity_collection_intro(text)
    if len(asked) < 2 and not (is_intro and not asked):
        return text
    parts = [p.strip(" \t-*") for p in _SATZ_SPLIT_RE.split(text.strip())]
    kept: list[str] = []
    for part in parts:
        if not part:
            continue
        if asked_identity_fields(part) or looks_like_identity_collection_intro(part):
            continue
        kept.append(part)
    first = asked[0] if asked else "vorname"
    ask = _SINGLE_IDENTITY_ASK[first]
    if not kept:
        return ask
    preamble = " ".join(kept).strip()
    if preamble.endswith((".", "!", "?")):
        return f"{preamble} {ask}"
    return f"{preamble}. {ask}"


def saeubern(sit: dict, text: str) -> str:
    """Gates vor TTS: Re-Greeting raus, gestapelte Identitätsfragen kollabieren."""
    t = _s(text)
    if not t:
        return t
    begr = _s(sit.get("begruessungText"))
    if not begr and sit.get("messages"):
        # Erste Assistenten-Antwort = Begrüßung
        for m in sit["messages"]:
            if m.get("role") == "assistant" and _s(m.get("content")):
                begr = _s(m.get("content"))
                break
    t = strip_repeated_greeting(t, begr)
    t = collapse_stacked_identity_ask(t)
    return t
