"""Kalender-Namen aus Firestore — die CF liefert nur einen Arzt je User.

getCalendarsForAgent mappt userName -> erste calendarId. Zimmer/Prophylaxe
am selben User (Thaler) kommen bei Bianca nie an. Dieses Modul liest die
Kalender-Sammlung direkt (gleicher Service-Account wie Anruf-Audio).

Zimmer 1-4 werden gemerged (Thaler-Raumkonzept), nie die
Behandlerliste umbauen. Notaus: KALENDER_DB=0. Nie werfend.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from kern.config import FIREBASE_CREDENTIALS
from kern.tenants import _sauber, ist_funktionskalender, zimmer_nr
from kern.zimmer_map import DEFAULT_MAP, THALER_CLIENT

# Thaler: CF-pre traegt nur Eva. Zimmer 1-4 kommen aus Firestore.

_SCOPE = "https://www.googleapis.com/auth/datastore"
_TOKEN_URI = "https://oauth2.googleapis.com/token"
_FS = "https://firestore.googleapis.com/v1"

_LOCK = threading.Lock()
_TOKEN: dict[str, Any] = {"wert": "", "bis": 0.0}
_CACHE: dict[str, tuple[float, dict[str, list[dict[str, str]]]]] = {}
_TTL_S = 300.0


def _s(v: Any) -> str:
    return str(v or "").strip()


def an() -> bool:
    if os.environ.get("KALENDER_DB", "1").strip().lower() in {"0", "false", "off", "no"}:
        return False
    return bool(FIREBASE_CREDENTIALS) and Path(FIREBASE_CREDENTIALS).is_file()


def _b64url(blob: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(blob).decode("ascii").rstrip("=")


def _access_token() -> str:
    with _LOCK:
        if _TOKEN["wert"] and _TOKEN["bis"] - time.time() > 120:
            return _TOKEN["wert"]
    import json
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    sa = json.loads(Path(FIREBASE_CREDENTIALS).read_text(encoding="utf-8"))
    token_uri = _s(sa.get("token_uri")) or _TOKEN_URI
    key = serialization.load_pem_private_key(
        sa["private_key"].encode("utf-8"), password=None)
    now = int(time.time())
    kopf = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode("utf-8"))
    claims = _b64url(json.dumps({
        "iss": sa["client_email"],
        "scope": _SCOPE,
        "aud": token_uri,
        "iat": now,
        "exp": now + 3600,
    }).encode("utf-8"))
    jwt = f"{kopf}.{claims}.{_b64url(key.sign(f'{kopf}.{claims}'.encode('ascii'), padding.PKCS1v15(), hashes.SHA256()))}"
    r = httpx.post(token_uri, data={
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": jwt,
    }, timeout=12)
    r.raise_for_status()
    d = r.json()
    with _LOCK:
        _TOKEN["wert"] = _s(d.get("access_token"))
        _TOKEN["bis"] = time.time() + float(d.get("expires_in") or 3600)
        return _TOKEN["wert"]


def _feld(fields: dict, name: str) -> Any:
    raw = (fields or {}).get(name) if isinstance(fields, dict) else None
    if not isinstance(raw, dict):
        return None
    if "stringValue" in raw:
        return raw["stringValue"]
    if "booleanValue" in raw:
        return bool(raw["booleanValue"])
    return None


def _liste(client_id: str, location_id: str) -> list[dict[str, str]]:
    import json
    sa = json.loads(Path(FIREBASE_CREDENTIALS).read_text(encoding="utf-8"))
    project = _s(sa.get("project_id"))
    if not project:
        return []
    url = (
        f"{_FS}/projects/{project}/databases/(default)/documents/"
        f"clients/{client_id}/locations/{location_id}/calendars"
    )
    r = httpx.get(
        url,
        params={"pageSize": 100},
        headers={"Authorization": f"Bearer {_access_token()}"},
        timeout=8.0,
    )
    if r.status_code < 200 or r.status_code >= 300:
        print(f"kalender-db fail http={r.status_code}", flush=True)
        return []
    docs = (r.json() or {}).get("documents") or []
    out: list[dict[str, str]] = []
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        pfad = _s(doc.get("name"))
        cid = pfad.rsplit("/", 1)[-1] if pfad else ""
        fields = doc.get("fields") if isinstance(doc.get("fields"), dict) else {}
        name = _sauber(_feld(fields, "name"))
        if not cid or not name:
            continue
        if _feld(fields, "isDeleted") or _feld(fields, "internal"):
            continue
        out.append({"id": cid, "name": name})
    return out


def _liste_rooms(client_id: str, location_id: str) -> list[dict[str, str]]:
    import json
    sa = json.loads(Path(FIREBASE_CREDENTIALS).read_text(encoding="utf-8"))
    project = _s(sa.get("project_id"))
    if not project:
        return []
    url = (
        f"{_FS}/projects/{project}/databases/(default)/documents/"
        f"clients/{client_id}/locations/{location_id}/rooms"
    )
    r = httpx.get(
        url,
        params={"pageSize": 50},
        headers={"Authorization": f"Bearer {_access_token()}"},
        timeout=8.0,
    )
    if r.status_code < 200 or r.status_code >= 300:
        print(f"kalender-db rooms fail http={r.status_code}", flush=True)
        return []
    out: list[dict[str, str]] = []
    for doc in (r.json() or {}).get("documents") or []:
        if not isinstance(doc, dict):
            continue
        pfad = _s(doc.get("name"))
        rid = pfad.rsplit("/", 1)[-1] if pfad else ""
        fields = doc.get("fields") if isinstance(doc.get("fields"), dict) else {}
        name = _sauber(_feld(fields, "name"))
        if not rid or not name or _feld(fields, "isDeleted"):
            continue
        out.append({"id": rid, "name": name})
    return out


def _stand(client_id: str, location_id: str) -> dict[str, list[dict[str, str]]]:
    cid, lid = _s(client_id), _s(location_id)
    leer: dict[str, list[dict[str, str]]] = {"calendars": [], "rooms": []}
    if not an() or not cid or not lid or cid != THALER_CLIENT:
        return leer
    key = f"{cid}|{lid}"
    now = time.time()
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and now - hit[0] < _TTL_S:
            return {"calendars": list(hit[1]["calendars"]), "rooms": list(hit[1]["rooms"])}
    try:
        cals = [
            c for c in _liste(cid, lid)
            if ist_funktionskalender(c) or zimmer_nr(c.get("name"))
        ]
        rooms = _liste_rooms(cid, lid)
    except Exception as e:
        print(f"kalender-db fail {type(e).__name__}: {e}", flush=True)
        return leer
    paket = {"calendars": cals, "rooms": rooms}
    with _LOCK:
        _CACHE[key] = (now, {
            "calendars": list(cals),
            "rooms": list(rooms),
        })
    print(
        "kalender-db thaler "
        + "cals=" + ",".join(c["name"] for c in cals)
        + " rooms=" + ",".join(r["name"] for r in rooms),
        flush=True,
    )
    return paket


def funktionsraeume(client_id: str, location_id: str) -> list[dict[str, str]]:
    """Prophylaxe-Kalender + Zimmer-Kalender (falls vorhanden)."""
    return list(_stand(client_id, location_id).get("calendars") or [])


def in_tenant_mergen(tenant: dict[str, Any]) -> None:
    """Prophylaxe-Kalender + Zi1-4-Raeume an den Thaler-Tenant haengen."""
    if not isinstance(tenant, dict):
        return
    if _s(tenant.get("clientId")) != THALER_CLIENT:
        return
    tenant.setdefault("zimmerMap", dict(DEFAULT_MAP))
    stand = _stand(_s(tenant.get("clientId")), _s(tenant.get("locationId")))
    cals = list(tenant.get("calendars") or [])
    have = {_s(c.get("id")) for c in cals if isinstance(c, dict)}
    for c in stand.get("calendars") or []:
        if _s(c.get("id")) and c["id"] not in have:
            cals.append({"id": c["id"], "name": c["name"]})
            have.add(c["id"])
    tenant["calendars"] = cals
    if stand.get("rooms"):
        tenant["rooms"] = list(stand["rooms"])
