"""Read-only Funktionsbeweis: eine frueher gescheiterte getFreeTimeSlots-Anfrage
fuer den Dr.Ralf-Kalender erneut senden und pruefen, ob sie jetzt 200 + Slots gibt.
Keine Buchung, nur Terminsuche.
"""
from __future__ import annotations

import glob
import json
import os

from kern import calendar

CAL = "TphQRh53x8SToBSa8DdB"  # Dr.Ralf


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
    req = None
    war_status = None
    for f in glob.glob(os.path.join(".data", "anrufe", "bianca", "*", "anruf.json")):
        try:
            m = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        for d in _iter_dispatch(m):
            r = d.get("request") or {}
            if str(r.get("calendarId")) == CAL:
                req = r
                war_status = d.get("httpStatus")
                break
        if req:
            break
    if not req:
        print("Keine frueheren getFreeTimeSlots-Anfragen fuer Dr.Ralf gefunden.")
        return 1

    print(f"Wiederhole Anfrage (frueher httpStatus={war_status}):")
    print("  " + json.dumps({k: req.get(k) for k in ("clientId", "locationId", "calendarId", "visitMotiveId", "startDate")}, ensure_ascii=False))
    status, data, _ = calendar._cf_call("getFreeTimeSlots", req)
    n = 0
    if isinstance(data, dict):
        slots = data.get("slots") or data.get("freeTimeSlots") or data.get("data")
        if isinstance(slots, list):
            n = len(slots)
    print(f"  JETZT httpStatus={status}  status={ (data or {}).get('status') if isinstance(data,dict) else '?'}  slots~={n}")
    print("  -> " + ("OK: Cloud-Function antwortet wieder" if status == 200 else "IMMER NOCH FEHLER"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
