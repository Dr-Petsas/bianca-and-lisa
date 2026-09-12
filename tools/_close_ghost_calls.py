"""Leere inProgress-CallR-Geister (Smoke/DID-Probe) auf canceled setzen."""
from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from kern.config import FIREBASE_CREDENTIALS

CLIENT = "MEe4ZQHEzOPzLcexyhdT"
LOC = "VjdvbRQHH8oTId4f0GiX"
PROJECT = "docgenda"
CANCELED = 9


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


def main() -> None:
    tok = token()
    h = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    parent_q = (
        f"projects/{PROJECT}/databases/(default)/documents/"
        f"clients/{CLIENT}/locations/{LOC}"
    )
    parent = (
        f"https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/(default)"
        f"/documents/clients/{CLIENT}/locations/{LOC}/phoneCalls"
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
    n = 0
    for row in r.json():
        doc = row.get("document") or {}
        pid = (doc.get("name") or "").rsplit("/", 1)[-1]
        fields = {k: _val(v) for k, v in (doc.get("fields") or {}).items()}
        phone = fields.get("callerPhoneNumber")
        status = fields.get("status")
        tr = fields.get("transcript") or []
        sid = str(fields.get("callSid") or "")
        if status != 3 or phone != "anonymous":
            continue
        if isinstance(tr, list) and tr:
            print("skip-has-tr", pid)
            continue
        if not sid.startswith("bianca-"):
            print("skip-sid", pid, sid)
            continue
        patch = httpx.patch(
            f"{parent}/{pid}",
            params=[
                ("updateMask.fieldPaths", "status"),
                ("updateMask.fieldPaths", "summary"),
                ("updateMask.fieldPaths", "endReason"),
            ],
            headers=h,
            json={"fields": {
                "status": {"integerValue": str(CANCELED)},
                "summary": {"stringValue": "Kein Gespräch — Leitungsprobe, kein Anrufer."},
                "endReason": {"stringValue": "canceled"},
            }},
            timeout=20,
        )
        n += 1
        print("close", pid, patch.status_code, fields.get("createdAt"), fields.get("calledNumber"))
        if patch.status_code >= 300:
            print(patch.text[:200])
    print("closed", n)


if __name__ == "__main__":
    main()
