"""Sprech-Schicht: JEDER gesprochene Satz geht hier durch.

Zwei Aufgaben:
1. Uhrzeiten und Daten ausschreiben. ElevenLabs liest "09:15" als Ziffernfolge
   und "2026-08-27" als Zahlensalat vor — gesprochen wird "neun Uhr fünfzehn"
   und "morgen".
2. Technische Begriffe und Regieanweisungen abfangen. Vorfall 27.08.2026:
   Lisa sagte "buche ihn dann sofort mit book_slot (Feld slot_iso)" laut vor.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Berlin")

_EINER = (
    "null", "eins", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht",
    "neun", "zehn", "elf", "zwölf", "dreizehn", "vierzehn", "fünfzehn",
    "sechzehn", "siebzehn", "achtzehn", "neunzehn",
)
_ZEHNER = {2: "zwanzig", 3: "dreißig", 4: "vierzig", 5: "fünfzig"}

_ORDINAL = {
    1: "ersten", 2: "zweiten", 3: "dritten", 4: "vierten", 5: "fünften",
    6: "sechsten", 7: "siebten", 8: "achten", 9: "neunten", 10: "zehnten",
    11: "elften", 12: "zwölften", 13: "dreizehnten", 14: "vierzehnten",
    15: "fünfzehnten", 16: "sechzehnten", 17: "siebzehnten", 18: "achtzehnten",
    19: "neunzehnten", 20: "zwanzigsten", 21: "einundzwanzigsten",
    22: "zweiundzwanzigsten", 23: "dreiundzwanzigsten", 24: "vierundzwanzigsten",
    25: "fünfundzwanzigsten", 26: "sechsundzwanzigsten", 27: "siebenundzwanzigsten",
    28: "achtundzwanzigsten", 29: "neunundzwanzigsten", 30: "dreißigsten",
    31: "einunddreißigsten",
}

_MONAT = {
    1: "Januar", 2: "Februar", 3: "März", 4: "April", 5: "Mai", 6: "Juni",
    7: "Juli", 8: "August", 9: "September", 10: "Oktober", 11: "November",
    12: "Dezember",
}

_WOCHENTAG = {
    0: "Montag", 1: "Dienstag", 2: "Mittwoch", 3: "Donnerstag",
    4: "Freitag", 5: "Samstag", 6: "Sonntag",
}

# Werkzeugnamen, Feldnamen, Entwickler-Jargon: nie in den Mund.
_TECH = re.compile(
    r"\b("
    r"book_slot|offer_slots|cancel_appointment|move_appointment|note_appointment|"
    r"list_appointments|create_patient|masbookappointment|mascreatepatient|"
    r"slot_?iso|patient_?id|visit_?motive(_?id)?|calendar_?id|appointment_?id|"
    r"json|payload|endpoint|cloud[- ]?function|tool[-_ ]?call"
    r")\b",
    re.I,
)

# Regieanweisungen aus Prompt und Werkzeug-Antworten (Du-Imperativ an das Modell).
_REGIE = re.compile(
    r"("
    r"sage\s+(?:dem|der)\s+patient|sage\s+ihm\b|sage\s+ihr\b|sag\s+dem\s+patient|"
    r"frage,\s*welcher\s+termin|buche\s+(?:ihn|sie|den)\s+dann|buche\s+ihn\s+sofort|"
    r"rufe\s+zuerst|übergib\b|uebergib\b|bestätige\s+erst|bestaetige\s+erst|"
    r"nicht\s+vorlesen|regieanweisung"
    r")",
    re.I,
)

# Wenn das Modell doch "Slot"/"Timeslot" sagt: patientenverständlich machen.
_SLOTWORT = (
    (re.compile(r"\b(?:zeit|time)[- ]?slots\b", re.I), "Termine"),
    (re.compile(r"\b(?:zeit|time)[- ]?slot\b", re.I), "Termin"),
    (re.compile(r"\bslots\b", re.I), "Termine"),
    (re.compile(r"\bslot\b", re.I), "Termin"),
)

_SATZ = re.compile(r"(?<=[.!?])\s+")


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _zahl(n: int) -> str:
    n = int(n)
    if n < 20:
        return _EINER[n]
    z, e = divmod(n, 10)
    if e == 0:
        return _ZEHNER.get(z, str(n))
    return f"{'ein' if e == 1 else _EINER[e]}und{_ZEHNER.get(z, str(z))}"


def zeit_wort(hour: int, minute: int = 0) -> str:
    h = max(0, min(23, int(hour)))
    m = max(0, min(59, int(minute)))
    hw = "ein" if h == 1 else _zahl(h)
    if m == 0:
        return f"{hw} Uhr"
    return f"{hw} Uhr {_zahl(m)}"


def tag_wort(jahr: int, monat: int, tag: int, *, heute: date | None = None) -> str:
    """Relativ wenn möglich ('morgen'), sonst 'Donnerstag, den siebenundzwanzigsten August'."""
    try:
        d = date(int(jahr), int(monat), int(tag))
    except ValueError:
        return ""
    ref = heute or datetime.now(TZ).date()
    delta = (d - ref).days
    if delta == 0:
        return "heute"
    if delta == 1:
        return "morgen"
    if delta == 2:
        return "übermorgen"
    wt = _WOCHENTAG[d.weekday()]
    kern = f"{wt}, den {_ORDINAL.get(d.day, str(d.day))} {_MONAT[d.month]}"
    if d.year != ref.year:
        kern += f" {d.year}"
    return kern


def _mit_praeposition(kern: str, praep: str) -> str:
    """'am' passt nur zu absoluten Tagen — 'am morgen' wäre falsch."""
    relativ = kern in {"heute", "morgen", "übermorgen"}
    if relativ:
        return kern
    return f"{praep or 'am'} {kern}"


def slot_wort(iso: str, *, heute: date | None = None) -> str:
    """'2026-08-27T09:15' -> 'morgen um neun Uhr fünfzehn'."""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{1,2}):(\d{2})", _s(iso))
    if not m:
        m2 = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", _s(iso))
        if not m2:
            return _s(iso)
        tag = tag_wort(m2.group(1), m2.group(2), m2.group(3), heute=heute)
        return _mit_praeposition(tag, "am")
    tag = tag_wort(m.group(1), m.group(2), m.group(3), heute=heute)
    uhr = zeit_wort(int(m.group(4)), int(m.group(5)))
    return f"{_mit_praeposition(tag, 'am')} um {uhr}"


def _ersetze_zeiten(text: str, heute: date | None = None) -> str:
    def iso_dt(mo: re.Match) -> str:
        praep = (mo.group(1) or "").strip()
        tag = tag_wort(mo.group(2), mo.group(3), mo.group(4), heute=heute)
        if not tag:
            return mo.group(0)
        uhr = zeit_wort(int(mo.group(5)), int(mo.group(6)))
        return f"{_mit_praeposition(tag, praep or 'am')} um {uhr}"

    def iso_d(mo: re.Match) -> str:
        praep = (mo.group(1) or "").strip()
        tag = tag_wort(mo.group(2), mo.group(3), mo.group(4), heute=heute)
        if not tag:
            return mo.group(0)
        return _mit_praeposition(tag, praep or "am")

    def de_d(mo: re.Match) -> str:
        praep = (mo.group(1) or "").strip()
        jahr = mo.group(4) or str((heute or datetime.now(TZ).date()).year)
        tag = tag_wort(jahr, mo.group(3), mo.group(2), heute=heute)
        if not tag:
            return mo.group(0)
        return _mit_praeposition(tag, praep or "am")

    def monat_datum(mo: re.Match) -> str:
        tag = int(mo.group(1))
        return f"{_ORDINAL.get(tag, str(tag))} {mo.group(2)}"

    def uhrzeit(mo: re.Match) -> str:
        return zeit_wort(int(mo.group(1)), int(mo.group(2)))

    def punkt_zeit(mo: re.Match) -> str:
        return zeit_wort(int(mo.group(1)), int(mo.group(2)))

    def stunde(mo: re.Match) -> str:
        return zeit_wort(int(mo.group(1)), 0)

    out = text
    out = re.sub(r"\b(am\s+|vom\s+|zum\s+|f(?:ü|ue)r\s+den\s+)?(\d{4})-(\d{2})-(\d{2})[T ](\d{1,2}):(\d{2})(?::\d{2})?(?:[+-]\d{2}:?\d{2}|Z)?", iso_dt, out)
    out = re.sub(r"\b(am\s+|vom\s+|zum\s+|f(?:ü|ue)r\s+den\s+)?(\d{4})-(\d{2})-(\d{2})\b", iso_d, out)
    # "9.30 Uhr" (Punkt-Schreibweise) MUSS vor der Datums-Regel laufen,
    # sonst würde "9.12 Uhr" als 9. Dezember gelesen.
    out = re.sub(r"\b(\d{1,2})\.(\d{2})\s*Uhr\b", punkt_zeit, out)
    out = re.sub(r"\b(am\s+|vom\s+|zum\s+)?(\d{1,2})\.\s?(\d{1,2})\.(?!\s*Uhr\b)\s?(\d{4})?", de_d, out)
    # "14. November" -> "vierzehnten November" (Ziffer vor Monatsnamen)
    out = re.sub(
        r"\b(\d{1,2})\.\s*(Januar|Februar|März|Maerz|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember)\b",
        monat_datum, out,
    )
    # "09:15 Uhr" und "09:15"
    out = re.sub(r"\b(\d{1,2}):(\d{2})\s*Uhr\b", uhrzeit, out)
    out = re.sub(r"\b(\d{1,2}):(\d{2})\b", uhrzeit, out)
    # "15 Uhr" -> "fünfzehn Uhr"
    out = re.sub(r"\b(\d{1,2})\s*Uhr\b", stunde, out)
    return out


def _scrub_tech(text: str) -> str:
    out = _TECH.sub("", text)
    return _s(out.replace("()", "").replace("( )", ""))


def sanitize(text: str, *, heute: date | None = None) -> str:
    """Der EINE Filter vor der Stimme."""
    roh = _s(text)
    if not roh:
        return ""
    saetze = [_s(s) for s in _SATZ.split(roh) if _s(s)]
    ohne_tech = [s for s in saetze if not _TECH.search(s)]
    if not ohne_tech:
        # Alles war technisch: Begriffe entkernen statt verstummen.
        ohne_tech = [t for t in (_scrub_tech(s) for s in saetze) if t]
    # Regieanweisungen werden NIE vorgelesen — dann lieber Stille.
    out = " ".join(s for s in ohne_tech if not _REGIE.search(s))
    for cre, ersatz in _SLOTWORT:
        out = cre.sub(ersatz, out)
    out = _ersetze_zeiten(out, heute)
    out = re.sub(r"\s+([.,;:!?])", r"\1", out)
    out = re.sub(r"\(\s*\)", "", out)
    return _s(out)
