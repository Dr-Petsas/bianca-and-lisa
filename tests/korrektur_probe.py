"""Live-Probe Korrekturen (Chef 27.08.2026): Gedächtnis sofort aktualisieren.

Spielt gegen den laufenden Bianca-Dienst (Port 8096) einen Anruf durch, in dem
der Anrufer Behandler UND Nachnamen korrigiert — Bianca muss beides sofort
übernehmen, darf nichts erneut erfragen und die Bestätigung muss den
korrigierten Stand nennen. Es wird NICHT gebucht (Abbruch vor dem Ja).
"""

from __future__ import annotations

import json
import sys

import httpx

BASE = "http://127.0.0.1:8096"


def _zug(client: httpx.Client, sid: str, text: str) -> str:
    antwort = ""
    with client.stream("POST", f"{BASE}/api/turn", json={"sessionId": sid, "text": text}, timeout=90.0) as r:
        for zeile in r.iter_lines():
            if not zeile:
                continue
            try:
                ev = json.loads(zeile)
            except ValueError:
                continue
            if ev.get("type") == "reply":
                antwort = ev.get("text") or ""
    print(f"  DU : {text}")
    print(f"  BIA: {antwort}")
    return antwort


def main() -> int:
    fehler: list[str] = []
    with httpx.Client() as client:
        start: dict = {}
        with client.stream("POST", f"{BASE}/api/start", json={"tenant": "meddent"}, timeout=30.0) as r:
            for zeile in r.iter_lines():
                if not zeile:
                    continue
                try:
                    ev = json.loads(zeile)
                except ValueError:
                    continue
                if "sessionId" in ev or ev.get("type") == "reply":
                    start.update(ev)
        sid = start.get("sessionId") or ""
        print(f"  BIA: {start.get('text')}")

        _zug(client, sid, "Guten Tag, ich hätte gern einen Termin bei Doktor Patrikis.")
        a2 = _zug(client, sid, "Nein, Moment — nicht Doktor Patrikis, ich habe mich vertan. Ich wollte zu Doktor Petsas.")
        if "patrikis" in a2.lower():
            fehler.append("Bianca beharrt nach der Korrektur auf Patrikis.")
        if "behandler" in a2.lower() and "?" in a2 and "petsas" not in a2.lower():
            fehler.append("Bianca fragt nach der Korrektur erneut nach dem Behandler.")

        _zug(client, sid, "Ich war noch nie bei Ihnen.")
        _zug(client, sid, "Eine Kontrolle bitte.")
        _zug(client, sid, "Ich heiße Paul Müller.")
        a6 = _zug(client, sid, "Halt, das war falsch — ich heiße Meier, nicht Müller.")
        if "müller" in a6.lower():
            fehler.append("Bianca spricht nach der Namens-Korrektur weiter von Müller.")

        # Stand am Dienst nachschlagen: Arzt und Nachname müssen korrigiert sein.
        h = client.get(f"{BASE}/health", timeout=15.0).json()
        s = (h.get("lastCall") or {}).get("sammler") or {}
        print(f"  >>> Sammler-Stand: arzt={s.get('arzt')!r} nachname={s.get('nachname')!r}")
        if "petsas" not in str(s.get("arzt", "")).lower():
            fehler.append(f"Behandler im Gehirn ist nicht Petsas: {s.get('arzt')!r}")
        if str(s.get("nachname", "")).lower() != "meier":
            fehler.append(f"Nachname im Gehirn ist nicht Meier: {s.get('nachname')!r}")

        _zug(client, sid, "Ach, ich melde mich später noch einmal. Danke!")
        client.post(f"{BASE}/api/hangup", json={"sessionId": sid}, timeout=30.0)

    if fehler:
        print("\nROT:")
        for f in fehler:
            print(f"  - {f}")
        return 1
    print("\nKORREKTUR-PROBE GRUEN — Arzt- und Namens-Korrektur sitzen sofort.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
