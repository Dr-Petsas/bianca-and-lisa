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
# Eine echte Frage am Satzanfang behauptet keine erledigte Aktion. Ein
# angehängtes „passt das?“ entschärft dagegen keine vorausgehende Lüge
# („Ich habe reserviert, passt das?“).
_REINE_FRAGE = re.compile(
    r"^(?:soll(?:en)?\s+(?:ich|wir)|m(?:ö|oe)chten\s+sie|darf\s+ich|"
    r"wollen\s+sie|kann\s+ich|haben\s+sie|ist\s+ihr|bekommen\s+sie)\b",
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
_CLAIM_TRANSFER = re.compile(
    r"\bich\s+(?:werde\s+|habe\s+|kann\s+)?(?:sie\s+)?(?:jetzt\s+)?"
    r"(?:zu\s+[^.!?]{1,40}\s+)?(?:durchstell\w*|verbind\w*|weiterleit\w*)\b|"
    r"\bich\s+stell\w*\s+sie\s+(?:jetzt\s+)?(?:zu\s+[^.!?]{1,40}\s+)?durch\b|"
    r"\bich\s+leit\w*\s+(?:die\s+verbindung|sie)\s+(?:jetzt\s+)?ein\b|"
    r"\bich\s+stell\w*\s+(?:die\s+)?verbindung\s+(?:jetzt\s+)?her\b|"
    r"\bsie\s+(?:werden|sind)\s+(?:jetzt\s+)?(?:durchgestellt|verbunden|weitergeleitet)\b",
    re.I,
)
_CLAIM_NOTIZ = re.compile(
    r"\b(?:notiz|vermerk)\w*\b[^.!?]{0,60}\b"
    r"(?:gemacht|hinterlegt|geschrieben|erstellt|angelegt|notiert|vermerkt|"
    r"ausgerichtet|weitergeleitet|weitergegeben)\b|"
    r"\bdem\s+(?:team|doktor|arzt)\b[^.!?]{0,30}\b(?:vorleg\w*|weitergeb\w*|ausricht\w*)",
    re.I,
)
_CLAIM_ANLEGEN = re.compile(
    r"\b(?:akte|patient(?:enakte)?|kartei)\b[^.!?]{0,30}\b"
    r"(?:angelegt|aufgenommen|erfasst)\b|"
    r"\b(?:angelegt|aufgenommen|erfasst)\b[^.!?]{0,30}\b"
    r"(?:als\s+patient|in\s+(?:unsere[rm]?\s+)?kartei)\b",
    re.I,
)

_ZEIT_MARK = re.compile(
    r"\b(?:heute|morgen|übermorgen|uebermorgen|montag|dienstag|mittwoch|"
    r"donnerstag|freitag|samstag|sonntag|januar|februar|märz|maerz|april|"
    r"mai|juni|juli|august|september|oktober|november|dezember)\b|"
    r"\b\d{1,2}(?::\d{2})?\s*uhr\b|\b\d{1,2}\.\d{1,2}\.|\b\d{4}-\d{2}-\d{2}\b",
    re.I,
)
_CLAIM_SLOT_POSITIV = re.compile(
    r"\b(?:frei|verfügbar|verfuegbar|möglich|moeglich|offen)\b|"
    r"\b(?:habe|hätte|haette|sehe|finde|biete|schlage)\b[^.!?]{0,50}"
    r"\b(?:termin|slot|platz|zeit)\b|"
    r"\b(?:termin|slot|platz)\b[^.!?]{0,35}\b(?:anbieten|vorschlagen)\b",
    re.I,
)
_CLAIM_SLOT_NEGATIV = re.compile(
    r"\b(?:kein(?:e[rmn]?|en)?|nicht\s+ein)\s+(?:weiterer?\s+|freie[rmn]?\s+)?"
    r"(?:termin|slot|platz)\b|"
    r"\b(?:nichts|kein(?:e[rmn]?|en)?)\s+(?:mehr\s+)?frei\b|"
    r"\bkalender\b[^.!?]{0,30}\b(?:voll|ausgebucht)\b",
    re.I,
)
_CLAIM_BESTAND_NEGATIV = re.compile(
    r"\b(?:sie|du)\s+hab(?:en|t)\s+(?:aktuell\s+|derzeit\s+|noch\s+)?"
    r"kein(?:en|e)?\s+(?:kommenden\s+|weiteren\s+|anderen\s+)?termin\b|"
    r"\bich\s+(?:sehe|finde)\b[^.!?]{0,45}\bkein(?:en|e)?\s+"
    r"(?:kommenden\s+|weiteren\s+|anderen\s+)?termin\b|"
    r"\bkein(?:e|en)?\s+(?:weiteren?|anderen?|kommenden?)\s+termine?\b",
    re.I,
)
_CLAIM_BESTAND_POSITIV = re.compile(
    r"\b(?:ihr|der)\s+(?:nächste[rn]?|naechste[rn]?|andere[rn]?|kommende[rn]?)\s+"
    r"termin\b[^.!?]{0,45}\b(?:ist|steht|findet)\b|"
    r"\bich\s+sehe\b[^.!?]{0,50}\b(?:ihren|einen)\s+(?:kommenden\s+)?termin\b",
    re.I,
)
_CLAIM_SMS = re.compile(
    r"\b(?:bestätigungs|bestaetigungs)?-?sms\b[^.!?]{0,55}\b"
    r"(?:kommt|geht|erhalten|bekommen|geschickt|gesendet|verschickt)\b|"
    r"\b(?:geschickt|gesendet|verschickt)\b[^.!?]{0,35}\b"
    r"(?:bestätigungs|bestaetigungs)?-?sms\b|"
    r"\b(?:sie|du)\s+(?:bekommen|erhalten)\b[^.!?]{0,35}\b"
    r"(?:bestätigungs|bestaetigungs)?-?sms\b",
    re.I,
)
_CLAIM_RUECKRUF = re.compile(
    r"\b(?:praxis|team|arzt|ärztin|aerztin|doktor)\b[^.!?]{0,45}"
    r"\b(?:meldet\s+sich|ruft\s+(?:sie\s+)?zurück|ruft\s+(?:sie\s+)?zurueck)\b|"
    r"\bich\s+rufe\s+sie\s+(?:zurück|zurueck)\b|"
    r"\brückruf\w*\b[^.!?]{0,45}\b(?:angelegt|eingetragen|notiert|"
    r"weitergegeben|vermerkt|veranlasst)\b",
    re.I,
)
_TRANSFER_WUNSCH = re.compile(
    r"\b(?:verbind\w*|durchstell\w*|weiterleit\w*|ans?\s+telefon|"
    r"an\s+den\s+apparat)\b|"
    r"\bmit\s+(?!(?:ihnen|dir|euch|bianca)\b)[^.!?]{1,45}\bsprechen\b|"
    r"\b(?:doktor|arzt|ärztin|aerztin|frau|herr|mitarbeiter\w*|"
    r"anmeldung|empfang|praxisleitung)\b[^.!?]{0,35}\bsprechen\b",
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


def _ev_transfer(sit: dict) -> bool:
    ziel = sit.get("weiterleitungZiel")
    return bool(isinstance(ziel, dict) and str(ziel.get("nummer") or "").strip())


def _ev_notiz(sit: dict) -> bool:
    if _ok(sit.get("lastNote")):
        return True
    return any(
        isinstance(ein, dict)
        and ein.get("name") in {"note_appointment", "praxis_notiz"}
        and _ok(ein)
        for ein in (sit.get("tools") or [])
    )


def _ev_anlegen(sit: dict) -> bool:
    return _ok(sit.get("lastCreate")) or _ok(sit.get("lastBook"))  # book legt Neupatient mit an


def _letztes_tool(sit: dict, namen: set[str]) -> dict:
    for ein in reversed(sit.get("tools") or []):
        if isinstance(ein, dict) and str(ein.get("name") or "") in namen:
            return ein
    return {}


def _ev_slot_positiv(sit: dict) -> bool:
    tool = _letztes_tool(sit, {"getFreeTimeSlots", "offer_slots"})
    return bool(_ok(tool) and int(tool.get("resultCount") or 0) > 0 and sit.get("offered"))


def _ev_slot_negativ(sit: dict) -> bool:
    tool = _letztes_tool(sit, {"getFreeTimeSlots", "offer_slots"})
    return bool(
        _ok(tool)
        and "resultCount" in tool
        and int(tool.get("resultCount") or 0) == 0
    )


def _ev_bestand(sit: dict, *, leer: bool) -> bool:
    tool = _letztes_tool(
        sit, {"agentFindPatientAppointments", "list_appointments"})
    if not _ok(tool) or tool.get("notFound") or tool.get("mehrdeutig"):
        return False
    if "resultCount" not in tool:
        return False
    anzahl = int(tool.get("resultCount") or 0)
    return anzahl == 0 if leer else anzahl > 0


def _ev_sms(sit: dict) -> bool:
    buch = sit.get("lastBook")
    return bool(_ok(buch) and not (buch or {}).get("verificationFailed"))


# (Name, Behauptungs-Regex, Evidenz-Praedikat)
AKTIONEN: list[tuple[str, re.Pattern, Callable[[dict], bool]]] = [
    ("buchen", _CLAIM_BUCHEN, _ev_buchen),
    ("absagen", _CLAIM_ABSAGEN, _ev_absagen),
    ("verschieben", _CLAIM_VERSCHIEBEN, _ev_verschieben),
    ("transfer", _CLAIM_TRANSFER, _ev_transfer),
    ("notiz", _CLAIM_NOTIZ, _ev_notiz),
    ("anlegen", _CLAIM_ANLEGEN, _ev_anlegen),
]


def modus() -> str:
    v = (os.environ.get("FAKTEN_WACHE") or "off").strip().lower()
    return v if v in {"off", "shadow", "enforce"} else "off"


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def unbelegte_behauptung(
    sit: dict, text: str, *, nutzertext: str | None = None
) -> str:
    """Erste Erledigt-Behauptung ohne passende Tool-Evidenz — sonst ''.

    Reine Fragen ('soll ich eintragen?') zaehlen nicht. Konkrete
    Slotangebote und Tatsachenbehauptungen mit angehängter Frage schon.
    """
    t = _s(text)
    if not t:
        return ""
    for satz in _SATZ.split(t):
        st = satz.strip()
        if not st:
            continue
        if (_CLAIM_BESTAND_NEGATIV.search(st)
                and not _ev_bestand(sit, leer=True)):
            return "bestand"
        if (_CLAIM_BESTAND_POSITIV.search(st)
                and not _ev_bestand(sit, leer=False)):
            return "bestand"
        if (_CLAIM_SLOT_NEGATIV.search(st) and not _ev_slot_negativ(sit)):
            return "slots"
        if (_ZEIT_MARK.search(st) and _CLAIM_SLOT_POSITIV.search(st)
                and not _ev_slot_positiv(sit)):
            return "slots"
        if _CLAIM_SMS.search(st) and not _ev_sms(sit):
            return "sms"
        if _CLAIM_RUECKRUF.search(st) and not _ev_notiz(sit):
            return "rueckruf"
        if _REINE_FRAGE.search(st):
            continue
        for name, cre, ev in AKTIONEN:
            if not cre.search(st):
                continue
            if name == "transfer" and nutzertext is not None:
                if not _TRANSFER_WUNSCH.search(_s(nutzertext)):
                    return "transfer"
            if not ev(sit):
                return name
    return ""
