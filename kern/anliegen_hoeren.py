"""Häufige Anliegen schärfer erkennen. Ändert keine Frage und keine Reihenfolge.

Die Goldsätze aus den 536 Live-Anrufen, die der Heuristik durchrutschen
(„Es geht um einen Termin.“, „Auch meinen Termin!“, „Terminauskunft“,
Schmerzen ohne sauberes Termin-Verb), werden hier einer Familie zugeordnet.
Eine offene Formularfrage (Name, Nummer, Slot) bleibt unangetastet.
"""

from __future__ import annotations

import re

_WUNSCH_RE = re.compile(
    r"br(?:ä|ae|a)?uch\w*|br(?:ü|ue)chte\w*|h(?:ä|ae)tt\w*|gerne|gern\b|m(?:ö|oe)cht\w*|"
    r"\bwill\b|\bwollte\b|\bmachen\b|\bbuch\w*|\bvereinbar\w*",
    re.I,
)
_BESTAND_RE = re.compile(
    r"terminauskunft|"
    r"\btermin\w*\s+(?:vergessen|verpasst|verschwitzt|verpennt)\b|"
    r"\b(?:vergessen|verpasst|verschwitzt|verpennt)\w*\b[^?.!]{0,24}\btermin\w*",
    re.I,
)
_MEIN_TERMIN_RE = re.compile(r"\bmein(?:en|em|er|e)?\s+termin\w*", re.I)
_BUCHEN_RE = re.compile(
    r"\bes\s+geht\s+um\b[^?.!]{0,32}\btermin\w*|"
    r"\btermin\s+machen\b|"
    r"\b(?:einen|ein)\s+termin\b",
    re.I,
)
_KEIN_NEUER_TERMIN_RE = re.compile(
    r"\bhab(?:e|en)?\s+ich\b|\bhab(?:e|en)?\s+(?:ich\s+)?(?:schon|bereits|noch)\b|"
    r"\bich\s+habe\s+(?:einen|ein|meinen)\s+termin\b",
    re.I,
)
_GRUND_RE = re.compile(
    r"\b(?:muttermal|blutabnahme|zahnreinigung|vorsorge|kontrolle|"
    r"f(?:ü|ue)llung|implantat)\w*\b",
    re.I,
)
_SCHMERZ_RE = re.compile(
    r"\bschmerz\w*|\bweh\b|tut\s+(?:\w+\s+)?weh",
    re.I,
)
_KEIN_SCHMERZ_RE = re.compile(r"kein\w*\s+(?:\w+\s+)?schmerz\w*|schmerzfrei", re.I)
_DOKUMENT_RE = re.compile(
    r"\brezept(?!ion)\w*|\b(?:ü|ue)berweisung\w*|\blabor\w*|\bbefund\w*|"
    r"\breklamation\w*|\brechnung\w*",
    re.I,
)
_PRAXIS_RE = re.compile(
    r"\b(?:öffnungszeiten|oeffnungszeiten|sprechzeiten)\b",
    re.I,
)
_FORM = {
    "name", "nachname", "vorname", "buchstabieren", "nachname_check",
    "vorname_check", "nachname_korr", "aenderung", "telefon", "telefon_check",
    "telefon_alt", "sms_empfaenger", "slotwahl", "bestaetigung", "wunsch",
    "versicherung", "versicherung_check",
}

HOTWORDS = (
    "Termin", "Terminauskunft", "absagen", "verschieben", "Kontrolle",
    "Vorsorge", "Schmerzen", "Anmeldung", "Rezeption", "Mitarbeiter",
    "Rückruf", "Rezept", "Überweisung", "Muttermal", "Blutabnahme",
    "Labor", "Befund", "Öffnungszeiten", "Füllung", "Implantat",
    "Zahnreinigung", "Notfall",
)


def _s(v) -> str:
    return str(v or "").strip()


def ist_bestand(text: str) -> bool:
    """Frage nach einem schon bestehenden Termin, kein neuer Wunsch."""
    t = _s(text)
    if not t or _WUNSCH_RE.search(t):
        return False
    if _BESTAND_RE.search(t):
        return True
    woerter = re.sub(r"[^\w\säöüÄÖÜß-]", " ", t).split()
    return len(woerter) <= 5 and bool(_MEIN_TERMIN_RE.search(t))


def familie(text: str) -> str:
    """buchen, auskunft, dokument, praxis, schmerzen — oder leer."""
    t = _s(text)
    if not t:
        return ""
    if ist_bestand(t):
        return "auskunft"
    if _DOKUMENT_RE.search(t):
        return "dokument"
    if _PRAXIS_RE.search(t):
        return "praxis"
    if _SCHMERZ_RE.search(t) and not _KEIN_SCHMERZ_RE.search(t):
        return "schmerzen"
    if _BUCHEN_RE.search(t) and not _KEIN_NEUER_TERMIN_RE.search(t):
        return "buchen"
    if _WUNSCH_RE.search(t) and (
        _GRUND_RE.search(t) or re.search(r"\btermin\w*", t, re.I)
    ):
        return "buchen"
    return ""


def _deutung(text: str, handlung: str, gegenstand: str) -> dict:
    return {
        "kanal": "ok",
        "zug": "wechseln",
        "fuer": "selbst",
        "ersatz": None,
        "spiegel": _s(text)[:80],
        "quelle": "anliegen",
        "handlung": handlung,
        "gegenstand": gegenstand,
    }


def _formular_offen(sit: dict) -> bool:
    s = sit.get("sammler") if isinstance(sit.get("sammler"), dict) else {}
    if s.get("buchstabenTeil") or s.get("telefonTeil") or s.get("vornameTeil"):
        return True
    return _s(s.get("frage")) in _FORM


def nachschaerfen(sit: dict, text: str, deutung: dict | None) -> dict:
    """Nur nachlegen, wenn die Heuristik leer blieb oder einen Bestandstermin
    als Neubuchung gelesen hat. Sonst die ursprüngliche Deutung."""
    aktuell = deutung if isinstance(deutung, dict) else {}
    if _formular_offen(sit or {}):
        return aktuell
    art = familie(text)
    handlung = _s(aktuell.get("handlung")) or "KEINE"
    if art == "auskunft" and handlung in {"KEINE", "ANLEGEN"}:
        return _deutung(text, "WISSEN", "VORGANG")
    if art == "dokument" and handlung == "KEINE":
        return _deutung(text, "ABGEBEN", "SACHE")
    if art == "praxis" and handlung == "KEINE":
        return _deutung(text, "WISSEN", "REGEL")
    if art in {"buchen", "schmerzen"} and handlung == "KEINE":
        return _deutung(text, "ANLEGEN", "VORGANG")
    return aktuell
