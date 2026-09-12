from pathlib import Path
import json
import re

for p in [Path("web/replay.html"), Path("bianca_web/replay.html")]:
    t = p.read_text(encoding="utf-8")
    m = re.search(r'<script id="DATA" type="application/json">(.*?)</script>', t, re.S)
    n = len(json.loads(m.group(1))) if m else 0
    print(p, "bytes", p.stat().st_size, "rows", n, "mitternacht", "Mitternacht" in t)
