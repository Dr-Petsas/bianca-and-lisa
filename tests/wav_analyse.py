"""Gespraechs-WAVs vom laufenden Dienst ziehen und objektiv vermessen.

Einmal-Werkzeug fuer die Artefakt-Diagnose 28.08.2026: holt die im Log
gesehenen /api/audio/<id>.wav-Blobs (RAM des laufenden Dienstes) und misst
je Stueck Dauer, RMS, Peak, Stille-Anteil und Clipping-Quote. Babble-
Renders (Runaway) und Pegel-Ausreisser fallen sofort auf.

Aufruf: python tests/wav_analyse.py http://127.0.0.1:8096 id1 id2 ...
"""
from __future__ import annotations

import io
import struct
import sys
import wave

import httpx


def messen(blob: bytes) -> dict:
    with wave.open(io.BytesIO(blob)) as w:
        rate = w.getframerate()
        n = w.getnframes()
        pcm = w.readframes(n)
    samples = struct.unpack(f"<{len(pcm)//2}h", pcm)
    dauer = n / rate if rate else 0.0
    if not samples:
        return {"dauer": 0.0}
    rms = (sum(s * s for s in samples) / len(samples)) ** 0.5
    peak = max(abs(s) for s in samples)
    clip = sum(1 for s in samples if abs(s) >= 32700) / len(samples)
    # Stille: 20-ms-Fenster unter Schwelle
    fenster = max(1, int(rate * 0.02))
    still = 0
    gesamt = 0
    for i in range(0, len(samples) - fenster, fenster):
        gesamt += 1
        block = samples[i:i + fenster]
        brms = (sum(s * s for s in block) / len(block)) ** 0.5
        if brms < 300:
            still += 1
    return {
        "dauer": round(dauer, 2),
        "rms": int(rms),
        "peak": peak,
        "clipPct": round(clip * 100, 2),
        "stillPct": round(100 * still / max(1, gesamt), 1),
    }


def main() -> None:
    basis = sys.argv[1].rstrip("/")
    ids = sys.argv[2:]
    with httpx.Client(timeout=10) as c:
        for aid in ids:
            try:
                r = c.get(f"{basis}/api/audio/{aid}.wav")
                if r.status_code != 200:
                    print(f"{aid}  HTTP {r.status_code}")
                    continue
                m = messen(r.content)
                print(f"{aid}  {m['dauer']:6.2f}s  rms={m['rms']:5d}  peak={m['peak']:5d}  "
                      f"clip={m['clipPct']:5.2f}%  still={m['stillPct']:5.1f}%  ({len(r.content)//1024} KB)")
            except Exception as e:
                print(f"{aid}  FEHLER {e}")


if __name__ == "__main__":
    main()
