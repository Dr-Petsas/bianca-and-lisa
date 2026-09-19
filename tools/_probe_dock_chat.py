"""Probe: Dock-Chatzeile Ende-zu-Ende gegen die echte API (api/start + api/turn).

Genau der Weg, den `bianca_web/app.js -> chatSenden` geht: Text rein, Text
raus, kein Mikrofon. Schreibt nichts (test + testNoWrite).

    python tools\\_probe_dock_chat.py [basis] [tenant]
"""
from __future__ import annotations

import json
import sys

import httpx

BASIS = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8096").rstrip("/")
TENANT = sys.argv[2] if len(sys.argv) > 2 else "meddent"

SAETZE = [
    "Guten Tag, ich braeuchte einen Termin zur Kontrolle.",
    "Nein, ich war noch nie bei Ihnen.",
    "Bei Doktor Petsas bitte.",
    "Wie bitte?",                       # Meta: wiederholen
    "Naechste Woche vormittags waere gut.",
    "Mein Nachname ist Tzannis, T wie Theodor, Z, A, N, N, I, S.",
    "Kiriakos.",
    "Gesetzlich.",
    "Ueberspringen wir das.",           # Meta: auslassen
    "Auf Wiederhoeren.",
]


def _letzte_zeile(text: str) -> dict:
    """Antwort kommt als NDJSON (Filler-Zeilen + Reply) — nur die letzte zaehlt."""
    daten: dict = {}
    for zeile in text.splitlines():
        zeile = zeile.strip()
        if not zeile:
            continue
        try:
            daten = json.loads(zeile)
        except json.JSONDecodeError:
            continue
    return daten


def main() -> int:
    with httpx.Client(timeout=httpx.Timeout(180.0, connect=10.0)) as c:
        r = c.post(f"{BASIS}/api/start", json={
            "tenant": TENANT, "test": True, "testName": "Dock-Chat-Probe",
            "testNoWrite": True,
        })
        r.raise_for_status()
        d = _letzte_zeile(r.text)
        sid = d.get("sessionId") or ""
        if not sid:
            print("keine Sitzung:", r.text[:300])
            return 1
        print(f"Sitzung {sid[:8]}  Praxis: {d.get('praxis')}")
        print(f"  BIANCA  {d.get('text')}")

        stumm = 0
        for satz in SAETZE:
            print(f"\n  ANRUFER {satz}")
            r = c.post(f"{BASIS}/api/turn", json={"sessionId": sid, "text": satz})
            r.raise_for_status()
            d = _letzte_zeile(r.text)
            # Halbsatz-Wache meldet sich als eigene Zeile `{"type":"warte"}` —
            # KEIN Feld `warte`. Wer nur auf das Feld schaut, haelt einen
            # bewusst stillen Zug faelschlich fuer eine tote Leitung.
            if d.get("type") == "warte" or d.get("warte"):
                print("  BIANCA  (hoert weiter zu — Satz klingt unfertig)")
                continue
            text = str(d.get("text") or "")
            if not text:
                stumm += 1
                print("  BIANCA  *** STUMM ***")
            else:
                print(f"  BIANCA  {text}")
            for t in (d.get("tools") or []):
                print(f"          werkzeug {t.get('name')} -> {t.get('status')}")
            buch = d.get("book") or None
            if buch:
                print(f"          buchung dryRun={buch.get('dryRun')} booked={buch.get('booked')}")
            if d.get("hangup"):
                print("          (aufgelegt)")
                break

        c.post(f"{BASIS}/api/hangup", json={"sessionId": sid})
    print(f"\nstumme Zuege: {stumm}")
    return 0 if stumm == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
