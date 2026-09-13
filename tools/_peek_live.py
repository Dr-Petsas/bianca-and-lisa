import json
import urllib.request
from pathlib import Path

print("=== LIVE ===")
try:
    with urllib.request.urlopen("http://127.0.0.1:8097/api/live", timeout=8) as r:
        d = json.loads(r.read().decode())
    print("laeuft", d.get("laeuft"))
    print("fehler", d.get("fehler"))
    print("laufId", d.get("laufId"))
    lt = d.get("lasttest") or {}
    print("phase", lt.get("phase"), "n", lt.get("n"), "fertig", lt.get("fertig"))
    print("transkript", len(lt.get("transkript") or []))
    print("blasen", len(lt.get("blasen") or []))
    erg = lt.get("ergebnis") or {}
    if erg:
        print("gehalten", erg.get("gehalten"), "fehler", erg.get("fehler"),
              "turns", erg.get("turns"), "dauerS", erg.get("dauerS"))
except Exception as e:
    print("live fail", type(e).__name__, e)

print("=== HUGE WAV TEXT ===")
hits = list(Path("/app").rglob("0005b038cfedaa162774.txt"))
print("hits", hits)
for p in hits:
    print(p, "len", p.stat().st_size)
    print(p.read_text(encoding="utf-8")[:800])
