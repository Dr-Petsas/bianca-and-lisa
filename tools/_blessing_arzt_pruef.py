"""Read-only Beleg fuer 'Could not load doctor' bei Blessing.

1) locationId + betroffene calendarIds aus den echten Manifesten ziehen
   (getFreeTimeSlots-Dispatch, clientId=UUJnPzoYPa4yYyzcaGlm).
2) Je Kalender per Firestore-REST userId/name/isDeleted/internal lesen.
3) Pruefen, ob das User-Dokument clients/<cid>/users/<userId> existiert.

Nur LESEN. Kein Schreibzugriff, keine Aenderung.
"""
from __future__ import annotations

import glob
import json
import os

import httpx

from kern import anrufaudio, standort

CID = "UUJnPzoYPa4yYyzcaGlm"
SCOPE = "https://www.googleapis.com/auth/datastore"
BASE = "https://firestore.googleapis.com/v1"


def _get(pfad: str):
    token = anrufaudio._access_token(SCOPE)
    r = httpx.get(f"{BASE}/{pfad}", headers={"Authorization": f"Bearer {token}"}, timeout=10.0)
    return r.status_code, r.json() if r.status_code == 200 else r.text


def _felder(doc):
    f = (doc or {}).get("fields") if isinstance(doc, dict) else None
    if not isinstance(f, dict):
        return {}
    return {k: standort._decode(v) for k, v in f.items()}


def _iter_dispatch(obj):
    if isinstance(obj, dict):
        if obj.get("route") == "getFreeTimeSlots" and "request" in obj:
            yield obj
        for v in obj.values():
            yield from _iter_dispatch(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_dispatch(v)


def main() -> int:
    # 1) locationId + calendarIds der fehlgeschlagenen Blessing-Aufrufe
    lids: set[str] = set()
    cals: dict[str, dict] = {}  # calId -> {n, fehler}
    for f in glob.glob(os.path.join(".data", "anrufe", "bianca", "*", "anruf.json")):
        try:
            m = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        for d in _iter_dispatch(m):
            req = d.get("request") or {}
            if str(req.get("clientId")) != CID:
                continue
            lid = str(req.get("locationId") or "")
            if lid:
                lids.add(lid)
            calid = str(req.get("calendarId") or "")
            if not calid:
                continue
            c = cals.setdefault(calid, {"n": 0, "fehler": 0})
            c["n"] += 1
            try:
                if int(d.get("httpStatus")) != 200:
                    c["fehler"] += 1
            except Exception:
                pass

    print(f"clientId = {CID}")
    print(f"locationId(s) = {sorted(lids)}")
    print(f"betroffene calendarIds = {sorted(cals)}")
    print("=" * 74)

    users_gesehen: dict[str, str] = {}
    for lid in sorted(lids):
        for calid, stat in sorted(cals.items(), key=lambda x: -x[1]["fehler"]):
            st, doc = _get(f"projects/{standort._projekt()}/databases/(default)/documents/"
                           f"clients/{CID}/locations/{lid}/calendars/{calid}")
            if st != 200:
                print(f"[cal {calid}] loc={lid} -> KEIN Kalender-Dok (http {st})")
                continue
            cf = _felder(doc)
            uid = str(cf.get("userId") or "")
            print(f"[cal {calid}] n={stat['n']} fehler={stat['fehler']} "
                  f"name={cf.get('name')!r} userId={uid!r} "
                  f"isDeleted={cf.get('isDeleted')} internal={cf.get('internal')} "
                  f"allowOnline={cf.get('allowOnlineAppointments')} license={cf.get('license')!r}")
            if uid and uid not in users_gesehen:
                us, udoc = _get(f"projects/{standort._projekt()}/databases/(default)/documents/"
                                f"clients/{CID}/users/{uid}")
                if us == 200:
                    uf = _felder(udoc)
                    users_gesehen[uid] = (f"EXISTIERT name={uf.get('firstName')} "
                                          f"{uf.get('lastName')} hidden={uf.get('hidden')} "
                                          f"role={uf.get('role')}")
                elif us == 404:
                    users_gesehen[uid] = ">>> FEHLT (404) — genau das wirft 'Could not load doctor'"
                else:
                    users_gesehen[uid] = f"http {us}: {str(udoc)[:80]}"
    print("=" * 74)
    print("User-Dokumente (clients/%s/users/<userId>):" % CID)
    for uid, info in users_gesehen.items():
        print(f"   {uid} -> {info}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
