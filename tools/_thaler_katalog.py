"""Thaler-Kalender + PZR-Motive aus der CF (read-only)."""
from __future__ import annotations

import json
import os

import httpx

from kern.config import CF_BASE

CLIENT = "7tTnJZfJkb801r2rmYed"
LOC = "loc_m219jgfb"


def main() -> None:
    print("CF_BASE", CF_BASE)
    r = httpx.post(
        f"{CF_BASE}/masVisitMotives",
        json={"clientId": CLIENT, "locationId": LOC},
        timeout=15.0,
    )
    print("motives status", r.status_code)
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    motive = data.get("motives") or data.get("data") or []
    if isinstance(data, dict):
        print("keys", list(data.keys())[:20])
    pzr = []
    for m in motive if isinstance(motive, list) else []:
        if not isinstance(m, dict):
            continue
        name = f"{m.get('name') or ''} {m.get('nameForPatient') or ''}"
        cals = m.get("calendarIds") or []
        line = {
            "id": m.get("id"),
            "name": m.get("name"),
            "pat": m.get("nameForPatient"),
            "cals": cals,
            "online": m.get("allowOnlineBooking"),
        }
        low = name.lower()
        if any(x in low for x in ("pzr", "zahnrein", "prophyl", "zahnstein")):
            pzr.append(line)
        if "zimmer" in low or "prophyl" in low:
            print("MOTIV", json.dumps(line, ensure_ascii=False))
    print("PZR-TREFFER", len(pzr))
    for line in pzr:
        print(" PZR", json.dumps(line, ensure_ascii=False))
    # Alle Kalender-Ids aus Motiven
    ids = {}
    for m in motive if isinstance(motive, list) else []:
        if not isinstance(m, dict):
            continue
        for c in m.get("calendarIds") or []:
            ids[str(c)] = ids.get(str(c), 0) + 1
    print("calendarIds in motives", ids)
    # Agent-Kalender via phone-call pre, wenn Token da
    url = os.environ.get("PICKADOC_PHONE_CALL_URL") or f"{CF_BASE}/onPickadocPhoneCall"
    tok = os.environ.get("PICKADOC_PHONE_CALL_API_TOKEN") or ""
    print("pre url", url, "tok", bool(tok))
    if tok:
        try:
            p = httpx.post(
                url,
                headers={"Authorization": f"Bearer {tok}", "x-api-key": tok},
                json={
                    "phase": "pre",
                    "calledNumber": "+4921154244105",
                    "callerPhone": "anonymous",
                },
                timeout=20.0,
            )
            print("pre status", p.status_code)
            pre = p.json() if p.headers.get("content-type", "").startswith("application/json") else {}
            cals = pre.get("calendars") or []
            print("CALS", json.dumps(cals, ensure_ascii=False)[:2000])
            vms = pre.get("visitMotives") or []
            print("pre motives", len(vms))
            for vm in vms:
                if not isinstance(vm, dict):
                    continue
                n = f"{vm.get('name') or ''} {vm.get('nameForPatient') or ''}".lower()
                if any(x in n for x in ("pzr", "zahnrein", "prophyl", "zimmer")):
                    print(" PRE-VM", json.dumps({
                        "id": vm.get("id"), "name": vm.get("name"),
                        "cals": vm.get("calendarIds"),
                    }, ensure_ascii=False))
        except Exception as e:
            print("pre err", type(e).__name__, e)


if __name__ == "__main__":
    main()
