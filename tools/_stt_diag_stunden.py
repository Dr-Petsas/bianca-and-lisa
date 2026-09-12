"""STT-Stundenprofil heute + Abgleich Live-Text vs Replay-Engine."""
from __future__ import annotations

import json
from pathlib import Path

root = Path("/app/.data/anrufe/bianca")
by_hour: dict[int, list[float]] = {}
for p in root.iterdir():
    f = p / "anruf.json"
    if not f.exists():
        continue
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        continue
    started = d.get("startedAt") or ""
    if not started.startswith("2026-09-09"):
        continue
    local_h = int(started[11:13]) + 2
    for z in d.get("zuege") or []:
        if z.get("art") != "listen":
            continue
        stt = (z.get("timings") or {}).get("stt")
        if isinstance(stt, (int, float)):
            by_hour.setdefault(local_h, []).append(float(stt))

print("=== STT by local hour today ===")
for h in sorted(by_hour):
    xs = sorted(by_hour[h])
    p50 = xs[len(xs) // 2]
    p90 = xs[int(len(xs) * 0.9)] if len(xs) > 1 else xs[0]
    slow = sum(1 for x in xs if x >= 1.5)
    print(
        f"  {h:02d}:00  n={len(xs):3d}  avg={sum(xs)/len(xs):.2f}  "
        f"p50={p50:.2f}  p90={p90:.2f}  max={max(xs):.2f}  >=1.5s={slow}"
    )

# Compare live textIn of slow call vs what engines produce now
call = Path("/app/.data/anrufe/bianca/1e9e1466410c49b6b400d1cccc7d7191/anruf.json")
d = json.loads(call.read_text(encoding="utf-8"))
print("\n=== slow call live textIn (engine fingerprint) ===")
for i, z in enumerate(d.get("zuege") or []):
    if z.get("art") != "listen":
        continue
    t = z.get("timings") or {}
    stt = t.get("stt")
    mark = "SLOW" if isinstance(stt, (int, float)) and stt >= 1.5 else "ok  "
    print(f"  {mark} stt={stt}  {repr(z.get('textIn') or '')}")
