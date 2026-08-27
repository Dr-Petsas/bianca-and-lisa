"""Behandler-Auflösung für eingehende Anrufe.

Drei Chef-Fälle (27.08.2026):
  "Ich war bei Doktor Patrikis"  -> nur in DESSEN Kalender suchen (genannt)
  "Weiß ich nicht mehr"          -> Patient in der Kartei auflösen, letzten
                                    Behandler nachschlagen (masPatientLastDoctor)
  "Ist mir egal"                 -> global frühester Slot über alle Kalender
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

import httpx

from kern.config import CF_BASE
from kern.tenants import kalender_von

_EGAL_RE = re.compile(
    r"\b(egal|gleich|wurst|hauptsache|keine\s+(präferenz|praeferenz|vorliebe)|"
    r"wer\s+(gerade\s+)?(zeit|frei)|der\s+(erste|nächste|naechste)\s*(freie)?|"
    r"schnellstmöglich|schnellstmoeglich|wer\s+zuerst|spielt\s+keine\s+rolle)\b",
    re.I,
)
_UNBEKANNT_RE = re.compile(
    r"(weiß\s+(ich\s+)?nicht|weiss\s+(ich\s+)?nicht|keine\s+ahnung|"
    r"nicht\s+mehr\s*(genau)?\s*(sagen|wissen)?|vergessen|"
    r"müsste\s+ich\s+nachschauen|muesste\s+ich\s+nachschauen|"
    r"kann\s+ich\s+nicht\s+sagen)",
    re.I,
)
_STOP = {
    "dr", "doktor", "frau", "herr", "herrn", "bei", "beim", "war", "ich",
    "glaube", "dem", "der", "die", "das", "arzt", "ärztin", "aerztin",
    "zahnarzt", "praxis", "einem", "einer", "mal", "schon", "damals",
    "letztes", "letzten", "jahr", "und", "zwar",
}


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _nachname(cal_name: str) -> str:
    toks = [t for t in _s(cal_name).lower().replace(".", " ").split() if t not in {"dr", "med", "prof"}]
    return toks[-1] if toks else ""


def _klang(wort: str) -> str:
    """Grobe deutsche Klang-Faltung für Nachnamen: STT-Hörfehler wie
    "Petzers"/"Petsas" oder "Patrikis"/"Patrickis" sollen zusammenfallen."""
    w = wort.lower()
    for a, b in (
        ("sch", "s"), ("tz", "z"), ("ts", "z"), ("ck", "k"), ("dt", "t"),
        ("th", "t"), ("ph", "f"), ("ie", "i"), ("ei", "ai"), ("ä", "e"),
        ("ö", "o"), ("ü", "u"), ("ß", "s"), ("y", "i"), ("v", "f"),
    ):
        w = w.replace(a, b)
    # Doppelbuchstaben eindampfen
    out = []
    for c in w:
        if not out or out[-1] != c:
            out.append(c)
    return "".join(out)


_DOKTOR_RE = re.compile(r"\b(dr\.?|doktor|arzt|ärztin|aerztin|behandler(?:in)?|prof\.?|professor)\b", re.I)


def deute(text: str, tenant: dict) -> dict[str, Any] | None:
    """Was sagt der Satz über den Wunsch-Behandler? None = nichts erkennbar."""
    raw = _s(text)
    if not raw:
        return None
    t = raw.lower()
    doktor_kontext = bool(_DOKTOR_RE.search(t))
    # Ein konkreter Name schlägt "egal"-Floskeln im selben Satz.
    tokens = [w for w in re.sub(r"[^\wäöüß]+", " ", t).split() if w not in _STOP and len(w) >= 3]
    best, roh_best, score = None, 0.0, 0.0
    for cal in tenant.get("calendars") or []:
        ziel = _nachname(cal.get("name"))
        if not ziel:
            continue
        for tok in tokens:
            roh = SequenceMatcher(None, tok, ziel).ratio()
            # Klang-Faltung: "Petzers" ~ "Petsas" liegt roh bei 0,62 — nach
            # Faltung darüber. Gleicher Wortanfang gibt einen Namens-Bonus.
            r = max(roh, SequenceMatcher(None, _klang(tok), _klang(ziel)).ratio())
            if len(tok) >= 4 and tok[:3] == ziel[:3]:
                r += 0.1
            if r > score:
                best, roh_best, score = cal, roh, r
    # Sicherer Treffer: roh eindeutig. Toleranter Treffer (Klang/Anfang) nur,
    # wenn der Satz erkennbar von einem Arzt spricht — sonst würde ein
    # Patienten-Vorname wie "Peter" auf "Petsas" springen.
    if best and (roh_best >= 0.72 or (score >= 0.72 and doktor_kontext)):
        return {"typ": "genannt", "calendarId": _s(best.get("id")), "calendarName": _s(best.get("name"))}
    if _UNBEKANNT_RE.search(t):
        return {"typ": "unbekannt"}
    if _EGAL_RE.search(t):
        return {"typ": "egal"}
    return None


def letzter_behandler(tenant: dict, patient_id: str) -> dict[str, Any]:
    """Letzten (oder nächsten) Termin des Patienten holen -> Kalender + Arzt."""
    pid = _s(patient_id)
    if not pid:
        return {"ok": False}
    body = {
        "clientId": _s(tenant.get("clientId")),
        "locationId": _s(tenant.get("locationId")),
        "patientId": pid,
    }
    try:
        r = httpx.post(f"{CF_BASE}/masPatientLastDoctor", json=body, timeout=8.0)
        data = r.json() if r.status_code == 200 else {}
    except (httpx.HTTPError, ValueError):
        return {"ok": False}
    if not isinstance(data, dict) or data.get("status") != "success":
        return {"ok": False}
    termin = data.get("lastAppointment") or data.get("nextAppointment") or {}
    if not termin:
        return {"ok": False, "leer": True}
    cal = kalender_von(tenant, _s(termin.get("calendarName")) or _s(termin.get("doctorName")))
    return {
        "ok": True,
        "calendarId": _s(termin.get("calendarId")) or _s((cal or {}).get("id")),
        "calendarName": _s((cal or {}).get("name")) or _s(termin.get("calendarName")),
        "doctorName": _s(termin.get("doctorName")),
        "lastIso": _s(termin.get("startIso")),
        "war": bool(data.get("lastAppointment")),
    }
