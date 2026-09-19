"""Read-only: echte Blessing-Zahlen fuer die Kunden-Mail.

Zaehlt aus .data/anrufe/bianca/*/anruf.json:
- Blessing-Gespraeche gesamt (clientId in Dispatch ODER Manifest-Feld)
- Gespraeche mit getFreeTimeSlots-Fehler (httpStatus != 200)
- davon: kein erfolgreicher Termin gebucht (nicht zum Ziel gekommen)
- Aufschluesselung nach betroffenem Kalender
"""
from __future__ import annotations

import glob
import json
import os

CID = "UUJnPzoYPa4yYyzcaGlm"


def _iter_dispatch(obj):
    if isinstance(obj, dict):
        if "route" in obj and ("httpStatus" in obj or "request" in obj):
            yield obj
        for v in obj.values():
            yield from _iter_dispatch(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_dispatch(v)


def main() -> int:
    fs = glob.glob(os.path.join(".data", "anrufe", "bianca", "*", "anruf.json"))
    blessing = set()
    gfts_any = set()
    gfts_fail = set()
    gebucht = set()            # sid mit erfolgreichem masBookAppointment
    fail_ohne_buchung = set()
    cal_fail = {}              # calendarId -> {n, fehler, sids:set}
    gesamt_manifeste = 0

    for f in fs:
        try:
            m = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        gesamt_manifeste += 1
        sid = str(m.get("id") or os.path.basename(os.path.dirname(f)))
        ist_blessing = False
        hat_gfts = False
        hat_gfts_fail = False
        hat_buchung = False
        for d in _iter_dispatch(m):
            req = d.get("request") or {}
            if str(req.get("clientId")) == CID:
                ist_blessing = True
            route = str(d.get("route") or "")
            try:
                st = int(d.get("httpStatus"))
            except Exception:
                st = -1
            if route == "getFreeTimeSlots" and str(req.get("clientId")) == CID:
                hat_gfts = True
                calid = str(req.get("calendarId") or "?")
                c = cal_fail.setdefault(calid, {"n": 0, "fehler": 0, "sids": set()})
                c["n"] += 1
                if st != 200:
                    hat_gfts_fail = True
                    c["fehler"] += 1
                    c["sids"].add(sid)
            if route in ("masBookAppointment", "bookAppointment") and st == 200:
                hat_buchung = True
        if ist_blessing:
            blessing.add(sid)
        if hat_gfts:
            gfts_any.add(sid)
        if hat_gfts_fail:
            gfts_fail.add(sid)
        if hat_buchung:
            gebucht.add(sid)
        if hat_gfts_fail and not hat_buchung:
            fail_ohne_buchung.add(sid)

    print("=" * 70)
    print("BLESSING — echte Zahlen aus den Anruf-Manifesten")
    print("=" * 70)
    print(f"Manifeste gesamt (alle Mandanten) ......... {gesamt_manifeste}")
    print(f"Blessing-Gespraeche gesamt ................ {len(blessing)}")
    print(f"  davon mit Terminsuche (getFreeTimeSlots) . {len(gfts_any)}")
    print(f"  davon mit Terminsuch-FEHLER .............. {len(gfts_fail)}")
    print(f"  Fehler-Gespraeche OHNE Buchung ........... {len(fail_ohne_buchung)}")
    if len(blessing):
        print(f"  -> Anteil betroffen an Blessing .......... {100.0*len(gfts_fail)/len(blessing):.1f} %")
        print(f"  -> Anteil ohne Ziel an Blessing .......... {100.0*len(fail_ohne_buchung)/len(blessing):.1f} %")
    if len(gfts_any):
        print(f"  -> Fehlerquote der Terminsuchen .......... {100.0*len(gfts_fail)/len(gfts_any):.1f} %")
    print("-" * 70)
    print("Betroffene Kalender (fehlgeschlagene Terminsuchen):")
    for calid, s in sorted(cal_fail.items(), key=lambda x: -x[1]["fehler"]):
        print(f"  {calid}  aufrufe={s['n']:4d}  fehler={s['fehler']:4d}  gespraeche={len(s['sids'])}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
