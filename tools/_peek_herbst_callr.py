"""CallR MedDent: Herbst / Narval / letzte Outbound (im Bianca-Container)."""
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
NEEDLE = ("herbst", "narval", "schiene", "patrik", "patrick")


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


def _blob(fields: dict) -> str:
    teile = [
        str(fields.get("callerFirstName") or ""),
        str(fields.get("callerLastName") or ""),
        str(fields.get("summary") or ""),
        str(fields.get("callerPhoneNumber") or ""),
        str(fields.get("calledNumber") or ""),
        str(fields.get("direction") or ""),
        str(fields.get("status") or ""),
    ]
    tr = fields.get("transcript") or []
    if isinstance(tr, list):
        for z in tr:
            if isinstance(z, dict):
                teile.append(str(z.get("message") or ""))
            else:
                teile.append(str(z))
    return " ".join(teile).lower()


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
            "limit": 80,
        }},
        timeout=40,
    )
    r.raise_for_status()
    hits = []
    last_out = []
    print("=== letzte 25 CallR ===")
    n = 0
    for row in r.json():
        doc = row.get("document") or {}
        name = (doc.get("name") or "").rsplit("/", 1)[-1]
        fields = {k: _val(v) for k, v in (doc.get("fields") or {}).items()}
        blob = _blob(fields)
        n += 1
        if n <= 25:
            print(
                n,
                (fields.get("createdAt") or "")[:19],
                fields.get("direction") or "-",
                fields.get("status") or "-",
                fields.get("callerFirstName"),
                fields.get("callerLastName"),
                "from", fields.get("callerPhoneNumber"),
                "to", fields.get("calledNumber"),
                "sid", (fields.get("callSid") or "")[:16],
            )
        if str(fields.get("direction") or "").lower() == "outbound":
            last_out.append((name, fields))
        if any(x in blob for x in NEEDLE):
            hits.append((name, fields))
    print(f"hits_herbst={len(hits)} outbound_in_80={len(last_out)}")
    for name, fields in hits[:8]:
        print("=== HIT", name)
        print("created", fields.get("createdAt"))
        print("status", fields.get("status"), "dir", fields.get("direction"))
        print("caller", fields.get("callerPhoneNumber"),
              fields.get("callerFirstName"), fields.get("callerLastName"))
        print("called", fields.get("calledNumber"))
        print("sid", fields.get("callSid"))
        print("summary", (fields.get("summary") or "")[:500])
        tr = fields.get("transcript") or []
        if isinstance(tr, list):
            for z in tr:
                if not isinstance(z, dict):
                    print(" ", z)
                    continue
                print(f"  [{z.get('role')}] {z.get('message')}")
    print("=== letzte outbound ===")
    for name, fields in last_out[:8]:
        print(
            (fields.get("createdAt") or "")[:19],
            name,
            fields.get("status"),
            fields.get("callerFirstName"),
            fields.get("callerLastName"),
            "to", fields.get("calledNumber"),
            "from", fields.get("callerPhoneNumber"),
            "sid", fields.get("callSid"),
            "sum", (fields.get("summary") or "")[:180],
        )


if __name__ == "__main__":
    main()
