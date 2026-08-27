"""Handprobe: /api/listen (Live-Text-Zweig + Leer-Audio-Zweig) im Stream."""
import json
import time

import httpx

BASE = "http://127.0.0.1:8095"

body = {
    "tenant": "meddent",
    "auftrag": "Kontrolltermin vereinbaren",
    "patient": {"name": "Anna Test", "firstName": "Anna", "lastName": "Test"},
}
sid = httpx.post(f"{BASE}/api/start", json=body, timeout=25).json()["sessionId"]
time.sleep(1.5)

# Zweig 1: Live-Transkript vom Browser (kein STT nötig)
t0 = time.perf_counter()
with httpx.stream(
    "POST", f"{BASE}/api/listen",
    data={"sessionId": sid, "text": "Gibt es diese Woche noch was Freies?"},
    files={"audio": ("turn.webm", b"\x00" * 400, "audio/webm")},
    timeout=60,
) as resp:
    print("LISTEN live", resp.status_code, resp.headers.get("content-type"))
    for line in resp.iter_lines():
        if not line.strip():
            continue
        ev = json.loads(line)
        print(f"  {round(time.perf_counter()-t0,2)}s {ev.get('type')} {str(ev.get('text') or ev.get('audioUrl') or ev.get('error') or '')[:90]}")

# Zweig 2: nur Mini-Audio (STT muss sauber 'empty' liefern, kein Haenger)
t0 = time.perf_counter()
with httpx.stream(
    "POST", f"{BASE}/api/listen",
    data={"sessionId": sid},
    files={"audio": ("turn.webm", b"\x00" * 400, "audio/webm")},
    timeout=60,
) as resp:
    print("LISTEN stt", resp.status_code, resp.headers.get("content-type"))
    for line in resp.iter_lines():
        if not line.strip():
            continue
        ev = json.loads(line)
        print(f"  {round(time.perf_counter()-t0,2)}s {ev.get('type')} {str(ev.get('text') or ev.get('error') or '')[:90]}")
