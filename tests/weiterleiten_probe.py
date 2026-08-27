"""Live-Probe Weiterleitung (Chef 27.08., zweite Fassung) gegen den laufenden
Bianca-Dienst auf 8096. Schreibt nichts in den Kalender — nur Gespraechszuege.

  1. "Kann ich bitte mit Doktor Patrikis sprechen?" -> DIREKT verbinden:
     zwei Filler (gesprochene Ansage, dann verbinden.mp3), Kirri-Platzhalter,
     KEIN Personalfrei-Text.
  2. Neue Sitzung, "Kann ich mit einem Mitarbeiter sprechen?" -> Wahrheit
     (personalfrei) + Arzt-Frage; Arzt genannt -> direkt verbinden.
"""

from __future__ import annotations

import json
import sys

import httpx

BIANCA = "http://127.0.0.1:8096"


def zug(client: httpx.Client, pfad: str, body: dict) -> tuple[dict, list[dict]]:
    reply: dict = {}
    filler: list[dict] = []
    with client.stream("POST", f"{BIANCA}{pfad}", json=body, timeout=90.0) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line.strip():
                continue
            ev = json.loads(line)
            if ev.get("type") == "filler":
                filler.append(ev)
            if ev.get("type") == "reply" or ("type" not in ev and ("sessionId" in ev or "text" in ev)):
                reply = ev
    return reply, filler


def main() -> int:
    c = httpx.Client()

    print("--- Fall 1: namentlich genannter Arzt -> direkt verbinden ---")
    start, _ = zug(c, "/api/start", {"tenant": "meddent"})
    sid = start.get("sessionId")
    assert sid, "keine Sitzung"
    out, filler = zug(c, "/api/turn", {"sessionId": sid, "text": "Kann ich bitte mit Doktor Patrikis sprechen?"})
    text = out.get("text") or ""
    print(f"  BIA: {text}")
    print(f"  Filler: {[f.get('audioUrl') for f in filler]}")
    assert "Kirri" in text, f"Platzhalter fehlt: {text!r}"
    assert "personalfrei" not in text and "KI-gef" not in text, f"Personalfrei-Ansage faelschlich da: {text!r}"
    assert len(filler) >= 2, f"Ansage+Jingle erwartet, kam: {filler}"
    assert filler[-1].get("audioUrl", "").endswith("verbinden.mp3"), "Jingle nicht als letzter Filler"
    print("  >>> ok: direkt verbunden (Ansage + Jingle), keine Personalfrei-Ansage")

    print("--- Fall 2: Mitarbeiter-Wunsch -> Wahrheit + Arzt-Frage -> verbinden ---")
    start2, _ = zug(c, "/api/start", {"tenant": "meddent"})
    sid2 = start2.get("sessionId")
    out2, _ = zug(c, "/api/turn", {"sessionId": sid2, "text": "Kann ich mit einem Mitarbeiter sprechen?"})
    text2 = out2.get("text") or ""
    print(f"  BIA: {text2}")
    assert "personalfrei" in text2, f"Wahrheit fehlt: {text2!r}"
    out3, filler3 = zug(c, "/api/turn", {"sessionId": sid2, "text": "Dann bitte zu Doktor Petsas."})
    text3 = out3.get("text") or ""
    print(f"  BIA: {text3}")
    print(f"  Filler: {[f.get('audioUrl') for f in filler3]}")
    assert "Kirri" in text3, f"Platzhalter fehlt: {text3!r}"
    assert filler3 and filler3[-1].get("audioUrl", "").endswith("verbinden.mp3"), "Jingle fehlt"
    print("  >>> ok: Wahrheit einmal, dann direkt verbunden")

    print("PROBE GRUEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
