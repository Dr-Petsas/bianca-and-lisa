from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from typing import Any

from kern.sitzung import merke_tool, merke_zug, oeffentlich as _oeffentlich  # noqa: F401 - geteilt mit Bianca
from lisa.config import DATA_DIR, DEV_PHONE
from lisa.patients import format_de_phone
from lisa.tenants import laden, motiv_von

_STORE: dict[str, dict[str, Any]] = {}
_LAST_PATH = DATA_DIR / "last_call.json"
_SESS_DIR = DATA_DIR / "sessions"


def neu(*, tenant_id: str, auftrag: str, patient: dict | None, past: list, upcoming: list) -> dict[str, Any]:
    tenant = laden(tenant_id)
    sid = secrets.token_hex(8)
    booking = {}
    if patient:
        nxt = (upcoming or [None])[0] if upcoming else None
        vm = motiv_von(tenant, "Kontrolluntersuchung")
        booking = {
            "patientId": patient.get("id") or "",
            "patientName": patient.get("name") or "",
            "firstName": patient.get("firstName") or "",
            "lastName": patient.get("lastName") or "",
            "calendarId": tenant.get("defaultCalendarId") or "",
            "calendarName": tenant.get("behandler") or "",
            "visitMotiveName": (vm or {}).get("name") or "Kontrolluntersuchung",
            "visitMotiveId": (vm or {}).get("id") or "",
            "appointmentId": (nxt or {}).get("id") if isinstance(nxt, dict) else "",
            "appointmentDate": (nxt or {}).get("date") or ((nxt or {}).get("iso") or "")[:10] if isinstance(nxt, dict) else "",
            "slotIso": (nxt or {}).get("iso") if isinstance(nxt, dict) else "",
            "phone": patient.get("phone") or "",
        }
    doc = {
        "id": sid,
        "tenant": tenant,
        "tenantId": tenant.get("_id"),
        "auftrag": auftrag,
        "patient": patient or {},
        "booking": booking,
        "past": past or [],
        "upcoming": upcoming or [],
        "devPhone": format_de_phone(DEV_PHONE),
        "messages": [],
        "tools": [],
        "zuege": [],
        "startedAt": datetime.now(timezone.utc).isoformat(),
    }
    _STORE[sid] = doc
    return doc


def _sichern(sit: dict[str, Any]) -> None:
    sid = sit.get("id")
    if not sid:
        return
    try:
        _SESS_DIR.mkdir(parents=True, exist_ok=True)
        roh = {k: v for k, v in sit.items() if k != "tenant"}
        (_SESS_DIR / f"{sid}.json").write_text(json.dumps(roh, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def holen(sid: str) -> dict[str, Any] | None:
    sid = (sid or "").strip()
    if not sid:
        return None
    hit = _STORE.get(sid)
    if hit:
        return hit
    pfad = _SESS_DIR / f"{sid}.json"
    try:
        roh = json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    roh["tenant"] = laden(roh.get("tenantId") or "")
    _STORE[sid] = roh
    return roh


def sichern(sit: dict[str, Any]) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _LAST_PATH.write_text(json.dumps(_oeffentlich(sit), ensure_ascii=False), encoding="utf-8")
        _sichern(sit)
    except OSError:
        pass


def last_call() -> dict[str, Any]:
    if _STORE:
        newest = max(_STORE.values(), key=lambda s: s.get("startedAt") or "")
        return _oeffentlich(newest)
    try:
        return json.loads(_LAST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
