"""Evidenzbasierter Fakten-/Erledigt-Waechter (W-FAKTEN-WACHE 09.09.2026).

Vorbild ist Claras UNVERIFIED_ACTION_FALLBACK: eine gesprochene Erledigt-
Behauptung ("Ihr Termin ist gebucht/abgesagt/verschoben", "ich habe eine Notiz
gemacht") darf nur raus, wenn das passende Werkzeug im Sitzungs-Ledger
ERFOLGREICH gelaufen ist. Wahrheit ist das Tool-Ledger (`sit["tools"]` bzw. die
gefalteten Marken lastBook/lastCancel/lastMove/lastNote/lastCreate aus
`kern/sitzung.merke_tool`), NICHT der LLM-Text.

Dieses Modul ist reine, bianca-freie Erkennung (kern-Schicht). Der Umgang mit
einer unbelegten Behauptung (Shadow-Log vs. Enforce-Umschreiben) liegt beim
Aufrufer (`bianca/agent`), damit dort die vorhandenen Frage-Formulierungen
wiederverwendet werden.

Notaus/Stufen `FAKTEN_WACHE=off|shadow|enforce` (Default off = kein Eingriff).
Tests: `tests/test_fakten_wache.py`.
"""

from __future__ import annotations

import os
import re
from typing import Any, Callable

_SATZ = re.compile(r"(?<=[.!?…])\s+")
# Fragen/Angebote sind KEINE Erledigt-Behauptung.
_FRAGE_MARK = re.compile(
    r"\b(soll(?:en)?\s+(?:ich|wir)|m(?:ö|oe)chten\s+sie|darf\s+ich|"
    r"wollen\s+sie|passt\s+(?:ihnen|das))\b",
    re.I,
)

_CLAIM_BUCHEN = re.compile(
    r"\b(gebucht|eingebucht|reserviert|fest\s+(?:ein)?getragen|"
    r"ist\s+(?:jetzt\s+)?(?:im|in\s+dem)\s+kalender|"
    r"hab(?:e)?\s+(?:ihn(?:en)?\s+|den\s+termin\s+)?(?:jetzt\s+|so\s+)?eingetragen|"
    r"ist\s+(?:jetzt\s+)?eingetragen|termin\s+steht)\b",
    re.I,
)
_CLAIM_ABSAGEN = re.compile(r"\b(abgesagt|storniert|gestrichen|gel(?:ö|oe)scht)\b", re.I)
_CLAIM_VERSCHIEBEN = re.compile(r"\b(verschoben|verlegt|umgebucht)\b", re.I)
_CLAIM_NOTIZ = re.compile(
    r"\b(?:notiz|vermerk)\w*\s+(?:gemacht|hinterlegt|geschrieben|erstellt|angelegt)\b|"
    r"\b(?:notiert|vermerkt|ausgerichtet|weitergeleitet|weitergegeben)\b|"
    r"\bdem\s+(?:team|doktor|arzt)\b[^.!?]{0,30}\b(?:vorleg\w*|weitergeb\w*|ausricht\w*)",
    re.I,
)
_CLAIM_ANLEGEN = re.compile(
    r"\b(?:neu\s+)?(?:angelegt|aufgenommen|neu\s+erfasst)\b|"
    r"\bin\s+(?:unsere[rm]?\s+)?kartei\s+(?:aufgenommen|angelegt|erfasst)\b",
    re.I,
)


def _ok(ein: Any) -> bool:
    return bool(isinstance(ein, dict) and (ein.get("ok") or ein.get("booked")))


def _ev_buchen(sit: dict) -> bool:
    return _ok(sit.get("lastBook"))


def _ev_absagen(sit: dict) -> bool:
    return _ok(sit.get("lastCancel"))


def _ev_verschieben(sit: dict) -> bool:
    return _ok(sit.get("lastMove"))


def _ev_notiz(sit: dict) -> bool:
    return bool(sit.get("noteWritten")) or _ok(sit.get("lastNote"))


def _ev_anlegen(sit: dict) -> bool:
    return _ok(sit.get("lastCreate")) or _ok(sit.get("lastBook"))  # book legt Neupatient mit an


# (Name, Behauptungs-Regex, Evidenz-Praedikat)
AKTIONEN: list[tuple[str, re.Pattern, Callable[[dict], bool]]] = [
    ("buchen", _CLAIM_BUCHEN, _ev_buchen),
    ("absagen", _CLAIM_ABSAGEN, _ev_absagen),
    ("verschieben", _CLAIM_VERSCHIEBEN, _ev_verschieben),
    ("notiz", _CLAIM_NOTIZ, _ev_notiz),
    ("anlegen", _CLAIM_ANLEGEN, _ev_anlegen),
]


def modus() -> str:
    v = (os.environ.get("FAKTEN_WACHE") or "off").strip().lower()
    return v if v in {"off", "shadow", "enforce"} else "off"


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def unbelegte_behauptung(sit: dict, text: str) -> str:
    """Erste Erledigt-Behauptung ohne passende Tool-Evidenz — sonst ''.

    Fragen/Angebote ('soll ich eintragen?', 'passt Ihnen?') zaehlen nicht.
    """
    t = _s(text)
    if not t:
        return ""
    for satz in _SATZ.split(t):
        st = satz.strip()
        if not st or st.rstrip().endswith("?") or _FRAGE_MARK.search(st):
            continue
        for name, cre, ev in AKTIONEN:
            if cre.search(st) and not ev(sit):
                return name
    return ""
