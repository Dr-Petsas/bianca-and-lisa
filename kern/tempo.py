"""Sprechtempo des Anrufers — Zugende-Pause nicht fest, sondern relativ.

Live Svetlana 04.09.2026: 350–500 ms Standard schnitt langsamen Anrufern
mitten im Satz (mindestens zehn Fehlstarts). Die ersten Antworten zeigen,
ob jemand bedächtig oder zügig spricht. Unbekannt = großzügig — nie hetzen.
"""

from __future__ import annotations

import re
from typing import Any

from kern import halbsatz

SCHNELL = "schnell"
LANGSAM = "langsam"
UNBEKANNT = "unbekannt"

_JA_NEIN = {
    "ja", "nein", "nee", "nö", "noe", "ok", "okay", "genau", "richtig",
    "passt", "yeah", "yes", "no", "jup", "jepp",
}
_KURZ_FERTIG = _JA_NEIN | {
    "hallo", "guten", "tag", "morgen", "abend", "tschüss", "tschueß",
    "danke", "bitte",
}


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def merken(sit: dict, text: str, *, audio_ms: int = 0, barge: bool = False,
           gehalten: bool = False) -> None:
    """Einen Anrufer-Zug in die Tempo-Historie legen (die letzten sechs)."""
    t = _s(text)
    if not t:
        return
    hist = sit.setdefault("sprechHist", [])
    if not isinstance(hist, list):
        hist = []
        sit["sprechHist"] = hist
    worte = t.split()
    hist.append({
        "w": len(worte),
        "ms": int(audio_ms or 0),
        "barge": bool(barge),
        "gehalten": bool(gehalten),
        "unfertig": bool(halbsatz.unfertig(t)),
        "kurzfertig": len(worte) <= 3 and worte[0].rstrip(".!?,;:").casefold() in _KURZ_FERTIG,
    })
    del hist[:-6]


def lage(sit: dict | None) -> str:
    """schnell / langsam / unbekannt — unbekannt, bis zwei Züge da sind."""
    hist = (sit or {}).get("sprechHist") if isinstance(sit, dict) else None
    if not isinstance(hist, list) or len(hist) < 2:
        return UNBEKANNT
    langsam = 0
    schnell = 0
    for h in hist:
        if not isinstance(h, dict):
            continue
        if h.get("barge") or h.get("gehalten") or h.get("unfertig"):
            langsam += 2
        w = int(h.get("w") or 0)
        ms = int(h.get("ms") or 0)
        if w <= 1 and not h.get("kurzfertig"):
            langsam += 1
        if h.get("kurzfertig") and not h.get("unfertig"):
            schnell += 1
        if ms >= 1800 and w <= 4:
            langsam += 2
    if langsam >= schnell + 1:
        return LANGSAM
    if schnell >= 2 and langsam == 0:
        return SCHNELL
    return UNBEKANNT


def pause_ms(basis: int, sit: dict | None = None) -> int:
    """Frage-Basis an das Sprechtempo anpassen."""
    b = max(200, int(basis or 500))
    l = lage(sit)
    if l == SCHNELL:
        return b
    if l == LANGSAM:
        return max(b, 1800) if b >= 1500 else max(b, 1100)
    return b if b >= 1500 else max(b, 800)


def warte_ms(sit: dict | None = None) -> int:
    """Ruhe nach einem gehaltenen Halbsatz — langsamer Sprecher bekommt mehr."""
    l = lage(sit)
    if l == LANGSAM:
        return 1400
    if l == UNBEKANNT:
        return 1100
    return 900
