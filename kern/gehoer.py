"""Rückfrage statt Raten, wenn STT-Text zerhackt ankommt (28.08.2026).

Sehr kurze oder in Einzelbuchstaben zerlegte Transkripte dürfen den
Buchungsfluss nicht mit Müll füttern. Stattdessen eine gezielte Rückfrage.
Buchstabieren und Nummern-Diktat bleiben unberührt — dort sind Häppchen
gewollt.
"""

from __future__ import annotations

import re
from typing import Any

_JA_NEIN = frozenset({
    "ja", "jo", "joa", "jupp", "jap", "jep", "genau", "stimmt", "richtig",
    "nein", "nee", "nö", "noe", "nicht", "ok", "okay", "so",
})
_FUELL = frozenset({"äh", "aeh", "ähm", "aehm", "hm", "mhm", "hmm"})

RUECK_TERMIN = "Ich habe Sie akustisch nicht ganz verstanden — ging es um einen neuen Termin?"
RUECK_JA_NEIN = "Ich habe Sie akustisch nicht ganz verstanden — war das ein Ja oder ein Nein?"
RUECK_NOCHMAL = "Entschuldigung, das ist bei mir zerhackt angekommen. Sagen Sie es bitte noch einmal."


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def wacklig(text: str, *, frage: str = "") -> bool:
    """True = nicht in den Sammler geben, sondern nachfragen."""
    if frage in {"buchstabieren", "telefon", "telefon_check"}:
        return False
    t = _s(text)
    if not t:
        return False
    low = t.casefold().strip(" .,!?…")
    if low in _JA_NEIN or low in _FUELL:
        return False
    if re.fullmatch(r"[\d\s./+-]+", t):
        return False
    worte = re.findall(r"[A-Za-zÄÖÜäöüß0-9]+", t)
    if not worte:
        return True
    if all(w.casefold() in _FUELL for w in worte):
        return False
    # Ein 1-2-Buchstaben-Token, das keine klare Kurzantwort ist.
    if len(worte) == 1 and len(worte[0]) <= 2 and worte[0].casefold() not in _JA_NEIN:
        return True
    # Mehrere Tokens, die Mehrheit Einzelbuchstaben — typisches STT-Zerhack.
    if len(worte) >= 3:
        einzeln = sum(1 for w in worte if len(w) == 1)
        if einzeln >= len(worte) * 0.6:
            return True
    return False


def rueckfrage(sit: dict) -> str:
    s = sit.get("sammler") or {}
    fid = _s(s.get("frage"))
    phase = _s(s.get("phase"))
    if phase in {"bestaetigen", "angebot"} or fid in {"telefon_check", "bestaetigung", "slotwahl"}:
        return RUECK_JA_NEIN
    if s.get("modus") == "buchen" or s.get("warSchonMal") is not None:
        return RUECK_TERMIN
    return RUECK_NOCHMAL


def feste_saetze() -> list[str]:
    return [RUECK_TERMIN, RUECK_JA_NEIN, RUECK_NOCHMAL]
