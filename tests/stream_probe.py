"""Handprobe: /api/turn-Stream — Füller-Timing und Sprech-Text. Kein Schreiben."""
import json
import time

import httpx

BASE = "http://127.0.0.1:8095"

body = {
    "tenant": "meddent",
    "auftrag": "Kontrolltermin vereinbaren",
    "patient": {"name": "Anna Test", "firstName": "Anna", "lastName": "Test"},
}
r = httpx.post(f"{BASE}/api/start", json=body, timeout=25)
d = r.json()
sid = d.get("sessionId")
print("START", r.status_code, "text=", (d.get("text") or "")[:90])
time.sleep(2.5)  # Anreicherung (Slots-Vorrat) fertig werden lassen

def zug(text: str) -> None:
    t0 = time.perf_counter()
    with httpx.stream("POST", f"{BASE}/api/turn", json={"sessionId": sid, "text": text}, timeout=60) as resp:
        print(f"TURN {text!r}", resp.status_code, resp.headers.get("content-type"))
        for line in resp.iter_lines():
            if not line.strip():
                continue
            ev = json.loads(line)
            dt = round(time.perf_counter() - t0, 2)
            typ = ev.get("type")
            if typ == "filler":
                print(f"  {dt}s FILLER url={ev.get('audioUrl')}")
            elif typ == "reply":
                print(f"  {dt}s REPLY  {ev.get('text')!r}")
                print("        timings", ev.get("timings"))
            else:
                print(f"  {dt}s {typ} {str(ev)[:110]}")


zug("Haben Sie kommende Woche vormittags etwas frei?")
zug("Am Montag Vormittag bitte, gerne gegen neun Uhr.")
zug("Gut, dann nehme ich den ersten Termin, den Sie genannt haben.")

lc = httpx.get(f"{BASE}/api/last-call", timeout=10).json()
call = lc.get("call") or {}
print("lastBook:", call.get("lastBook"))
print("lastCreate:", call.get("lastCreate"))
