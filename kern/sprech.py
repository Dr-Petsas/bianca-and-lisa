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


def heute_zeile(jetzt: datetime | None = None) -> str:
    """Datums-Anker fuer den LLM-Systemprompt (30.08.2026): das Modell kennt
    das heutige Datum sonst NICHT und raet bei "Welcher Tag ist heute?".
    Die Terminmaschine rechnet unabhaengig davon immer mit der echten Uhr."""
    if jetzt is None:
        j = datetime.now(TZ)
    elif jetzt.tzinfo is not None:
        j = jetzt.astimezone(TZ)
    else:
        j = jetzt  # naiv (Tests): unveraendert verwenden
    morgen = j.date() + timedelta(days=1)
    return (
        f"Heute ist {_WOCHENTAG[j.weekday()]}, der {j.day}. {_MONAT[j.month]} {j.year}, "
        f"es ist {j.hour:02d}:{j.minute:02d} Uhr. "
        f"Morgen ist {_WOCHENTAG[morgen.weekday()]}, der {morgen.day}. {_MONAT[morgen.month]}."
    )

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

# Abkuerzungen ausschreiben — ElevenLabs buchstabiert "Dr." sonst.
# Muss VOR dem Satz-Splitten laufen, sonst gilt der Punkt als Satzende.
_ABK = (
    (re.compile(r"\bProf\.\s*Dr\.\s*", re.I), "Professor Doktor "),
    (re.compile(r"\bDr\.\s*med\.\s*dent\.\s*", re.I), "Doktor "),
    (re.compile(r"\bDr\.\s*med\.\s*", re.I), "Doktor "),
    (re.compile(r"\bDr\.\s*", re.I), "Doktor "),
    (re.compile(r"\bProf\.\s*", re.I), "Professor "),
    (re.compile(r"\bz\.\s*B\.\s*", re.I), "zum Beispiel "),
    (re.compile(r"\bbzw\.\s*", re.I), "beziehungsweise "),
    (re.compile(r"\busw\.\s*", re.I), "und so weiter "),
    (re.compile(r"\bca\.\s*", re.I), "circa "),
    (re.compile(r"\bStr\.\s*", re.I), "Straße "),
    (re.compile(r"\bggf\.\s*", re.I), "gegebenenfalls "),
)

# Interne Motiv-Kuerzel nie vorsprechen (Chef 20.09.2026): "KCH Kontrolle"
# -> "Kontrolle", "ZE Eingliederung" -> "Eingliederung".
_MOTIV_KUERZEL_RE = re.compile(
    r"\b(?:KCH|KFO|ZE|IMP|PAR|PRO|SLM|KB)(?:\s*\d)?[\s\-]+",
    re.I,
)


def motiv_kuerzel_raus(name: str, *, kurz: bool = False) -> str:
    """'KCH Kontrolluntersuchung' -> 'Kontrolluntersuchung'.

    ``kurz=True`` nimmt bei Schraegstrich nur den ersten Teil
    ('akute Beschwerden/Notfall' -> 'akute Beschwerden'), wie die alte
    Bianca. Am ganzen Satz bleibt der Schraegstrich stehen.
    """
    text = _s(name)
    if not text:
        return ""
    text = _MOTIV_KUERZEL_RE.sub("", text).strip()
    if kurz and "/" in text:
        text = text.split("/", 1)[0].strip()
    return text or _s(name)


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


# --- Satz-Grenz-Wache fuer den TTS-Split (W-TTS-NAHT 31.08.2026) -------------
# Portiert aus dem alten phone_agent (tts_chunks._splittable_prefix): ein
# Punkt hinter Ordnungszahl ("im 3. Stock"), Abkuerzung ("St. Martin",
# "Bahnhofstr. 12") oder Einzelbuchstabe ist KEIN Satzende — ein Split dort
# schneidet mitten in der Phrase, die Stimme klingt abgehackt.

ABKUERZUNGEN = frozenset({
    "dr", "prof", "med", "dent", "fr", "hr", "frl",
    "str", "nr", "tel", "abs", "st",
    "ca", "bzw", "ggf", "evtl", "inkl", "exkl", "zzgl", "usw", "etc",
    "min", "std", "mind", "max",
    "mo", "di", "mi", "do", "sa", "so",
    "z", "b",
})

_ABK_WORT_RE = re.compile(r"([A-Za-zÄÖÜäöüß]+)$")


def kein_satzende(davor: str) -> bool:
    """True, wenn der Text VOR einem '.' mit Ziffer, Abkuerzung oder
    Einzelbuchstabe endet — der Punkt gehoert dann zum Wort, nicht zum Satz.
    ``davor`` ist der Text OHNE den Punkt selbst."""
    d = davor.rstrip()
    if re.search(r"\d$", d):
        return True
    m = _ABK_WORT_RE.search(d)
    if m:
        w = m.group(1).lower()
        # endswith("str") faengt Strassennamen ("Bahnhofstr.", "Hauptstr.").
        return len(w) == 1 or w in ABKUERZUNGEN or w.endswith("str")
    return False


_TTS_SPLIT_RE = re.compile(r"(?<=[.!?]) +(?=[A-ZÄÖÜ])")


def tts_saetze(text: str) -> list[str]:
    """Satz-Split fuer die Stimme (dienst._sprech_blob / stimme_stream):
    wie der alte Split an [.!?]+Leerraum+Grossbuchstabe, aber NIE hinter
    Ordnungszahlen/Abkuerzungen — phone_agent-Lektion gegen abgehackte
    Woerter an der Naht."""
    t = _s(text)
    if not t:
        return []
    out: list[str] = []
    start = 0
    for m in _TTS_SPLIT_RE.finditer(t):
        vorn = t[start:m.start()]
        if vorn.endswith(".") and kein_satzende(vorn[:-1]):
            continue
        if vorn.strip():
            out.append(vorn.strip())
        start = m.end()
    rest = t[start:].strip()
    if rest:
        out.append(rest)
    return out


def _zahl(n: int) -> str:
    n = int(n)
    if n < 20:
        return _EINER[n]
    z, e = divmod(n, 10)
    if e == 0:
        return _ZEHNER.get(z, str(n))
    return f"{'ein' if e == 1 else _EINER[e]}und{_ZEHNER.get(z, str(z))}"


# --- Euro-Beträge (Chef 27.08.2026: grobe Preise nennen können) -------------
# _zahl/_ZEHNER decken nur Uhrzeiten (0-59) — Beträge brauchen die volle Reihe.

_ZEHNER_BETRAG = {
    2: "zwanzig", 3: "dreißig", 4: "vierzig", 5: "fünfzig",
    6: "sechzig", 7: "siebzig", 8: "achtzig", 9: "neunzig",
}


def _unter_hundert(n: int) -> str:
    if n < 20:
        return _EINER[n]
    z, e = divmod(n, 10)
    if e == 0:
        return _ZEHNER_BETRAG[z]
    return f"{'ein' if e == 1 else _EINER[e]}und{_ZEHNER_BETRAG[z]}"


def _unter_tausend(n: int) -> str:
    h, rest = divmod(n, 100)
    kopf = (("ein" if h == 1 else _EINER[h]) + "hundert") if h else ""
    if rest or not kopf:
        return kopf + _unter_hundert(rest)
    return kopf


def betrag_wort(n: int) -> str:
    """120 -> 'einhundertzwanzig', 1600 -> 'sechzehnhundert' (Sprech-Stil),
    2500 -> 'zweitausendfünfhundert'. Außerhalb 0..999999 bleiben Ziffern."""
    n = int(n)
    if n < 0 or n > 999_999:
        return str(n)
    if n < 1000:
        return _unter_tausend(n)
    if 1100 <= n <= 1999 and n % 100 == 0:
        return _unter_hundert(n // 100) + "hundert"
    t, rest = divmod(n, 1000)
    kopf = ("ein" if t == 1 else _unter_tausend(t)) + "tausend"
    return kopf + (_unter_tausend(rest) if rest else "")


# "1.400" (Tausenderpunkt) oder "1400"; Lookbehind schützt Dezimal-/Teilzahlen
# ("149,50 Euro" bleibt unangetastet, statt ",50" zu "fünfzig" zu machen).
_EURO_ZAHL = r"\d{1,3}(?:\.\d{3})+|\d+"
_EURO_SPANNE_RE = re.compile(
    rf"(?<![\d,.])({_EURO_ZAHL})\s*(bis|und|[-–—])\s*({_EURO_ZAHL})\s*(?:Euros?\b|€)"
)
_EURO_RE = re.compile(rf"(?<![\d,.])({_EURO_ZAHL})\s*(?:Euros?\b|€)")


def zahl_wort(n: int) -> str:
    """Reine Zahl als Wort: 4 -> 'vier', 21 -> 'einundzwanzig', 0 -> 'null'."""
    return betrag_wort(n)


def _betrag_gesprochen(n: int) -> str:
    return "ein" if n == 1 else betrag_wort(n)


_ZIF_WORT = (
    "null", "eins", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun",
)
# Rohziffern an Qwen3 = Kauderwelsch (06.09.2026). Gesprochen wird
# Ziffer fuer Ziffer in Gruppen, wie bianca.telefon.sprechbar.
_RUF_RE = re.compile(
    r"(?<![\d])(?:\+ ?49[\s/-]*|0049[\s/-]*)?"
    r"0?[1-9]\d(?:[\s/-]?\d){7,12}(?![\d])"
)


def _ruf_worte(nummer: str) -> str:
    d = "".join(c for c in nummer if c.isdigit())
    if d.startswith("49") and len(d) >= 11:
        d = "0" + d[2:]
    if not (d.startswith("0") and 10 <= len(d) <= 13):
        return nummer
    try:
        from bianca import telefon as tel
        return tel.sprechbar(d)
    except Exception:
        kopf = 4 if d.startswith("01") and len(d) >= 11 else min(4, len(d))
        teile = [d[:kopf]]
        rest = d[kopf:]
        while rest:
            n = 3 if len(rest) % 2 == 1 else 2
            teile.append(rest[:n])
            rest = rest[n:]
        return ", ".join(" ".join(_ZIF_WORT[int(c)] for c in g) for g in teile if g)


def _ersetze_rufnummern(text: str) -> str:
    def _eins(m: re.Match[str]) -> str:
        worte = _ruf_worte(m.group(0))
        if worte == m.group(0):
            return m.group(0)
        if m.start() > 0 and text[m.start() - 1] not in " \n\t([":
            return " " + worte
        return worte
    return _RUF_RE.sub(_eins, text)


def _ersetze_euro(text: str) -> str:
    def spanne(mo: re.Match) -> str:
        a = int(mo.group(1).replace(".", ""))
        b = int(mo.group(3).replace(".", ""))
        if a > 999_999 or b > 999_999:
            return mo.group(0)
        conn = mo.group(2) if mo.group(2) in {"bis", "und"} else "bis"
        return f"{_betrag_gesprochen(a)} {conn} {_betrag_gesprochen(b)} Euro"

    def einzel(mo: re.Match) -> str:
        n = int(mo.group(1).replace(".", ""))
        if n > 999_999:
            return mo.group(0)
        return f"{_betrag_gesprochen(n)} Euro"

    out = _EURO_SPANNE_RE.sub(spanne, text)
    return _EURO_RE.sub(einzel, out)


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


def ansage_woche(iso: str, *, heute: date | None = None) -> str:
    """Chef 20.09.2026: ohne 1./2./3., Woche statt morgen/übermorgen.

    dieselbe Woche  -> 'diesen Mittwoch um zehn Uhr zehn'
    nächste Woche   -> 'nächsten Montag um neun Uhr fünfzehn'
    später          -> 'Montag, den fünften Oktober um neun Uhr'
    heute           -> 'heute um …' (klarer als 'diesen Sonntag')
    """
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{1,2}):(\d{2})", _s(iso))
    if not m:
        return slot_wort(iso, heute=heute)
    d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    uhr = zeit_wort(int(m.group(4)), int(m.group(5)))
    ref = heute or datetime.now(TZ).date()
    wt = _WOCHENTAG[d.weekday()]
    if d == ref:
        return f"heute um {uhr}"
    diese_mo = ref - timedelta(days=ref.weekday())
    slot_mo = d - timedelta(days=d.weekday())
    wochen = (slot_mo - diese_mo).days // 7
    if wochen <= 0:
        return f"diesen {wt} um {uhr}"
    if wochen == 1:
        return f"nächsten {wt} um {uhr}"
    # Schon gesprochen — nie "Montag den 12.10.", sonst verdoppelt sanitize
    # den Wochentag und klebt "Oktoberum" (Live 41352183).
    kern = f"{wt}, den {_ORDINAL.get(d.day, str(d.day))} {_MONAT[d.month]}"
    if d.year != ref.year:
        kern += f" {d.year}"
    return f"{kern} um {uhr}"


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

    def wt_den_d(mo: re.Match) -> str:
        jahr = mo.group(4) or str((heute or datetime.now(TZ).date()).year)
        tag = tag_wort(jahr, mo.group(3), mo.group(2), heute=heute)
        if not tag:
            return mo.group(0)
        wt = mo.group(1)
        # tag_wort liefert "Donnerstag, den zehnten September" oder "morgen".
        if "," in tag:
            return tag
        return f"{wt}, {tag}" if tag not in {"heute", "morgen", "übermorgen"} else tag

    out = text
    out = re.sub(r"\b(am\s+|vom\s+|zum\s+|f(?:ü|ue)r\s+den\s+)?(\d{4})-(\d{2})-(\d{2})[T ](\d{1,2}):(\d{2})(?::\d{2})?(?:[+-]\d{2}:?\d{2}|Z)?", iso_dt, out)
    out = re.sub(r"\b(am\s+|vom\s+|zum\s+|f(?:ü|ue)r\s+den\s+)?(\d{4})-(\d{2})-(\d{2})\b", iso_d, out)
    # "9.30 Uhr" (Punkt-Schreibweise) MUSS vor der Datums-Regel laufen,
    # sonst würde "9.12 Uhr" als 9. Dezember gelesen.
    out = re.sub(r"\b(\d{1,2})\.(\d{2})\s*uhr\b", punkt_zeit, out, flags=re.I)
    # "Montag den 12.10." / "Dienstag 22.09." ist EIN Datum —
    # nicht noch einmal "am Montag" davorsetzen.
    out = re.sub(
        r"\b(Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag)"
        r",?\s+(?:den\s+)?(\d{1,2})\.\s?(\d{1,2})\.(?:\s?(\d{4}))?",
        wt_den_d,
        out,
        flags=re.I,
    )
    # \s? nur zusammen mit der Jahreszahl, sonst frisst es das Leerzeichen
    # vor "um" ("Oktoberum neun Uhr", Live 41352183).
    out = re.sub(
        r"\b(am\s+|vom\s+|zum\s+)?(\d{1,2})\.\s?(\d{1,2})\.(?!\s*uhr\b)(?:\s?(\d{4}))?",
        de_d,
        out,
        flags=re.I,
    )
    # "14. November" -> "vierzehnten November" (Ziffer vor Monatsnamen)
    out = re.sub(
        r"\b(\d{1,2})\.\s*(Januar|Februar|März|Maerz|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember)\b",
        monat_datum, out,
    )
    # "09:15 Uhr" und "09:15" — Semikolon wie Parakeet 9;30
    out = re.sub(r"\b(\d{1,2})[:;](\d{2})\s*uhr\b", uhrzeit, out, flags=re.I)
    out = re.sub(r"\b(\d{1,2})[:;](\d{2})\b", uhrzeit, out)
    # "15 Uhr" -> "fünfzehn Uhr"
    out = re.sub(r"\b(\d{1,2})\s*uhr\b", stunde, out, flags=re.I)

    def uhr_minute_wort(mo: re.Match) -> str:
        mm = int(mo.group(1))
        if 0 <= mm <= 59:
            return f"Uhr {_zahl(mm)}"
        return mo.group(0)

    # "neun Uhr 30" nach der Stunden-Umwandlung → "neun Uhr dreißig"
    out = re.sub(r"\buhr\s+(\d{1,2})\b", uhr_minute_wort, out, flags=re.I)
    return out


def _scrub_tech(text: str) -> str:
    out = _TECH.sub("", text)
    return _s(out.replace("()", "").replace("( )", ""))


# Chef 08.09.2026: Das Wort "Krebs" wird am Telefon nicht gesagt.
# Live Blessing 15.09.2026 zeigte aber die teure Nebenwirkung der pauschalen
# Ersetzung: "Hautkrebs-Screening" wurde als "Kontrolle" vorgelesen. Der
# Anrufer widersprach, obwohl intern bereits das richtige Screening-Motiv
# gewählt war. Spezifische Haut-Vorsorge bleibt deshalb spezifisch, nur das
# belastete Wort fällt: Hautscreening/Hautvorsorge statt Kontrolle.
_KREBS_TOKEN_RE = re.compile(r"[A-Za-zÄÖÜäöüß\-]*[Kk]rebs[A-Za-zÄÖÜäöüß\-]*")
_HAUTKREBS_SPEZIFISCH = (
    (re.compile(r"\bHautkrebs[\s-]*Screening\b", re.I), "Hautscreening"),
    (re.compile(r"\bHautkrebsscreening\b", re.I), "Hautscreening"),
    (re.compile(r"\bHautkrebs[\s-]*Vorsorge\b", re.I), "Hautvorsorge"),
    (re.compile(r"\bHautkrebsvorsorge\b", re.I), "Hautvorsorge"),
    (re.compile(r"\bHautkrebs[\s-]*Untersuchung\b", re.I), "Hautuntersuchung"),
    (re.compile(r"\bHautkrebsuntersuchung\b", re.I), "Hautuntersuchung"),
)


def ohne_krebs(text: str) -> str:
    """Krebswort entfernen, ohne ein konkretes Hautscreening umzubenennen."""
    roh = _s(text)
    if not roh or "krebs" not in roh.lower():
        return roh
    out = roh
    for cre, ersatz in _HAUTKREBS_SPEZIFISCH:
        out = cre.sub(ersatz, out)
    out = _KREBS_TOKEN_RE.sub("Kontrolle", out)
    out = re.sub(r"\bzum\s+Kontrolle\b", "zur Kontrolle", out, flags=re.I)
    out = re.sub(r"\bden\s+Kontrolle\b", "die Kontrolle", out, flags=re.I)
    out = re.sub(r"\bein\s+Kontrolle\b", "eine Kontrolle", out, flags=re.I)
    out = re.sub(r"(?:Kontrolle[\s\-]+){2,}", "Kontrolle ", out, flags=re.I)
    return _s(out)


def sanitize(text: str, *, heute: date | None = None) -> str:
    """Der EINE Filter vor der Stimme."""
    roh = _s(text)
    if not roh:
        return ""
    for cre, ersatz in _ABK:
        roh = cre.sub(ersatz, roh)
    roh = motiv_kuerzel_raus(roh)
    roh = _s(roh)
    saetze = [_s(s) for s in _SATZ.split(roh) if _s(s)]
    ohne_tech = [s for s in saetze if not _TECH.search(s)]
    if not ohne_tech:
        # Alles war technisch: Begriffe entkernen statt verstummen.
        ohne_tech = [t for t in (_scrub_tech(s) for s in saetze) if t]
    # Regieanweisungen werden NIE vorgelesen — dann lieber Stille.
    out = " ".join(s for s in ohne_tech if not _REGIE.search(s))
    for cre, ersatz in _SLOTWORT:
        out = cre.sub(ersatz, out)
    # Euro VOR den Zeit-/Datumsregeln: danach sind die Ziffern schon Worte
    # und keine Datumsregel kann einen Preis mehr zerlegen.
    out = _ersetze_euro(out)
    out = _ersetze_rufnummern(out)
    out = _ersetze_zeiten(out, heute)
    out = re.sub(r"\s+([.,;:!?])", r"\1", out)
    out = re.sub(r"\(\s*\)", "", out)
    return ohne_krebs(_s(out))
