"""Live-Probe (read-only): verliert Bianca in langen Gespraechen den Faden?

Laeuft IM bianca-Container gegen die eigene Dock-API (Testsitzung ohne
Kalender-Write). Simuliert ein zaehes Gespraech mit Abschweifern und echter
Funkstille und meldet jeden stummen Zug sowie wortgleiche Wiederholungen.

    docker exec -w /app telefonki-bianca-1 python tools/_probe_langgespraech.py
"""

from __future__ import annotations

import json

import httpx

BASIS = "http://127.0.0.1:8096"


def _lies(r: httpx.Response) -> dict:
    """Zug-Antwort lesen — /api/turn liefert NDJSON, /api/stille flaches JSON."""
    r.raise_for_status()
    letzte: dict = {}
    for zeile in r.text.splitlines():
        if not zeile.strip():
            continue
        posten = json.loads(zeile)
        if "type" not in posten or posten.get("type") in ("reply", "warte"):
            letzte = posten
    return letzte


def main() -> None:
    drehbuch = [
        ("sagen", "Guten Tag, ich braeuchte einen Termin zur Kontrolle."),
        ("sagen", "Ja, ich war schon oefter da."),
        ("stille", ""),
        ("sagen", "Ach wissen Sie, das Wetter ist heute wirklich schrecklich."),
        ("sagen", "Mein Nachbar sagt auch immer, im September regnet es am meisten."),
        ("stille", ""),
        ("stille", ""),
        ("sagen", "Hmm."),
        ("stille", ""),
        ("sagen", "Was meinten Sie gerade?"),
        ("stille", ""),
        ("stille", ""),
        ("sagen", "Ja."),
    ]
    with httpx.Client() as client:
        r = client.post(f"{BASIS}/api/start", json={"test": True, "testNoWrite": True}, timeout=60)
        r.raise_for_status()
        sid = r.json().get("sessionId") or r.json().get("id")
        print(f"session {sid}")
        gesehen: list[str] = []
        stumm = 0
        doppelt = 0
        for i, (art, satz) in enumerate(drehbuch, 1):
            if art == "sagen":
                posten = _lies(client.post(f"{BASIS}/api/turn",
                                           json={"sessionId": sid, "text": satz}, timeout=120))
                print(f"{i:02d} ANRUFER : {satz}")
            else:
                posten = _lies(client.post(f"{BASIS}/api/stille",
                                           json={"sessionId": sid}, timeout=120))
                print(f"{i:02d} (Funkstille)")
            text = " ".join((posten.get("text") or "").split())
            auf = posten.get("hangup")
            print(f"   BIANCA  : {text[:160] or '<STUMM>'}{'  [LEGT AUF]' if auf else ''}")
            if not text and not auf:
                stumm += 1
            elif text and text in gesehen:
                doppelt += 1
                print("   ^^ WORTGLEICHE WIEDERHOLUNG")
            if text:
                gesehen.append(text)
            if auf:
                break
        client.post(f"{BASIS}/api/hangup", json={"sessionId": sid}, timeout=60)
        print(f"\nstumme Zuege: {stumm}   wortgleiche Wiederholungen: {doppelt}")


if __name__ == "__main__":
    main()
