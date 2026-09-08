"""Servicebeschwerde vs. klinisches Problem vs. Notfall (W-ANLIEGEN-ART
09.09.2026).

Chef-Anforderung: Zusatzangebote (PZR-Mitbuchung, Bleaching) dürfen NICHT
kommen, während sich jemand beschwert oder einen Notfall hat — das wirkt
taktlos. Dafür trennt dieses Modul drei Lagen:

- **notfall**  — klinischer Notfall (starke Schmerzen, Blutung, dicke Backe,
  ausgeschlagener Zahn). Die Buchung routet das über die Akut-Motive weiter
  (unverändert); hier zählt nur: KEIN Upsell.
- **beschwerde** — Servicebeschwerde (Wartezeit, Unfreundlichkeit,
  Reklamation, Ärger). KEIN Upsell, empathischer Ton (LLM).
- **klinisch**  — Beschwerden/Schmerz ohne Notfallmarker (Kontext für den
  Prompt; die Akut-Wachen im Fluss greifen ohnehin).

Reine, bianca-freie Erkennung (kern). Der Fluss (`bianca/flow._einschub`) fragt
`upsell_gesperrt(sit)`. Sticky innerhalb des Anrufs (die höchste gesehene Lage
bleibt). Notaus/Stufen `ANLIEGEN_ART=off|shadow|enforce` (Default off).
Tests: `tests/test_anliegen_art.py`.
"""

from __future__ import annotations

import os
import re
from typing import Any

_NOTFALL_RE = re.compile(
    r"\bnotfall\b|\bakut\w*|starke?\s+schmerz|unertr(?:ä|ae)glich|"
    r"\bblut\w*|geschwollen|dicke?\s+backe|ausgeschlagen|abgebrochen\w*\s+zahn|"
    r"\bzahn\b[^.!?]{0,20}\b(?:abgebrochen|rausgefallen|locker)|"
    r"nicht\s+mehr\s+aus(?:zu)?halten|h(?:ö|oe)llische?\s+schmerz",
    re.I,
)
_BESCHWERDE_RE = re.compile(
    r"\bbeschwer\w*|\breklamat\w*|\bunversch(?:ä|ae)mt\w*|\bfrech\w*|"
    r"\bunfreundlich\w*|\bunh(?:ö|oe)flich\w*|zu\s+lange\s+(?:ge)?wart\w*|"
    r"ewig\s+(?:ge)?wart\w*|stunden?\s+(?:ge)?wart\w*|schlecht\s+behandelt|"
    r"falsch\s+behandelt|\bunzufrieden\w*|ver(?:ä|ae)rgert|\b(?:ä|ae)rgerlich\w*|"
    r"\bkatastrophe\b|entt(?:ä|ae)uscht\w*|nicht\s+akzeptabel|"
    r"eine\s+frechheit|\bsauer\b\s+(?:auf|wegen)|\bskandal\w*",
    re.I,
)
_KLINISCH_RE = re.compile(
    r"\bschmerz\w*|zahnweh|\bweh\b|\bpocht\b|\bzieht\b|empfindlich|"
    r"\bentz(?:ü|ue)nd\w*|\beiter\w*",
    re.I,
)

_RANG = {"": 0, "klinisch": 1, "beschwerde": 2, "notfall": 3}


def modus() -> str:
    v = (os.environ.get("ANLIEGEN_ART") or "off").strip().lower()
    return v if v in {"off", "shadow", "enforce"} else "off"


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def art(text: str) -> str:
    """Lage eines Satzes — Priorität notfall > beschwerde > klinisch."""
    t = _s(text)
    if not t:
        return ""
    if _NOTFALL_RE.search(t):
        return "notfall"
    if _BESCHWERDE_RE.search(t):
        return "beschwerde"
    if _KLINISCH_RE.search(t):
        return "klinisch"
    return ""


def merken(sit: dict, text: str) -> str:
    """Höchste gesehene Lage im Anruf festhalten (sticky). Off => no-op."""
    if modus() == "off":
        return ""
    neu = art(text)
    alt = _s(sit.get("anliegenArt"))
    if _RANG.get(neu, 0) > _RANG.get(alt, 0):
        sit["anliegenArt"] = neu
    return _s(sit.get("anliegenArt"))


def aktiv(sit: dict) -> bool:
    """Läuft gerade eine Beschwerde/ein Notfall (Upsell wäre taktlos)?"""
    return _s(sit.get("anliegenArt")) in {"beschwerde", "notfall"}


def upsell_gesperrt(sit: dict) -> bool:
    """Enforce + aktive Beschwerde/Notfall => Zusatzangebote gesperrt."""
    return modus() == "enforce" and aktiv(sit)
