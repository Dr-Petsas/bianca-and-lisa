"""Wunsch-Parser und Slot-Auswahl — portiert aus MAS lisa/callBooking.js (pure)."""

from __future__ import annotations

import re
from datetime import datetime, timezone
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
    if re.search(r"vormittag|frueh|früh|morgens", t):
        wish["hourMin"], wish["hourMax"] = 7, 12
    elif "nachmittag" in t:
        wish["hourMin"], wish["hourMax"] = 12, 18
    elif re.search(r"abend|spaet|spät", t):
        wish["hourMin"], wish["hourMax"] = 16, 21
    if re.search(r"n[äa]chste woche|kommende woche", t):
        wish["minDaysAhead"] = 7
    elif re.search(r"uebernaechste|übernächste", t):
        wish["minDaysAhead"] = 14
    hm = re.search(r"\b(?:um|gegen)\s+(\d{1,2})(?::(\d{2}))?\s*uhr", t)
    if hm:
        wish["hour"] = min(23, int(hm.group(1)))
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


def pick_slots(iso_slots: list[str], *, wish: dict | None = None, now_ms: int | None = None,
               exclude_iso: str = "", max_n: int = 3) -> dict[str, Any]:
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

    def apply(pool: list) -> list:
        if not wish:
            return pool
        out = pool
        if wish.get("date"):
            out = [p for p in out if p["date"] == wish["date"]]
        if wish.get("weekday") is not None:
            out = [p for p in out if _weekday_of(p["date"]) == wish["weekday"]]
        if wish.get("minDaysAhead"):
            out = [p for p in out if p["ms"] >= now + wish["minDaysAhead"] * 86400000]
        if wish.get("hour") is not None:
            out = [p for p in out if abs(p["hour"] - wish["hour"]) <= 1]
        elif wish.get("hourMin") is not None:
            out = [p for p in out if wish["hourMin"] <= p["hour"] < wish["hourMax"]]
        return out

    pool = apply(parsed)
    matched = not wish or bool(pool)
    if not pool:
        pool = parsed
    by_day, seen = [], set()
    for p in pool:
        if p["date"] in seen:
            continue
        seen.add(p["date"])
        by_day.append(p)
        if len(by_day) >= max_n:
            break
    for p in pool:
        if len(by_day) >= max_n:
            break
        if p not in by_day:
            by_day.append(p)
    by_day.sort(key=lambda p: p["ms"])
    slots = [{"iso": p["iso"], "date": p["date"], "time": p["time"]} for p in by_day]
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
