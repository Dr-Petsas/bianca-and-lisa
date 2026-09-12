"""Einen CallR-Datensatz inkl. Transkript lesen. PEEK_ID=..."""
from __future__ import annotations

import json
import os
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
    if "timestampValue" in v:
        return v["timestampValue"]
    if "arrayValue" in v:
        return [_val(x) for x in (v["arrayValue"].get("values") or [])]
    if "mapValue" in v:
        return {k: _val(v2) for k, v2 in (v["mapValue"].get("fields") or {}).items()}
    return v


def main() -> None:
    pid = (os.environ.get("PEEK_ID") or "").strip()
    if not pid:
        raise SystemExit("PEEK_ID fehlt")
    h = {"Authorization": f"Bearer {token()}"}
    url = (
        f"https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/(default)"
        f"/documents/clients/{CLIENT}/locations/{LOC}/phoneCalls/{pid}"
    )
    r = httpx.get(url, headers=h, timeout=20)
    r.raise_for_status()
    fields = {k: _val(v) for k, v in (r.json().get("fields") or {}).items()}
    print("id", pid)
    print("created", fields.get("createdAt"))
    print("status", fields.get("status"))
    print("caller", fields.get("callerPhoneNumber"),
          fields.get("callerFirstName"), fields.get("callerLastName"))
    print("dauer", fields.get("callDuration"), "audio", bool(fields.get("audioRecordingUrl")))
    print("summary", fields.get("summary") or "")
    tr = fields.get("transcript") or []
    print("tr_n", len(tr) if isinstance(tr, list) else tr)
    if isinstance(tr, list):
        for z in tr:
            if isinstance(z, dict):
                print(f"  [{z.get('role')}] {z.get('message')}")


if __name__ == "__main__":
    main()
