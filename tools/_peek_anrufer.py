import json
from pathlib import Path

root = Path("/app/.data/anrufe/bianca")
for d in sorted(root.iterdir()):
    p = d / "anruf.json"
    if not p.is_file():
        continue
    m = json.loads(p.read_text(encoding="utf-8"))
    start = (m.get("startedAt") or "")[:19]
    if start < "2026-09-07T22":
        continue
    keys = [k for k in m.keys() if k not in ("zuege",)]
    print("===", d.name[:12], start, "keys", keys)
    for k in ("anrufer", "patientName", "patientId", "caller", "telefon"):
        if k in m:
            print(" ", k, m.get(k))
    z0 = (m.get("zuege") or [None])[0]
    if isinstance(z0, dict):
        print("  z0 keys", list(z0.keys())[:20])
