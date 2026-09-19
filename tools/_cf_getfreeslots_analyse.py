"""getFreeTimeSlots-500-Analyse aus echten Anruf-Manifesten (read-only).

Gruppiert JEDEN aufgezeichneten getFreeTimeSlots-Aufruf nach clientId+calendarId
und klassifiziert die Fehlermeldung ("Could not load doctor" etc.). Beweist, ob
sich die 500er auf bestimmte Kalender/Aerzte ballen (Datenintegritaet) oder
zufaellig streuen (Transient/Timeout). Nichts wird geschrieben.

Chef 18.09.2026: "warum haben wir mit getFreeTimeSlots so viele probleme?"
"""
from __future__ import annotations

import glob
import json
import os
import re


def _iter_dispatch(obj):
    if isinstance(obj, dict):
        if "route" in obj and ("httpStatus" in obj or "ms" in obj):
            yield obj
        for v in obj.values():
            yield from _iter_dispatch(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_dispatch(v)


_KLASSEN = [
    ("could not load doctor", "Could not load doctor"),
    ("could not load user calendars", "Could not load user calendars"),
    ("could not load calendar", "Could not load calendar"),
    ("could not load location", "Could not load location"),
    ("missing parameters", "Missing parameters"),
    ("no visit motive", "No visit motive found"),
    ("no calendar found", "No calendar found"),
    ("invalid", "invalid-argument"),
]


def _klassifiziere(status, resp) -> str:
    if status == 0:
        return "TIMEOUT/Verbindung (status 0)"
    txt = ""
    if isinstance(resp, dict):
        txt = json.dumps(resp, ensure_ascii=False)
    else:
        txt = str(resp or "")
    low = txt.lower()
    for nadel, name in _KLASSEN:
        if nadel in low:
            return name
    if status == 200:
        return "OK"
    return f"anderer {status}: {txt[:80]}"


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--stimme", default="bianca")
    args = ap.parse_args()

    base = os.path.join(".data", "anrufe", args.stimme)
    fs = glob.glob(os.path.join(base, "*", "anruf.json"))

    ges = {"n": 0, "ok": 0, "fehler": 0}
    klassen: dict[str, int] = {}
    # (clientId, calendarId, calendarName) -> {n, ok, fehler, msg}
    kal: dict[tuple, dict] = {}

    for f in fs:
        try:
            m = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        sid = str(m.get("id") or "")[:12]
        for d in _iter_dispatch(m):
            if str(d.get("route") or "") != "getFreeTimeSlots":
                continue
            try:
                st = int(d.get("httpStatus"))
            except Exception:
                st = -1
            req = d.get("request") or {}
            resp = d.get("response")
            cid = str(req.get("clientId") or "?")
            calid = str(req.get("calendarId") or "(egal/keiner)")
            calname = str(req.get("calendarName") or req.get("spokenDoctorName") or "")
            kl = _klassifiziere(st, resp)

            ges["n"] += 1
            klassen[kl] = klassen.get(kl, 0) + 1
            k = kal.setdefault((cid, calid, calname), {"n": 0, "ok": 0, "fehler": 0, "msgs": {}, "sids": set()})
            k["n"] += 1
            if st == 200:
                ges["ok"] += 1
                k["ok"] += 1
            else:
                ges["fehler"] += 1
                k["fehler"] += 1
                k["msgs"][kl] = k["msgs"].get(kl, 0) + 1
                k["sids"].add(sid)

    print("=" * 78)
    print(f" getFreeTimeSlots-ANALYSE  stimme={args.stimme}  manifeste={len(fs)}")
    print("=" * 78)
    n = ges["n"] or 1
    print(f" Aufrufe gesamt: {ges['n']}   OK: {ges['ok']} ({100.0*ges['ok']/n:.1f}%)   Fehler: {ges['fehler']} ({100.0*ges['fehler']/n:.1f}%)")
    print("-" * 78)
    print(" Fehlerklassen (alle Aufrufe):")
    for kl, c in sorted(klassen.items(), key=lambda x: -x[1]):
        print(f"   {c:5d}  {kl}")
    print("-" * 78)
    print(" Kalender mit den meisten FEHLERN (clientId / calendarId / name):")
    rang = sorted(kal.items(), key=lambda x: -x[1]["fehler"])
    for (cid, calid, calname), k in rang[:25]:
        if k["fehler"] == 0:
            continue
        quote = 100.0 * k["fehler"] / (k["n"] or 1)
        msgs = ", ".join(f"{v}x {mk}" for mk, v in sorted(k["msgs"].items(), key=lambda x: -x[1]))
        print(f"   cid={cid[:20]:20s} cal={calid[:22]:22s} n={k['n']:4d} fehler={k['fehler']:4d} ({quote:5.1f}%)  {calname[:20]}")
        print(f"        -> {msgs}   sids: {', '.join(sorted(k['sids'])[:4])}")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
