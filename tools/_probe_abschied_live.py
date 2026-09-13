"""Live-Probe (read-only): legt Bianca bei einem klaren Abschied auf?

Laeuft IM bianca-Container gegen die eigene Dock-API — kein Kalender-Write,
kein echter Anruf. Zeigt je Satz den gesprochenen Text und das hangup-Feld.

    docker exec -w /app telefonki-bianca-1 python tools/_probe_abschied_live.py
"""

from __future__ import annotations

import json

import httpx

BASIS = "http://127.0.0.1:8096"


def _zug(client: httpx.Client, sid: str, text: str) -> dict:
    r = client.post(
        f"{BASIS}/api/turn",
        json={"sessionId": sid, "text": text},
        timeout=90,
    )
    r.raise_for_status()
    letzte: dict = {}
    for zeile in r.text.splitlines():
        if not zeile.strip():
            continue
        posten = json.loads(zeile)
        if posten.get("type") in ("reply", "transcript", "warte"):
            letzte = posten
    return letzte


def main() -> None:
    saetze = [
        "Guten Tag, ich haette gern einen Termin zur Kontrolle.",
        "Ach wissen Sie was, ich melde mich spaeter nochmal. Auf Wiederhoeren!",
    ]
    with httpx.Client() as client:
        r = client.post(f"{BASIS}/api/start", json={"test": True, "testNoWrite": True}, timeout=60)
        r.raise_for_status()
        sid = r.json().get("sessionId") or r.json().get("id")
        print(f"session {sid}")
        for satz in saetze:
            posten = _zug(client, sid, satz)
            print(f"  ANRUFER : {satz}")
            print(f"  BIANCA  : {(posten.get('text') or '').strip()[:200]}")
            print(f"  hangup  : {posten.get('hangup')}")
        client.post(f"{BASIS}/api/hangup", json={"sessionId": sid}, timeout=60)


if __name__ == "__main__":
    main()
