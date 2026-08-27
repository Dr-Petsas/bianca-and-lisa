"""Haertefall: sofortiges "Ja" — der vorbereitete Anliegen-Satz ist noch nicht da."""
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

# KEIN sleep: sofort antworten, bevor das Modell den Satz gebaut hat.
t0 = time.perf_counter()
with httpx.stream("POST", f"{BASE}/api/turn", json={"sessionId": sid, "text": "Ja."}, timeout=60) as resp:
    for line in resp.iter_lines():
        if not line.strip():
            continue
        ev = json.loads(line)
        if ev.get("type") == "reply":
            print(f"  {round(time.perf_counter()-t0,2)}s ANTWORT: {ev.get('text')}")
        elif ev.get("type") == "filler":
            print(f"  {round(time.perf_counter()-t0,2)}s FUELLER")

httpx.post(f"{BASE}/api/hangup", json={"sessionId": sid}, timeout=20)
