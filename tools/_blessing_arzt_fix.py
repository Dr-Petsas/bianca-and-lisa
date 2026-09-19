"""Mitarbeiter-Dokumente fuer verwaiste Blessing-Kalender anlegen.

Fuer jeden angegebenen Kalender:
  1) Kalender lesen -> userId, name, abbreviation, avatarUrl, openingHours, allowOnline
  2) pruefen, ob clients/<cid>/users/<userId> existiert
  3) wenn NICHT: ein Mitarbeiter-Dokument feldgleich zur Praxis-Vorlage anlegen
     (an GENAU der userId, auf die der Kalender schon zeigt -> Dropdown passt).

Sicherheit:
  - Ohne --schreiben nur Trockenlauf (zeigt den geplanten Datensatz).
  - Existiert das User-Dokument schon, wird NICHTS ueberschrieben (skip).
  - Backup/Plan wird als JSON nach .data/_blessing_arzt_fix_plan.json geschrieben.

NUR Neuanlegen fehlender Mitarbeiter. Kein Loeschen, kein Ueberschreiben.
"""
from __future__ import annotations

import argparse
import json
import os

import httpx

from kern import anrufaudio, standort

CID = "UUJnPzoYPa4yYyzcaGlm"
LID = "dlxNwKLaA5VMEWQ5AjsL"
LOCNAME = "Reutlingen"
SCOPE = "https://www.googleapis.com/auth/datastore"
BASE = "https://firestore.googleapis.com/v1"

# Kalender, deren Mitarbeiter fehlt (aus der Fehler-Analyse)
KALENDER = [
    "TphQRh53x8SToBSa8DdB",  # Dr.Ralf   (online, Hauptursache)
    "thJWFH9ikCX92FMTeMmQ",  # Maziers   (intern)
    "deDUTuOCXG37pmT8wRdk",  # Arzthelferin (intern)
]


def _pfad(rest: str) -> str:
    return f"projects/{standort._projekt()}/databases/(default)/documents/{rest}"


def _get(rest: str):
    token = anrufaudio._access_token(SCOPE)
    r = httpx.get(f"{BASE}/{_pfad(rest)}", headers={"Authorization": f"Bearer {token}"}, timeout=15.0)
    return r.status_code, (r.json() if r.status_code == 200 else r.text)


def _patch(rest: str, fields: dict):
    token = anrufaudio._access_token(SCOPE)
    r = httpx.patch(
        f"{BASE}/{_pfad(rest)}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"fields": fields},
        timeout=20.0,
    )
    return r.status_code, (r.json() if r.status_code == 200 else r.text)


def _felder(doc):
    f = (doc or {}).get("fields") if isinstance(doc, dict) else None
    if not isinstance(f, dict):
        return {}
    return {k: standort._decode(v) for k, v in f.items()}


def _enc(v):
    """Python-Wert -> Firestore-typisierter Wert (bool VOR int pruefen!)."""
    if v is None:
        return {"nullValue": None}
    if isinstance(v, bool):
        return {"booleanValue": v}
    if isinstance(v, int):
        return {"integerValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    if isinstance(v, str):
        return {"stringValue": v}
    if isinstance(v, list):
        return {"arrayValue": {"values": [_enc(x) for x in v]}}
    if isinstance(v, dict):
        return {"mapValue": {"fields": {k: _enc(x) for k, x in v.items()}}}
    return {"stringValue": str(v)}


def _mitarbeiter_bauen(calid: str, cal: dict, uid: str) -> dict:
    name = str(cal.get("name") or "").strip()
    # "Dr.Ralf" / "Dr. Ralf" -> Titel "Dr.", Nachname "Ralf"; sonst Name = Nachname
    titel = ""
    nachname = name
    low = name.lower()
    if low.startswith("dr"):
        titel = "Dr."
        rest = name[2:].lstrip(". ").strip()
        nachname = rest or name
    rolle = "assistant" if ("helfer" in low or "assisten" in low) else "doctor"
    doc = {
        "id": uid,
        "clientId": CID,
        "locationId": LID,
        "locationName": LOCNAME,
        "role": rolle,
        "email": "",
        "firstName": "",
        "lastName": nachname,
        "gender": "f",
        "title": titel,
        "abbreviation": str(cal.get("abbreviation") or ""),
        "languages": [],
        "isEnabled": True,
        "profile": "",
        "calendarIds": [calid],
        "allowOnlineAppointments": bool(cal.get("allowOnlineAppointments")),
        "isAdmin": False,
        "avatarUrl": str(cal.get("avatarUrl") or ""),
        "signature": "",
        "roomIds": [],
        "showTour": False,
        "hidden": False,
    }
    oh = cal.get("openingHours")
    if isinstance(oh, dict) and oh:
        doc["openingHours"] = oh
    return doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--schreiben", action="store_true", help="wirklich schreiben")
    args = ap.parse_args()

    plan = []
    for calid in KALENDER:
        st, caldoc = _get(f"clients/{CID}/locations/{LID}/calendars/{calid}")
        if st != 200:
            print(f"[{calid}] Kalender nicht lesbar (http {st}) -> skip")
            continue
        cal = _felder(caldoc)
        uid = str(cal.get("userId") or "")
        if not uid:
            print(f"[{calid}] kein userId am Kalender -> skip")
            continue
        us, _ = _get(f"clients/{CID}/users/{uid}")
        neu = _mitarbeiter_bauen(calid, cal, uid)
        eintrag = {"calendarId": calid, "userId": uid, "userExists": us == 200, "doc": neu}
        plan.append(eintrag)
        print("=" * 66)
        print(f"Kalender {calid}  name={cal.get('name')!r}  userId={uid}")
        print(f"  User existiert? {'JA (skip)' if us == 200 else 'NEIN -> anlegen'}")
        print(f"  role={neu['role']} titel={neu['title']!r} nachname={neu['lastName']!r} "
              f"online={neu['allowOnlineAppointments']} foto={'ja' if neu['avatarUrl'] else 'nein'} "
              f"sprechzeiten={'ja' if 'openingHours' in neu else 'nein'}")

        if args.schreiben and us != 200:
            fields = {k: _enc(v) for k, v in neu.items()}
            ws, wr = _patch(f"clients/{CID}/users/{uid}", fields)
            print(f"  SCHREIBEN -> http {ws}")
            if ws != 200:
                print(f"    FEHLER: {str(wr)[:300]}")
            else:
                # Gegenlesen
                vs, vdoc = _get(f"clients/{CID}/users/{uid}")
                vf = _felder(vdoc)
                print(f"    gegengelesen: role={vf.get('role')} name="
                      f"{vf.get('firstName')} {vf.get('lastName')} title={vf.get('title')!r}")

    # Plan/Backup ablegen
    os.makedirs(".data", exist_ok=True)
    with open(os.path.join(".data", "_blessing_arzt_fix_plan.json"), "w", encoding="utf-8") as fh:
        json.dump(plan, fh, ensure_ascii=False, indent=2)
    print("=" * 66)
    print("Plan/Backup -> .data/_blessing_arzt_fix_plan.json")
    print("Modus:", "SCHREIBEN" if args.schreiben else "TROCKENLAUF (nichts geschrieben)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
