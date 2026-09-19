"""Read-only: erste echte Anrufer-Saetze, Begruessung ueberspringen."""
import json
import pathlib
import re

_GRUSS = re.compile(
    r"(?:hallo,\s+hautarztpraxis|praxis doktor|thaler zahnmedizin|"
    r"zahn[aä]rzte im medical|sie sprechen mit|wie kann ich)",
    re.I,
)

root = pathlib.Path("/app/.data/anrufe/bianca")
n = 0
for p in sorted(root.glob("*/anruf.json")):
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        continue
    if not isinstance(data, dict):
        continue
    genommen = ""
    for z in data.get("zuege") or []:
        if not isinstance(z, dict):
            continue
        t = ""
        for k in ("anrufer", "user", "gesagt", "textIn", "transcript"):
            v = z.get(k)
            if isinstance(v, str) and v.strip():
                t = v.strip()
                break
        if not t:
            continue
        if _GRUSS.search(t) and len(t) > 40:
            continue
        genommen = t.replace("\n", " ")[:220]
        break
    if genommen:
        print(genommen)
        n += 1
print(f"#COUNT {n}", flush=True)
