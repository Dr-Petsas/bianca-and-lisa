"""Handprobe: kommen die Fueller-Audios als brauchbares WAV an?"""
import json
import time

import httpx

BASE = "http://127.0.0.1:8095"

sid = httpx.post(f"{BASE}/api/start", json={
    "tenant": "meddent",
    "auftrag": "Kontrolltermin vereinbaren",
    "patient": {"name": "Anna Test", "firstName": "Anna", "lastName": "Test", "gender": "f"},
}, timeout=25).json()["sessionId"]
time.sleep(2.0)

gesehen = set()
for frage in [
    "Haben Sie kommende Woche vormittags etwas frei?",
    "Und Donnerstag nachmittags?",
    "Welchen Termin habe ich denn aktuell?",
    "Geht auch Freitag frueh?",
]:
    t0 = time.perf_counter()
    with httpx.stream("POST", f"{BASE}/api/turn", json={"sessionId": sid, "text": frage}, timeout=60) as resp:
        for line in resp.iter_lines():
            if not line.strip():
                continue
            ev = json.loads(line)
            if ev.get("type") != "filler":
                continue
            url = ev["audioUrl"]
            a = httpx.get(BASE + url, timeout=10)
            kb = round(len(a.content) / 1024)
            sek = round(len(a.content) / (24000 * 2), 2)  # s16le mono 24 kHz
            gesehen.add(url)
            print(f"{round(time.perf_counter()-t0,2)}s {url} {a.headers.get('content-type')} "
                  f"{kb} kB ~{sek}s kopf={a.content[:4]}")
print(f"verschiedene Fueller in 4 Zuegen: {len(gesehen)}")
