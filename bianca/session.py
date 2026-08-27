"""Biancas Sitzungs-Ablage — eigener Store und eigene Dateien neben Lisa.

Ein eingehender Anruf beginnt anonym: kein Patient, kein Auftrag. Alles, was
Bianca über den Anrufer erfährt, sammelt das Gehirn (sit["sammler"]) und
spiegelt es in sit["patient"] / sit["booking"], sobald es fest ist.
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from typing import Any

from kern.config import DATA_DIR
from kern.sitzung import merke_tool, merke_zug, oeffentlich  # noqa: F401 - geteilt mit Lisa
from kern.tenants import laden

_STORE: dict[str, dict[str, Any]] = {}
_LAST_PATH = DATA_DIR / "bianca_last_call.json"
_SESS_DIR = DATA_DIR / "bianca_sessions"


def neu(*, tenant_id: str) -> dict[str, Any]:
    tenant = laden(tenant_id)
    sid = secrets.token_hex(8)
    doc = {
        "id": sid,
        "stimme": "Bianca",
        "tenant": tenant,
        "tenantId": tenant.get("_id"),
        "auftrag": "Eingehender Anruf: Terminwunsch aufnehmen und buchen.",
        "patient": {},
        "booking": {},
        "past": [],
        "upcoming": [],
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
    except (OSError, TypeError):
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


def _mit_sammler(sit: dict[str, Any]) -> dict[str, Any]:
    out = oeffentlich(sit)
    s = sit.get("sammler") or {}
    out["sammler"] = {
        "vorname": s.get("vorname") or "",
        "nachname": s.get("nachname") or "",
        "buchstabiert": bool(s.get("buchstabiert")),
        "grund": s.get("grund") or "",
        "telefon": s.get("telefon") or "",
        "warSchonMal": s.get("warSchonMal"),
        "arzt": (s.get("arzt") or {}).get("calendarName") or (s.get("arzt") or {}).get("typ") or "",
        "phase": s.get("phase") or "",
    }
    return out


def merke_zug_sichern(sit: dict[str, Any], **zug: Any) -> None:
    merke_zug(sit, **zug)


def sichern(sit: dict[str, Any]) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _LAST_PATH.write_text(json.dumps(_mit_sammler(sit), ensure_ascii=False), encoding="utf-8")
        _sichern(sit)
    except OSError:
        pass


def last_call() -> dict[str, Any]:
    if _STORE:
        newest = max(_STORE.values(), key=lambda s: s.get("startedAt") or "")
        return _mit_sammler(newest)
    try:
        return json.loads(_LAST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
