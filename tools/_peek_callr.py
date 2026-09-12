"""CallR-PhoneCalls aus Firestore lesen (im Bianca-Container)."""
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
IDS = [
    "5WPPaqu2qrZxjpkMWSPv",
    "8VIe3PaIpB1rl2h0EKNS",
    "yxQS2b7voUschMDHHbbE",
]
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
        "iat": now,
        "exp": now + 3600,
    }).encode())
    sig = key.sign(f"{kopf}.{claims}".encode(), padding.PKCS1v15(), hashes.SHA256())
    jwt = f"{kopf}.{claims}.{_b64url(sig)}"
    r = httpx.post(sa.get("token_uri") or "https://oauth2.googleapis.com/token", data={
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": jwt,
    }, timeout=20)
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
        return v["doubleValue"]
    if "booleanValue" in v:
        return v["booleanValue"]
    if "timestampValue" in v:
        return v["timestampValue"]
    if "arrayValue" in v:
        return [_val(x) for x in (v["arrayValue"].get("values") or [])]
    if "mapValue" in v:
        return {k: _val(x) for k, x in (v["mapValue"].get("fields") or {}).items()}
    if "nullValue" in v:
        return None
    return v


def main() -> None:
    tok = token()
    h = {"Authorization": f"Bearer {tok}"}
    base = f"https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/(default)/documents"
    parent = f"{base}/clients/{CLIENT}/locations/{LOC}/phoneCalls"
    for pid in IDS:
        r = httpx.get(f"{parent}/{pid}", headers=h, timeout=20)
        print("===", pid, r.status_code)
        if r.status_code != 200:
            print(r.text[:300])
            continue
        fields = {k: _val(v) for k, v in (r.json().get("fields") or {}).items()}
        tr = fields.get("transcript") or []
        print("status", fields.get("status"))
        print("name", fields.get("callerFirstName"), fields.get("callerLastName"))
        print("phone", fields.get("callerPhone") or fields.get("from"))
        print("created", fields.get("createdAt"))
        print("duration", fields.get("callDuration"))
        print("summary", (fields.get("summary") or "")[:180])
        print("audio", bool(fields.get("audioRecordingUrl")))
        print("transcript_n", len(tr) if isinstance(tr, list) else type(tr))
        if isinstance(tr, list):
            for item in tr[:12]:
                if isinstance(item, dict):
                    print(" ", item.get("role"), (item.get("message") or "")[:120])

    # Neueste 8 Calls (createdAt desc) via runQuery
    body = {
        "structuredQuery": {
            "from": [{"collectionId": "phoneCalls"}],
            "orderBy": [{"field": {"fieldPath": "createdAt"}, "direction": "DESCENDING"}],
            "limit": 8,
        }
    }
    q = httpx.post(
        f"{base}/clients/{CLIENT}/locations/{LOC}:runQuery",
        headers=h, json=body, timeout=30,
    )
    print("=== latest query", q.status_code)
    if q.status_code != 200:
        print(q.text[:400])
        return
    for row in q.json():
        doc = row.get("document") or {}
        name = (doc.get("name") or "").split("/")[-1]
        fields = {k: _val(v) for k, v in (doc.get("fields") or {}).items()}
        tr = fields.get("transcript") or []
        n = len(tr) if isinstance(tr, list) else 0
        print(
            fields.get("createdAt"), name,
            fields.get("status"),
            (fields.get("callerLastName") or ""),
            "tr", n,
            "audio", bool(fields.get("audioRecordingUrl")),
        )


if __name__ == "__main__":
    main()
