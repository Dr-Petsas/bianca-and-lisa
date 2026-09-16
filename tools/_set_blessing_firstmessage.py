"""Setzt agents/8JoAXSHoBoHITzB20deb.firstMessage auf den aktuellen
Blessing-Wortlaut aus tenants/blessing.json (Quelle der Wahrheit fuer den
Wortlaut ist die Datei; die DB ist die Wahrheit fuer den LIVE-Anruf).

Nur EIN Feld (updateMask.fieldPaths=firstMessage). Sicherheitswache: Doc-ID,
clientId und Blessing-Bezug werden vor dem Schreiben geprueft. Read-only, wenn
--schreiben NICHT gesetzt ist.

Aufruf IM Container:
    python tools/_set_blessing_firstmessage.py            # nur anzeigen
    python tools/_set_blessing_firstmessage.py --schreiben # patchen
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from kern import anrufaudio  # noqa: E402
from kern.config import FIREBASE_CREDENTIALS  # noqa: E402

BASE = "https://firestore.googleapis.com/v1"
SCOPE = "https://www.googleapis.com/auth/datastore"
DOC_ID = "8JoAXSHoBoHITzB20deb"
CLIENT_ID = "UUJnPzoYPa4yYyzcaGlm"

neu = str(json.loads(Path("/app/tenants/blessing.json").read_text(
    encoding="utf-8"))["begruessungText"])
assert "digitalen Assistentin" in neu, f"Tenant-Wortlaut unerwartet: {neu!r}"

proj = json.loads(Path(FIREBASE_CREDENTIALS).read_text(
    encoding="utf-8"))["project_id"]
token = anrufaudio._access_token(SCOPE)
kopf = {"Authorization": f"Bearer {token}"}
doc_url = f"{BASE}/projects/{proj}/databases/(default)/documents/agents/{DOC_ID}"

with httpx.Client(timeout=30.0) as c:
    r = c.get(doc_url, headers=kopf)
    r.raise_for_status()
    fields = r.json().get("fields") or {}
    alt = (fields.get("firstMessage") or {}).get("stringValue") or ""
    cid = (fields.get("clientId") or {}).get("stringValue") or ""
    print(f"projekt={proj} doc=agents/{DOC_ID} clientId={cid!r}")
    print(f"ALT firstMessage: {alt!r}")
    print(f"NEU firstMessage: {neu!r}")

    assert cid == CLIENT_ID, f"clientId passt nicht ({cid!r}) - ABBRUCH"
    assert "Blessing" in alt, f"Kein Blessing-Bezug im ALT-Wert - ABBRUCH"

    if "--schreiben" not in sys.argv:
        print("\n(Read-only. Mit --schreiben patchen.)")
        raise SystemExit(0)

    if alt == neu:
        print("\nBereits gesetzt - kein Schreibvorgang noetig.")
        raise SystemExit(0)

    pr = c.patch(
        doc_url,
        headers=kopf,
        params=[("updateMask.fieldPaths", "firstMessage")],
        json={"fields": {"firstMessage": {"stringValue": neu}}},
    )
    pr.raise_for_status()
    nach = (pr.json().get("fields", {}).get("firstMessage", {})
            .get("stringValue") or "")
    print(f"\nGESCHRIEBEN. Read-back: {nach!r}")
    assert nach == neu, "Read-back weicht ab!"
    print("OK")
