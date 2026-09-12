import json
from pathlib import Path

p = Path("/app/tests/baukasten/berichte/last-20260912-104427/lasttest.json")
data = json.loads(p.read_text(encoding="utf-8"))
tr = data.get("transkript") or []
print("STORIES")
for sitz in (data.get("plan") or {}).get("sitze") or []:
    print(sitz)
print("\nLAEUFE")
for x in data.get("laeufe") or []:
    print("---", x.get("nr"), x.get("tenant"), x.get("kurz"), "ok", x.get("ok"))
    print(" story", x.get("story"))
    print(" fehler", x.get("fehler"))
    print(" zuege", [(z.get("baustein"), (z.get("soll") or "")[:80], (z.get("text") or "")[:80]) for z in (x.get("zuege") or [])])

print("\nTRANSKRIPT")
for z in tr:
    print(f"{z.get('phase'):8} #{z.get('nr')} {z.get('tenant')} {z.get('wer'):7} {(z.get('baustein') or ''):22} {(z.get('text') or '')[:160]}")
