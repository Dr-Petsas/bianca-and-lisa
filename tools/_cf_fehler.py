"""Fehlerklassen einer CF-Route aus den Manifesten (read-only)."""
from __future__ import annotations
import glob, json, os, sys
from collections import Counter

route_soll = sys.argv[1] if len(sys.argv) > 1 else "getFreeTimeSlots"
stimme = sys.argv[2] if len(sys.argv) > 2 else "bianca"


def _iter(obj):
    if isinstance(obj, dict):
        if obj.get("route") and ("httpStatus" in obj or "response" in obj):
            yield obj
        for v in obj.values():
            yield from _iter(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter(v)


status_ct: Counter = Counter()
msg_ct: Counter = Counter()
beispiele: list = []
base = os.path.join(".data", "anrufe", stimme)
for f in glob.glob(os.path.join(base, "*", "anruf.json")):
    try:
        m = json.load(open(f, encoding="utf-8"))
    except Exception:
        continue
    sid = str(m.get("id") or "")[:12]
    for d in _iter(m):
        if str(d.get("route") or "") != route_soll:
            continue
        try:
            st = int(d.get("httpStatus"))
        except Exception:
            st = -1
        status_ct[st] += 1
        if st == 200:
            continue
        resp = d.get("response")
        msg = ""
        if isinstance(resp, dict):
            msg = str(resp.get("message") or resp.get("error") or resp.get("status") or "")[:120]
        elif isinstance(resp, str):
            msg = resp[:120]
        if not msg:
            msg = "(keine message)"
        msg_ct[(st, msg)] += 1
        if len(beispiele) < 12:
            beispiele.append((st, sid, msg))

print(f"== {route_soll} ({stimme}) ==")
print("Status-Verteilung:")
for st, n in status_ct.most_common():
    print(f"  http {st:>4} : {n}")
print("\nFehlermeldungen (status, message -> n):")
for (st, msg), n in msg_ct.most_common(15):
    print(f"  [{st}] {msg}  -> {n}")
print("\nBeispiele (status, sid, message):")
for st, sid, msg in beispiele:
    print(f"  {st}  {sid}  {msg}")
