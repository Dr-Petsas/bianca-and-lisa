"""Kontrolle: waehrend der Identitaetsphase darf KEIN Fueller kommen."""
import json
import time

import httpx

BASE = "http://127.0.0.1:8095"

r = httpx.post(f"{BASE}/api/start", json={
    "tenant": "meddent",
    "auftrag": "Kontrolltermin anbieten - die letzte Kontrolle war vor drei Jahren.",
    "patient": {"name": "Levi Tzannis", "firstName": "Levi", "lastName": "Tzannis", "gender": "m"},
}, timeout=30).json()
sid = r["sessionId"]
print("GRUSS:", r["text"])
time.sleep(3)

for satz in ["Ja, der bin ich.", "Vormittags waere gut."]:
    t0 = time.perf_counter()
    print(f"MENSCH: {satz}")
    with httpx.stream("POST", f"{BASE}/api/turn", json={"sessionId": sid, "text": satz}, timeout=60) as resp:
        for line in resp.iter_lines():
            if not line.strip():
                continue
            ev = json.loads(line)
            dt = round(time.perf_counter() - t0, 3)
            typ = ev.get("type")
            inhalt = ev.get("audioUrl") if typ == "filler" else (ev.get("text") or "")
            print(f"  {dt}s {typ}: {str(inhalt)[:90]}")

httpx.post(f"{BASE}/api/hangup", json={"sessionId": sid}, timeout=20)
