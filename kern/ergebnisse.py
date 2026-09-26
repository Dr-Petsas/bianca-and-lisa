"""Live-Ergebnisseite: Anliegen, Cloud Functions, Auslastung.

Liest die Mitschnitte unter ``.data/anrufe/bianca/``. Studio-Testlaeufe
bleiben daneben unter ``/api/statistik`` — diese Auswertung gilt den
echten Anrufen, damit sich sehen laesst, was erkannt, geschrieben und
gleichzeitig belastet wurde.
"""
from __future__ import annotations

import bisect
import json
import math
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from kern import anruf_anliegen, mitschnitt
from kern.config import DATA_DIR


_STIMME = "bianca"
_SEIT_DATEI = "ergebnisse-seit"
_BASELINE_DATEI = "ergebnisse-baseline.json"
_UMSTELLUNG_DATEI = "ergebnisse-umstellung.json"
_TAGE_DATEI = "ergebnisse-tage.json"
_TAG_STUNDE = 20
_TAG_RUECKBLICK = 14
_PRAXIS_FEST = ("meddent", "thaler", "blessing", "ruether")
_SCHNITT_LOCK = threading.Lock()
_MANIFEST_LOCK = threading.Lock()
_MANIFEST_CACHE: dict[str, tuple[tuple[int, float], list[dict[str, Any]]]] = {}
# Diagramm reicht 14 Tage zurück. Ältere Mitschnitte werden nicht mehr geparst.
_MANIFEST_RUECKBLICK_TAGE = _TAG_RUECKBLICK + 2
_FEST_ANLIEGEN = frozenset({"buchen", "absagen", "verschieben", "auskunft"})
_VERFAHREN = "namenslink-neupatient"
_TENANT_TITEL = {
    "meddent": "MedDent",
    "thaler": "Thaler",
    "blessing": "Blessing",
    "ruether": "Rüther",
}


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _praxis_name(tid: str) -> str:
    kid = _s(tid)
    if not kid:
        return "unbekannt"
    if kid in _TENANT_TITEL:
        return _TENANT_TITEL[kid]
    try:
        from kern import tenants
        for t in tenants.liste():
            if not isinstance(t, dict):
                continue
            if kid in {
                _s(t.get("id")), _s(t.get("clientId")), _s(t.get("locationId")),
            }:
                return _s(t.get("praxisNameMelde") or t.get("praxisName")
                          or t.get("id")) or kid
    except Exception:
        pass
    return kid


def seit_ab() -> datetime | None:
    """Untere Grenze der Ergebnisseite — Datei setzen = Stats resetten."""
    p = Path(DATA_DIR) / _SEIT_DATEI
    if not p.is_file():
        return None
    try:
        return _parse_zeit(p.read_text(encoding="utf-8").splitlines()[0])
    except OSError:
        return None


def seit_setzen(t: datetime | None = None) -> datetime:
    """Zählung ab ``t`` (UTC jetzt, wenn leer). Mitschnitte bleiben liegen."""
    grenze = t or datetime.now(timezone.utc)
    if grenze.tzinfo is None:
        grenze = grenze.replace(tzinfo=timezone.utc)
    else:
        grenze = grenze.astimezone(timezone.utc)
    p = Path(DATA_DIR) / _SEIT_DATEI
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(grenze.isoformat(), encoding="utf-8")
    return grenze


def _berlin():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Europe/Berlin")
    except Exception:
        return timezone(timedelta(hours=2))


def _vergleich_am(umgestellt: datetime) -> datetime:
    lokal = umgestellt.astimezone(_berlin())
    return (lokal + timedelta(days=1)).replace(second=0, microsecond=0)


def _json_lesen(name: str) -> dict[str, Any] | None:
    p = Path(DATA_DIR) / name
    if not p.is_file():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    return raw if isinstance(raw, dict) else None


def _json_schreiben(name: str, daten: dict[str, Any]) -> None:
    p = Path(DATA_DIR) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(daten, ensure_ascii=False, indent=2), encoding="utf-8")


def baseline_lesen() -> dict[str, Any] | None:
    return _json_lesen(_BASELINE_DATEI)


def umstellung_lesen() -> dict[str, Any] | None:
    return _json_lesen(_UMSTELLUNG_DATEI)


def _delta_gesamt(alt: dict[str, Any] | None, neu: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(alt, dict) or not isinstance(neu, dict):
        return None
    keys = (
        "gespraeche", "anliegenErkannt", "anliegenErledigt", "anliegenQuote",
        "cfOk", "cfLeer", "cfFail", "cfQuote",
    )
    aus: dict[str, Any] = {}
    for k in keys:
        try:
            a = float(alt.get(k) or 0)
            b = float(neu.get(k) or 0)
        except (TypeError, ValueError):
            continue
        aus[k] = round(b - a, 1)
    return aus


def stand_sichern(name: str = "vor-namenslink-neupatient") -> dict[str, Any]:
    """Aktuelle Zahlen als Baseline-Report ablegen — ohne Reset."""
    daten = _auswerten("")
    now = datetime.now(timezone.utc)
    vergleich = _vergleich_am(now)
    paket = {
        "name": name,
        "verfahren": _VERFAHREN,
        "gesichertAt": now.isoformat(),
        "vergleichAm": vergleich.isoformat(),
        "daten": {
            "seit": daten.get("seit"),
            "gesamt": daten.get("gesamt"),
            "anliegen": daten.get("anliegen"),
            "cfs": daten.get("cfs"),
        },
    }
    _json_schreiben(_BASELINE_DATEI, paket)
    _json_schreiben(_UMSTELLUNG_DATEI, {
        "verfahren": _VERFAHREN,
        "titel": "Neupatienten: Namens-SMS + Platzhalter-Termin",
        "umgestelltAt": now.isoformat(),
        "vergleichAm": vergleich.isoformat(),
    })
    return paket


def umstellen(name: str = "vor-namenslink-neupatient") -> dict[str, Any]:
    """Baseline sichern, dann Ergebnisseite neu zählen."""
    vorher = stand_sichern(name)
    neu = seit_setzen()
    return {
        "verfahren": _VERFAHREN,
        "seit": neu.isoformat(),
        "vergleichAm": vorher.get("vergleichAm"),
        "vorher": vorher,
    }


def _nach_seit(m: dict[str, Any], grenze: datetime | None) -> bool:
    if grenze is None:
        return True
    start = _parse_zeit(m.get("startedAt"))
    return start is not None and start >= grenze


def _parse_zeit(roh: Any) -> datetime | None:
    text = _s(roh)
    if not text:
        return None
    try:
        t = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(timezone.utc)


def _ms(v: Any) -> int | None:
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def _fenster(m: dict[str, Any]) -> tuple[datetime, datetime] | None:
    start = _parse_zeit(m.get("startedAt"))
    if start is None:
        return None
    ende = _parse_zeit(m.get("endedAt"))
    if ende is None:
        dauer = _ms(m.get("dauerMs"))
        if dauer is None:
            zuege = [z for z in (m.get("zuege") or []) if isinstance(z, dict)]
            if zuege:
                letzter = _parse_zeit(zuege[-1].get("zeit"))
                off = _ms(zuege[-1].get("offsetMs"))
                if letzter is not None:
                    ende = letzter
                elif off is not None:
                    ende = start
                    ende = datetime.fromtimestamp(
                        start.timestamp() + off / 1000.0, tz=timezone.utc)
        else:
            ende = datetime.fromtimestamp(
                start.timestamp() + dauer / 1000.0, tz=timezone.utc)
    if ende is None:
        ende = start
    if ende < start:
        ende = start
    return start, ende


def _tenant_id(m: dict[str, Any]) -> str:
    return _s(m.get("tenantId")) or "unbekannt"


def _manifest_signatur(basis: Path) -> tuple[int, float]:
    n = 0
    mx = 0.0
    for d in basis.iterdir():
        if not d.is_dir():
            continue
        try:
            st = (d / "anruf.json").stat()
        except OSError:
            continue
        n += 1
        if st.st_mtime > mx:
            mx = st.st_mtime
    return n, mx


def _manifeste_frisch(basis: Path) -> list[dict[str, Any]]:
    """Nur Mitschnitte aus dem Diagramm-Fenster. Der Ordner wächst sonst
    jeden Tag, und die Seite hat jedes Mal die ganze Historie geparst."""
    grenze = time.time() - _MANIFEST_RUECKBLICK_TAGE * 86400
    aus: list[dict[str, Any]] = []
    for d in basis.iterdir():
        if not d.is_dir():
            continue
        try:
            if (d / "anruf.json").stat().st_mtime < grenze:
                continue
        except OSError:
            continue
        m = mitschnitt._laden(d)
        if not isinstance(m, dict):
            continue
        if m.get("testAnruf"):
            continue
        m = dict(m)
        m["_sid"] = _s(m.get("id") or d.name)
        aus.append(m)
    aus.sort(key=lambda x: _s(x.get("startedAt")), reverse=True)
    return aus


def _manifeste(stimme: str = _STIMME) -> list[dict[str, Any]]:
    basis = Path(DATA_DIR) / "anrufe" / (stimme or "").strip().lower()
    if not basis.is_dir():
        return []
    sig = _manifest_signatur(basis)
    schluessel = str(basis)
    with _MANIFEST_LOCK:
        hit = _MANIFEST_CACHE.get(schluessel)
        if hit and hit[0] == sig:
            return hit[1]
    liste = _manifeste_frisch(basis)
    with _MANIFEST_LOCK:
        _MANIFEST_CACHE[schluessel] = (sig, liste)
    return liste


def _passt_tenant(m: dict[str, Any], erlaubt: set[str] | None) -> bool:
    if not erlaubt:
        return True
    return _tenant_id(m) in erlaubt


def _response_grund(resp: Any) -> str:
    if isinstance(resp, dict):
        for k in ("grund", "error", "message", "msg", "reason", "code"):
            w = _s(resp.get(k))
            if w:
                return w[:160]
        err = resp.get("error")
        if isinstance(err, dict):
            return _response_grund(err)
    if isinstance(resp, str):
        return _s(resp)[:160]
    return ""


_LEER_LABEL = {
    "absentExcused": "von der Praxis storniert",
    "isDeleted": "im Papierkorb",
    "past": "bereits vorbei",
    "virtual": "virtuell / unbestätigt",
    "none": "kein Termin in der Akte",
    "mixed": "kein kommender Termin",
    "no_upcoming": "kein kommender Termin",
    "not_found": "Patient nicht gefunden",
}


def _cf_response(t: dict[str, Any]) -> dict[str, Any]:
    d = t.get("dispatch") if isinstance(t.get("dispatch"), dict) else {}
    resp = d.get("response")
    return resp if isinstance(resp, dict) else {}


def _cf_http(t: dict[str, Any]) -> int:
    d = t.get("dispatch") if isinstance(t.get("dispatch"), dict) else {}
    try:
        return int(d.get("httpStatus") or 0)
    except (TypeError, ValueError):
        return 0


def _cf_leer_status(t: dict[str, Any]) -> str:
    resp = _cf_response(t)
    st = _s(resp.get("status") or t.get("noUpcomingReason") or t.get("cfStatus"))
    if st in _LEER_LABEL:
        return st
    if t.get("notFound") and _cf_http(t) in {0, 404}:
        return "no_upcoming" if resp.get("patient") or t.get("patientId") else "not_found"
    if _cf_http(t) == 404 and _cf_name(t) == "agentFindPatientAppointments":
        return "no_upcoming" if resp.get("patient") else "not_found"
    return ""


def _cf_grund(t: dict[str, Any]) -> str:
    if t.get("verificationFailed"):
        return "Kalenderbeweis fehlgeschlagen"
    if t.get("patientMismatch"):
        return "Patient passt nicht zur Buchung"
    if t.get("mehrdeutig"):
        return "mehrdeutig"
    leer = _cf_leer_status(t)
    if leer:
        resp = _cf_response(t)
        code = _s(t.get("noUpcomingReason") or resp.get("noUpcomingReason") or leer)
        return _LEER_LABEL.get(code, _LEER_LABEL.get(leer, "kein kommender Termin"))
    if t.get("notFound"):
        return "nicht gefunden"
    d = t.get("dispatch") if isinstance(t.get("dispatch"), dict) else {}
    code = _cf_http(t)
    msg = _response_grund(d.get("response"))
    if code >= 400:
        return f"HTTP {code}" + (f": {msg}" if msg else "")
    if msg:
        return msg
    spoken = _s(t.get("spoken"))
    if spoken:
        return spoken[:160]
    return "Werkzeug nicht ok"


def _cf_lage(t: dict[str, Any]) -> str:
    """ok = geschrieben/gefunden, leer = designed empty, fail = Technik."""
    if t.get("verificationFailed") or t.get("patientMismatch"):
        return "fail"
    if _cf_leer_status(t):
        return "leer"
    code = _cf_http(t)
    if code >= 500 or code in {408, 429}:
        return "fail"
    if code >= 400:
        return "fail"
    if code == 0 and not t.get("ok"):
        return "fail"
    return "ok" if t.get("ok") or 200 <= code < 300 else "fail"


def _cf_ok(t: dict[str, Any]) -> bool:
    return _cf_lage(t) == "ok"


def _dispatch_liste(t: dict[str, Any]) -> list[dict[str, Any]]:
    aus: list[dict[str, Any]] = []
    d = t.get("dispatch") if isinstance(t.get("dispatch"), dict) else None
    if d and (_s(d.get("route")) or _s(t.get("cf"))):
        aus.append(d)
    if d:
        for extra in ("verificationDispatch", "phoneFixDispatch"):
            n = d.get(extra)
            if isinstance(n, dict) and _s(n.get("route")):
                aus.append(n)
    return aus


def _werkzeuge(m: dict[str, Any]) -> list[dict[str, Any]]:
    roh: list[dict[str, Any]] = []
    for z in m.get("zuege") or []:
        if not isinstance(z, dict):
            continue
        for t in z.get("tools") or []:
            if isinstance(t, dict):
                roh.append(t)
    for t in m.get("tools") or []:
        if isinstance(t, dict):
            roh.append(t)
    gesehen: set[tuple[Any, ...]] = set()
    aus: list[dict[str, Any]] = []
    for t in roh:
        d = t.get("dispatch") if isinstance(t.get("dispatch"), dict) else {}
        key = (
            _s(d.get("route") or t.get("cf") or t.get("name")),
            d.get("httpStatus"),
            t.get("ms") if t.get("ms") is not None else d.get("ms"),
            bool(t.get("ok")),
            _s(t.get("appointmentId")),
        )
        if key in gesehen:
            continue
        gesehen.add(key)
        aus.append(t)
    return aus


def _cf_name(t: dict[str, Any], d: dict[str, Any] | None = None) -> str:
    d = d if isinstance(d, dict) else (
        t.get("dispatch") if isinstance(t.get("dispatch"), dict) else {})
    return _s(d.get("route") or t.get("cf") or t.get("name")) or "unbekannt"


def _zug_latenz_s(z: dict[str, Any]) -> float | None:
    tim = z.get("timings") if isinstance(z.get("timings"), dict) else {}
    for k in ("total", "gesamt", "all"):
        try:
            v = float(tim.get(k))
        except (TypeError, ValueError):
            continue
        if v > 0:
            return v if v < 120 else v / 1000.0
    teile = []
    for k in ("stt", "llm", "tts"):
        try:
            v = float(tim.get(k) or 0)
        except (TypeError, ValueError):
            v = 0.0
        if v > 0:
            teile.append(v if v < 120 else v / 1000.0)
    if teile:
        return sum(teile)
    return None


def _zug_zeit(m: dict[str, Any], z: dict[str, Any], start: datetime) -> datetime:
    t = _parse_zeit(z.get("zeit"))
    if t is not None:
        return t
    off = _ms(z.get("offsetMs"))
    if off is not None:
        return datetime.fromtimestamp(
            start.timestamp() + off / 1000.0, tz=timezone.utc)
    return start


def _p90(werte: list[float]) -> float:
    if not werte:
        return 0.0
    xs = sorted(werte)
    i = max(0, min(len(xs) - 1, math.ceil(0.9 * len(xs)) - 1))
    return round(xs[i], 3)


def _mittel(werte: list[float]) -> float:
    return round(sum(werte) / len(werte), 3) if werte else 0.0


def _anliegen_zeilen(anrufe: list[dict[str, Any]]) -> list[dict[str, Any]]:
    erkannt: Counter[str] = Counter()
    ok: Counter[str] = Counter()
    beispiele: dict[str, list[dict[str, str]]] = defaultdict(list)
    for m in anrufe:
        ids = anruf_anliegen.ids_von(m)
        sid = _s(m.get("_sid") or m.get("id"))
        for i in ids:
            erkannt[i] += 1
            fertig = anruf_anliegen.erledigt(m, i)
            if fertig:
                ok[i] += 1
            stand = "erledigt" if fertig else "offen"
            liste = beispiele[i]
            if len(liste) < 24:
                liste.append({
                    "sid": sid,
                    "tenant": _tenant_id(m),
                    "zeit": _s(m.get("startedAt")),
                    "stand": stand,
                })
    zeilen = []
    for i in anruf_anliegen.REIHE:
        n = erkannt.get(i, 0)
        e = ok.get(i, 0)
        fest = i in _FEST_ANLIEGEN
        zeilen.append({
            "id": i,
            "titel": anruf_anliegen.TITEL[i],
            "gruppe": "Terminverwaltung" if fest else "Einstellbare Anliegen",
            "fest": fest,
            "erkannt": n,
            "erledigt": e,
            "offen": n - e,
            "quote": round(100.0 * e / n, 1) if n else None,
            "gespraeche": beispiele.get(i, []),
            "offenGespraeche": [
                g for g in beispiele.get(i, []) if g.get("stand") != "erledigt"
            ],
        })
    return zeilen


def _cf_zeilen(anrufe: list[dict[str, Any]]) -> list[dict[str, Any]]:
    zaehl: dict[str, dict[str, Any]] = {}
    for m in anrufe:
        sid = _s(m.get("_sid") or m.get("id"))
        for t in _werkzeuge(m):
            dispatches = _dispatch_liste(t)
            if not dispatches:
                continue
            for d in dispatches:
                name = _cf_name(t, d)
                if name == "unbekannt":
                    continue
                bucket = zaehl.setdefault(name, {
                    "cf": name,
                    "laeufe": 0,
                    "ok": 0,
                    "leer": 0,
                    "fail": 0,
                    "ms": [],
                    "gruende": Counter(),
                    "hinweise": [],
                    "fails": [],
                    "oks": [],
                })
                bucket["laeufe"] += 1
                status = d.get("httpStatus")
                try:
                    code = int(status) if status is not None else 0
                except (TypeError, ValueError):
                    code = 0
                ms = _ms(d.get("ms") if d.get("ms") is not None else t.get("ms"))
                if ms is not None:
                    bucket["ms"].append(ms)
                fake = dict(t)
                if d:
                    fake["dispatch"] = d
                lage = _cf_lage(fake)
                if lage == "ok":
                    bucket["ok"] += 1
                    if len(bucket["oks"]) < 12:
                        bucket["oks"].append({
                            "sid": sid,
                            "tenant": _tenant_id(m),
                            "zeit": _s(m.get("startedAt")),
                            "grund": "ok",
                        })
                    continue
                grund = _cf_grund(fake)
                if lage == "leer":
                    bucket["leer"] += 1
                    bucket["gruende"][grund] += 1
                    if len(bucket["hinweise"]) < 12:
                        bucket["hinweise"].append({
                            "sid": sid,
                            "tenant": _tenant_id(m),
                            "zeit": _s(m.get("startedAt")),
                            "grund": grund,
                            "httpStatus": code or None,
                        })
                    continue
                bucket["fail"] += 1
                bucket["gruende"][grund] += 1
                if len(bucket["fails"]) < 12:
                    bucket["fails"].append({
                        "sid": sid,
                        "tenant": _tenant_id(m),
                        "zeit": _s(m.get("startedAt")),
                        "grund": grund,
                        "httpStatus": code or None,
                    })
    zeilen = []
    for name, b in sorted(zaehl.items(), key=lambda x: (-x[1]["laeufe"], x[0])):
        n = b["laeufe"]
        technik_ok = b["ok"] + b["leer"]
        zeilen.append({
            "cf": name,
            "laeufe": n,
            "ok": b["ok"],
            "leer": b["leer"],
            "fail": b["fail"],
            "quote": round(100.0 * technik_ok / n, 1) if n else 0.0,
            "msMittel": int(round(sum(b["ms"]) / len(b["ms"]))) if b["ms"] else 0,
            "gruende": [
                {"grund": g, "anzahl": c}
                for g, c in b["gruende"].most_common(8)
            ],
            "hinweise": b["hinweise"],
            "fails": b["fails"],
            "oks": b["oks"],
        })
    return zeilen


def _auslastung(alle: list[dict[str, Any]]) -> dict[str, Any]:
    intervalle: list[dict[str, Any]] = []
    events: list[tuple[datetime, int, str, str]] = []
    for m in alle:
        fen = _fenster(m)
        if fen is None:
            continue
        start, ende = fen
        if ende == start:
            ende = datetime.fromtimestamp(start.timestamp() + 1.0, tz=timezone.utc)
        tid = _tenant_id(m)
        sid = _s(m.get("_sid") or m.get("id"))
        intervalle.append({
            "sid": sid,
            "tenant": tid,
            "praxis": _praxis_name(tid),
            "von": start.isoformat(),
            "bis": ende.isoformat(),
            "dauerS": round((ende - start).total_seconds(), 1),
        })
        events.append((start, 1, tid, sid))
        events.append((ende, -1, tid, sid))
    events.sort(key=lambda x: (x[0], x[1]))
    aktiv: dict[str, set[str]] = defaultdict(set)
    aktiv_n = 0
    peak = 0
    peak_t = ""
    peak_praxen: list[str] = []
    alle_gleich: list[dict[str, Any]] = []
    punkte: list[dict[str, Any]] = []
    # Stand nach jedem Zeitpunkt, damit die Latenz nicht für jeden Zug
    # noch einmal alle Intervalle durchzählt (das wurde bei ~1000 Anrufen
    # zur Mehr-Sekunden-Pause der Ergebnisseite).
    marken: list[datetime] = []
    staende: list[int] = []
    praxen = sorted({i["tenant"] for i in intervalle})
    n_praxen = max(1, len(praxen))
    last_t: datetime | None = None
    for t, delta, tid, sid in events:
        if last_t is not None and t != last_t:
            n_aktiv_praxen = sum(1 for s in aktiv.values() if s)
            punkte.append({
                "t": last_t.isoformat(),
                "n": aktiv_n,
                "praxen": {k: len(v) for k, v in aktiv.items() if v},
            })
            if n_aktiv_praxen >= n_praxen and n_praxen >= 2 and aktiv_n >= n_praxen:
                alle_gleich.append({
                    "t": last_t.isoformat(),
                    "n": aktiv_n,
                    "praxen": {k: len(v) for k, v in aktiv.items() if v},
                })
        if delta > 0:
            aktiv[tid].add(sid)
            aktiv_n += 1
        else:
            aktiv[tid].discard(sid)
            if not aktiv[tid]:
                aktiv.pop(tid, None)
            aktiv_n = max(0, aktiv_n - 1)
        if aktiv_n > peak:
            peak = aktiv_n
            peak_t = t.isoformat()
            peak_praxen = sorted(k for k, v in aktiv.items() if v)
        if marken and marken[-1] == t:
            staende[-1] = aktiv_n
        else:
            marken.append(t)
            staende.append(aktiv_n)
        last_t = t
    if last_t is not None:
        punkte.append({
            "t": last_t.isoformat(),
            "n": aktiv_n,
            "praxen": {k: len(v) for k, v in aktiv.items() if v},
        })

    def _n_bei(ts: datetime) -> int:
        if not marken:
            return 0
        i = bisect.bisect_right(marken, ts) - 1
        if i < 0:
            return 0
        return staende[i]

    lat_buckets: dict[int, list[float]] = defaultdict(list)
    for m in alle:
        fen = _fenster(m)
        if fen is None:
            continue
        start, _ende = fen
        for z in m.get("zuege") or []:
            if not isinstance(z, dict):
                continue
            lat = _zug_latenz_s(z)
            if lat is None:
                continue
            n = max(1, _n_bei(_zug_zeit(m, z, start)))
            lat_buckets[n].append(lat)

    drift = []
    for n in sorted(lat_buckets):
        xs = lat_buckets[n]
        drift.append({
            "gleichzeitig": n,
            "zuege": len(xs),
            "mittelS": _mittel(xs),
            "p90S": _p90(xs),
        })
    allein = lat_buckets.get(1, [])
    last = []
    for n, xs in lat_buckets.items():
        if n >= 2:
            last.extend(xs)
    return {
        "anrufe": len(intervalle),
        "praxen": [
            {"id": t, "name": _praxis_name(t),
             "anrufe": sum(1 for i in intervalle if i["tenant"] == t)}
            for t in praxen
        ],
        "spitze": {
            "n": peak,
            "zeit": peak_t,
            "praxen": [{"id": p, "name": _praxis_name(p)} for p in peak_praxen],
        },
        "alleGleichzeitig": alle_gleich[:24],
        "alleGleichzeitigN": len(alle_gleich),
        "intervalle": intervalle,
        "verlauf": _verlauf_kuerzen(punkte),
        "latenz": {
            "alleinS": _mittel(allein),
            "gleichzeitigS": _mittel(last),
            "deltaS": round(_mittel(last) - _mittel(allein), 3) if allein and last else 0.0,
            "nachLast": drift,
        },
    }


def _berlin_dt(t: datetime) -> datetime:
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(_berlin())


def tag_schluss(t: datetime) -> datetime:
    """20:00 Europe/Berlin, an dem der Tag dieses Zeitpunkts endet.

    Genau 20:00 gehört schon zum neuen Tag. Der Schluss liegt dann am
    nächsten Kalendertag.
    """
    lokal = _berlin_dt(t)
    schluss = lokal.replace(hour=_TAG_STUNDE, minute=0, second=0, microsecond=0)
    if lokal >= schluss:
        schluss += timedelta(days=1)
    return schluss


def tag_label(t: datetime) -> str:
    """Kalenderdatum des 20:00-Endes, zu dem der Zeitpunkt gehört."""
    return tag_schluss(t).date().isoformat()


def tag_fenster(label: str) -> tuple[datetime, datetime]:
    ende_datum = datetime.fromisoformat(label).date()
    ende = datetime(
        ende_datum.year, ende_datum.month, ende_datum.day,
        _TAG_STUNDE, 0, tzinfo=_berlin(),
    )
    start = ende - timedelta(days=1)
    return start.astimezone(timezone.utc), ende.astimezone(timezone.utc)


def letzte_grenze(jetzt: datetime) -> datetime:
    """Letztes erreichtes 20:00. Genau 20:00 zählt als erreicht."""
    lokal = _berlin_dt(jetzt)
    grenze = lokal.replace(hour=_TAG_STUNDE, minute=0, second=0, microsecond=0)
    if lokal < grenze:
        grenze -= timedelta(days=1)
    return grenze.astimezone(timezone.utc)


def _im_fenster(m: dict[str, Any], von: datetime, bis: datetime) -> bool:
    start = _parse_zeit(m.get("startedAt"))
    return start is not None and von <= start < bis


def _fehler_je_praxis(anrufe: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fehlerquote je Praxis PRO ANRUF, evidenzbasiert (Chef 26.09.2026):

    Ein Fehler ist NUR ein von Bianca ausgelöster Dialogfehler (Missverständnis
    nicht korrigiert, Wiederholungs-/Presence-Schleife, Technikfehler,
    „Patient nicht gefunden“). Anruferabbrüche (Auflegen, Ablehnen) sind neutral
    und zählen weder als Fehler noch als Erfolg. Nenner = gewertete Job-Anrufe
    (ok + Fehler)."""
    ok: Counter[str] = Counter()
    fehler: Counter[str] = Counter()
    gruende: dict[str, Counter[str]] = defaultdict(Counter)
    fails: dict[str, list[dict[str, str]]] = defaultdict(list)
    for m in anrufe:
        tid = _tenant_id(m)
        art, warum = anruf_anliegen.anruf_wertung(m)
        if art == "fehler":
            fehler[tid] += 1
            for g in warum:
                gruende[tid][g] += 1
            liste = fails[tid]
            if len(liste) < 24:
                liste.append({
                    "sid": _s(m.get("_sid") or m.get("id")),
                    "tenant": tid,
                    "zeit": _s(m.get("startedAt")),
                    "grund": ", ".join(warum),
                })
        elif art == "ok":
            ok[tid] += 1
        # neutral: nicht werten
    ids = list(_PRAXIS_FEST)
    for tid in sorted(set(ok) | set(fehler)):
        if tid not in ids:
            ids.append(tid)
    zeilen = []
    for tid in ids:
        o = int(ok.get(tid, 0))
        f = int(fehler.get(tid, 0))
        n = o + f
        zeilen.append({
            "id": tid,
            "name": _praxis_name(tid),
            "erkannt": n,          # gewertete Job-Anrufe
            "erledigt": o,         # sauber gelöst
            "offen": f,            # Bianca-Fehler
            # Erfolgsquote der gewerteten Job-Anrufe. Ohne gewerteten Anruf
            # bleibt der Punkt leer, sonst sähe ein stiller Tag wie 0 % aus.
            "quote": round(100.0 * o / n, 1) if n else None,
            "fehlerquote": round(100.0 * f / n, 1) if n else 0.0,
            "gruende": [{"grund": g, "anzahl": c}
                        for g, c in gruende.get(tid, Counter()).most_common()],
            "fails": fails.get(tid, []),
        })
    return zeilen


def _praxis_mit_quote(p: dict[str, Any]) -> dict[str, Any]:
    """Alte Tagesablage kennt nur die Fehlerquote. Die Kurve zeichnet die Erfolgsquote."""
    zeile = dict(p)
    n = int(zeile.get("erkannt") or 0)
    offen = int(zeile.get("offen") or 0)
    if n <= 0:
        zeile["quote"] = None
    elif zeile.get("quote") is None:
        zeile["quote"] = round(100.0 * max(0, n - offen) / n, 1)
    return zeile


def _tage_lesen() -> dict[str, Any]:
    roh = _json_lesen(_TAGE_DATEI) or {}
    tage = roh.get("tage")
    if not isinstance(tage, dict):
        tage = {}
    return {"letzterSchnitt": _s(roh.get("letzterSchnitt")), "tage": tage}


def _reihen_labels(jetzt: datetime) -> list[str]:
    heute = _berlin_dt(jetzt).date()
    labels = {(heute - timedelta(days=i)).isoformat() for i in range(_TAG_RUECKBLICK)}
    offen = tag_label(jetzt)
    labels.add(offen)
    labels.add((datetime.fromisoformat(offen).date() - timedelta(days=1)).isoformat())
    return sorted(labels)


def _punkt(tag: str, von: datetime, bis: datetime, teil: list[dict[str, Any]], offen: bool) -> dict[str, Any]:
    return {
        "tag": tag,
        "von": von.isoformat(),
        "bis": bis.isoformat(),
        "offen": offen,
        "praxen": [_praxis_mit_quote(p) for p in _fehler_je_praxis(teil)],
    }


def _archiv_punkt(tag: str, eintrag: dict[str, Any]) -> dict[str, Any]:
    zeile = dict(eintrag)
    zeile["tag"] = tag
    zeile["offen"] = False
    praxen = zeile.get("praxen")
    if not isinstance(praxen, list):
        praxen = _fehler_je_praxis([])
    zeile["praxen"] = [_praxis_mit_quote(p) for p in praxen]
    return zeile


def tage_anzeige(jetzt: datetime | None = None, stimme: str = _STIMME) -> dict[str, Any]:
    """Geschlossene Tage aus der Ablage, der laufende Tag frisch aus den Mitschnitten.

    Liegt der Zähler-Reset mitten im offenen Tag, bleibt der Stand davor als
    eigener Punkt (Schlüssel mit Uhrzeit) und der offene Punkt zählt nur noch
    Anrufe ab diesem Reset.
    """
    jetzt = jetzt or datetime.now(timezone.utc)
    stand = _tage_lesen()
    archiv = stand["tage"]
    manifest = _manifeste(stimme)
    offen_label = tag_label(jetzt)
    seit = seit_ab()
    reihe: list[dict[str, Any]] = []
    for label in _reihen_labels(jetzt):
        von, bis = tag_fenster(label)
        if label == offen_label or label not in archiv:
            teil = [m for m in manifest if _im_fenster(m, von, bis)]
            punkt_von = von
            if label == offen_label and seit is not None and von < seit < bis:
                teil = [
                    m for m in teil
                    if (start := _parse_zeit(m.get("startedAt"))) is not None and start >= seit
                ]
                punkt_von = seit
            reihe.append(_punkt(label, punkt_von, bis, teil, label == offen_label))
            continue
        reihe.append(_archiv_punkt(label, archiv[label]))
    for tag, eintrag in archiv.items():
        if "T" not in tag or not isinstance(eintrag, dict):
            continue
        von = _parse_zeit(eintrag.get("von"))
        if von is None or von < jetzt - timedelta(days=_TAG_RUECKBLICK):
            continue
        reihe.append(_archiv_punkt(tag, eintrag))
    reihe.sort(key=lambda punkt: (punkt.get("von") or "", punkt.get("tag") or ""))
    return {
        "grenze": f"{_TAG_STUNDE:02d}:00",
        "zeitzone": "Europe/Berlin",
        "letzterSchnitt": stand.get("letzterSchnitt") or "",
        "reihe": reihe,
    }


def zwischenstand(jetzt: datetime | None = None, stimme: str = _STIMME) -> dict[str, Any]:
    """Aktuelle Karten ins Zeitdiagramm schreiben und die Zählung danach bei null beginnen."""
    with _SCHNITT_LOCK:
        return _zwischenstand(jetzt or datetime.now(timezone.utc), stimme)


def _zwischenstand(jetzt: datetime, stimme: str) -> dict[str, Any]:
    label = tag_label(jetzt)
    fenster_von, fenster_bis = tag_fenster(label)
    seit = seit_ab()
    anfang = seit if seit is not None and seit > fenster_von else fenster_von
    if anfang > fenster_bis:
        anfang = fenster_von
    ende = jetzt if jetzt < fenster_bis else fenster_bis
    manifest = _manifeste(stimme)
    teil = [m for m in manifest if _im_fenster(m, anfang, ende)]
    stand = _tage_lesen()
    tage = dict(stand["tage"])
    key = _berlin_dt(ende).strftime("%Y-%m-%dT%H:%M")
    tage[key] = {
        "von": anfang.isoformat(),
        "bis": ende.isoformat(),
        "praxen": _fehler_je_praxis(teil),
    }
    behalten = sorted(tage)[-90:]
    _json_schreiben(_TAGE_DATEI, {
        "letzterSchnitt": stand.get("letzterSchnitt") or "",
        "tage": {k: tage[k] for k in behalten},
    })
    neu = seit_setzen(ende)
    return {
        "geschrieben": key,
        "gespraeche": len(teil),
        "seit": neu.isoformat(),
    }


def tag_schneiden(jetzt: datetime | None = None) -> dict[str, Any]:
    """Um 20:00 den abgeschlossenen Tag ins Diagramm schreiben und die Zähler nullen."""
    with _SCHNITT_LOCK:
        return _tag_schneiden(jetzt or datetime.now(timezone.utc))


def _tag_schneiden(jetzt: datetime) -> dict[str, Any]:
    grenze = letzte_grenze(jetzt)
    stand = _tage_lesen()
    letzter = _parse_zeit(stand.get("letzterSchnitt"))
    if letzter is not None and letzter >= grenze:
        return {"geschnitten": False, "letzterSchnitt": letzter.isoformat()}
    tage = dict(stand["tage"])
    manifest = _manifeste()
    schluss_datum = _berlin_dt(grenze).date()
    geschrieben: list[str] = []
    for i in range(_TAG_RUECKBLICK):
        label = (schluss_datum - timedelta(days=i)).isoformat()
        von, bis = tag_fenster(label)
        if bis > grenze:
            continue
        if label in tage and bis < grenze and letzter is not None:
            continue
        teil = [m for m in manifest if _im_fenster(m, von, bis)]
        tage[label] = {
            "von": von.isoformat(),
            "bis": bis.isoformat(),
            "praxen": _fehler_je_praxis(teil),
        }
        geschrieben.append(label)
    behalten = sorted(tage)[-90:]
    tage = {k: tage[k] for k in behalten}
    _json_schreiben(_TAGE_DATEI, {
        "letzterSchnitt": grenze.isoformat(),
        "tage": tage,
    })
    seit = seit_ab()
    if seit is None or seit < grenze:
        seit_setzen(grenze)
    return {
        "geschnitten": True,
        "letzterSchnitt": grenze.isoformat(),
        "geschrieben": sorted(geschrieben),
    }


def _verlauf_kuerzen(punkte: list[dict[str, Any]], max_n: int = 240) -> list[dict[str, Any]]:
    if len(punkte) <= max_n:
        return punkte
    schritt = max(1, len(punkte) // max_n)
    aus = [punkte[i] for i in range(0, len(punkte), schritt)]
    if punkte and aus[-1] is not punkte[-1]:
        aus.append(punkte[-1])
    return aus


def _erlaubt(tenant: str) -> set[str] | None:
    fn = getattr(mitschnitt, "erlaubt_von", None)
    erlaubt_liste = fn(tenant) if callable(fn) else ([tenant] if _s(tenant) else None)
    return {x for x in (erlaubt_liste or []) if x} or None


def _block_von(gefiltert: list[dict[str, Any]], last_basis: list[dict[str, Any]]) -> dict[str, Any]:
    """Karten, Anliegen-Tabelle und Cloud Functions aus einer Anrufliste."""
    anliegen = _anliegen_zeilen(gefiltert)
    erkannt = sum(z["erkannt"] for z in anliegen)
    erledigt = sum(z["erledigt"] for z in anliegen)
    cfs = _cf_zeilen(gefiltert)
    cf_ok = sum(z["ok"] for z in cfs)
    cf_leer = sum(z.get("leer", 0) for z in cfs)
    cf_fail = sum(z["fail"] for z in cfs)
    last = _auslastung(last_basis)
    return {
        "gesamt": {
            "gespraeche": len(gefiltert),
            "anliegenErkannt": erkannt,
            "anliegenErledigt": erledigt,
            "anliegenQuote": round(100.0 * erledigt / erkannt, 1) if erkannt else 0.0,
            "cfOk": cf_ok,
            "cfLeer": cf_leer,
            "cfFail": cf_fail,
            "cfQuote": round(100.0 * (cf_ok + cf_leer) / max(1, cf_ok + cf_leer + cf_fail), 1),
            "gleichzeitigMax": last["spitze"]["n"],
            "latenzAlleinS": last["latenz"]["alleinS"],
            "latenzGleichzeitigS": last["latenz"]["gleichzeitigS"],
            "latenzDeltaS": last["latenz"]["deltaS"],
        },
        "anliegen": anliegen,
        "cfs": cfs,
        "auslastung": last,
    }


def _auswerten(tenant: str = "", stimme: str = _STIMME) -> dict[str, Any]:
    """Anliegen, CFs und Auslastung aus den Live-Mitschnitten ab dem 20:00-Schnitt."""
    erlaubt = _erlaubt(tenant)
    grenze = seit_ab()
    alle = [m for m in _manifeste(stimme) if _nach_seit(m, grenze)]
    gefiltert = [m for m in alle if _passt_tenant(m, erlaubt)]
    block = _block_von(gefiltert, alle)
    return {
        "quelle": "mitschnitt",
        "tenant": _s(tenant),
        "seit": grenze.isoformat() if grenze else "",
        **block,
    }


def _summe_von_tage(tage: dict[str, Any], tenant: str = "", stimme: str = _STIMME) -> dict[str, Any]:
    """Summe genau über die Tage, die das Diagramm zeichnet. Der 20:00-Schnitt lässt sie stehen."""
    erlaubt = _erlaubt(tenant)
    reihe = tage.get("reihe") or []
    manifest = _manifeste(stimme)
    von = _parse_zeit(reihe[0].get("von")) if reihe else None
    bis = _parse_zeit(reihe[-1].get("bis")) if reihe else None
    im_fenster = [
        m for m in manifest
        if von is not None and bis is not None and _im_fenster(m, von, bis)
    ]
    gefiltert = [m for m in im_fenster if _passt_tenant(m, erlaubt)]
    block = _block_von(gefiltert, im_fenster)
    block["von"] = von.isoformat() if von else ""
    block["bis"] = bis.isoformat() if bis else ""
    return block


def _strategien() -> list[dict[str, Any]]:
    """Was die jeweilige Bianca beim nächsten Anruf wirklich benutzt.

    Dieselbe Auflösung wie am Telefon: Portal, sonst die veröffentlichte
    Studio-Datei, sonst der eingebaute Standard.
    """
    from kern import anliegen_ablage, anliegen_katalog as ak, tenants
    from kern.slots import such_fenster_tage

    monate_von = {92: 3, 183: 6, 274: 9, 366: 12}
    aus: list[dict[str, Any]] = []
    for kennung in _PRAXIS_FEST:
        try:
            t = anliegen_ablage.anreichern(tenants.laden(kennung), kennung)
        except Exception:
            continue
        tage = such_fenster_tage(t)
        quelle = _s(t.get("_anliegenPolicyQuelle")) or "standard"
        regeln = ak.aus_tenant(t) if quelle != "standard" else {}
        zeilen = []
        for a in ak.KATALOG:
            r = regeln.get(a.id)
            if r is None:
                zeilen.append({
                    "id": a.id,
                    "titel": a.titel,
                    "text": "nicht gesetzt — bisheriger Gesprächsweg",
                })
                continue
            opt = next((o for o in a.optionen if o.id == r.wahl), None)
            zeilen.append({
                "id": a.id,
                "titel": a.titel,
                "text": opt.text if opt else r.wahl,
            })
        aus.append({
            "id": kennung,
            "titel": _TENANT_TITEL.get(kennung, kennung),
            "quelle": quelle,
            "suchFensterTage": tage,
            "suchFensterMonate": monate_von.get(tage),
            "anliegen": zeilen,
        })
    return aus


def aus_mitschnitten(tenant: str = "", stimme: str = _STIMME) -> dict[str, Any]:
    d = _auswerten(tenant, stimme)
    um = umstellung_lesen() or {}
    vorher = baseline_lesen()
    daten = vorher.get("daten") if isinstance(vorher, dict) else None
    d["umstellung"] = um
    d["vorher"] = daten if isinstance(daten, dict) else None
    d["tage"] = tage_anzeige()
    d["summe"] = _summe_von_tage(d["tage"], tenant, stimme)
    d["delta"] = _delta_gesamt(
        (d["vorher"] or {}).get("gesamt") if isinstance(d["vorher"], dict) else None,
        d.get("gesamt"),
    )
    d["strategien"] = _strategien()
    return d
