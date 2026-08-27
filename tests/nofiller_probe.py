"""Gegenprobe: Geplauder darf KEINEN Fueller bekommen."""
import json
import time

import httpx

BASE = "http://127.0.0.1:8095"

sid = httpx.post(f"{BASE}/api/start", json={
    "tenant": "meddent",
    "auftrag": "Rueckruf ankuendigen",
    "patient": {"name": "Anna Test", "firstName": "Anna", "lastName": "Test", "gender": "f"},
}, timeout=25).json()["sessionId"]
time.sleep(1.5)

for frage in ["Wer sind Sie denn?", "Woher haben Sie meine Nummer?", "Danke, das war alles."]:
    t0 = time.perf_counter()
    typen = []
    with httpx.stream("POST", f"{BASE}/api/turn", json={"sessionId": sid, "text": frage}, timeout=60) as resp:
        for line in resp.iter_lines():
            if not line.strip():
                continue
            ev = json.loads(line)
            typen.append((round(time.perf_counter() - t0, 2), ev.get("type")))
            if ev.get("type") == "reply":
                print(f"{frage!r}\n   -> {ev.get('text')}")
    print("   Ereignisse:", typen)
