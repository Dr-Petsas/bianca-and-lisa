"""Handprobe: die vier Gespraechswege des Identitaetschecks am echten Dienst.

Nur Reden, kein Schreiben — die Wege enden vor einer Buchung.
"""
import json
import sys
import time

import httpx

BASE = "http://127.0.0.1:8095"
PATIENT = {
    "id": "campaignr-test-dr-petsas",
    "name": "Levi Tzannis",
    "firstName": "Levi",
    "lastName": "Tzannis",
    "gender": "m",
}
AUFTRAG = ("Kontrolltermin anbieten — die letzte Kontrolle war vor drei Jahren. "
           "Freundlich anbieten und nach vormittags oder nachmittags fragen.")


def starten() -> tuple[str, str]:
    r = httpx.post(f"{BASE}/api/start", json={
        "tenant": "meddent", "auftrag": AUFTRAG, "patient": dict(PATIENT),
    }, timeout=30)
    d = r.json()
    return d.get("sessionId"), d.get("text")


def zug(sid: str, text: str) -> tuple[str, float, bool]:
    t0 = time.perf_counter()
    antwort, filler_kam = "", False
    with httpx.stream("POST", f"{BASE}/api/turn", json={"sessionId": sid, "text": text}, timeout=90) as resp:
        for line in resp.iter_lines():
            if not line.strip():
                continue
            ev = json.loads(line)
            if ev.get("type") == "filler":
                filler_kam = True
            elif ev.get("type") == "reply":
                antwort = ev.get("text") or ""
    return antwort, round(time.perf_counter() - t0, 2), filler_kam


def weg(titel: str, saetze: list[str]) -> None:
    print(f"\n===== {titel} =====")
    sid, gruss = starten()
    print(f"LISA  : {gruss}")
    time.sleep(3.0)  # Anliegen-Satz im Hintergrund fertig werden lassen
    for s in saetze:
        print(f"MENSCH: {s}")
        antwort, dt, fill = zug(sid, s)
        marke = " [FUELLER]" if fill else ""
        print(f"LISA  : {antwort}   ({dt}s){marke}")
    httpx.post(f"{BASE}/api/hangup", json={"sessionId": sid}, timeout=30)


weg("1. Richtige Person bestaetigt", [
    "Ja, der bin ich.",
    "Vormittags waere gut.",
])

weg("2. Falsche Person, dann Dritter uebernimmt", [
    "Nein.",
    "Das ist mein Sohn, worum geht es denn?",
    "Vormittags passt ihm besser.",
])

weg("3. Person wird ans Telefon geholt", [
    "Einen Moment, ich hole ihn.",
    "Hallo, ja?",
])

weg("4. Direkt Dritter: schlaeft", [
    "Der schlaeft gerade, koennen Sie es mir sagen?",
    "Sagen Sie mir einfach einen Termin, ich richte es aus.",
])

print("\nfertig")
