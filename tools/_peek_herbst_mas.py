"""MAS-Kontext + CallR-Patient zu Herbst (im Bianca-Container)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from kern.config import FIREBASE_CREDENTIALS, MAS_CLIENT_ID, MAS_TOKEN, MAS_URL

PHONE = "+491777074403"
NAME = "Patrick Herbst"
CLIENT = "MEe4ZQHEzOPzLcexyhdT"
LOC = "VjdvbRQHH8oTId4f0GiX"
PROJECT = "docgenda"


def _b64url(b: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def fb_token() -> str:
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


def mas_headers() -> dict:
    h = {"X-Client-Id": MAS_CLIENT_ID or CLIENT}
    if MAS_TOKEN:
        h["X-Service-Token"] = MAS_TOKEN
    return h


def main() -> None:
    print("MAS_URL", MAS_URL)
    print("MAS_CLIENT", MAS_CLIENT_ID)
    print("MAS_GEDAECHTNIS", os.environ.get("MAS_GEDAECHTNIS"))
    h = mas_headers()
    for label, url, params in (
        ("caller-context", f"{MAS_URL}/brain/caller-context", {"phone": PHONE}),
        ("karteikarte", f"{MAS_URL}/brain/karteikarte", {"name": NAME, "sinceDays": 90}),
        ("karteikarte2", f"{MAS_URL}/brain/karteikarte", {"name": "Herbst", "sinceDays": 90}),
        ("search", f"{MAS_URL}/brain/search",
         {"q": "Herbst", "kind": "event", "sinceDays": 30, "limit": 15}),
        ("search-phone", f"{MAS_URL}/brain/search",
         {"q": "01777074403", "kind": "event", "sinceDays": 30, "limit": 15}),
        ("search-narval", f"{MAS_URL}/brain/search",
         {"q": "Narval", "kind": "event", "sinceDays": 30, "limit": 15}),
    ):
        try:
            r = httpx.get(url, params=params, headers=h, timeout=20)
            print(f"\n=== {label} {r.status_code} ===")
            print(json.dumps(r.json(), ensure_ascii=False)[:2500])
        except Exception as e:
            print(f"\n=== {label} FAIL {e}")

    # Patient in Firestore
    tok = fb_token()
    fh = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    parent = f"projects/{PROJECT}/databases/(default)/documents/clients/{CLIENT}"
    print("\n=== patients query Herbst ===")
    r = httpx.post(
        f"https://firestore.googleapis.com/v1/{parent}:runQuery",
        headers=fh,
        json={"structuredQuery": {
            "from": [{"collectionId": "patients"}],
            "where": {"fieldFilter": {
                "field": {"fieldPath": "lastName"},
                "op": "EQUAL",
                "value": {"stringValue": "Herbst"},
            }},
            "limit": 10,
        }},
        timeout=30,
    )
    print("status", r.status_code)
    for row in r.json() if r.status_code == 200 else []:
        doc = row.get("document") or {}
        pid = (doc.get("name") or "").rsplit("/", 1)[-1]
        fields = {k: _val(v) for k, v in (doc.get("fields") or {}).items()}
        print("patient", pid, fields.get("firstName"), fields.get("lastName"),
              "mobile", fields.get("mobilePhoneNumber"),
              "phone", fields.get("phoneNumber"),
              "notes", str(fields.get("notes") or fields.get("note") or "")[:200])
        keys = sorted(fields.keys())
        print("  keys", [k for k in keys if "note" in k.lower() or "phone" in k.lower()
                          or "comment" in k.lower() or "thema" in k.lower()][:30])


if __name__ == "__main__":
    main()
