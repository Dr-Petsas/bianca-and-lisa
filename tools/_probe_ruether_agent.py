"""Read-only: Agent-Datensatz zu einer Telefonnummer in Firestore nachsehen.

Kein Cloud-Function-Aufruf (die pre-Phase wuerde einen PhoneCall-Datensatz
anlegen) — nur Firestore-REST mit dem Service-Account, wie kern/standort.py.

Aufruf (im Container):
    python tools/_probe_ruether_agent.py +4921154244160
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


def projekt() -> str:
    daten = json.loads(Path(FIREBASE_CREDENTIALS).read_text(encoding="utf-8"))
    return str(daten.get("project_id") or "")


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


def main() -> None:
    gesucht = sys.argv[1] if len(sys.argv) > 1 else "+4921154244160"
    ziffern = "".join(c for c in gesucht if c.isdigit())[-6:]
    token = anrufaudio._access_token(SCOPE)
    kopf = {"Authorization": f"Bearer {token}"}
    p = projekt()
    print(f"projekt={p} gesucht={gesucht!r} (Endziffern {ziffern})\n")

    with httpx.Client(timeout=30.0) as c:
        # 1) Alle Agenten listen (Maske: nur die Kennfelder) und selbst filtern.
        treffer = []
        alle = 0
        seite = ""
        while True:
            params = [("pageSize", "300")]
            for f in ("phoneNumber", "name", "direction", "enabled",
                      "clientId", "locationId"):
                params.append(("mask.fieldPaths", f))
            if seite:
                params.append(("pageToken", seite))
            r = c.get(f"{BASE}/projects/{p}/databases/(default)/documents/agents",
                      headers=kopf, params=params)
            r.raise_for_status()
            daten = r.json()
            for doc in daten.get("documents") or []:
                alle += 1
                f = felder(doc)
                nummer = "".join(ch for ch in str(f.get("phoneNumber") or "")
                                 if ch.isdigit())
                if ziffern and nummer.endswith(ziffern):
                    treffer.append((doc.get("name") or "", f))
            seite = daten.get("nextPageToken") or ""
            if not seite:
                break
        print(f"agents-Sammlung: {alle} Datensaetze, {len(treffer)} mit passender Nummer")

        for pfad, f in treffer:
            doc_id = pfad.rsplit("/", 1)[-1]
            print(f"\n=== agents/{doc_id} ===")
            r = c.get(f"{BASE}/{pfad}", headers=kopf)
            r.raise_for_status()
            voll = felder(r.json())
            kurz = {}
            for k in ("name", "phoneNumber", "direction", "enabled", "clientId",
                      "locationId", "voiceId", "voiceName", "mainLanguage",
                      "firstMessage", "keywords", "visitMotiveId",
                      "callForwardingToolEnabled", "createAppointmentToolEnabled",
                      "cancelAppointmentToolEnabled",
                      "postponeAppointmentToolEnabled", "temperature",
                      "fachgebiet", "specialty"):
                if k in voll:
                    kurz[k] = voll[k]
            print(json.dumps(kurz, ensure_ascii=False, indent=2))
            print("-- Prompt-Felder (Laenge in Zeichen) --")
            for k in ("rolePrompt", "tasksPrompt", "specialFeaturesPrompt",
                      "locationPrompt", "patientsPrompt", "appointmentPrompt",
                      "referrerPrompt", "mandatoryPrompt",
                      "miscellaneousPrompt", "systemPrompt"):
                v = str(voll.get(k) or "")
                if v:
                    print(f"  {k}: {len(v)} Zeichen | {v[:120]!r}")
                else:
                    print(f"  {k}: LEER")
            wl = voll.get("callForwardings")
            print(f"  callForwardings: {wl!r}")
            cid, lid = str(voll.get("clientId") or ""), str(voll.get("locationId") or "")
            if cid:
                r2 = c.get(f"{BASE}/projects/{p}/databases/(default)/documents/clients/{cid}",
                           headers=kopf, params=[("mask.fieldPaths", "name")])
                if r2.status_code == 200:
                    print(f"  client: {felder(r2.json()).get('name')!r}")
            if cid and lid:
                r3 = c.get(
                    f"{BASE}/projects/{p}/databases/(default)/documents/"
                    f"clients/{cid}/locations/{lid}",
                    headers=kopf,
                )
                if r3.status_code == 200:
                    lf = felder(r3.json())
                    print(f"  location: {lf.get('name')!r} "
                          f"strasse={lf.get('street')!r} ort={lf.get('city')!r}")
                    print(f"  openingHours: {json.dumps(lf.get('openingHours'), ensure_ascii=False)[:400]}")
                # Kalender + Besuchsgruende der Praxis
                for sub in ("calendars", "visitMotives"):
                    r4 = c.get(
                        f"{BASE}/projects/{p}/databases/(default)/documents/"
                        f"clients/{cid}/locations/{lid}/{sub}",
                        headers=kopf, params=[("pageSize", "100")],
                    )
                    if r4.status_code != 200:
                        print(f"  {sub}: HTTP {r4.status_code}")
                        continue
                    docs = r4.json().get("documents") or []
                    print(f"  {sub}: {len(docs)}")
                    for d in docs[:40]:
                        df = felder(d)
                        print(f"     - {d['name'].rsplit('/', 1)[-1]}  "
                              f"{df.get('name')!r} "
                              f"dauer={df.get('duration')} "
                              f"online={df.get('allowOnlineBooking')}")


if __name__ == "__main__":
    main()
