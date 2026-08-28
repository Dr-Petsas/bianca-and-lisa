"""Sperrzeiten: Feiertage (NRW), Wochenende, Praxiszeiten — nie buchen.

Eine Quelle für Bianca und Lisa. Portiert aus MAS holidays.js (NRW, Düsseldorf),
ohne Import aus Clara/MAS. Chef 28.08.2026: Feiertage, Wochenenden und
außerhalb der Praxiszeiten dürfen keine Termine bekommen.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Berlin")

_WOCHENTAG = (
    "Montag", "Dienstag", "Mittwoch", "Donnerstag",
    "Freitag", "Samstag", "Sonntag",
)
_TAG_KEY = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

# Fallback, wenn der Mandant keine officeHours trägt (Zahnärzte im Medical Center).
DEFAULT_STUNDEN: dict[str, list[list[str]]] = {
    "mon": [["08:00", "18:00"]],
    "tue": [["08:00", "18:00"]],
    "wed": [["08:00", "18:00"]],
    "thu": [["08:00", "18:00"]],
    "fri": [["08:00", "16:00"]],
    "sat": [],
    "sun": [],
}

_OFFEN_RE = re.compile(
    r"oeffnungszeit|öffnungszeit|wann\s+(?:habt|haben)\s+(?:ihr|sie)\s+auf|"
    r"(?:seid|habt|haben)\s+(?:ihr|sie)\s+(?:auch\s+)?(?:am\s+)?"
    r"(samstag|sonntag|wochenende|feiertag)|"
    r"(samstag|sonntag|wochenende|feiertag).{0,28}"
    r"(?:auf|offen|geöffnet|geoeffnet|termin|sprech|da\b|geschlossen)",
    re.I,
)
_ABWESEN_RE = re.compile(
    r"\b(?:urlaub|abwesend|abwesenheit|fortbildung|nicht\s+da|"
    r"wann\s+(?:ist|kommt)\s+(?:er|sie|der\s+doktor).{0,20}wieder|"
    r"ist\s+(?:er|sie|doktor|dr\.?).{0,24}(?:da|anwesend|im\s+haus))\b",
    re.I,
)


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def ostersonntag(jahr: int) -> date:
    """Gregorianisch, Gauß/Anonymous — wie MAS holidays.js."""
    a = jahr % 19
    b = jahr // 100
    c = jahr % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    monat = (h + l - 7 * m + 114) // 31
    tag = ((h + l - 7 * m + 114) % 31) + 1
    return date(jahr, monat, tag)


_FEIER_CACHE: dict[int, dict[str, str]] = {}


def feiertage_nrw(jahr: int) -> dict[str, str]:
    hit = _FEIER_CACHE.get(jahr)
    if hit is not None:
        return hit
    ostern = ostersonntag(jahr)
    mp = {
        f"{jahr}-01-01": "Neujahr",
        (ostern - timedelta(days=2)).isoformat(): "Karfreitag",
        (ostern + timedelta(days=1)).isoformat(): "Ostermontag",
        f"{jahr}-05-01": "Tag der Arbeit",
        (ostern + timedelta(days=39)).isoformat(): "Christi Himmelfahrt",
        (ostern + timedelta(days=50)).isoformat(): "Pfingstmontag",
        (ostern + timedelta(days=60)).isoformat(): "Fronleichnam",
        f"{jahr}-10-03": "Tag der Deutschen Einheit",
        f"{jahr}-11-01": "Allerheiligen",
        f"{jahr}-12-25": "Erster Weihnachtstag",
        f"{jahr}-12-26": "Zweiter Weihnachtstag",
    }
    _FEIER_CACHE[jahr] = mp
    return mp


def feiertag_name(tag: date | str) -> str:
    iso = tag.isoformat() if isinstance(tag, date) else _s(tag)[:10]
    if len(iso) < 10:
        return ""
    try:
        jahr = int(iso[:4])
    except ValueError:
        return ""
    return feiertage_nrw(jahr).get(iso, "")


def ist_wochenende(tag: date | str) -> bool:
    d = _als_datum(tag)
    return bool(d and d.weekday() >= 5)


def _als_datum(tag: date | str | None) -> date | None:
    if isinstance(tag, date) and not isinstance(tag, datetime):
        return tag
    raw = _s(tag)[:10]
    if len(raw) < 10:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _dt(iso: str) -> datetime | None:
    raw = _s(iso).replace(" ", "T").replace("Z", "+00:00")
    if len(raw) < 16 or raw[10] != "T":
        return None
    if len(raw) == 16:
        raw += ":00"
    try:
        d = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=TZ)
    return d.astimezone(TZ)


def _minuten(hhmm: str) -> int | None:
    m = re.match(r"^(\d{1,2}):(\d{2})$", _s(hhmm))
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if 0 <= h <= 23 and 0 <= mi <= 59:
        return h * 60 + mi
    return None


def _praxis_stunden(tenant: dict | None) -> dict[str, list[list[str]]]:
    t = tenant if isinstance(tenant, dict) else {}
    raw = t.get("officeHours") or t.get("office_hours")
    if isinstance(raw, dict) and raw:
        return raw
    return DEFAULT_STUNDEN


def _extra_zu(tenant: dict | None, tag: date) -> str:
    t = tenant if isinstance(tenant, dict) else {}
    for x in t.get("closedDates") or t.get("closed_dates") or []:
        if isinstance(x, str) and x[:10] == tag.isoformat():
            return "geschlossen"
        if isinstance(x, dict) and _s(x.get("date"))[:10] == tag.isoformat():
            return _s(x.get("name")) or "geschlossen"
    return ""


def tag_grund(tag: date | str, tenant: dict | None = None) -> str:
    """Warum der Kalendertag zu ist — '' wenn ein normaler Werktag."""
    d = _als_datum(tag)
    if not d:
        return ""
    extra = _extra_zu(tenant, d)
    if extra:
        return extra
    feier = feiertag_name(d)
    if feier:
        return f"{feier}, ein Feiertag"
    if d.weekday() >= 5:
        return _WOCHENTAG[d.weekday()]
    fenster = _praxis_stunden(tenant).get(_TAG_KEY[d.weekday()]) or []
    if not fenster:
        return _WOCHENTAG[d.weekday()]
    return ""


def naechster_werktag(tag: date | str, tenant: dict | None = None,
                      *, inklusiv: bool = False) -> date:
    d = _als_datum(tag) or datetime.now(TZ).date()
    if not inklusiv:
        d = d + timedelta(days=1)
    for _ in range(21):
        if not tag_grund(d, tenant):
            return d
        d += timedelta(days=1)
    return d


def im_sprechfenster(iso: str, tenant: dict | None = None) -> bool:
    dt = _dt(iso)
    if not dt:
        return False
    if tag_grund(dt.date(), tenant):
        return False
    fenster = _praxis_stunden(tenant).get(_TAG_KEY[dt.weekday()]) or []
    jetzt = dt.hour * 60 + dt.minute
    for paar in fenster:
        if not isinstance(paar, (list, tuple)) or len(paar) < 2:
            continue
        a, b = _minuten(paar[0]), _minuten(paar[1])
        if a is None or b is None:
            continue
        if a <= jetzt < b:
            return True
    return False


def slot_frei(iso: str, tenant: dict | None = None) -> bool:
    return im_sprechfenster(iso, tenant)


def buch_verbot(iso: str, tenant: dict | None = None) -> str:
    """Sprechbarer Grund, warum dieser Slot nicht gebucht werden darf — '' wenn frei."""
    dt = _dt(iso)
    if not dt:
        return ""
    grund = tag_grund(dt.date(), tenant)
    if grund:
        if "Feiertag" in grund:
            return (
                f"{grund} — da haben wir geschlossen. "
                "Ich schaue auf den nächsten Werktag."
            )
        if grund in {"Samstag", "Sonntag"}:
            return (
                f"{grund}s haben wir geschlossen. "
                "Ich schaue auf den nächsten Werktag."
            )
        return (
            f"An dem Tag haben wir geschlossen ({grund}). "
            "Ich schaue auf den nächsten Werktag."
        )
    if not im_sprechfenster(iso, tenant):
        return (
            "Außerhalb der Sprechzeiten vergeben wir keine Termine. "
            "Montag bis Donnerstag bis achtzehn Uhr, Freitag bis sechzehn Uhr."
        )
    return ""


def wunsch_richten(wish: dict | None, tenant: dict | None = None,
                   *, heute: date | None = None) -> tuple[dict, str]:
    """Geschlossenen Wunsch auf den nächsten Werktag schieben + Vorrede."""
    w = dict(wish or {})
    ref = heute or datetime.now(TZ).date()
    vor = ""
    tag = _als_datum(w.get("date"))
    wd = w.get("weekday")
    if tag:
        grund = tag_grund(tag, tenant)
        if grund:
            neu = naechster_werktag(tag, tenant, inklusiv=False)
            w["date"] = neu.isoformat()
            w["weekday"] = None
            vor = buch_verbot(f"{tag.isoformat()}T10:00", tenant)
    elif wd in (0, 6):  # parse_slot_wish: 0=So, 6=Sa
        name = "Sonntag" if wd == 0 else "Samstag"
        neu = naechster_werktag(ref, tenant, inklusiv=False)
        w["weekday"] = None
        w["date"] = neu.isoformat()
        vor = f"{name}s haben wir geschlossen. Ich schaue auf den nächsten Werktag."
    stunde = w.get("hour")
    if stunde is not None:
        probe = tag or (date.fromisoformat(w["date"]) if w.get("date") else ref)
        iso = f"{probe.isoformat()}T{int(stunde):02d}:00"
        if not im_sprechfenster(iso, tenant) and not tag_grund(probe, tenant):
            w["hour"] = None
            vor = (vor + " " if vor else "") + (
                "Zu der Uhrzeit haben wir geschlossen. "
                "Montag bis Donnerstag bis achtzehn Uhr, Freitag bis sechzehn Uhr."
            )
    return w, vor.strip()


def ist_offen_frage(text: str) -> bool:
    return bool(_OFFEN_RE.search(text or ""))


def offen_antwort(text: str, tenant: dict | None = None, *, heute: date | None = None) -> str:
    t = tenant if isinstance(tenant, dict) else {}
    wissen = t.get("wissen") if isinstance(t.get("wissen"), dict) else {}
    kern = _s(wissen.get("oeffnung")) or (
        "Montag bis Donnerstag von acht bis achtzehn Uhr, "
        "Freitag von acht bis sechzehn Uhr. Samstag und Sonntag geschlossen."
    )
    raw = _s(text).lower()
    ref = heute or datetime.now(TZ).date()
    if "samstag" in raw:
        return "Samstags haben wir geschlossen. " + kern
    if "sonntag" in raw:
        return "Sonntags haben wir geschlossen. " + kern
    if "wochenende" in raw:
        return "Am Wochenende haben wir geschlossen. " + kern
    dm = re.search(r"\b(\d{1,2})\.\s?(\d{1,2})\.(?:\s?(\d{4}))?", raw)
    if dm:
        jahr = int(dm.group(3) or ref.year)
        try:
            d = date(jahr, int(dm.group(2)), int(dm.group(1)))
        except ValueError:
            d = None
        if d:
            grund = tag_grund(d, tenant)
            if grund:
                return (
                    f"Am {_WOCHENTAG[d.weekday()]}, den {d.day}. {d.month}., "
                    f"haben wir geschlossen — {grund}. " + kern
                )
    if "feiertag" in raw:
        return "An gesetzlichen Feiertagen haben wir geschlossen. " + kern
    return kern


def ist_abwesen_frage(text: str) -> bool:
    return bool(_ABWESEN_RE.search(text or ""))
