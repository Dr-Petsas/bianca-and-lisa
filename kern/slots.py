"""Wunsch-Parser und Slot-Auswahl — portiert aus MAS lisa/callBooking.js (pure)."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Berlin")
WEEKDAYS = [
    (1, re.compile(r"\bmontags?\b")),
    (2, re.compile(r"\bdienstags?\b")),
    (3, re.compile(r"\bmittwochs?\b")),
    (4, re.compile(r"\bdonnerstags?\b")),
    (5, re.compile(r"\bfreitags?\b")),
    (6, re.compile(r"\bsamstags?\b")),
    (0, re.compile(r"\bsonntags?\b")),
]


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


# Zahlwort-Stunden fuer "zwölf Uhr fünfzehn" — live 27.08.2026: die Uhrzeit in
# Worten wurde gar nicht erkannt, der Wunsch "früher, so zwölf Uhr fünfzehn"
# lief als "vormittags" und bot nur andere Tage an.
_STUNDEN_WORT = {
    "ein": 1, "eins": 1, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "fuenf": 5,
    "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10, "elf": 11,
    "zwölf": 12, "zwoelf": 12, "dreizehn": 13, "vierzehn": 14, "fünfzehn": 15,
    "fuenfzehn": 15, "sechzehn": 16, "siebzehn": 17, "achtzehn": 18,
    "neunzehn": 19, "zwanzig": 20, "einundzwanzig": 21, "zweiundzwanzig": 22,
    "dreiundzwanzig": 23,
}
_UHR_RE = re.compile(
    r"\b(?:(?:um|gegen|auf|ab)\s+)?(\d{1,2}|"
    + "|".join(sorted(_STUNDEN_WORT, key=len, reverse=True))
    + r")(?:[:.](\d{2}))?\s*uhr\b",
    re.I,
)
_UHR_ZIFFER_RE = re.compile(r"\b(\d{1,2})[:;](\d{2})\b")
_UHR_PUNKT_RE = re.compile(r"\b(\d{1,2})[.,](\d{2})\s*uhr\b", re.I)


def _stunde_von(token: str) -> int | None:
    tok = token.strip().lower()
    if tok.isdigit():
        n = int(tok)
        return n if 0 <= n <= 23 else None
    return _STUNDEN_WORT.get(tok)


# STT klebt "neun Uhr dreißig" zu "neununddreißig" / "neun und dreißig"
# und "9:30" manchmal zu "um 39". Stunden 1–9, Minute immer 30.
_EINER_UHR = {
    "ein": 1, "eins": 1, "zwei": 2, "drei": 3, "vier": 4,
    "fünf": 5, "fuenf": 5, "sechs": 6, "sieben": 7, "acht": 8, "neun": 9,
}
_GEQUETSCHT_DREISSIG_RE = re.compile(
    r"\b(" + "|".join(sorted(_EINER_UHR, key=len, reverse=True)) + r")"
    r"(?:\s+und\s+|und)"
    r"(drei[sß]+ig)\b",
    re.I,
)
_ZAHL_DREISSIG_RE = re.compile(r"\b(?:um|gegen|auf)\s+3([1-9])\b", re.I)
_ZEIT_CUE_RE = re.compile(
    r"\b(?:um|gegen|auf|uhr|termin|vormittag|nachmittag|mittag|abend|"
    r"passt|bitte|frei|heute|morgen|übermorgen|uebermorgen|"
    r"montags?|dienstags?|mittwochs?|donnerstags?|freitags?|"
    r"samstags?|sonntags?)\b",
    re.I,
)
_ALTER_RE = re.compile(r"\b(?:jahre?|alt|geboren|geburtstag|alter)\b", re.I)
_GEQUETSCHT_FUELL = frozenset({
    "bitte", "gerne", "gern", "dann", "doch", "so", "etwa",
    "ungefähr", "ungefaehr", "der", "die", "das", "um", "gegen",
    "auf", "ein", "eine", "termin", "uhr", "passt", "heute", "morgen",
})


def _gequetscht_ok(text: str, m: re.Match) -> bool:
    if _ALTER_RE.search(text):
        return False
    if _ZEIT_CUE_RE.search(text):
        return True
    woerter = re.findall(r"[^\W\d_]+", text.casefold(), re.UNICODE)
    mashed = {
        m.group(0).casefold(),
        m.group(1).casefold(),
        m.group(2).casefold(),
        "und",
    }
    rest = [w for w in woerter if w not in mashed and w not in _GEQUETSCHT_FUELL]
    return not rest


def gequetscht_dreissig(text: str) -> tuple[int, int] | None:
    """'neununddreißig' / 'neun und dreißig' / 'um 39' → Stunde :30."""
    raw = _s(text)
    if not raw:
        return None
    m = _GEQUETSCHT_DREISSIG_RE.search(raw)
    if m and _gequetscht_ok(raw, m):
        h = _EINER_UHR.get(m.group(1).lower())
        if h:
            return h, 30
    m = _ZAHL_DREISSIG_RE.search(raw)
    if m:
        return int(m.group(1)), 30
    return None


def zeit_stt_hotwords() -> list[str]:
    """Parakeet soll 'Uhr' und 'dreißig' nicht zusammenkleben."""
    return ["Uhr", "dreißig", "dreissig", "halb"]


def _praxis_stunde(h: int) -> int:
    """'bis 4' am Telefon ist 16 Uhr, nicht 4 Uhr nachts."""
    return h + 12 if 1 <= int(h) <= 6 else int(h)


_SPANNE_STUNDE = (
    r"(\d{1,2}|" + "|".join(sorted(_EINER_UHR, key=len, reverse=True)) + r")"
)
_AB_UHR_RE = re.compile(
    r"\b(?:ab|fruehestens|frühestens|nach)\s+" + _SPANNE_STUNDE + r"(?::\d{2})?\s*uhr\b",
    re.I,
)
_AB_STUNDE_RE = re.compile(
    r"\b(?:ab|fruehestens|frühestens|nach)\s+" + _SPANNE_STUNDE + r"\b(?!\s*[.:]|uhr)",
    re.I,
)
_BIS_ARBEITEN_RE = re.compile(
    r"\bbis\s+" + _SPANNE_STUNDE + r"(?::\d{2})?(?:\s*uhr)?\s+"
    r"(?:arbeiten|arbeit\b|auf\s+arbeit|im\s+b[uü]ro)",
    re.I,
)
_ARBEITE_BIS_RE = re.compile(
    r"\barbeite\w*.{0,80}\bbis\s+" + _SPANNE_STUNDE,
    re.I,
)
_ZAHL_KLEIN = {
    "ein": 1, "eine": 1, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "fuenf": 5,
    "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10, "elf": 11,
    "zwölf": 12, "zwoelf": 12,
}
_ZAHL_ALT = r"\d{1,2}|" + "|".join(sorted(_ZAHL_KLEIN, key=len, reverse=True))
_IN_WOCHEN_RE = re.compile(
    r"\bin\s+(?:etwa\s+|ca\.?\s+|rund\s+)?(" + _ZAHL_ALT + r")\s+wochen?\b", re.I,
)
_IN_MONATEN_RE = re.compile(
    r"\bin\s+(?:etwa\s+|ca\.?\s+|rund\s+)?(" + _ZAHL_ALT + r")\s+monat(?:en)?\b", re.I,
)
_IN_TAGEN_RE = re.compile(
    r"\bin\s+(?:etwa\s+|ca\.?\s+|rund\s+)?(" + _ZAHL_ALT + r")\s+tagen\b", re.I,
)


def _zahl_klein(tok: str) -> int:
    tok = tok.strip().lower()
    if tok.isdigit():
        return int(tok)
    return int(_ZAHL_KLEIN.get(tok, 0))


def _uhr_spanne_min(t: str) -> int | None:
    """Früheste Stunde: 'ab 15 Uhr', 'bis 4 arbeiten', 'ich muss bis 16 Uhr arbeiten'."""
    m = _BIS_ARBEITEN_RE.search(t) or _ARBEITE_BIS_RE.search(t)
    if m:
        h = _stunde_von(m.group(1))
        if h is not None:
            return _praxis_stunde(h)
    m = _AB_UHR_RE.search(t)
    if m:
        h = _stunde_von(m.group(1))
        if h is not None:
            return _praxis_stunde(h) if 0 < h < 7 else h
    if re.search(r"\b(?:erst|danach|nur|immer)\b", t):
        m = _AB_STUNDE_RE.search(t)
        if m and not re.search(r"\bab\s+\d{1,2}\s*[./]\s*\d", t):
            h = _stunde_von(m.group(1))
            if h is not None:
                return _praxis_stunde(h) if 0 < h < 7 else h
    return None


def _voraus_tage(t: str) -> int:
    """'in zwei Wochen' → 14, 'in 7 Monaten' → 210, gedeckelt auf ein Jahr."""
    tage = 0
    m = _IN_WOCHEN_RE.search(t)
    if m:
        tage = max(tage, _zahl_klein(m.group(1)) * 7)
    m = _IN_MONATEN_RE.search(t)
    if m:
        tage = max(tage, _zahl_klein(m.group(1)) * 30)
    m = _IN_TAGEN_RE.search(t)
    if m:
        tage = max(tage, _zahl_klein(m.group(1)))
    return min(tage, 366) if tage else 0


def parse_slot_wish(text: str) -> dict[str, Any] | None:
    raw = _s(text)
    if not raw:
        return None
    t = f" {raw.lower()} "
    wish: dict[str, Any] = {
        "weekday": None, "hourMin": None, "hourMax": None,
        "hour": None, "minDaysAhead": 0, "date": None, "tage": None,
    }
    for idx, cre in WEEKDAYS:
        if cre.search(t):
            wish["weekday"] = idx
            break
    # Wortgrenzen: "früher"/"frühestens" ist ein RELATIVER Wunsch (vor dem
    # bestehenden Termin), KEINE Tageszeit — live 27.08.2026 wurde "früher"
    # als "vormittags 7-12" gedeutet und der Nachmittags-Slot fiel weg.
    if re.search(r"vormittag|morgens|\bmorgans\b|\bfrüh\b|\bfrueh\b", t):
        wish["hourMin"], wish["hourMax"] = 7, 12
    elif "nachmittag" in t:
        wish["hourMin"], wish["hourMax"] = 12, 18
    elif re.search(r"(?<!vor)(?<!nach)\bmittags?\b", t):
        wish["hourMin"], wish["hourMax"] = 12, 15
    elif re.search(r"abend|\bspaet\b|\bspät\b", t):
        wish["hourMin"], wish["hourMax"] = 16, 21
    if re.search(r"(?:ueber|über)n[äa]chste", t) and "woche" in t:
        wish["minDaysAhead"] = 14
    elif re.search(r"n[äa]chste woche|kommende woche", t):
        wish["minDaysAhead"] = 7
    voraus = _voraus_tage(t)
    if voraus:
        wish["minDaysAhead"] = max(int(wish["minDaysAhead"] or 0), voraus)
    # Uhrzeit: Ziffern ("13:15", "um 9 Uhr") UND Zahlwörter ("zwölf Uhr zwanzig").
    # Bei "statt zwölf Uhr fünfundvierzig bitte zwölf Uhr zwanzig" zählt die
    # ZIEL-Zeit — Nennungen direkt nach "statt" werden übersprungen.
    stunde = None
    minute = None
    for m in _UHR_RE.finditer(t):
        davor = t[max(0, m.start() - 12):m.start()]
        if re.search(r"\bstatt\s*$", davor):
            continue
        h = _stunde_von(m.group(1))
        if h is not None:
            stunde = h
            minute = int(m.group(2)) if m.group(2) and 0 <= int(m.group(2)) <= 59 else None
    if stunde is None:
        for src in (_UHR_ZIFFER_RE, _UHR_PUNKT_RE):
            for m in src.finditer(t):
                davor = t[max(0, m.start() - 12):m.start()]
                if re.search(r"\bstatt\s*$", davor):
                    continue
                h = _stunde_von(m.group(1))
                if h is not None and 0 <= int(m.group(2)) <= 59:
                    stunde = h
                    minute = int(m.group(2))
    if stunde is None:
        g = gequetscht_dreissig(t)
        if g:
            stunde, minute = g
    elif minute is None and re.search(r"\bdrei[sß]+ig\b", t):
        minute = 30
    # "ab 15 Uhr" / "bis 4 arbeiten" ist eine Untergrenze, keine Punktlandung.
    spanne = _uhr_spanne_min(t)
    if spanne is not None:
        lo = wish["hourMin"]
        wish["hourMin"] = spanne if lo is None else max(int(lo), spanne)
        if wish["hourMax"] is None or int(wish["hourMax"]) <= int(wish["hourMin"]):
            wish["hourMax"] = 20
        if stunde is not None and (
            int(stunde) == int(spanne) or (int(stunde) < 7 and int(stunde) + 12 == int(spanne))
        ):
            stunde = None
            minute = None
    if stunde is not None:
        wish["hour"] = stunde
        if minute is not None:
            wish["minute"] = minute
    # "heute um 14 Uhr einen Termin … verschieben": die Uhr gehört zum
    # BESTANDSTERMIN, nicht zum Neu-Wunsch (Lülf 08.09.2026).
    if _bestand_uhr_im_satz(t) and not re.search(
            r"\b(?:auf|zu|lieber|geht(?:'s|s)?)\s+(?:um\s+)?\d", t):
        wish["hour"] = None
        wish.pop("minute", None)
    datum = datum_aus_text(raw)
    tage = tage_aus_text(raw)
    if tage:
        wish["date"] = tage[0]
        if len(tage) > 1:
            wish["tage"] = tage
        wish["weekday"] = None
    elif datum:
        wish["date"] = datum
        wish["weekday"] = None
    if not wish.get("date"):
        _monatsspanne(t, wish)
    return wish


def _monatsende(jahr: int, monat: int) -> date:
    if monat == 12:
        return date(jahr + 1, 1, 1) - timedelta(days=1)
    return date(jahr, monat + 1, 1) - timedelta(days=1)


def _monatsspanne(t: str, wish: dict) -> None:
    """'nächsten Monat' / 'im Oktober' → von/bis, die Suche startet dort."""
    heute = datetime.now(TZ).date()
    erster = letzter = None
    if re.search(r"\bmonats?\b", t):
        if re.search(r"(?:ueber|über)n[äa]chste", t):
            sprung = 2
        elif re.search(r"n[äa]chste", t):
            sprung = 1
        elif re.search(r"\b(?:diese[mn]|laufende[mn])\s+monat", t):
            sprung = 0
        else:
            sprung = None
        if sprung is not None:
            monat = heute.month - 1 + sprung
            jahr = heute.year + monat // 12
            monat = monat % 12 + 1
            erster = date(jahr, monat, 1) if sprung else heute
            letzter = _monatsende(jahr, monat)
    if erster is None:
        for name, num in _MONAT_NAME.items():
            if name in {"jan", "feb", "mär", "mar"}:
                continue
            if re.search(rf"\b{re.escape(name)}\b", t):
                jahr = heute.year + (1 if num < heute.month else 0)
                erster = date(jahr, num, 1)
                if erster < heute:
                    erster = heute
                letzter = _monatsende(jahr, num)
                break
    if erster is None or letzter is None:
        return
    wish["von"] = erster.isoformat()
    wish["bis"] = letzter.isoformat()
    voraus = max(0, (erster - heute).days)
    if voraus:
        wish["minDaysAhead"] = max(int(wish.get("minDaysAhead") or 0), voraus)


_BESTAND_UHR_RE = re.compile(
    r"(?:heute|morgen).{0,28}\buhr\b.{0,80}termin|"
    r"termin.{0,48}(?:heute|morgen).{0,28}\buhr|"
    r"habe.{0,24}um\s+\w.{0,24}termin.{0,48}verschieb",
    re.I | re.S,
)


def _bestand_uhr_im_satz(t: str) -> bool:
    return bool(re.search(r"\bverschieb", t) and _BESTAND_UHR_RE.search(t))


_MONAT_NAME = {
    "januar": 1, "jan": 1, "februar": 2, "feb": 2,
    "märz": 3, "maerz": 3, "mär": 3, "marz": 3,
    "april": 4, "apr": 4, "mai": 5, "juni": 6, "jun": 6,
    "juli": 7, "jul": 7, "august": 8, "aug": 8,
    "september": 9, "sept": 9, "sep": 9,
    "oktober": 10, "okt": 10, "november": 11, "nov": 11,
    "dezember": 12, "dez": 12,
}
_MONAT_RE = re.compile(
    r"\b(\d{1,2})\.?\s+("
    + "|".join(sorted(_MONAT_NAME, key=len, reverse=True))
    + r")(?:\s+(\d{4}))?\b",
    re.I,
)
# "am 15.09" / "15.09." / "3.9.2026" — der Punkt nach dem Monat ist optional.
# "um 9.15" und "9.15 Uhr" bleiben Uhrzeiten, kein Datum.
_DATUM_ZAHL_RE = re.compile(r"\b(\d{1,2})\.\s*(\d{1,2})(?:\.(\d{4})?)?")

# "Donnerstag der 10." / "dem 21." / "den 29." — Tag ohne Monatsname.
# Nicht "am 3. Oktober" / "am 15.09" (das ist ein volles Datum).
_TAG_ORD_RE = re.compile(
    r"\b(?:am|dem|den|der)\s+(\d{1,2})\.(?!\s*\d)(?!\s*(?:"
    + "|".join(sorted(_MONAT_NAME, key=len, reverse=True))
    + r")\b)",
    re.I,
)
# "10. oder 21." ohne zweiten Artikel.
_TAG_ORD_MEHR_RE = re.compile(
    r"(?:oder|,|/|und)\s+(?:(?:am|dem|den|der)\s+)?(\d{1,2})\.(?!\s*\d)",
    re.I,
)


def _kalendertag(jahr: int, monat: int, tag: int):
    try:
        return datetime(jahr, monat, tag, tzinfo=TZ).date()
    except ValueError:
        return None


def _jahr_rollen(d):
    """Vergangene Kalendertage ohne Jahr → nächstes Jahr (am 15.03. im August)."""
    heute = datetime.now(TZ).date()
    if d < heute:
        try:
            return d.replace(year=d.year + 1)
        except ValueError:
            return d
    return d


def datum_aus_text(text: str) -> str:
    """Deutsches Datum aus dem Satz: 'am 15.09', 'am 3.9.', '15. September'."""
    raw = _s(text)
    if not raw:
        return ""
    t = f" {raw.lower()} "
    m = _MONAT_RE.search(t)
    if m:
        tag, monat = int(m.group(1)), _MONAT_NAME[m.group(2).lower()]
        jahr = int(m.group(3)) if m.group(3) else datetime.now(TZ).year
        d = _kalendertag(jahr, monat, tag)
        if d:
            if not m.group(3):
                d = _jahr_rollen(d)
            return d.isoformat()
    for dm in _DATUM_ZAHL_RE.finditer(t):
        davor = t[max(0, dm.start() - 8):dm.start()]
        danach = t[dm.end():dm.end() + 8]
        if re.search(r"uhr", danach):
            continue
        if re.search(r"\bum\s+$", davor):
            continue
        tag, monat = int(dm.group(1)), int(dm.group(2))
        if not (1 <= monat <= 12 and 1 <= tag <= 31):
            continue
        jahr_roh = dm.group(3)
        jahr = int(jahr_roh) if jahr_roh else datetime.now(TZ).year
        d = _kalendertag(jahr, monat, tag)
        if not d:
            continue
        if not jahr_roh:
            d = _jahr_rollen(d)
        return d.isoformat()
    return ""


def _tag_im_monat(tag: int, heute: date | None = None):
    """Nächster Kalendertag mit dieser Monatszahl (ab heute, sonst nächster Monat)."""
    if not (1 <= tag <= 31):
        return None
    basis = heute or datetime.now(TZ).date()
    d = _kalendertag(basis.year, basis.month, tag)
    if d and d >= basis:
        return d
    if basis.month == 12:
        return _kalendertag(basis.year + 1, 1, tag)
    return _kalendertag(basis.year, basis.month + 1, tag)


def tage_aus_text(text: str) -> list[str]:
    """Alle 'der 10.' / 'dem 21.' im Satz → ISO-Tage, aufsteigend, ohne Duplikat."""
    raw = _s(text)
    if not raw:
        return []
    heute = datetime.now(TZ).date()
    gefunden: list[str] = []
    gesehen: set[str] = set()
    t = f" {raw.lower()} "
    zahlen: list[int] = []
    for m in _TAG_ORD_RE.finditer(t):
        zahlen.append(int(m.group(1)))
    for m in _TAG_ORD_MEHR_RE.finditer(t):
        zahlen.append(int(m.group(1)))
    for n in zahlen:
        d = _tag_im_monat(n, heute)
        if not d:
            continue
        iso = d.isoformat()
        if iso in gesehen:
            continue
        gesehen.add(iso)
        gefunden.append(iso)
    return gefunden


def _region_tage(iso_date: str, radius: int = 2) -> list[str]:
    d = date.fromisoformat(iso_date)
    return [(d + timedelta(days=i)).isoformat() for i in range(-radius, radius + 1)]


_WT = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
_MONAT_WORT = {
    1: "Januar", 2: "Februar", 3: "März", 4: "April", 5: "Mai", 6: "Juni",
    7: "Juli", 8: "August", 9: "September", 10: "Oktober", 11: "November",
    12: "Dezember",
}
_ORDNUNG = {
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
_BIS_20 = (
    "null", "eins", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht",
    "neun", "zehn", "elf", "zwölf", "dreizehn", "vierzehn", "fünfzehn",
    "sechzehn", "siebzehn", "achtzehn", "neunzehn",
)
_ZEHNER = ("", "", "zwanzig", "dreißig", "vierzig", "fünfzig")


def _zahl_wort(n: int, *, stunde: bool = False) -> str:
    n = int(n)
    if n < 20:
        if stunde and n == 1:
            return "ein"
        return _BIS_20[n]
    zehner, einer = divmod(n, 10)
    if einer == 0:
        return _ZEHNER[zehner]
    eins = "ein" if einer == 1 else _BIS_20[einer]
    return f"{eins}und{_ZEHNER[zehner]}"


def _uhr_wort(hour: int, minute: int) -> str:
    stunde = _zahl_wort(int(hour), stunde=True)
    if int(minute) == 0:
        return f"{stunde} Uhr"
    return f"{stunde} Uhr {_zahl_wort(int(minute))}"


def _menge_wort(n: int) -> str:
    n = int(n)
    if 0 <= n < 20:
        return _zahl_wort(n)
    return str(n)


def tag_relativ(iso: str, *, heute: date | None = None) -> str:
    """Diese Woche 'diesen Freitag', nächste 'nächsten Montag',
    danach 'Dienstag in drei Wochen' / 'in vier Monaten' / 'den zwölften Oktober'."""
    d = date.fromisoformat(str(iso)[:10])
    ref = heute or datetime.now(TZ).date()
    wt = _WT[d.weekday()]
    wochen = (
        (d - timedelta(days=d.weekday())) - (ref - timedelta(days=ref.weekday()))
    ).days // 7
    if wochen <= 0:
        return f"diesen {wt}"
    if wochen == 1:
        return f"nächsten {wt}"
    if wochen <= 7:
        return f"{wt} in {_menge_wort(wochen)} Wochen"
    monate = (d.year - ref.year) * 12 + (d.month - ref.month)
    if monate >= 2:
        return f"{wt} in {_menge_wort(monate)} Monaten"
    return f"den {_ORDNUNG.get(d.day, str(d.day))} {_MONAT_WORT[d.month]}"


def spoken_slot(iso: str, heute: date | None = None) -> str:
    """Uhrzeit mit relativem Tag: 'diesen Freitag um neun Uhr dreißig'."""
    rel = tag_relativ(iso, heute=heute)
    try:
        stunde, minute = int(iso[11:13]), int(iso[14:16])
    except (TypeError, ValueError):
        return rel
    uhr = _uhr_wort(stunde, minute)
    if rel.startswith("den "):
        return f"{rel} um {uhr}"
    if " in " in rel and rel.endswith(("Wochen", "Monaten")):
        tag, rest = rel.split(" in ", 1)
        if rest.endswith("Monaten"):
            d = date.fromisoformat(str(iso)[:10])
            kalender = f"den {_ORDNUNG.get(d.day, str(d.day))} {_MONAT_WORT[d.month]}"
            return f"{tag} in {rest}, {kalender}, um {uhr}"
        return f"{tag} in {rest} um {uhr}"
    return f"{rel} um {uhr}"


def lage_von_stunde(hour: int) -> str:
    h = int(hour)
    if h < 12:
        return "frueh"
    if h < 15:
        return "mittags"
    if h < 18:
        return "nachmittags"
    return "abends"


def lage_von_text(text: str) -> str:
    t = _s(text).lower()
    if "nachmittag" in t:
        return "nachmittags"
    if re.search(r"(?<!vor)(?<!nach)\bmittags?\b", t):
        return "mittags"
    if re.search(r"vormittag|morgens|\bmorgans\b|\bfrüh\b|\bfrueh\b", t):
        return "frueh"
    if re.search(r"\babends?\b", t):
        return "abends"
    return ""


def lage_wort(hour: int) -> str:
    return {
        "frueh": "früh",
        "mittags": "mittags",
        "nachmittags": "nachmittags",
        "abends": "abends",
    }[lage_von_stunde(hour)]


def grob_label(iso: str, *, heute: date | None = None) -> str:
    """'diesen Montag früh' / 'Dienstag mittags in drei Wochen' — ohne Uhrzeit."""
    rel = tag_relativ(iso, heute=heute)
    try:
        lage = lage_wort(int(iso[11:13]))
    except (TypeError, ValueError):
        return rel
    if rel.startswith("den "):
        return f"{rel} {lage}"
    if " in " in rel:
        tag, rest = rel.split(" in ", 1)
        return f"{tag} {lage} in {rest}"
    return f"{rel} {lage}"


def _weekday_of(date_str: str) -> int:
    d = datetime.fromisoformat(f"{date_str}T12:00:00+00:00")
    return int(d.astimezone(TZ).strftime("%w"))  # 0=So


# Nie benachbarte Leer-Slots anbieten (Chef 27.08.2026, live: 12:15/12:45/13:15
# bzw. 09:30/09:45/10:00): am selben Tag mindestens 2,5 Stunden Abstand.
MIN_ABSTAND_MS = 150 * 60000
# Früher/später im ±3-h-Fenster: 30 Minuten reichen, sonst passt nur ein Slot.
SCHUB_ABSTAND_MS = 30 * 60000


def _vertraegt(kand: dict, gewaehlt: list[dict]) -> bool:
    return all(
        g["date"] != kand["date"] or abs(g["ms"] - kand["ms"]) >= MIN_ABSTAND_MS
        for g in gewaehlt
    )


def _streuen(pool: list[dict], parsed: list[dict], wish: dict | None, max_n: int) -> list[dict]:
    """Gestreute Auswahl: Vielfalt vor Dichte, der Wunsch bleibt führend.

    1. Erstes Angebot: bei konkreter Zielzeit ("gegen zehn") der nächstliegende
       Slot, sonst der früheste im Wunschrahmen.
    2. Dann je ein Slot pro WEITEREM Tag (Tag A vormittags + Tag B nachmittags
       schlägt zwei nahe Slots am selben Tag).
    3. Dann derselbe Tag, aber nur mit >= 2,5 h Abstand.
    4. Fallback (< 2 Optionen): lieber EIN Slot des Wunschtags plus Alternativen
       anderer Tage außerhalb des Wunschrahmens.
    5. Allerletzter Ausweg: nahe Slots durchrutschen lassen — besser als nichts.
    """
    if not pool:
        return []
    anker = pool[0]
    if wish and wish.get("hour") is not None:
        ziel = int(wish["hour"]) * 60 + int(wish.get("minute") or 0)
        anker = min(pool, key=lambda p: (abs(p["hour"] * 60 + int(p["time"][3:5]) - ziel), p["ms"]))
    gewaehlt = [anker]
    for p in pool:
        if len(gewaehlt) >= max_n:
            break
        if p["date"] not in {g["date"] for g in gewaehlt}:
            gewaehlt.append(p)
    for p in pool:
        if len(gewaehlt) >= max_n:
            break
        if p not in gewaehlt and _vertraegt(p, gewaehlt):
            gewaehlt.append(p)
    # Tageszeit, Tag oder Fenster: keine fremden Slots dazumischen.
    # Sonst wird aus "Nachmittag" wieder Montag früh (Blessing 22.09.).
    eng = bool(wish and (
        wish.get("hourMin") is not None or wish.get("hour") is not None
        or wish.get("weekday") is not None or wish.get("date")
        or wish.get("von") or wish.get("bis")
    ))
    if len(gewaehlt) < 2 and not eng:
        pool_ids = {id(p) for p in pool}
        for p in parsed:
            if len(gewaehlt) >= max_n:
                break
            if id(p) not in pool_ids and p not in gewaehlt and _vertraegt(p, gewaehlt):
                gewaehlt.append(p)
    if len(gewaehlt) < 2:
        for p in pool:
            if len(gewaehlt) >= max_n:
                break
            if p not in gewaehlt:
                gewaehlt.append(p)
    rest = sorted((g for g in gewaehlt if g is not anker), key=lambda p: p["ms"])
    return [anker] + rest


def _schub_dicht(pool: list[dict], max_n: int) -> list[dict]:
    """Nächste freie Plätze im Fenster, 30-Minuten-Abstand — kein Tages-Streu."""
    if not pool:
        return []
    out: list[dict] = []
    for p in pool:
        if all(p["date"] != g["date"] or abs(p["ms"] - g["ms"]) >= SCHUB_ABSTAND_MS for g in out):
            out.append(p)
        if len(out) >= max_n:
            break
    return out


def pick_slots(iso_slots: list[str], *, wish: dict | None = None, now_ms: int | None = None,
               exclude_iso: str = "", exclude_isos: list | set | None = None,
               max_n: int = 3, dringend: bool = False,
               schub: bool = False) -> dict[str, Any]:
    now = now_ms if now_ms is not None else int(datetime.now(TZ).timestamp() * 1000)
    # Gesperrte ISOs (Buchungs-Fails): per Minuten-Praefix, damit Offset-Formen
    # denselben Slot treffen (W-BOOK-RETRY 01.09.2026).
    gesperrt = {str(x)[:16] for x in (exclude_isos or []) if x}
    if exclude_iso:
        gesperrt.add(str(exclude_iso)[:16])
    parsed = []
    for iso in iso_slots or []:
        m = re.match(r"^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})", str(iso))
        if not m:
            continue
        try:
            ms = int(datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp() * 1000)
        except ValueError:
            continue
        if ms < now + 60 * 60000:
            continue
        if str(iso)[:16] in gesperrt:
            continue
        parsed.append({
            "iso": str(iso), "date": m.group(1), "time": f"{m.group(2)}:{m.group(3)}",
            "hour": int(m.group(2)), "ms": ms,
        })
    parsed.sort(key=lambda p: p["ms"])

    def apply(pool: list, w: dict | None = None) -> list:
        w = wish if w is None else w
        if not w:
            return pool
        out = pool
        if w.get("tage"):
            erlaubt = {str(d) for d in w["tage"] if d}
            if erlaubt:
                out = [p for p in out if p["date"] in erlaubt]
        elif w.get("date"):
            out = [p for p in out if p["date"] == w["date"]]
        if w.get("weekday") is not None:
            out = [p for p in out if _weekday_of(p["date"]) == w["weekday"]]
        if w.get("von"):
            out = [p for p in out if p["date"] >= str(w["von"])]
        if w.get("bis"):
            out = [p for p in out if p["date"] <= str(w["bis"])]
        if w.get("minDaysAhead"):
            # "Nächste Woche" meint den TAG in einer Woche ab Mitternacht —
            # nicht "mindestens 168 Stunden ab jetzt". Sonst fehlen am Zieltag
            # alle Zeiten VOR der aktuellen Uhrzeit (live 27.08.2026: Angebot
            # begann um 10:55 statt 09:55, weil der Anruf um 10:41 lief).
            ziel = datetime.fromtimestamp(now / 1000, TZ) + timedelta(days=w["minDaysAhead"])
            mitternacht = ziel.replace(hour=0, minute=0, second=0, microsecond=0)
            out = [p for p in out if p["ms"] >= int(mitternacht.timestamp() * 1000)]
        if w.get("hour") is not None:
            if w.get("minute") is not None:
                ziel_m = int(w["hour"]) * 60 + int(w["minute"])
                out = [
                    p for p in out
                    if p["hour"] * 60 + int(p["time"][3:5]) == ziel_m
                ]
            else:
                out = [p for p in out if int(p["hour"]) == int(w["hour"])]
        elif w.get("minutenMin") is not None:
            lo = int(w["minutenMin"])
            hi = int(w.get("minutenMax") if w.get("minutenMax") is not None else 24 * 60)
            out = [p for p in out if lo <= (p["hour"] * 60 + int(p["time"][3:5])) <= hi]
        elif w.get("hourMin") is not None:
            out = [p for p in out if w["hourMin"] <= p["hour"] < w["hourMax"]]
        return out

    pool = apply(parsed)
    matched = not wish or bool(pool)
    schieben = bool(schub or (wish and wish.get("schub")))
    nur_tag = bool(wish and wish.get("weekday") is not None)
    if not pool and wish and wish.get("date") and not schieben and not wish.get("tage"):
        # Konkretes Datum ohne Treffer: ±2 Tage in der Region, nicht irgendwo.
        nachbarn = [d for d in _region_tage(str(wish["date"]), 2) if d != wish["date"]]
        w2 = dict(wish)
        w2.pop("date", None)
        w2["tage"] = nachbarn
        pool = apply(parsed, w2)
        if pool:
            ziel = str(wish["date"])

            def _nahe(p: dict) -> tuple:
                return (abs((date.fromisoformat(p["date"]) - date.fromisoformat(ziel)).days), p["ms"])

            pool = sorted(pool, key=_nahe)
    if not pool and wish and (nur_tag or wish.get("hour") is not None):
        # Wunschzeit nicht frei: naechste Zeiten AM Wunschtag, nie die
        # ersten Slots der Kalenderseite (Live 888da5c5: Dienstag 13:30
        # wurde mit Montag 09:15 aufgefuellt).
        kandidaten = list(parsed)
        if nur_tag:
            kandidaten = [p for p in kandidaten if _weekday_of(p["date"]) == wish["weekday"]]
        if wish.get("hour") is not None and kandidaten:
            ziel_m = int(wish["hour"]) * 60 + int(wish.get("minute") or 0)
            kandidaten = sorted(
                kandidaten,
                key=lambda p: (
                    abs(p["hour"] * 60 + int(p["time"][3:5]) - ziel_m),
                    p["ms"],
                ),
            )
        if kandidaten:
            pool = kandidaten
            matched = False
    if not pool and parsed and not schieben and wish:
        # Volle Kalenderseite nie als "kein Termin" verwerfen (Blessing
        # 24.09.2026: 20 Zeiten da, gesagt wurde "nichts frei").
        ziel = str(wish.get("date") or wish.get("von") or "")[:10]
        ziel_m = None
        if wish.get("hour") is not None:
            ziel_m = int(wish["hour"]) * 60 + int(wish.get("minute") or 0)

        def _rang(p: dict) -> tuple:
            tage = 99
            if len(ziel) == 10:
                try:
                    tage = abs((date.fromisoformat(p["date"]) - date.fromisoformat(ziel)).days)
                except ValueError:
                    tage = 99
            minute = 0 if ziel_m is None else abs(
                p["hour"] * 60 + int(p["time"][3:5]) - ziel_m)
            return (tage, minute, p["ms"])

        pool = sorted(parsed, key=_rang)
        matched = False
    elif not pool:
        if schieben:
            return {"slots": [], "wishMatched": False}
        pool = parsed
    if dringend:
        auswahl = pool[:max_n]
    elif schieben or (wish and wish.get("date") and not matched) or (not matched and (nur_tag or (wish and wish.get("hour") is not None))):
        # Wunschzeit verfehlt: dicht am Anker bleiben, nicht Tage streuen.
        auswahl = _schub_dicht(pool, max_n)
    elif nur_tag or (wish and wish.get("hour") is not None):
        # Treffer im Wunschrahmen: Alternativen nur AUS diesem Rahmen.
        auswahl = _streuen(pool, pool, wish, max_n)
    else:
        auswahl = _streuen(pool, parsed, wish, max_n)
    slots = [{"iso": p["iso"], "date": p["date"], "time": p["time"]} for p in auswahl]
    return {"slots": slots, "wishMatched": matched}


def _oder(teile: list[str]) -> str:
    teile = [x for x in teile if x]
    if not teile:
        return ""
    if len(teile) == 1:
        return teile[0]
    if len(teile) == 2:
        return f"{teile[0]} oder {teile[1]}"
    return ", ".join(teile[:-1]) + " oder " + teile[-1]


_WOCHENTAG_STAMM = (
    (1, "montag"), (2, "dienstag"), (3, "mittwoch"),
    (4, "donnerstag"), (5, "freitag"), (6, "samstag"), (0, "sonntag"),
)
_ANGEBOT_NEIN_RE = re.compile(
    r"\b(?:keiner|keins|keines)\b|"
    r"\bkeine[rn]?\s+(?:davon|termin)|"
    r"passt(?:\s+mir)?\s+nicht|nichts\s+davon|geht(?:\s+bei\s+mir)?\s+nicht|"
    r"\bdavor\b|nicht\s+schneller|"
    r"brauche\s+(?:ich\s+)?(?:das\s+)?nicht|"
    r"nicht\s+in\s+\w+\s+monat",
    re.I,
)
_JAHR_RE = re.compile(
    r"\b20\d{2}\b|neue[sn]?\s+jahr|n[äa]chste[sn]?\s+jahr",
    re.I,
)
_LISTENWAHL_RE = re.compile(
    r"\b(?:der|die|das|den)\s+(?:früher|frueher|später|spaeter|hintere|vordere)\w*\b|"
    r"\b(?:vorne|hinten)\b",
    re.I,
)


def wochentag_im_text(text: str) -> int | None:
    """Wochentag, auch in 'Freitagvormittag' ohne Wortgrenze."""
    t = f" {_s(text).lower()} "
    for idx, cre in WEEKDAYS:
        if cre.search(t):
            return idx
    for idx, stamm in _WOCHENTAG_STAMM:
        if re.search(rf"\b{stamm}", t):
            return idx
    return None


def angebot_abgelehnt(text: str) -> bool:
    """'Keiner', 'passt nicht', 'davor' wählen nie einen Termin.

    'Nein, den ersten' und 'nein, dienstags' bleiben eine Wahl, wenn der
    Tag im Angebot liegt. Das prüft der Aufrufer über wahl_gesperrt.
    """
    return bool(_ANGEBOT_NEIN_RE.search(_s(text)))


def such_richtung(text: str) -> str:
    t = _s(text).lower()
    if re.search(r"\b(?:früher|frueher|davor|vorher)\b|nicht\s+schneller|"
                 r"nicht\s+in\s+\w+\s+monat|brauche\s+(?:ich\s+)?(?:das\s+)?nicht", t):
        return "frueher"
    if re.search(r"\bspäter\b|\bspaeter\b", t) and not _LISTENWAHL_RE.search(t):
        return "spaeter"
    return "fenster"


def richtungswunsch(text: str, offered: list[dict]) -> dict | None:
    """Wunsch außerhalb der genannten Tage: früher, später, Jahr, Monat."""
    t = f" {_s(text).lower()} "
    isos = sorted(str(o.get("iso") or "") for o in offered or [] if o.get("iso"))
    jahr = _JAHR_RE.search(t)
    if jahr and jahr.group(0)[:2] == "20":
        j = int(jahr.group(0))
        heute = datetime.now(TZ).date()
        anfang = date(j, 1, 1)
        ende = date(j, 12, 31)
        if ende < heute:
            return None
        if anfang < heute:
            anfang = heute
        return {"von": anfang.isoformat(), "bis": ende.isoformat(), "minDaysAhead": 0}
    if re.search(r"neue[sn]?\s+jahr|n[äa]chste[sn]?\s+jahr", t):
        j = datetime.now(TZ).year + 1
        return {"von": f"{j}-01-01", "bis": f"{j}-12-31", "minDaysAhead": 0}
    if not isos:
        return None
    if re.search(r"\bspäter\b|\bspaeter\b", t) and not _LISTENWAHL_RE.search(t):
        tag = date.fromisoformat(isos[-1][:10]) + timedelta(days=1)
        return {"von": tag.isoformat(), "minDaysAhead": 0}
    if such_richtung(text) == "frueher":
        tag = date.fromisoformat(isos[0][:10]) - timedelta(days=1)
        heute = datetime.now(TZ).date()
        if tag < heute:
            tag = heute
        out: dict[str, Any] = {"bis": tag.isoformat(), "minDaysAhead": 0}
        wd = wochentag_im_text(text)
        if wd is not None:
            out["weekday"] = wd
        return out
    return None


def wahl_gesperrt(text: str, offered: list[dict]) -> bool:
    """Ablehnung und ein Tag, der nicht in der Liste steht, sind keine Zusage."""
    if angebot_abgelehnt(text):
        return True
    if _LISTENWAHL_RE.search(_s(text)):
        return False
    wd = wochentag_im_text(text)
    if wd is not None and offered:
        if not any(_weekday_of(str(o.get("iso") or "")[:10]) == wd for o in offered):
            return True
    t = _s(text).lower()
    if re.search(r"\b(?:später|spaeter|früher|frueher)\b", t):
        if re.search(r"\buhr\b|\d{1,2}[:.]\d{2}", t):
            return False
        return True
    if re.search(r"\bnein\b", t) and not re.search(
            r"\b(?:erste|zweite|dritte|letzte)\w*", t):
        if wd is None:
            return True
    return False


def naechster_iso(iso_slots: list, *, wish: dict | None = None) -> str:
    """Nächster echter Termin, wenn von/bis im Fenster nichts trifft."""
    isos = []
    for v in iso_slots or []:
        iso = v.get("iso") if isinstance(v, dict) else str(v)
        if iso:
            isos.append(str(iso))
    if not isos:
        return ""
    if wish and (wish.get("von") or wish.get("bis")):
        von = str(wish.get("von") or "")
        bis = str(wish.get("bis") or "")
        im_fenster = [
            iso for iso in isos
            if (not von or iso[:10] >= von) and (not bis or iso[:10] <= bis)
        ]
        if im_fenster:
            return ""
        return min(isos)
    if wish and pick_slots(isos, wish=wish).get("slots"):
        return ""
    return min(isos)


def _stehende_liste(text: str, offered: list[dict]) -> bool:
    """Genau einer der genannten Termine ist gemeint.

    'Mittwochfrüh bitte, in sechs Wochen' wählt den so angesagten Termin.
    'in zwei Wochen' gegen ein Angebot 'in sechs Wochen' sucht weiter.
    """
    if not offered or angebot_abgelehnt(text):
        return False
    treffer = _auswahl_nach_label(text, offered)
    if len(treffer) != 1:
        return False
    ziel = str(treffer[0].get("iso") or "")
    label = ""
    for slot, lab in zip(offered, _angebot_labels(offered)):
        if str(slot.get("iso") or "") == ziel:
            label = lab.lower()
            break
    span = re.search(
        r"\bin\s+(?:\S+\s+){0,3}(?:woche|wochen|monat|monaten|tagen)\b",
        _s(text).lower(),
    )
    if span and span.group(0) not in label:
        return False
    return True


def will_neu_suchen(text: str, offered: list[dict]) -> bool:
    """Neuer Rahmen ('ab 15 Uhr', 'in zwei Wochen', 'nächsten Monat') — keine Wahl aus dem Angebot."""
    if _stehende_liste(text, offered):
        return False
    if not offered:
        return False
    if _JAHR_RE.search(_s(text)):
        return True
    w = parse_slot_wish(text) or {}
    if w.get("weekday") is None:
        wd = wochentag_im_text(text)
        if wd is not None:
            w = dict(w)
            w["weekday"] = wd
    if not w:
        return False
    if int(w.get("minDaysAhead") or 0) > 0 or w.get("von") or w.get("bis"):
        return True
    if _uhr_spanne_min(f" {_s(text).lower()} ") is not None:
        return True
    tage = {str(o.get("iso") or "")[:10] for o in offered}
    if w.get("date") and w["date"] not in tage:
        return True
    if w.get("weekday") is not None:
        # "Dienstag mittags" trifft auch ein Angebot, dessen spätere Zeit
        # nur zur Unterscheidung "mittags" heißt (10:10 früh, 10:30 mittags).
        gleiche = [
            o for o in offered
            if _weekday_of(str(o.get("iso") or "")[:10]) == w["weekday"]
        ]
        if not gleiche:
            return True
        if _auswahl_nach_label(text, offered):
            return False
        lage = lage_von_text(text)
        if lage and not any(
            lage_von_stunde(int(str(o.get("iso"))[11:13])) == lage for o in gleiche
        ):
            return True
        return False
    if w.get("hour") is not None:
        return not any(int(str(o.get("iso"))[11:13]) == int(w["hour"]) for o in offered)
    if w.get("hourMin") is not None and lage_von_text(text):
        return True
    return False


_LAGE_KETTE = ("frueh", "mittags", "nachmittags", "abends")
_LAGE_WORT = {
    "frueh": "früh",
    "mittags": "mittags",
    "nachmittags": "nachmittags",
    "abends": "abends",
}


def _angebot_labels(slots: list[dict], heute: date | None = None) -> list[str]:
    """Tageszeit je Termin. Zwei Zeiten am selben Tag teilen sich nie dasselbe Wort:
    10:10 bleibt früh, 10:30 wird mittags, damit die Uhrzeit noch nicht fällt."""
    rels: list[str] = []
    stufe: list[int] = []
    for x in slots:
        rels.append(tag_relativ(x["iso"], heute=heute))
        try:
            stufe.append(_LAGE_KETTE.index(lage_von_stunde(int(x["iso"][11:13]))))
        except (TypeError, ValueError, IndexError):
            stufe.append(0)
    benutzt: set[tuple[str, int]] = set()
    for i in range(len(slots)):
        while stufe[i] < len(_LAGE_KETTE) - 1 and (rels[i], stufe[i]) in benutzt:
            stufe[i] += 1
        benutzt.add((rels[i], stufe[i]))
    labels = []
    for i, rel in enumerate(rels):
        lage = _LAGE_WORT[_LAGE_KETTE[stufe[i]]]
        if rel.startswith("den "):
            labels.append(f"{rel} {lage}")
        elif " in " in rel:
            tag, rest = rel.split(" in ", 1)
            labels.append(f"{tag} {lage} in {rest}")
        else:
            labels.append(f"{rel} {lage}")
    return labels


_WT_STAMM = (
    r"(?:montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)"
)


def _lage_worte(text: str) -> set[str]:
    t = _s(text).lower()
    # 'Mittwochfrüh' und 'Freitagvormittag' sind ein Wort. Die Tageszeit
    # steckt dann ohne eigene Wortgrenze im Wochentag.
    if "nachmittag" in t or re.search(rf"{_WT_STAMM}nachmittag", t):
        return {"nachmittags"}
    if re.search(rf"(?<!vor)(?<!nach)\bmittags?\b|{_WT_STAMM}mittag", t):
        return {"mittags"}
    if re.search(
        rf"vormittag|morgens|\bmorgans\b|\bfrüh\b|\bfrueh\b|{_WT_STAMM}fr(?:ue|ü)h",
        t,
    ):
        return {"früh"}
    if re.search(rf"\babends?\b|{_WT_STAMM}abend", t):
        return {"abends"}
    return set()


def _wochentage_im_text(text: str) -> list[str]:
    t = _s(text).lower()
    namen = (
        "montag", "dienstag", "mittwoch", "donnerstag",
        "freitag", "samstag", "sonntag",
    )
    return [name for name in namen if re.search(rf"\b{name}", t)]


def _span_im_text(text: str) -> str:
    """'in zwei Wochen' — die Spanne, die Bianca selbst vorgesprochen hat."""
    m = re.search(
        r"\bin\s+(?:\S+\s+){0,3}(?:woche|wochen|monat|monaten|tagen)\b",
        _s(text).lower(),
    )
    return m.group(0) if m else ""


def _auswahl_nach_label(
    text: str, offered: list[dict], heute: date | None = None,
) -> list[dict]:
    tage = _wochentage_im_text(text)
    lagen = _lage_worte(text)
    span = _span_im_text(text)
    if not tage and not lagen and not span:
        return []
    out = []
    for slot, label in zip(offered, _angebot_labels(offered, heute)):
        lab = label.lower()
        if tage and not any(tag in lab for tag in tage):
            continue
        if lagen and not any(lage in lab for lage in lagen):
            continue
        if span and span not in lab:
            continue
        out.append(slot)
    return out


def angebot_engen(
    text: str, offered: list[dict], heute: date | None = None,
) -> list[dict]:
    """'Montag früh' oder 'Dienstag mittags' grenzt das Angebot ein."""
    if not offered or will_neu_suchen(text, offered):
        return []
    aus = _auswahl_nach_label(text, offered, heute)
    if aus and len(aus) < len(offered):
        return aus
    w = parse_slot_wish(text) or {}
    out = list(offered)
    if w.get("date"):
        out = [o for o in out if str(o.get("iso") or "").startswith(str(w["date"]))]
    elif w.get("hour") is not None:
        out = [o for o in out if int(str(o.get("iso"))[11:13]) == int(w["hour"])]
    if not out or len(out) == len(offered):
        return []
    return out


def spoken_offer(
    slots: list[dict], *, wish_matched: bool = True, genau: bool = False,
    heute: date | None = None,
) -> str:
    """Zuerst die Tageszeit, die Uhrzeit erst bei der konkreten Wahl."""
    if not slots:
        return (
            "Im Moment habe ich leider keinen freien Termin. "
            "Die Praxis meldet sich kurzfristig bei Ihnen."
        )
    labels = _angebot_labels(slots, heute)
    if genau or len(slots) == 1 or len(set(labels)) < len(labels):
        kerne = [spoken_slot(x["iso"], heute=heute) for x in slots]
        frage = " Welcher passt Ihnen?" if len(slots) > 1 else " Passt Ihnen das?"
        kern = f"Ich kann Ihnen {_oder(kerne)} anbieten.{frage}"
    else:
        kern = f"Ich kann Ihnen {_oder(labels)} anbieten."
    if not wish_matched:
        kern = "Genau dann ist leider nichts frei. " + kern
    return kern


REGIE_ANGEBOT = (
    "Nenne die freien Zeiten genau so, wie sie im Feld spoken stehen. "
    "Sobald der Patient einen wählt: sofort book_slot mit dem unveränderten iso."
)
