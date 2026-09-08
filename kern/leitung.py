"""Leitungs-Statusfrage: sitzt der Anrufer schon auf der richtigen Nummer?

Live 08.09.2026 01:44: „Hallo, Petsas mein Name. Bin ich mit der Praxis
Dr. Petsas verbunden?“ — Name Petsas + Verb „verbunden“ löste Jingle und
echte Weiterleitung aus. Das ist eine Ja/Nein-Prüfung der Leitung, kein
„verbinden Sie mich“.
"""

from __future__ import annotations

import re

# „bin ich / spreche ich / habe ich … verbunden/erreicht“ — Status, nie
# Imperativ. „Könnte ich mit Doktor X verbunden?“ bleibt Transfer
# (kein bin/spreche/habe ich).
_LEITUNG_CHECK_RE = re.compile(
    r"\b(?:bin\s+ich|sind\s+wir|spreche\s+ich|rede\s+ich|"
    r"habe\s+ich|haben\s+wir)\b"
    r".{0,90}?\b(?:verbunden|erreicht)\b|"
    r"\b(?:richtige|korrekte)\s+praxis\b|"
    r"\bbin\s+ich\s+(?:hier\s+)?richtig\b|"
    r"\bspreche\s+ich\s+(?:hier\s+)?(?:schon\s+)?mit\s+(?:der\s+)?praxis\b|"
    r"\bmit\s+der\s+praxis\b.{0,50}?\bverbunden\b",
    re.I,
)


def ist_leitung_check(text: str) -> bool:
    t = " ".join(str(text or "").split()).strip()
    return bool(t and _LEITUNG_CHECK_RE.search(t))
