"""Persistente Kampagnen: Liste, die Lisa abtelefoniert.

Chef-Seite (web/kampagne.html). Kein CampaignR, kein ElevenLabs.
Gespräche hängen über campaignId an GET /api/gespraeche.
"""

from __future__ import annotations

import json
import re
import secrets
import threading
from datetime import datetime, timezone
from typing import Any

from lisa.bewerbung import DEFAULT_AUFTRAG as _DEFAULT_AUFTRAG
from lisa.config import DATA_DIR

_DIR = DATA_DIR / "kampagnen"
_LOCK = threading.Lock()

_STATUS = ("offen", "laeuft", "erreicht", "kein_anschluss", "spaeter", "skip")


def _jetzt() -> str:
    return datetime.now(timezone.utc).isoformat()


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _tel(v: Any) -> str:
    return "".join(c for c in _s(v) if c.isdigit() or c == "+")


def _neu_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


def parse_liste(roh: str) -> list[dict[str, str]]:
    """CSV oder Zeilen 'Name;Telefon;Notiz' / 'Name, Telefon'."""
    out: list[dict[str, str]] = []
    gesehen: set[str] = set()
    for raw in (roh or "").splitlines():
        zeile = raw.strip()
        if not zeile or zeile.startswith("#"):
            continue
        if (
            re.match(r"^(name|praxis|empfaenger)\b", zeile, re.I)
            and ("," in zeile or ";" in zeile)
            and not re.search(r"\d{6,}", zeile)
        ):
            continue
        teile = [t.strip().strip('"') for t in re.split(r"[;\t,]", zeile) if t.strip()]
        if not teile:
            continue
        name, phone, notiz = "", "", ""
        if len(teile) == 1:
            nur = teile[0]
            ziff = "".join(c for c in nur if c.isdigit())
            if len(ziff) >= 6:
                phone = nur
                name = ziff
            else:
                name = nur
        else:
            a, b = teile[0], teile[1]
            za = "".join(c for c in a if c.isdigit())
            zb = "".join(c for c in b if c.isdigit())
            if len(zb) >= 6 or (len(zb) > len(za)):
                name, phone = a, b
            elif len(za) >= 6:
                phone, name = a, b
            else:
                name, phone = a, b
            notiz = teile[2] if len(teile) > 2 else ""
        phone = _tel(phone)
        name = _s(name) or phone
        if not phone:
            continue
        key = phone[-10:] if len(phone) >= 10 else phone
        if key in gesehen:
            continue
        gesehen.add(key)
        out.append({"name": name, "phone": phone, "notiz": _s(notiz)})
    return out


def _pfad(kid: str):
    return _DIR / f"{kid}.json"


def _lesen(kid: str) -> dict[str, Any] | None:
    p = _pfad(kid)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _schreiben(doc: dict[str, Any]) -> None:
    _DIR.mkdir(parents=True, exist_ok=True)
    kid = _s(doc.get("id"))
    if not kid:
        raise ValueError("kampagne ohne id")
    tmp = _DIR / f".{kid}.tmp"
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_pfad(kid))


def liste() -> list[dict[str, Any]]:
    _DIR.mkdir(parents=True, exist_ok=True)
    out: list[dict[str, Any]] = []
    with _LOCK:
        for p in sorted(_DIR.glob("k_*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            rec = d.get("empfaenger") or []
            out.append({
                "id": d.get("id"),
                "name": d.get("name") or "Kampagne",
                "auftrag": d.get("auftrag") or "",
                "tenant": d.get("tenant") or "",
                "createdAt": d.get("createdAt") or "",
                "updatedAt": d.get("updatedAt") or "",
                "anzahl": len(rec),
                "offen": sum(1 for e in rec if (e.get("status") or "offen") == "offen"),
                "erreicht": sum(1 for e in rec if e.get("status") == "erreicht"),
            })
    return out


def holen(kid: str) -> dict[str, Any] | None:
    with _LOCK:
        return _lesen(_s(kid))


def anlegen(*, name: str = "", auftrag: str = "", tenant: str = "",
            empfaenger_roh: str = "", empfaenger: list | None = None) -> dict[str, Any]:
    kid = _neu_id("k")
    rec = _empfaenger_neu(empfaenger_roh, empfaenger)
    doc = {
        "id": kid,
        "name": _s(name) or "Neue Kampagne",
        "auftrag": _s(auftrag) or _DEFAULT_AUFTRAG,
        "tenant": _s(tenant),
        "createdAt": _jetzt(),
        "updatedAt": _jetzt(),
        "empfaenger": rec,
    }
    with _LOCK:
        _schreiben(doc)
    return doc


def speichern(kid: str, *, name: str | None = None, auftrag: str | None = None,
              tenant: str | None = None) -> dict[str, Any] | None:
    with _LOCK:
        doc = _lesen(_s(kid))
        if not doc:
            return None
        if name is not None:
            doc["name"] = _s(name) or doc.get("name")
        if auftrag is not None:
            doc["auftrag"] = _s(auftrag) or doc.get("auftrag")
        if tenant is not None:
            doc["tenant"] = _s(tenant)
        doc["updatedAt"] = _jetzt()
        _schreiben(doc)
        return doc


def empfaenger_dazu(kid: str, *, roh: str = "", zeilen: list | None = None) -> dict[str, Any] | None:
    neu = _empfaenger_neu(roh, zeilen)
    with _LOCK:
        doc = _lesen(_s(kid))
        if not doc:
            return None
        da = {(_s(e.get("phone"))[-10:] if len(_s(e.get("phone"))) >= 10 else _s(e.get("phone")))
              for e in (doc.get("empfaenger") or [])}
        for e in neu:
            key = e["phone"][-10:] if len(e["phone"]) >= 10 else e["phone"]
            if key in da:
                continue
            da.add(key)
            doc.setdefault("empfaenger", []).append(e)
        doc["updatedAt"] = _jetzt()
        _schreiben(doc)
        return doc


def empfaenger_weg(kid: str, eid: str) -> dict[str, Any] | None:
    with _LOCK:
        doc = _lesen(_s(kid))
        if not doc:
            return None
        doc["empfaenger"] = [
            e for e in (doc.get("empfaenger") or []) if _s(e.get("id")) != _s(eid)
        ]
        doc["updatedAt"] = _jetzt()
        _schreiben(doc)
        return doc


def markieren(kid: str, eid: str, *, status: str = "", session_id: str = "") -> dict[str, Any] | None:
    st = _s(status)
    if st and st not in _STATUS:
        return None
    with _LOCK:
        doc = _lesen(_s(kid))
        if not doc:
            return None
        hit = None
        for e in doc.get("empfaenger") or []:
            if _s(e.get("id")) == _s(eid):
                hit = e
                break
        if not hit:
            return None
        if st:
            hit["status"] = st
        if session_id:
            hit["sessionId"] = _s(session_id)
            hit["startedAt"] = hit.get("startedAt") or _jetzt()
        if st == "laeuft":
            hit["startedAt"] = _jetzt()
        doc["updatedAt"] = _jetzt()
        _schreiben(doc)
        return doc


def naechste_offen(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if not doc:
        return None
    for e in doc.get("empfaenger") or []:
        if (e.get("status") or "offen") == "offen":
            return e
    return None


def _empfaenger_neu(roh: str, zeilen: list | None) -> list[dict[str, Any]]:
    rows: list[dict[str, str]] = []
    if _s(roh):
        rows.extend(parse_liste(roh))
    for item in zeilen or []:
        if not isinstance(item, dict):
            continue
        phone = _tel(item.get("phone") or item.get("telefon") or item.get("nummer"))
        name = _s(item.get("name") or item.get("praxis") or phone)
        if not phone:
            continue
        rows.append({
            "name": name,
            "phone": phone,
            "notiz": _s(item.get("notiz") or item.get("arzt") or item.get("note")),
        })
    out: list[dict[str, Any]] = []
    gesehen: set[str] = set()
    for r in rows:
        key = r["phone"][-10:] if len(r["phone"]) >= 10 else r["phone"]
        if key in gesehen:
            continue
        gesehen.add(key)
        out.append({
            "id": _neu_id("e"),
            "name": r["name"],
            "phone": r["phone"],
            "notiz": r["notiz"],
            "status": "offen",
            "sessionId": "",
            "startedAt": "",
        })
    return out
