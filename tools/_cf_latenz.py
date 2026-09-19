"""CF-Zuverlaessigkeit aus echten Anruf-Manifesten (read-only).

Durchsucht ``.data/anrufe/<stimme>/*/anruf.json`` nach ALLEN aufgezeichneten
Cloud-Function-Aufrufen (``dispatch`` mit ``route``/``httpStatus``/``ms``) und
gibt je Route Zahlen aus: Aufrufe, Fehlerquote (httpStatus != 200 oder 0),
Timeout-Verdacht (status 0) und Latenz-Perzentile. Nichts wird geschrieben.

Zweck (Chef 18.09.2026): "warum antwortet getFreeTimeSlots manchmal nicht?"
"""

from __future__ import annotations

import glob
import json
import os
from datetime import datetime, timezone


def _iter_dispatch(obj):
    """Rekursiv jedes dict mit einem 'route'-Feld finden (Dispatch-Meta)."""
    if isinstance(obj, dict):
        if "route" in obj and ("httpStatus" in obj or "ms" in obj):
            yield obj
        for v in obj.values():
            yield from _iter_dispatch(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_dispatch(v)


def _perzentil(werte, p):
    if not werte:
        return 0
    s = sorted(werte)
    i = min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1))))
    return s[i]


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--stimme", default="bianca")
    ap.add_argument("--tag", default="", help="YYYY-MM-DD (Default: alle)")
    ap.add_argument("--route", default="", help="nur eine Route")
    args = ap.parse_args()

    base = os.path.join(".data", "anrufe", args.stimme)
    fs = glob.glob(os.path.join(base, "*", "anruf.json"))
    routen: dict[str, dict] = {}
    langsamste: list[tuple] = []

    for f in fs:
        try:
            m = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        if args.tag and str(m.get("startedAt") or "")[:10] != args.tag:
            continue
        sid = str(m.get("id") or "")[:12]
        for d in _iter_dispatch(m):
            route = str(d.get("route") or "?")
            if args.route and route != args.route:
                continue
            st = d.get("httpStatus")
            try:
                st = int(st)
            except Exception:
                st = -1
            ms = d.get("ms")
            try:
                ms = int(ms)
            except Exception:
                ms = None
            r = routen.setdefault(route, {"n": 0, "ok": 0, "timeout": 0, "http_fehler": 0, "ms": []})
            r["n"] += 1
            if st == 200:
                r["ok"] += 1
            elif st == 0:
                r["timeout"] += 1        # httpx.HTTPError -> status 0 (Timeout/Verbindung)
            else:
                r["http_fehler"] += 1
            if ms is not None:
                r["ms"].append(ms)
                if st != 200 or ms >= 5000:
                    langsamste.append((ms, st, route, sid))

    print("=" * 72)
    print(f" CF-ZUVERLAESSIGKEIT  stimme={args.stimme}  tag={args.tag or 'alle'}")
    print("=" * 72)
    kopf = f" {'route':30s} {'n':>5s} {'ok%':>6s} {'t/o':>4s} {'httpE':>5s} {'p50':>6s} {'p95':>6s} {'max':>6s}"
    print(kopf)
    print("-" * 72)
    for route, r in sorted(routen.items(), key=lambda x: -x[1]["n"]):
        n = r["n"]
        okq = (100.0 * r["ok"] / n) if n else 0
        p50 = _perzentil(r["ms"], 50)
        p95 = _perzentil(r["ms"], 95)
        mx = max(r["ms"]) if r["ms"] else 0
        print(f" {route:30s} {n:5d} {okq:6.1f} {r['timeout']:4d} {r['http_fehler']:5d} {p50:6d} {p95:6d} {mx:6d}")
    print("-" * 72)
    print(" Langsamste / fehlerhafte Aufrufe (ms, status, route, sid):")
    for ms, st, route, sid in sorted(langsamste, reverse=True)[:20]:
        print(f"   {ms:6d} ms  status={st:<4} {route:26s} {sid}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
