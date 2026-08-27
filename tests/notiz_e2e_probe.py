"""E2E-Handprobe: Anruf -> Live-Buchung -> Notiz/Protokoll im Termin -> Aufraeumen.

Nutzt den CampaignR-Fixture-Patienten (Chef-Testidentitaet, Dev-Handy) wie die
UI-Auswahl. Der gebuchte Termin wird am Ende per ID wieder abgesagt.
"""
import json
import time

import httpx

BASE = "http://127.0.0.1:8095"
CF = "https://europe-west3-docgenda.cloudfunctions.net"

ten = json.load(open("tenants/meddent.json", encoding="utf-8"))

body = {
    "tenant": "meddent",
    "auftrag": "Neuen Kontrolltermin vereinbaren",
    "patient": {
        "id": "campaignr-test-dr-petsas",
        "name": "Dr. Petsas",
        "firstName": "Dr.",
        "lastName": "Petsas",
        "phone": "+491776004600",
    },
}
r = httpx.post(f"{BASE}/api/start", json=body, timeout=25)
d = r.json()
sid = d.get("sessionId")
print("START", r.status_code, d.get("text"))
time.sleep(2.5)


def zug(text: str) -> None:
    t0 = time.perf_counter()
    with httpx.stream("POST", f"{BASE}/api/turn", json={"sessionId": sid, "text": text}, timeout=90) as resp:
        print(f"TURN {text!r}")
        for line in resp.iter_lines():
            if not line.strip():
                continue
            ev = json.loads(line)
            dt = round(time.perf_counter() - t0, 2)
            if ev.get("type") == "reply":
                print(f"  {dt}s REPLY {ev.get('text')!r}")
            elif ev.get("type") == "filler":
                print(f"  {dt}s FILLER")


zug("Haben Sie heute noch etwas frei? Gerne vormittags.")
zug("Den ersten genannten Termin bitte, buchen Sie den fest.")
zug("Bitte notieren Sie noch: Ich habe grosse Angst vor Spritzen.")

hp = httpx.post(f"{BASE}/api/hangup", json={"sessionId": sid}, timeout=30)
print("HANGUP", hp.status_code, str(hp.json())[:220])

lc = httpx.get(f"{BASE}/api/last-call", timeout=10).json()
call = lc.get("call") or {}
buch = call.get("lastBook") or {}
note = call.get("lastNote") or {}
aid = buch.get("appointmentId") or ""
print("lastBook:", {k: buch.get(k) for k in ("ok", "booked", "slotIso", "appointmentId")})
print("lastNote:", {k: note.get(k) for k in ("ok", "spoken")})

if aid:
    # Kontroll-Lesen: Marker anhaengen, zurueckgelieferte comments pruefen.
    probe = httpx.post(f"{CF}/masAppointmentNote", json={
        "clientId": ten["clientId"], "locationId": ten["locationId"],
        "appointmentId": aid, "note": "PROBE-MARKER",
    }, timeout=25).json()
    comments = probe.get("comments") or ""
    print("comments enthaelt Protokoll:", "Telefonprotokoll" in comments)
    print("comments enthaelt Angst-Notiz:", "Angst vor Spritzen" in comments)
    print("--- comments (Anfang) ---")
    print(comments[:700])
    print("---")
    weg = httpx.post(f"{CF}/agentCancelAppointmentById", json={
        "clientId": ten["clientId"], "locationId": ten["locationId"], "appointmentId": aid,
    }, timeout=25)
    print("AUFGERAEUMT:", weg.status_code, weg.text[:120])
else:
    print("KEINE TERMIN-ID — Buchung pruefen!")
