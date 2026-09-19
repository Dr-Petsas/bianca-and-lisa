# -*- coding: utf-8 -*-
import json
import glob

ps = sorted(glob.glob("/app/.data/anrufe/bianca/*/anruf.json"))
print("n", len(ps))
# nimm einen mit mehreren Zuegen
best = None
for p in ps:
    try:
        m = json.loads(open(p, encoding="utf-8").read())
    except Exception:
        continue
    z = m.get("zuege") or []
    if len(z) >= 4:
        best = (p, m)
        break
if not best:
    raise SystemExit("kein manifest")
p, m = best
print("file", p)
print("top", sorted(m.keys()))
print("nzuege", len(m.get("zuege") or []))
for i, z in enumerate((m.get("zuege") or [])[:3]):
    print("--- zug", i, "keys", sorted(z.keys()) if isinstance(z, dict) else type(z))
    if isinstance(z, dict):
        slim = {k: z[k] for k in z if k not in {"audio", "wav", "pcm"}}
        # kuerzen
        s = json.dumps(slim, ensure_ascii=False)
        print(s[:2000])
