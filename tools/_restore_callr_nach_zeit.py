"""Leere CallR-Zeilen nach Pourianmehr per Zeit+Nummer fuellen.

Nie vorhandene Transkripte ueberschreiben. Match nur wenn Mitschnitt
dieselbe Anrufernummer und Startzeit ±8 min hat.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from kern.config import FIREBASE_CREDENTIALS, PHONE_CALL_TOKEN, PHONE_CALL_URL

CLIENT = "MEe4ZQHEzOPzLcexyhdT"
LOC = "VjdvbRQHH8oTId4f0GiX"
PROJECT = "docgenda"
ROOT = Path("/app/.data/anrufe/bianca")
CANCELED = 9
INPROGRESS = 3
AB = datetime(2026, 9, 8, 8, 37, tzinfo=timezone.utc)
FENSTER_S = 8 * 60


def _b64url(b: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def token() -> str:
    sa = json.loads(Path(FIREBASE_CREDENTIALS).read_text(encoding="utf-8"))
    key = serialization.load_pem_private_key(sa["private_key"].encode(), password=None)
    now = int(time.time())
    kopf = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    claims = _b64url(json.dumps({
        "iss": sa["client_email"],
        "scope": "https://www.googleapis.com/auth/datastore",
        "aud": sa.get("token_uri") or "https://oauth2.googleapis.com/token",
        "iat": now, "exp": now + 3600,
    }).encode())
    sig = key.sign(f"{kopf}.{claims}".encode(), padding.PKCS1v15(), hashes.SHA256())
    jwt = f"{kopf}.{claims}.{_b64url(sig)}"
    r = httpx.post(
        sa.get("token_uri") or "https://oauth2.googleapis.com/token",
        data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
              "assertion": jwt},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _val(v):
    if not isinstance(v, dict):
        return v
    if "stringValue" in v:
        return v["stringValue"]
    if "integerValue" in v:
        return int(v["integerValue"])
    if "booleanValue" in v:
        return v["booleanValue"]
    if "timestampValue" in v:
        return v["timestampValue"]
    if "arrayValue" in v:
        return [_val(x) for x in (v["arrayValue"].get("values") or [])]
    if "mapValue" in v:
        return {k: _val(v2) for k, v2 in (v["mapValue"].get("fields") or {}).items()}
    if "nullValue" in v:
        return None
    return v


def _s(v) -> str:
    return " ".join(str(v or "").split()).strip()


def _dt(s: str):
    t = (s or "").strip()
    if not t:
        return None
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        return None


def _norm_phone(s: str) -> str:
    z = "".join(c for c in _s(s) if c.isdigit())
    if z.startswith("00"):
        z = z[2:]
    if z.startswith("0") and not z.startswith("00"):
        z = "49" + z[1:]
    return z


def _transkript(m: dict) -> tuple[list[dict], int]:
    out = []
    for z in m.get("zuege") or []:
        if not isinstance(z, dict):
            continue
        secs = int(round(float(z.get("offsetMs") or 0) / 1000.0))
        if _s(z.get("textIn")):
            out.append({"role": "user", "message": _s(z.get("textIn")),
                        "timeInCallSecs": secs})
        if _s(z.get("text")):
            out.append({"role": "agent", "message": _s(z.get("text")),
                        "timeInCallSecs": secs})
    dauer = int(round(float(m.get("dauerMs") or 0) / 1000.0))
    return out, dauer


def _anrufe() -> list[dict]:
    rows = []
    if not ROOT.is_dir():
        return rows
    for d in ROOT.iterdir():
        p = d / "anruf.json"
        if not p.is_file():
            continue
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        start = _dt(m.get("startedAt") or "")
        if not start or start < AB:
            continue
        m["_sid"] = d.name
        m["_start"] = start
        rows.append(m)
    return rows


def _caller_of(m: dict) -> str:
    an = m.get("anrufer") if isinstance(m.get("anrufer"), dict) else {}
    for k in ("telefon", "phone", "callerPhone"):
        n = _norm_phone(an.get(k) or m.get(k) or "")
        if n:
            return n
    return _norm_phone(m.get("callerPhone") or "")


def _match_zeit(fields: dict, anrufe: list[dict]) -> dict | None:
    pcid = _s(fields.get("id"))
    for m in anrufe:
        if pcid and _s(m.get("phoneCallId")) == pcid:
            return m
    phone = _norm_phone(fields.get("callerPhoneNumber") or "")
    created = _dt(fields.get("createdAt") or "")
    if not phone or not created:
        return None
    treffer = []
    for m in anrufe:
        if _caller_of(m) != phone:
            continue
        start = m.get("_start")
        if not start:
            continue
        delta = abs((start - created).total_seconds())
        if delta <= FENSTER_S:
            treffer.append((delta, m))
    if len(treffer) != 1:
        return None
    return treffer[0][1]


def _cf_post(pcid: str, transcript: list, dauer: int) -> bool:
    if not transcript or not PHONE_CALL_TOKEN:
        return False
    r = httpx.post(
        PHONE_CALL_URL,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {PHONE_CALL_TOKEN}",
            "x-api-key": PHONE_CALL_TOKEN,
        },
        json={
            "phase": "post",
            "phoneCallId": pcid,
            "clientId": CLIENT,
            "locationId": LOC,
            "transcript": transcript,
            "callDurationSecs": dauer,
            "endReason": "hangup",
        },
        timeout=30,
    )
    print("  post", pcid, r.status_code, r.text[:160])
    return 200 <= r.status_code < 300


def main() -> None:
    dry = os.environ.get("DRY") != "0"
    print("dry", dry)
    tok = token()
    h = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    parent_q = (
        f"projects/{PROJECT}/databases/(default)/documents/"
        f"clients/{CLIENT}/locations/{LOC}"
    )
    r = httpx.post(
        f"https://firestore.googleapis.com/v1/{parent_q}:runQuery",
        headers=h,
        json={"structuredQuery": {
            "from": [{"collectionId": "phoneCalls"}],
            "orderBy": [{"field": {"fieldPath": "createdAt"}, "direction": "DESCENDING"}],
            "limit": 40,
        }},
        timeout=30,
    )
    r.raise_for_status()
    anrufe = _anrufe()
    print("mitschnitte_seit_pourianmehr", len(anrufe))
    for m in anrufe:
        print("  sid", m["_sid"], m["_start"].isoformat()[:19],
              "pcid", m.get("phoneCallId") or "-",
              "name", m.get("patientName") or "-",
              "tel", _caller_of(m) or "-",
              "listen", sum(1 for z in (m.get("zuege") or [])
                            if isinstance(z, dict) and z.get("art") == "listen"))
    parent = (
        f"https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/(default)"
        f"/documents/clients/{CLIENT}/locations/{LOC}/phoneCalls"
    )
    filled = skipped = leer = canceled = 0
    for row in r.json():
        doc = row.get("document") or {}
        pid = (doc.get("name") or "").rsplit("/", 1)[-1]
        fields = {k: _val(v) for k, v in (doc.get("fields") or {}).items()}
        fields["id"] = pid
        created = _dt(fields.get("createdAt") or "")
        if not created or created < AB:
            continue
        tr = fields.get("transcript") or []
        n = len(tr) if isinstance(tr, list) else 0
        print("callr", pid, created.isoformat()[:19],
              "status", fields.get("status"),
              "caller", fields.get("callerPhoneNumber"),
              "name", fields.get("callerFirstName"), fields.get("callerLastName"),
              "tr", n)
        if isinstance(tr, list) and tr:
            skipped += 1
            continue
        leer += 1
        m = _match_zeit(fields, anrufe)
        if not m:
            print("  kein eindeutiger mitschnitt")
            if fields.get("status") == INPROGRESS:
                print("  setze canceled")
                if not dry:
                    patch = httpx.patch(
                        f"{parent}/{pid}",
                        params=[
                            ("updateMask.fieldPaths", "status"),
                            ("updateMask.fieldPaths", "endReason"),
                        ],
                        headers=h,
                        json={"fields": {
                            "status": {"integerValue": str(CANCELED)},
                            "endReason": {"stringValue": "canceled"},
                        }},
                        timeout=20,
                    )
                    print("  cancel", pid, patch.status_code)
                canceled += 1
            continue
        tr2, dauer = _transkript(m)
        print("  match", m.get("_sid"), "zuege", len(tr2), "dry", dry)
        if tr2 and not dry:
            if _cf_post(pid, tr2, dauer):
                filled += 1
        elif tr2:
            filled += 1
    print("filled", filled, "canceled", canceled, "skipped_has_tr", skipped, "leer", leer)


if __name__ == "__main__":
    main()
