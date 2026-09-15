"""Read-only: Oeffnungszeiten + Motiv-Buchbarkeit der Ruether-Praxis ansehen.

Nutzt kern/standort.py (Firestore-REST, Service-Account) — kein CF-Aufruf,
also kein PhoneCall-Datensatz.

Aufruf (im Container):
    python tools/_probe_ruether_standort.py
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
CLIENT = "AWdFeDldR81P3jmiq869"
LOC = "loc_d7gfcuss"


def decode(v):
    if not isinstance(v, dict):
        return v
    for k in ("stringValue", "booleanValue", "integerValue", "doubleValue",
              "timestampValue"):
        if k in v:
            return v[k]
    if "nullValue" in v:
        return None
    if "mapValue" in v:
        return {a: decode(b) for a, b in (v["mapValue"].get("fields") or {}).items()}
    if "arrayValue" in v:
        return [decode(x) for x in (v["arrayValue"].get("values") or [])]
    return v


def felder(doc: dict) -> dict:
    return {k: decode(v) for k, v in (doc.get("fields") or {}).items()}


TAGE = ("monday", "tuesday", "wednesday", "thursday", "friday",
        "saturday", "sunday")
DE = {"monday": "Montag", "tuesday": "Dienstag", "wednesday": "Mittwoch",
      "thursday": "Donnerstag", "friday": "Freitag", "saturday": "Samstag",
      "sunday": "Sonntag"}


def uhr(block) -> str:
    if not isinstance(block, dict):
        return "?"
    h = str(block.get("hour") or "0")
    m = str(block.get("minute") or "0")
    return f"{int(h):02d}:{int(m):02d}"


def main() -> None:
    p = json.loads(Path(FIREBASE_CREDENTIALS).read_text(encoding="utf-8"))["project_id"]
    kopf = {"Authorization": f"Bearer {anrufaudio._access_token(SCOPE)}"}
    doc = f"{BASE}/projects/{p}/databases/(default)/documents/clients/{CLIENT}/locations/{LOC}"

    with httpx.Client(timeout=30.0) as c:
        r = c.get(doc, headers=kopf)
        r.raise_for_status()
        f = felder(r.json())
        print(f"Standort: {f.get('name')!r}")
        print(f"  Strasse: {f.get('street')!r}  PLZ/Ort: {f.get('zipCode')!r} {f.get('city')!r}")
        print(f"  Telefon: {f.get('phoneNumber')!r}  Mail: {f.get('email')!r}")
        print(f"  Zeitzone: {f.get('timeZone')!r}")
        oh = f.get("openingHours") or {}
        print("\n-- Oeffnungszeiten (Standorteinstellungen) --")
        for t in TAGE:
            d = oh.get(t)
            if not isinstance(d, dict):
                print(f"  {DE[t]:<11} FEHLT")
                continue
            if not d.get("hasOpen"):
                print(f"  {DE[t]:<11} geschlossen")
                continue
            zeile = f"  {DE[t]:<11} {uhr((d.get('open') or {}).get('start'))}"
            zeile += f"-{uhr((d.get('open') or {}).get('end'))}"
            if d.get("hasPause"):
                zeile += (f"   Pause {uhr((d.get('pause') or {}).get('start'))}"
                          f"-{uhr((d.get('pause') or {}).get('end'))}")
            print(zeile)

        print("\n-- Besuchsgruende: telefonisch buchbar? --")
        r = c.get(f"{doc}/visitMotives", headers=kopf, params=[("pageSize", "200")])
        r.raise_for_status()
        docs = r.json().get("documents") or []
        ja, nein = [], []
        for d in docs:
            df = felder(d)
            name = str(df.get("name") or "")
            eintrag = f"{name} ({df.get('duration')} min)"
            (ja if df.get("allowOnlineBooking") else nein).append(eintrag)
        print(f"  BUCHBAR ({len(ja)}):")
        for x in sorted(ja):
            print(f"     + {x}")
        print(f"  NICHT buchbar ({len(nein)}) — Ben findet dafuer KEINE Zeiten:")
        for x in sorted(nein):
            print(f"     - {x}")

        print("\n-- Kalender --")
        r = c.get(f"{doc}/calendars", headers=kopf, params=[("pageSize", "100")])
        r.raise_for_status()
        for d in r.json().get("documents") or []:
            df = felder(d)
            print(f"  {d['name'].rsplit('/', 1)[-1]}  {df.get('name')!r} "
                  f"aktiv={df.get('enabled')} online={df.get('allowOnlineBooking')}")


if __name__ == "__main__":
    main()
