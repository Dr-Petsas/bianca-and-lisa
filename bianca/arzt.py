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

    # Korrektur-Sätze ("nein, nicht Doktor Patrikis — ich wollte zu Doktor
    # Petsas", Chef 27.08.2026): der VERNEINTE Name fliegt vor dem Abgleich
    # raus, sonst gewinnt er den Gleichstand und Bianca wechselt nicht.
    nachnamen = [n for n in (_nachname(c.get("name")) for c in tenant.get("calendars") or []) if n]
    if nachnamen:
        t = re.sub(
            r"\bnicht\s+(?:zu[mr]?\s+|bei\s+)?(?:dr\.?\s*|doktor\s+|prof\.?\s*|professor\s+|herrn?\s+|frau\s+)?(?:"
            + "|".join(re.escape(n) for n in nachnamen) + r")\b",
            " ", t,
        )

    # Ein konkreter Name schlägt "egal"-Floskeln im selben Satz.
    tokens = [w for w in re.sub(r"[^\wäöüß]+", " ", t).split() if w not in _STOP and len(w) >= 3]
    kandidaten: list[tuple[dict, float, float, int]] = []  # (cal, roh, score, position)
    for cal in tenant.get("calendars") or []:
        ziel = _nachname(cal.get("name"))
        if not ziel:
            continue
        roh_b, score_b, pos_b = 0.0, 0.0, -1
        for pos, tok in enumerate(tokens):
            roh = SequenceMatcher(None, tok, ziel).ratio()
            # Klang-Faltung: "Petzers" ~ "Petsas" liegt roh bei 0,62 — nach
            # Faltung darüber. Gleicher Wortanfang gibt einen Namens-Bonus.
            r = max(roh, SequenceMatcher(None, _klang(tok), _klang(ziel)).ratio())
            if len(tok) >= 4 and tok[:3] == ziel[:3]:
                r += 0.1
            if r > score_b:
                roh_b, score_b, pos_b = roh, r, pos
        if score_b > 0:
            kandidaten.append((cal, roh_b, score_b, pos_b))
    # Sicherer Treffer: roh eindeutig. Toleranter Treffer (Klang/Anfang) nur,
    # wenn der Satz erkennbar von einem Arzt spricht — sonst würde ein
    # Patienten-Vorname wie "Peter" auf "Petsas" springen.
    tragfaehig = [k for k in kandidaten if k[1] >= 0.72 or (k[2] >= 0.72 and doktor_kontext)]
    if tragfaehig:
        korrektur = bool(re.search(r"\bnicht\b|\bsondern\b|\bstatt\b|\blieber\b|vertan|meinte|falsch|verwechselt", t))
        if korrektur and len(tragfaehig) > 1:
            # Korrektur-Satz mit zwei Namen: das Gemeinte steht HINTEN
            # ("nicht Petzers, lieber Patrikis" — Chef 27.08.2026).
            best = max(tragfaehig, key=lambda k: (k[3], k[2]))[0]
        else:
            best = max(tragfaehig, key=lambda k: k[2])[0]
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
    vergangen = data.get("lastAppointment") or {}
    return {
        "ok": True,
        "calendarId": _s(termin.get("calendarId")) or _s((cal or {}).get("id")),
        "calendarName": _s((cal or {}).get("name")) or _s(termin.get("calendarName")),
        "doctorName": _s(termin.get("doctorName")),
        "lastIso": _s(termin.get("startIso")),
        "war": bool(data.get("lastAppointment")),
        # Besuchsgrund des VERGANGENEN Termins (Rueckblick-Ansprache, Chef
        # 30.08.2026) — bewusst nie vom Zukunfts-Termin.
        "grund": _s(vergangen.get("visitMotiveName")),
    }
