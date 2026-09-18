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
from kern.tenants import ist_funktionskalender, kalender_von

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


# Titel/Grade sind kein Namensteil. Live-Befund 14.09.2026 01:00: der
# MedDent-DB-Kalender heisst "Doktor Theodosios Patrikis, M.Sc." — der alte
# Splitter nahm das LETZTE Token ("sc") als Nachnamen, "zu Doktor Patrikis"
# traf also NIE (deute -> None, Wunsch fiel still auf den Default-Kalender).
# Grade hinter dem Komma fallen komplett weg (wie in patients.arzt_sprechname).
_GRAD_TOKS = {
    "dr", "med", "dent", "prof", "doktor", "professor", "univ", "habil",
    "m", "sc", "msc", "ma", "mba", "phd", "dds", "dmd", "bsc", "ba", "mag", "dipl",
    "frau", "herr", "herrn",
}


def _namens_tokens(cal_name: str) -> list[str]:
    kern = _s(cal_name).split(",")[0]
    return [t for t in kern.lower().replace(".", " ").split() if t not in _GRAD_TOKS]


def _nachname(cal_name: str) -> str:
    toks = _namens_tokens(cal_name)
    return toks[-1] if toks else ""


def _vornamen(cal_name: str) -> list[str]:
    toks = _namens_tokens(cal_name)
    return toks[:-1] if len(toks) >= 2 else []


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


_DOKTOR_RE = re.compile(
    r"\b(dr\.?|doktor|arzt|ärztin|aerztin|behandler(?:in)?|prof\.?|professor|"
    r"frau|herrn?)\b",
    re.I,
)
# Live Thaler 08.09.2026: STT „Eva Kahler“ / „Frau Parler“ für Thaler —
# Klang-Score reicht, aber ohne Doktor-Wort galt der Treffer nicht.
_STT_NACHNAME = {
    "kahler": "thaler",
    "kaler": "thaler",
    "parler": "thaler",
    "tahler": "thaler",
    "taler": "thaler",
}


def deute(text: str, tenant: dict) -> dict[str, Any] | None:
    """Was sagt der Satz über den Wunsch-Behandler? None = nichts erkennbar."""
    raw = _s(text)
    if not raw:
        return None
    t = raw.lower()
    doktor_kontext = bool(_DOKTOR_RE.search(t))

    # W-BEHANDLER-SPERRE (Chef 13.09.2026): telefonisch gesperrte Behandler
    # (Nikolaou) stehen nicht mehr in calendars — aber ihr Name muss weiter
    # ERKANNT werden, sonst faellt "zu Doktor Nikolaou" still auf den
    # Default-Kalender (Live-Probe 13.09.: Ansage Nikolaou, Buchung Petsas).
    # Sie laufen als Kandidaten mit und liefern typ="gesperrt".
    from kern import behandler_sperre
    pool: list[tuple[dict, bool]] = [
        (c, False) for c in tenant.get("calendars") or [] if isinstance(c, dict)
    ] + [(c, True) for c in behandler_sperre.gesperrte_kalender(tenant)]

    # Korrektur-Sätze ("nein, nicht Doktor Patrikis — ich wollte zu Doktor
    # Petsas", Chef 27.08.2026): der VERNEINTE Name fliegt vor dem Abgleich
    # raus, sonst gewinnt er den Gleichstand und Bianca wechselt nicht.
    nachnamen = [
        n for n in (
            _nachname(c.get("name"))
            for c, _g in pool
            if not ist_funktionskalender(c)
        ) if n
    ]
    if nachnamen:
        t = re.sub(
            r"\bnicht\s+(?:zu[mr]?\s+|bei\s+)?(?:dr\.?\s*|doktor\s+|prof\.?\s*|professor\s+|herrn?\s+|frau\s+)?(?:"
            + "|".join(re.escape(n) for n in nachnamen) + r")\b",
            " ", t,
        )

    # Ein konkreter Name schlägt "egal"-Floskeln im selben Satz.
    tokens = [w for w in re.sub(r"[^\wäöüß]+", " ", t).split() if w not in _STOP and len(w) >= 3]
    kandidaten: list[tuple[dict, float, float, int, bool, bool]] = []  # (cal, roh, score, position, mit_vorname, gesperrt)
    for cal, gesperrt in pool:
        if ist_funktionskalender(cal):
            continue
        ziel = _nachname(cal.get("name"))
        if not ziel:
            continue
        roh_b, score_b, pos_b = 0.0, 0.0, -1
        mit_vorname = bool(set(_vornamen(cal.get("name"))) & set(tokens))
        for pos, tok in enumerate(tokens):
            roh = SequenceMatcher(None, tok, ziel).ratio()
            # Klang-Faltung: "Petzers" ~ "Petsas" liegt roh bei 0,62 — nach
            # Faltung darüber. Gleicher Wortanfang gibt einen Namens-Bonus.
            r = max(roh, SequenceMatcher(None, _klang(tok), _klang(ziel)).ratio())
            alias = _STT_NACHNAME.get(tok) or _STT_NACHNAME.get(_klang(tok))
            if alias and (alias == ziel or _klang(alias) == _klang(ziel)):
                roh, r = 1.0, 1.0
            if len(tok) >= 4 and tok[:3] == ziel[:3]:
                r += 0.1
            if r > score_b:
                roh_b, score_b, pos_b = roh, r, pos
        if score_b > 0:
            # Vorname + ähnlicher Nachname zählt wie Doktor-Kontext
            # („Eva Kahler“ ohne Frau/Doktor).
            kandidaten.append((cal, roh_b, score_b, pos_b, mit_vorname, gesperrt))
    # Sicherer Treffer: roh eindeutig. Toleranter Treffer (Klang/Anfang) nur,
    # wenn der Satz erkennbar von einem Arzt spricht — sonst würde ein
    # Patienten-Vorname wie "Peter" auf "Petsas" springen.
    tragfaehig = [
        k for k in kandidaten
        if k[1] >= 0.72 or (k[2] >= 0.72 and (doktor_kontext or k[4]))
    ]
    if tragfaehig:
        korrektur = bool(re.search(r"\bnicht\b|\bsondern\b|\bstatt\b|\blieber\b|vertan|meinte|falsch|verwechselt", t))
        if korrektur and len(tragfaehig) > 1:
            # Korrektur-Satz mit zwei Namen: das Gemeinte steht HINTEN
            # ("nicht Petzers, lieber Patrikis" — Chef 27.08.2026).
            sieger = max(tragfaehig, key=lambda k: (k[3], k[2]))
        else:
            sieger = max(tragfaehig, key=lambda k: k[2])
        best = sieger[0]
        if sieger[5]:
            # Gesperrter Behandler genannt: KEIN Kalender — der Aufrufer
            # (gehirn.einsammeln) sagt es ehrlich und bietet die freien an.
            return {"typ": "gesperrt", "calendarId": "",
                    "calendarName": _s(best.get("name")), "name": _s(best.get("name"))}
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
    vergangen = data.get("lastAppointment") or {}
    # W-BEHANDLER-SPERRE: lag der letzte Termin bei einem telefonisch
    # gesperrten Behandler, darf weder sein Kalender (die CF liefert dessen
    # calendarId mit!) noch per kalender_von der DEFAULT-Kalender herauskommen
    # — Bianca sagte sonst "Sie waren zuletzt bei Doktor Petsas" und buchte
    # still in den internen Nikolaou-Kalender. Historie (Besuch/Grund) bleibt.
    from kern import behandler_sperre
    name_roh = _s(termin.get("calendarName")) or _s(termin.get("doctorName"))
    termin_cid = _s(termin.get("calendarId"))
    gesperrt_kal = next(
        (g for g in behandler_sperre.gesperrte_kalender(tenant)
         if (termin_cid and termin_cid == _s(g.get("id")))
         or (name_roh and behandler_sperre.ist_gesperrt(tenant, name_roh))),
        None,
    )
    if gesperrt_kal:
        return {
            "ok": True,
            "gesperrt": True,
            "calendarId": "",
            "calendarName": _s(gesperrt_kal.get("name")) or name_roh,
            "doctorName": _s(termin.get("doctorName")) or _s(gesperrt_kal.get("name")),
            "lastIso": _s(termin.get("startIso")),
            "war": bool(data.get("lastAppointment")),
            "lastAppointment": data.get("lastAppointment") or {},
            "nextAppointment": data.get("nextAppointment") or {},
            "grund": _s(vergangen.get("visitMotiveName")),
        }
    # W-KALENDER-TOT (17.09.2026): die CF liefert die calendarId des ALTEN
    # Termins — bei Blessing zeigte sie auf einen geloeschten Kalender
    # (TphQRh53…), und jede Slotsuche damit lief auf 500 „Could not load
    # doctor" (61 Fehler in 10 Anrufen, immer „Terminkalender antwortet
    # nicht" + Rueckruf-Notiz). Eine Kalender-Id zaehlt nur, wenn der Mandant
    # sie heute fuehrt; sonst wird der Behandler ueber den NAMEN aufgeloest
    # (einziger Behandler-Kalender zaehlt auch) — und ohne Treffer bleibt sie
    # leer, damit der Fluss ehrlich nach dem Behandler fragt.
    cf_cid = _s(termin.get("calendarId"))
    kal_tot = _kalender_tot(tenant, cf_cid)
    if kal_tot:
        cal = _kalender_nur_name(tenant, name_roh)
        cid = _s((cal or {}).get("id"))
        print(f"kartei-kalender-tot cf={cf_cid} name={name_roh!r} -> {cid or '-'}", flush=True)
    else:
        cal = kalender_von(tenant, name_roh)
        cid = cf_cid or _s((cal or {}).get("id"))
    return {
        "ok": True,
        "calendarId": cid,
        "calendarName": _s((cal or {}).get("name")) or _s(termin.get("calendarName")),
        "doctorName": _s(termin.get("doctorName")),
        "lastIso": _s(termin.get("startIso")),
        "war": bool(data.get("lastAppointment")),
        "lastAppointment": data.get("lastAppointment") or {},
        "nextAppointment": data.get("nextAppointment") or {},
        # Besuchsgrund des VERGANGENEN Termins (Rueckblick-Ansprache, Chef
        # 30.08.2026) — bewusst nie vom Zukunfts-Termin.
        "grund": _s(vergangen.get("visitMotiveName")),
        "kalenderTot": kal_tot,
    }


def _kalender_tot(tenant: dict, calendar_id: str) -> bool:
    """True, wenn die Id NICHT zu den heutigen Kalendern des Mandanten gehoert.

    Ohne Kalenderliste (Dock-Tests, alte Sitzungen) wird nichts verworfen —
    im Zweifel gilt die Antwort der Plattform wie bisher."""
    cid = _s(calendar_id)
    cals = tenant.get("calendars") if isinstance(tenant.get("calendars"), list) else []
    ids = {_s(c.get("id")) for c in cals if isinstance(c, dict) and _s(c.get("id"))}
    if not cid or not ids:
        return False
    if cid in ids:
        return False
    # Gesperrte Behandler fuehrt behandler_sperre getrennt — die sind nicht
    # tot, sondern bewusst ausgeblendet (oben schon behandelt).
    gesperrt = tenant.get("_gesperrteKalender") if isinstance(tenant.get("_gesperrteKalender"), list) else []
    if any(_s(g.get("id")) == cid for g in gesperrt if isinstance(g, dict)):
        return False
    return True


def _kalender_nur_name(tenant: dict, name: str) -> dict[str, Any] | None:
    """Kalender ueber den Namen — OHNE den Default-Rueckfall von kalender_von.

    Trifft der Name keinen Kalender, zaehlt nur noch ein EINZIGER
    Behandler-Kalender (Blessing) als eindeutig; sonst None."""
    from kern import tenants as kern_tenants
    cals = tenant.get("calendars") if isinstance(tenant.get("calendars"), list) else []
    q = _s(name).lower()
    if q and cals:
        for c in cals:
            if _s(c.get("name")).lower() == q:
                return c
        tokens = [t for t in q.replace(".", " ").split() if t not in {"dr", "doktor", "med", "frau", "herr"}]
        best, score = None, 0
        for c in cals:
            n = _s(c.get("name")).lower()
            s = sum(1 for t in tokens if len(t) >= 3 and t in n)
            if s > score:
                best, score = c, s
        if best:
            return best
    personen = kern_tenants.behandler_kalender(tenant)
    if len(personen) == 1:
        return personen[0]
    return None
