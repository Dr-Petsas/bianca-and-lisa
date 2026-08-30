"""Wunsch-Parser und Slot-Auswahl — portiert aus MAS lisa/callBooking.js (pure)."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from kern.sprech import slot_wort

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
    + r")(?::(\d{2}))?\s*uhr\b",
    re.I,
)
_UHR_ZIFFER_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")


def _stunde_von(token: str) -> int | None:
    tok = token.strip().lower()
    if tok.isdigit():
        n = int(tok)
        return n if 0 <= n <= 23 else None
    return _STUNDEN_WORT.get(tok)


def parse_slot_wish(text: str) -> dict[str, Any] | None:
    raw = _s(text)
    if not raw:
        return None
    t = f" {raw.lower()} "
    wish: dict[str, Any] = {
        "weekday": None, "hourMin": None, "hourMax": None,
        "hour": None, "minDaysAhead": 0, "date": None,
    }
    for idx, cre in WEEKDAYS:
        if cre.search(t):
            wish["weekday"] = idx
            break
    # Wortgrenzen: "früher"/"frühestens" ist ein RELATIVER Wunsch (vor dem
    # bestehenden Termin), KEINE Tageszeit — live 27.08.2026 wurde "früher"
    # als "vormittags 7-12" gedeutet und der Nachmittags-Slot fiel weg.
    if re.search(r"vormittag|morgens|\bfrüh\b|\bfrueh\b", t):
        wish["hourMin"], wish["hourMax"] = 7, 12
    elif "nachmittag" in t:
        wish["hourMin"], wish["hourMax"] = 12, 18
    elif re.search(r"abend|\bspaet\b|\bspät\b", t):
        wish["hourMin"], wish["hourMax"] = 16, 21
    if re.search(r"n[äa]chste woche|kommende woche", t):
        wish["minDaysAhead"] = 7
    elif re.search(r"uebernaechste|übernächste", t):
        wish["minDaysAhead"] = 14
    # Uhrzeit: Ziffern ("13:15", "um 9 Uhr") UND Zahlwörter ("zwölf Uhr zwanzig").
    # Bei "statt zwölf Uhr fünfundvierzig bitte zwölf Uhr zwanzig" zählt die
    # ZIEL-Zeit — Nennungen direkt nach "statt" werden übersprungen.
    stunde = None
    for m in _UHR_RE.finditer(t):
        davor = t[max(0, m.start() - 12):m.start()]
        if re.search(r"\bstatt\s*$", davor):
            continue
        h = _stunde_von(m.group(1))
        if h is not None:
            stunde = h
    if stunde is None:
        for m in _UHR_ZIFFER_RE.finditer(t):
            davor = t[max(0, m.start() - 12):m.start()]
            if re.search(r"\bstatt\s*$", davor):
                continue
            h = _stunde_von(m.group(1))
            if h is not None and 0 <= int(m.group(2)) <= 59:
                stunde = h
    if stunde is not None:
        wish["hour"] = stunde
    datum = datum_aus_text(raw)
    if datum:
        wish["date"] = datum
    return wish


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


def _region_tage(iso_date: str, radius: int = 2) -> list[str]:
    d = date.fromisoformat(iso_date)
    return [(d + timedelta(days=i)).isoformat() for i in range(-radius, radius + 1)]


def spoken_slot(iso: str) -> str:
    """Sprechbar, nicht ablesbar: 'morgen um neun Uhr fünfzehn'."""
    return slot_wort(iso)


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
        ziel = int(wish["hour"]) * 60
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
    if len(gewaehlt) < 2:
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
               exclude_iso: str = "", max_n: int = 3, dringend: bool = False,
               schub: bool = False) -> dict[str, Any]:
    now = now_ms if now_ms is not None else int(datetime.now(TZ).timestamp() * 1000)
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
        if exclude_iso and str(iso) == exclude_iso:
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
        if w.get("minDaysAhead"):
            # "Nächste Woche" meint den TAG in einer Woche ab Mitternacht —
            # nicht "mindestens 168 Stunden ab jetzt". Sonst fehlen am Zieltag
            # alle Zeiten VOR der aktuellen Uhrzeit (live 27.08.2026: Angebot
            # begann um 10:55 statt 09:55, weil der Anruf um 10:41 lief).
            ziel = datetime.fromtimestamp(now / 1000, TZ) + timedelta(days=w["minDaysAhead"])
            mitternacht = ziel.replace(hour=0, minute=0, second=0, microsecond=0)
            out = [p for p in out if p["ms"] >= int(mitternacht.timestamp() * 1000)]
        if w.get("hour") is not None:
            out = [p for p in out if abs(p["hour"] - w["hour"]) <= 1]
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
    if not pool:
        if schieben or (wish and (wish.get("date") or wish.get("tage") or wish.get("minutenMin") is not None)):
            # Schub/Datum ohne Treffer: NICHT auf die drei Vormittagsslots
            # zurückfallen (live 30.08.2026: „keine weiteren“ + dieselben 09:45er).
            return {"slots": [], "wishMatched": False}
        pool = parsed
    if dringend:
        auswahl = pool[:max_n]
    elif schieben or (wish and wish.get("date") and not matched):
        # Region um ein leeres Wunschdatum: nur die Nachbartage, kein
        # Streu-Fallback auf Vormittage in drei Wochen.
        auswahl = _schub_dicht(pool, max_n)
    else:
        auswahl = _streuen(pool, parsed, wish, max_n)
    slots = [{"iso": p["iso"], "date": p["date"], "time": p["time"]} for p in auswahl]
    return {"slots": slots, "wishMatched": matched}


def spoken_offer(slots: list[dict], *, wish_matched: bool = True) -> str:
    """Nur was der Patient hört — keine Werkzeugnamen, keine Regie."""
    if not slots:
        return (
            "Im Moment habe ich leider keinen freien Termin. "
            "Die Praxis meldet sich kurzfristig bei Ihnen."
        )
    liste = "; oder ".join(spoken_slot(x["iso"]) for x in slots)
    if wish_matched:
        return f"Frei ist {liste}. Welcher passt Ihnen?"
    return f"Genau dann ist leider nichts frei. Frei wäre {liste}. Welcher passt Ihnen?"


REGIE_ANGEBOT = (
    "Nenne die freien Zeiten genau so, wie sie im Feld spoken stehen. "
    "Sobald der Patient einen wählt: sofort book_slot mit dem unveränderten iso."
)
