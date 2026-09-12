"""Letzte CallR-Datensaetze + Transkript (im Bianca-Container)."""
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
    if "doubleValue" in v:
        return float(v["doubleValue"])
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
    h = {"Authorization": f"Bearer {token()}", "Content-Type": "application/json"}
    parent = (
        f"projects/{PROJECT}/databases/(default)/documents/"
        f"clients/{CLIENT}/locations/{LOC}"
    )
    r = httpx.post(
        f"https://firestore.googleapis.com/v1/{parent}:runQuery",
        headers=h,
        json={"structuredQuery": {
            "from": [{"collectionId": "phoneCalls"}],
            "orderBy": [{"field": {"fieldPath": "createdAt"}, "direction": "DESCENDING"}],
            "limit": 20,
        }},
        timeout=30,
    )
    r.raise_for_status()
    for row in r.json():
        doc = row.get("document") or {}
        name = (doc.get("name") or "").rsplit("/", 1)[-1]
        fields = {k: _val(v) for k, v in (doc.get("fields") or {}).items()}
        tr = fields.get("transcript") or []
        print("===")
        print("id", name)
        print("created", fields.get("createdAt"))
        print("status", fields.get("status"))
        print("caller", fields.get("callerPhoneNumber"),
              fields.get("callerFirstName"), fields.get("callerLastName"))
        print("called", fields.get("calledNumber"))
        print("sid", fields.get("callSid"))
        print("dauer", fields.get("callDuration"), "audio", bool(fields.get("audioRecordingUrl")))
        print("summary", (fields.get("summary") or "")[:400])
        print("tr_n", len(tr) if isinstance(tr, list) else tr)
        if isinstance(tr, list):
            for z in tr:
                if not isinstance(z, dict):
                    print(" ", z)
                    continue
                print(f"  [{z.get('role')}] {z.get('message')}")


if __name__ == "__main__":
    main()
