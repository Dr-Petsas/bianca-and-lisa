from __future__ import annotations

import json
from typing import Any

from kern.config import DEFAULT_TENANT, TENANTS_DIR
from kern.stt_lexikon import NACHNAMEN, PRAXIS, VORNAMEN


def _sauber(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def liste() -> list[dict[str, str]]:
    out = []
    if not TENANTS_DIR.is_dir():
        return out
    for p in sorted(TENANTS_DIR.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        out.append({
            "id": p.stem,
            "clientId": _sauber(d.get("clientId")) or p.stem,
            "praxisName": _sauber(d.get("praxisName")) or p.stem,
        })
    return out


def laden(tenant_id: str = "") -> dict[str, Any]:
    name = _sauber(tenant_id) or DEFAULT_TENANT
    pfad = TENANTS_DIR / f"{name}.json"
    if not pfad.is_file():
        pfad = TENANTS_DIR / f"{DEFAULT_TENANT}.json"
    raw = json.loads(pfad.read_text(encoding="utf-8"))
    raw["_id"] = pfad.stem
    return raw


def stt_keywords(tenant: dict[str, Any]) -> list[str]:
    """Hotwords fuer die STT-Nachkorrektur (Clara-V7-Stufen, ohne Marker).

    1. Behandler-Nachnamen des Mandanten (Betsas -> Petsas).
    2. Haeufige Vornamen + Praxiswoerter (stt_lexikon) — Clara V7 schickt
       ein ganzes Profil-Lexikon, nicht nur drei Aerzte.
    Bewusst KEINE Marker (Heads-up, Teleskopkrone, Kons): Patiententelefon.
    """
    kandidaten: list[str] = []
    quellen: list[Any] = [tenant.get("behandler")]
    cals = tenant.get("calendars") if isinstance(tenant.get("calendars"), list) else []
    quellen += [c.get("name") for c in cals if isinstance(c, dict)]
    for q in quellen:
        for tok in _sauber(q).replace(".", " ").split():
            t = tok.strip("-()")
            if len(t) >= 4 and t.lower() not in {"doktor", "prof", "med", "dent"}:
                kandidaten.append(t[0].upper() + t[1:])
    kandidaten.extend(VORNAMEN)
    kandidaten.extend(NACHNAMEN)
    kandidaten.extend(PRAXIS)
    out: list[str] = []
    for k in kandidaten:
        if k not in out:
            out.append(k)
    return out


def kalender_liste(tenant: dict[str, Any]) -> list[dict[str, Any]]:
    """Alle Behandler-Kalender des Mandanten, ohne Default-Rückfall."""
    cals = tenant.get("calendars") if isinstance(tenant.get("calendars"), list) else []
    return [c for c in cals if isinstance(c, dict) and _sauber(c.get("id"))]


def kalender_von(tenant: dict[str, Any], name: str = "") -> dict[str, Any] | None:
    cals = tenant.get("calendars") if isinstance(tenant.get("calendars"), list) else []
    q = _sauber(name).lower()
    if q:
        for c in cals:
            if _sauber(c.get("name")).lower() == q:
                return c
        tokens = [t for t in q.replace(".", " ").split() if t not in {"dr", "doktor", "med"}]
        best, score = None, 0
        for c in cals:
            n = _sauber(c.get("name")).lower()
            s = sum(1 for t in tokens if t and t in n)
            if s > score:
                best, score = c, s
        if best:
            return best
    cid = _sauber(tenant.get("defaultCalendarId"))
    if cid:
        return next((c for c in cals if _sauber(c.get("id")) == cid), {"id": cid, "name": ""})
    return cals[0] if cals else None


def motiv_von(tenant: dict[str, Any], name: str = "") -> dict[str, Any] | None:
    vms = tenant.get("visitMotives") if isinstance(tenant.get("visitMotives"), list) else []
    q = _sauber(name).lower()
    if q:
        for v in vms:
            if _sauber(v.get("name")).lower() == q:
                return v
        hit = next((v for v in vms if q in _sauber(v.get("name")).lower() or _sauber(v.get("name")).lower() in q), None)
        if hit:
            return hit
    return next((v for v in vms if "kontroll" in _sauber(v.get("name")).lower()), vms[0] if vms else None)
