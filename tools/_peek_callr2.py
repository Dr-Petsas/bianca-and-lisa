"""Leere CallR-Eintraege von heute voellig ausgeben."""
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
    "hlMnyGH5wvqJzC7JFENT",
    "PMkLTer3zQ6YgSgauyNZ",
    "VW85xL54s6JuIVf2049z",
    "Q2Rqmi2ds47CqS8R1ZRZ",
    "Z3B8ww6ZRP2ryx0lX5qM",
    "0DYWkRTDOmL5e7WhC2qH",
    "hK4yvZKx4wWN3lZdmJIt",
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


KEEP = (
    "status", "callerFirstName", "callerLastName", "callerPhone", "from",
    "to", "calledNumber", "patientId", "summary", "callDuration",
    "createdAt", "endedAt", "endReason", "agentId", "direction",
    "audioRecordingUrl", "transcript", "categories",
)


def main() -> None:
    tok = token()
    h = {"Authorization": f"Bearer {tok}"}
    parent = (
        f"https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/(default)"
        f"/documents/clients/{CLIENT}/locations/{LOC}/phoneCalls"
    )
    for pid in IDS:
        r = httpx.get(f"{parent}/{pid}", headers=h, timeout=20)
        print("===", pid, r.status_code)
        if r.status_code != 200:
            print(r.text[:200])
            continue
        fields = {k: _val(v) for k, v in (r.json().get("fields") or {}).items()}
        for k in KEEP:
            if k not in fields:
                continue
            v = fields[k]
            if k == "transcript":
                print(f"  {k}: n={len(v) if isinstance(v, list) else v}")
            elif k == "audioRecordingUrl":
                print(f"  {k}: {bool(v)} {(str(v)[:60] if v else '')}")
            else:
                print(f"  {k}: {v}")
        extra = [k for k in fields if k not in KEEP]
        print("  andere", extra)


if __name__ == "__main__":
    main()
