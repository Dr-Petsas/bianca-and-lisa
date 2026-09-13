"""Thaler-Raeume + Motiv-roomIds."""
import json
from pathlib import Path

import httpx

from kern import kalender_db
from kern.config import FIREBASE_CREDENTIALS

CLIENT = "7tTnJZfJkb801r2rmYed"
LOC = "loc_m219jgfb"


def _sv(fields, name):
    return kalender_db._feld(fields, name)


def _arr_ids(fields, name):
    raw = (fields or {}).get(name) or {}
    vals = (raw.get("arrayValue") or {}).get("values") or []
    out = []
    for v in vals:
        if isinstance(v, dict) and v.get("stringValue"):
            out.append(v["stringValue"])
    return out


def main() -> None:
    sa = json.loads(Path(FIREBASE_CREDENTIALS).read_text(encoding="utf-8"))
    token = kalender_db._access_token()
    base = (
        f"{kalender_db._FS}/projects/{sa['project_id']}/databases/(default)/documents/"
        f"clients/{CLIENT}/locations/{LOC}"
    )
    h = {"Authorization": f"Bearer {token}"}
    rooms = httpx.get(f"{base}/rooms", params={"pageSize": 50}, headers=h, timeout=12)
    print("ROOMS http", rooms.status_code)
    for doc in (rooms.json() or {}).get("documents") or []:
        f = doc.get("fields") or {}
        print(" ROOM", _sv(f, "name"), (doc.get("name") or "").rsplit("/", 1)[-1],
              "card", _sv(f, "cardinality"), "del", _sv(f, "isDeleted"))
    vms = httpx.get(f"{base}/visitMotives", params={"pageSize": 200}, headers=h, timeout=20)
    print("MOTIVES http", vms.status_code, "n", len((vms.json() or {}).get("documents") or []))
    for doc in (vms.json() or {}).get("documents") or []:
        f = doc.get("fields") or {}
        rids = _arr_ids(f, "roomIds")
        name = _sv(f, "name") or ""
        online = _sv(f, "allowOnlineBooking")
        if rids or any(x in name.lower() for x in ("pzr", "zahnrein", "prophyl", "notfall", "akut", "schmerz", "kontroll", "füll", "fuell")):
            print(" VM", name, "online", online, "rooms", rids, (doc.get("name") or "").rsplit("/", 1)[-1])


if __name__ == "__main__":
    main()
