"""Wunsch-Parser und Slot-Auswahl — portiert aus MAS lisa/callBooking.js (pure)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
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
    dm = re.search(r"\b(\d{1,2})\.\s?(\d{1,2})\.(?:\s?(\d{4}))?", t)
    if dm:
        year = dm.group(3) or str(datetime.now(TZ).year)
        wish["date"] = f"{year}-{int(dm.group(2)):02d}-{int(dm.group(1)):02d}"
    return wish


def spoken_slot(iso: str) -> str:
    """Sprechbar, nicht ablesbar: 'morgen um neun Uhr fünfzehn'."""
    return slot_wort(iso)


def _weekday_of(date_str: str) -> int:
    d = datetime.fromisoformat(f"{date_str}T12:00:00+00:00")
    return int(d.astimezone(TZ).strftime("%w"))  # 0=So


# Nie benachbarte Leer-Slots anbieten (Chef 27.08.2026, live: 12:15/12:45/13:15
# bzw. 09:30/09:45/10:00): am selben Tag mindestens 2,5 Stunden Abstand.
MIN_ABSTAND_MS = 150 * 60000


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


def pick_slots(iso_slots: list[str], *, wish: dict | None = None, now_ms: int | None = None,
               exclude_iso: str = "", exclude_isos: list | set | None = None,
               max_n: int = 3, dringend: bool = False) -> dict[str, Any]:
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

    def apply(pool: list) -> list:
        if not wish:
            return pool
        out = pool
        if wish.get("date"):
            out = [p for p in out if p["date"] == wish["date"]]
        if wish.get("weekday") is not None:
            out = [p for p in out if _weekday_of(p["date"]) == wish["weekday"]]
        if wish.get("minDaysAhead"):
            # "Nächste Woche" meint den TAG in einer Woche ab Mitternacht —
            # nicht "mindestens 168 Stunden ab jetzt". Sonst fehlen am Zieltag
            # alle Zeiten VOR der aktuellen Uhrzeit (live 27.08.2026: Angebot
            # begann um 10:55 statt 09:55, weil der Anruf um 10:41 lief).
            ziel = datetime.fromtimestamp(now / 1000, TZ) + timedelta(days=wish["minDaysAhead"])
            mitternacht = ziel.replace(hour=0, minute=0, second=0, microsecond=0)
            out = [p for p in out if p["ms"] >= int(mitternacht.timestamp() * 1000)]
        if wish.get("hour") is not None:
            out = [p for p in out if abs(p["hour"] - wish["hour"]) <= 1]
        elif wish.get("hourMin") is not None:
            out = [p for p in out if wish["hourMin"] <= p["hour"] < wish["hourMax"]]
        return out

    pool = apply(parsed)
    matched = not wish or bool(pool)
    if not pool:
        pool = parsed
    if dringend:
        # Notfall/akute Beschwerden: die NÄCHSTMÖGLICHEN Plätze dicht anbieten —
        # Dringlichkeit schlägt Streuung (Chef 27.08.2026).
        auswahl = pool[:max_n]
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
