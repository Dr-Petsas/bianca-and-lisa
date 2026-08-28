"""End-zu-End-Latenz am laufenden Bianca-Dienst messen: POST /api/listen mit
echtem Sprach-WAV, Zeitmarken je NDJSON-Event (transcript = STT fertig,
erstes filler/vorab-Audio = erster hörbarer Ton, reply = alles fertig).

    python tests/latenz_e2e.py [basis] [vorab]

Mit "vorab" wird der Dock-Ablauf seit dem 28.08.2026 nachgestellt: Mitschnitt
schon beim Stille-VERDACHT an /api/hoervorab, ~350 ms später (Stille-
Bestätigung) der Zug mit vorabId — misst den echten Gewinn des Vorab-Pfads.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

BASIS = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8096"
VORAB = "vorab" in sys.argv[2:]

# Echte Bianca-Stimme aus dem Platten-Cache als Anrufer-Ersatz — Scribe
# transkribiert das sauber, die Dauer (~2-3 s) entspricht einem kurzen Satz.
kandidaten = sorted((Path(".data") / "tts-cache").glob("*.wav"),
                    key=lambda f: f.stat().st_size)
if not kandidaten:
    sys.exit("kein WAV im tts-cache")
wav = kandidaten[len(kandidaten) // 2]
print(f"probe-wav: {wav.name} ({wav.stat().st_size // 1024} KB)")

client = httpx.Client(timeout=httpx.Timeout(60.0, connect=5.0))
start = client.post(f"{BASIS}/api/start", json={}).json()
sid = start.get("sessionId")
print(f"sitzung: {sid}")

daten: dict = {"sessionId": sid}
if VORAB:
    # Dock-Nachstellung: Vorab beim Stille-Verdacht, Zug ~350 ms später.
    tv = time.perf_counter()
    v = client.post(f"{BASIS}/api/hoervorab", data={"sessionId": sid},
                    files={"audio": (wav.name, wav.read_bytes(), "audio/wav")}).json()
    if v.get("vorabId"):
        daten["vorabId"] = v["vorabId"]
        print(f"vorab gestartet nach {time.perf_counter() - tv:.2f}s — 0,35 s Stille-Fenster …")
        time.sleep(0.35)

t0 = time.perf_counter()
marken: list[tuple[float, str]] = []
with client.stream(
    "POST", f"{BASIS}/api/listen",
    data=daten,
    files={"audio": (wav.name, wav.read_bytes(), "audio/wav")},
) as r:
    r.raise_for_status()
    for zeile in r.iter_lines():
        if not zeile.strip():
            continue
        ev = json.loads(zeile)
        t = time.perf_counter() - t0
        typ = ev.get("type")
        if typ == "transcript":
            marken.append((t, f"transcript  {ev.get('textIn')!r}"))
        elif typ == "filler":
            marken.append((t, f"audio-out   {ev.get('audioUrl')}"))
        elif typ == "reply":
            tt = ev.get("timings") or {}
            marken.append((t, f"reply       timings={tt} text={str(ev.get('text'))[:60]!r}"))
        else:
            marken.append((t, f"{typ}"))

for t, was in marken:
    print(f"  {t:6.2f}s  {was}")
