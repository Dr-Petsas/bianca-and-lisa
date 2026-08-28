"""Wunsch-Parser und Slot-Auswahl — portiert aus MAS lisa/callBooking.js (pure)."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from kern.sprech import slot_wort
from kern import zeiten

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

# Relative Tagesangaben — Zahlwörter für „in drei Tagen“ / „in zwei Wochen“.
_KLEINZAHL = {
    "ein": 1, "eine": 1, "einem": 1, "einen": 1, "eins": 1,
    "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "fuenf": 5,
    "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10,
    "elf": 11, "zwölf": 12, "zwoelf": 12,
}
_M_WORT = {
    "fünf": 5, "fuenf": 5, "zehn": 10, "fünfzehn": 15, "fuenfzehn": 15,
    "zwanzig": 20, "dreißig": 30, "dreissig": 30, "vierzig": 40,
    "fünfundvierzig": 45, "fuenfundvierzig": 45, "fünfzig": 50, "fuenfzig": 50,
}
_M_ZEHNER = {
    "zwanzig": 20, "dreißig": 30, "dreissig": 30, "vierzig": 40,
    "fünfzig": 50, "fuenfzig": 50,
}
_WT_NAME = {
    "montag": 1, "dienstag": 2, "mittwoch": 3, "donnerstag": 4,
    "freitag": 5, "samstag": 6, "sonntag": 0,
}


def _stunde_von(token: str) -> int | None:
    tok = token.strip().lower()
    if tok.isdigit():
        n = int(tok)
        return n if 0 <= n <= 23 else None
    return _STUNDEN_WORT.get(tok)


def _kleinzahl(token: str) -> int | None:
    tok = token.strip().lower()
    if tok.isdigit():
        n = int(tok)
        return n if 1 <= n <= 31 else None
    return _KLEINZAHL.get(tok)


def relatives_datum(text: str, *, heute: date | None = None) -> str:
    """ISO-Tag aus 'heute/morgen/übermorgen/in drei Tagen' — '' wenn keiner."""
    t = f" {_s(text).lower()} "
    ref = heute or datetime.now(TZ).date()
    if re.search(r"\bübermorgen|uebermorgen\b", t):
        return (ref + timedelta(days=2)).isoformat()
    if re.search(r"\bvorgestern\b", t):
        return (ref - timedelta(days=2)).isoformat()
    if re.search(r"\bmorgen\b", t):
        return (ref + timedelta(days=1)).isoformat()
    if re.search(r"\bgestern\b", t):
        return (ref - timedelta(days=1)).isoformat()
    if re.search(r"\bheute\b", t):
        return ref.isoformat()
    m = re.search(
        r"\bin\s+(\d{1,2}|" + "|".join(sorted(_KLEINZAHL, key=len, reverse=True))
        + r")\s+tagen?\b",
        t,
    )
    if m:
        n = _kleinzahl(m.group(1))
        if n:
            return (ref + timedelta(days=n)).isoformat()
    return ""


def _wochentag_datum(text: str, *, heute: date | None = None) -> str:
    """'diesen Freitag' / 'kommenden Montag' → ISO-Tag, sonst ''."""
    t = f" {_s(text).lower()} "
    m = re.search(
        r"\b(diese[nsm]?|kommende[nsm]?|nächste[nsm]?|naechste[nsm]?)\s+"
        r"(montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)\b",
        t,
    )
    if not m:
        return ""
    ref = heute or datetime.now(TZ).date()
    ziel = _WT_NAME[m.group(2)]
    py = (ziel - 1) % 7
    delta = (py - ref.weekday()) % 7
    diesen = m.group(1).startswith("diese")
    if delta == 0 and not diesen:
        delta = 7
    return (ref + timedelta(days=delta)).isoformat()


def parse_slot_wish(text: str, *, heute: date | None = None) -> dict[str, Any] | None:
    raw = _s(text)
    if not raw:
        return None
    t = f" {raw.lower()} "
    ref = heute or datetime.now(TZ).date()
    wish: dict[str, Any] = {
        "weekday": None, "hourMin": None, "hourMax": None,
        "hour": None, "minDaysAhead": 0, "date": None, "maxDate": None,
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
    _zahl_alt = "|".join(sorted(_KLEINZAHL, key=len, reverse=True))
    if re.search(r"uebernaechste|übernächste", t):
        wish["minDaysAhead"] = 14
    else:
        wochen = re.search(rf"\bin\s+(\d{{1,2}}|{_zahl_alt})\s+wochen?\b", t)
        if wochen:
            n = _kleinzahl(wochen.group(1))
            if n:
                wish["minDaysAhead"] = 7 * n
        elif re.search(r"n[äa]chste woche|kommende woche", t):
            wish["minDaysAhead"] = 7
        elif re.search(r"diese\s+woche|noch\s+diese\s+woche", t):
            # Bis einschließlich Sonntag dieser Kalenderwoche.
            wish["maxDate"] = (ref + timedelta(days=(6 - ref.weekday()))).isoformat()
    if re.search(r"\bwochenende\b", t):
        wish["weekday"] = 6
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
        year = int(dm.group(3) or ref.year)
        try:
            d = date(year, int(dm.group(2)), int(dm.group(1)))
        except ValueError:
            d = None
        if d is not None:
            if d < ref - timedelta(days=60):
                try:
                    d = date(year + 1, d.month, d.day)
                except ValueError:
                    pass
            wish["date"] = d.isoformat()
    if not wish.get("date"):
        fest = _wochentag_datum(t, heute=ref) or relatives_datum(t, heute=ref)
        if fest:
            wish["date"] = fest
    return wish


def spoken_slot(iso: str) -> str:
    """Sprechbar, nicht ablesbar: 'morgen um neun Uhr fünfzehn'."""
    return slot_wort(iso)


def naechster_montag(heute: datetime | None = None, *, wochen: int = 1) -> datetime:
    """Montag der nächsten (wochen=1) bzw. übernächsten Kalenderwoche."""
    tag = (heute or datetime.now(TZ)).astimezone(TZ).date()
    bis_montag = (7 - tag.weekday()) % 7
    if bis_montag == 0:
        bis_montag = 7
    ziel = tag + timedelta(days=bis_montag + 7 * max(0, wochen - 1))
    return datetime(ziel.year, ziel.month, ziel.day, tzinfo=TZ)


def wunsch_start(wish: dict | None, now: datetime | None = None) -> datetime | None:
    """Ab wann der Wunsch gilt. 'Nächste Woche' = nächster Montag, nicht heute+7.

    Live 28.08.2026 (Freitag): minDaysAhead=7 landete auf dem 4. September und
    ließ Montag–Donnerstag der echten nächsten Woche weg — 'am schnellsten'
    war damit eine Woche zu spät.
    """
    if not wish:
        return None
    if wish.get("date"):
        try:
            d = datetime.fromisoformat(str(wish["date"])).date()
        except ValueError:
            return None
        return datetime(d.year, d.month, d.day, tzinfo=TZ)
    tage = int(wish.get("minDaysAhead") or 0)
    if not tage:
        return None
    anker = now or datetime.now(TZ)
    if tage >= 14:
        return naechster_montag(anker, wochen=2)
    if tage >= 7:
        return naechster_montag(anker, wochen=1)
    return anker.astimezone(TZ).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=tage)


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
               exclude_iso: str = "", max_n: int = 3, dringend: bool = False,
               tenant: dict | None = None) -> dict[str, Any]:
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
    parsed = [p for p in parsed if zeiten.slot_frei(p["iso"], tenant)]
    parsed.sort(key=lambda p: p["ms"])

    def apply(pool: list) -> list:
        if not wish:
            return pool
        out = pool
        if wish.get("date"):
            out = [p for p in out if p["date"] == wish["date"]]
        if wish.get("weekday") is not None:
            out = [p for p in out if _weekday_of(p["date"]) == wish["weekday"]]
        if wish.get("minDaysAhead") or wish.get("date"):
            # 'Nächste Woche' = nächster Montag 00:00, nicht heute+7 Tage
            # (live 28.08.2026: Freitag+7 übersprang die echte nächste Woche).
            start = wunsch_start(wish, datetime.fromtimestamp(now / 1000, TZ))
            if start:
                out = [p for p in out if p["ms"] >= int(start.timestamp() * 1000)]
        if wish.get("maxDate"):
            out = [p for p in out if p["date"] <= str(wish["maxDate"])]
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


def _minuten_von(wort: str) -> int | None:
    """Minutenwort 1-59 — auch zusammengesetzt ('vierundvierzig')."""
    w = _s(wort).lower()
    if not w:
        return None
    if w in _M_WORT:
        return _M_WORT[w]
    if w in _STUNDEN_WORT and _STUNDEN_WORT[w] <= 20:
        return _STUNDEN_WORT[w]
    m = re.match(r"^([a-zäöüß]+)und([a-zäöüß]+)$", w)
    if m and m.group(1) in _STUNDEN_WORT and _STUNDEN_WORT[m.group(1)] <= 9 and m.group(2) in _M_ZEHNER:
        return _M_ZEHNER[m.group(2)] + _STUNDEN_WORT[m.group(1)]
    return None


def zeit_von(t: str) -> tuple[int | None, int | None]:
    """Gehörte Uhrzeit: '9 uhr 15', 'um 14:30', 'neun uhr fünfzehn', 'halb zehn'."""
    m = re.search(r"\b(\d{1,2})(?:[:.](\d{2}))?\s*uhr\b(?:\s+(\d{1,2})\b)?", t)
    if not m:
        m = re.search(r"\bum\s+(\d{1,2})(?:[:.](\d{2}))?\b", t)
    if m:
        minute = m.group(2) or (m.group(3) if m.lastindex and m.lastindex >= 3 else None)
        return int(m.group(1)), (int(minute) if minute else None)
    m = re.search(r"\bhalb\s+([a-zäöü]+|\d{1,2})\b", t)
    if m:
        w = m.group(1)
        h = int(w) if w.isdigit() else _STUNDEN_WORT.get(w)
        if h:
            return h - 1, 30
    m = re.search(r"\b([a-zäöü]+)\s+uhr(?:\s+([a-zäöüß]+))?\b", t)
    if m and m.group(1) in _STUNDEN_WORT:
        return _STUNDEN_WORT[m.group(1)], _minuten_von(m.group(2) or "")
    return None, None


_ORDINAL_SLOT = (
    (re.compile(r"\b(erste[rns]?|ersteren|nummer\s+(eins|1)|angebot\s+(eins|1))\b"), 0),
    (re.compile(r"\b(zweite[rns]?|nummer\s+(zwei|2)|angebot\s+(zwei|2))\b"), 1),
    (re.compile(r"\b(dritte[rns]?|nummer\s+(drei|3)|angebot\s+(drei|3))\b"), 2),
    (re.compile(r"\b(vierte[rns]?|nummer\s+(vier|4)|angebot\s+(vier|4))\b"), 3),
)
_DIESER_RE = re.compile(
    r"\b(diese[rsnm]?|den\s+da|der\s+da|das\s+da|genau\s+de[rn]s?|"
    r"den\s+hier|der\s+hier|genau\s+diese[rsnm]?)\b",
)
_DIESER_ZEIT_RE = re.compile(
    r"\b(woche|wochenende|montag|dienstag|mittwoch|donnerstag|freitag|"
    r"samstag|sonntag|monat|jahr)\b",
)


def slot_wahl(text: str, offered: list[dict], *, heute: date | None = None) -> str:
    """Welchen der angebotenen Termine meint der Satz? '' wenn unklar.

    Versteht Uhrzeit, Wochentag, TT.MM., heute/morgen/übermorgen/in N Tagen,
    vormittags/nachmittags, erste/zweite/dritte/letzte, und 'dieser'/'den da'
    als den zuletzt genannten (letzten) Vorschlag.
    """
    if not offered:
        return ""
    t = f" {_s(text).lower()} "
    ref = heute or datetime.now(TZ).date()

    hour, minute = zeit_von(t)
    if hour is not None:
        c = [o for o in offered
             if int(o["iso"][11:13]) == hour and (minute is None or int(o["iso"][14:16]) == minute)]
        if not c:
            c = [o for o in offered
                 if int(o["iso"][11:13]) % 12 == hour % 12 and (minute is None or int(o["iso"][14:16]) == minute)]
        if len(c) == 1:
            return c[0]["iso"]
        if minute is not None and not c:
            ziel = hour * 60 + minute

            def _abstand(o: dict) -> int:
                slot = int(o["iso"][11:13]) * 60 + int(o["iso"][14:16])
                slot12 = (int(o["iso"][11:13]) % 12) * 60 + int(o["iso"][14:16])
                return min(abs(slot - ziel), abs(slot12 - (hour % 12) * 60 - minute))

            nah = sorted(offered, key=_abstand)
            if _abstand(nah[0]) <= 20 and (len(nah) == 1 or _abstand(nah[1]) > _abstand(nah[0])):
                return nah[0]["iso"]

    for idx, cre in WEEKDAYS:
        if cre.search(t):
            c = [o for o in offered if _weekday_of(o["iso"][:10]) == idx]
            if len(c) == 1:
                return c[0]["iso"]

    dm = re.search(r"\b(\d{1,2})\.\s?(\d{1,2})\.", t)
    if dm:
        jahr = offered[0]["iso"][:4]
        datum = f"{jahr}-{int(dm.group(2)):02d}-{int(dm.group(1)):02d}"
        c = [o for o in offered if o["iso"].startswith(datum)]
        if len(c) == 1:
            return c[0]["iso"]

    rel = relatives_datum(t, heute=ref)
    if rel:
        c = [o for o in offered if o["iso"].startswith(rel)]
        if len(c) == 1:
            return c[0]["iso"]

    if re.search(r"n[äa]chste woche|kommende woche", t):
        start = naechster_montag(datetime(ref.year, ref.month, ref.day, tzinfo=TZ)).date().isoformat()
        c = [o for o in offered if o["iso"][:10] >= start]
        # Nur wählen, wenn die Woche die Liste wirklich teilt — sonst ist
        # „nächste Woche?“ ein neuer Wunsch, kein Griff nach dem einzigen Slot.
        if len(c) == 1 and len(c) < len(offered):
            return c[0]["iso"]
    if re.search(r"diese\s+woche|noch\s+diese\s+woche", t):
        ende = (ref + timedelta(days=(6 - ref.weekday()))).isoformat()
        c = [o for o in offered if o["iso"][:10] <= ende]
        if len(c) == 1 and len(c) < len(offered):
            return c[0]["iso"]

    if "vormittag" in t or "nachmittag" in t:
        früh = "vormittag" in t
        c = [o for o in offered
             if (int(o["iso"][11:13]) < 12) == früh]
        if len(c) == 1:
            return c[0]["iso"]

    if re.search(r"\b(letzte[rns]?)\b", t):
        return offered[-1]["iso"]
    for cre, idx in _ORDINAL_SLOT:
        if cre.search(t) and len(offered) > idx:
            return offered[idx]["iso"]

    if _DIESER_RE.search(t) and not _DIESER_ZEIT_RE.search(t):
        return offered[-1]["iso"]

    return ""
