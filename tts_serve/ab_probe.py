"""Hoerproben fuer den A/B-Vergleich Chatterbox gegen CosyVoice.

Rendert dieselben Saetze gegen den angegebenen TTS-Container und legt sie als
WAV unter tts_serve/bench_out/ab-vergleich/ ab — Dateiname traegt die Engine.

  .venv\\Scripts\\python tts_serve\\ab_probe.py --url http://192.168.0.246:8210 --name chatterbox
  .venv\\Scripts\\python tts_serve\\ab_probe.py --url http://192.168.0.246:8211 --name cosyvoice
"""

from __future__ import annotations

import argparse
import struct
import sys
import time
from pathlib import Path

import httpx

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER.parent))

RATE = 24000

SAETZE = [
    ("begruessung", "Guten Tag, Praxis med dent, mein Name ist Bianca. Was kann ich für Sie tun?"),
    ("termin", "Am Donnerstag, dem vierzehnten, hätte ich um halb elf einen Termin frei, alternativ am Freitagnachmittag um Viertel nach drei."),
    ("rueckfrage", "Einen kleinen Moment bitte, ich schaue kurz in den Kalender. Können Sie mir noch Ihr Geburtsdatum nennen?"),
]

VOICES = ["bianca", "lisa"]


def _wav(pcm: bytes) -> bytes:
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(pcm), b"WAVE", b"fmt ", 16,
        1, 1, RATE, RATE * 2, 2, 16, b"data", len(pcm),
    )
    return header + pcm


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True)
    p.add_argument("--name", required=True, help="Engine-Name fuer die Dateinamen")
    a = p.parse_args()
    out = HIER / "bench_out" / "ab-vergleich"
    out.mkdir(parents=True, exist_ok=True)
    for voice in VOICES:
        for kennung, text in SAETZE:
            t0 = time.monotonic()
            r = httpx.post(f"{a.url.rstrip('/')}/speak", json={"text": text, "voice": voice}, timeout=120.0)
            dauer = time.monotonic() - t0
            if r.status_code != 200:
                print(f"FEHLER {voice}/{kennung}: HTTP {r.status_code} {r.text[:120]}")
                continue
            datei = out / f"{a.name}-{voice}-{kennung}.wav"
            datei.write_bytes(_wav(r.content))
            print(f"{datei.name}: {len(r.content) / 2 / RATE:.1f} s Audio in {dauer:.1f} s")
    print(f"\nProben liegen in: {out}")


if __name__ == "__main__":
    main()
