"""Misst /speak-stream: Zeit bis zum ERSTEN Chunk (TTFB — das hoert der
Anrufer als Reaktionszeit) und Gesamtzeit, gegen /speak als Vergleich.

    python tts_serve/stream_probe.py http://192.168.0.246:8211 bianca
"""

from __future__ import annotations

import sys
import time

import httpx

SAETZE = [
    "Guten Tag, hier ist die Zahnarztpraxis Doktor Petsas, mein Name ist Bianca. Was kann ich für Sie tun?",
    "Ich habe am Donnerstag um vierzehn Uhr dreißig einen Termin für Sie gefunden. Passt Ihnen das, oder soll ich noch einen anderen Vorschlag heraussuchen?",
    "Alles klar, dann trage ich Sie für Donnerstag ein.",
]


def main() -> None:
    basis = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://192.168.0.246:8211"
    stimme = sys.argv[2] if len(sys.argv) > 2 else "bianca"
    client = httpx.Client(timeout=httpx.Timeout(120.0, connect=5.0))
    rate = 24000

    for satz in SAETZE:
        # Blocking als Referenz
        t0 = time.perf_counter()
        r = client.post(f"{basis}/speak", json={"text": satz, "voice": stimme})
        r.raise_for_status()
        block_s = time.perf_counter() - t0
        audio_s = len(r.content) / 2 / rate

        # Stream: TTFB + Gesamt
        t0 = time.perf_counter()
        erster = 0.0
        gesamt_bytes = 0
        with client.stream(
            "POST", f"{basis}/speak-stream", json={"text": satz, "voice": stimme}
        ) as antwort:
            antwort.raise_for_status()
            for chunk in antwort.iter_bytes():
                if chunk and not erster:
                    erster = time.perf_counter() - t0
                gesamt_bytes += len(chunk)
        stream_s = time.perf_counter() - t0
        stream_audio_s = gesamt_bytes / 2 / rate

        print(
            f"[{len(satz):3d} Zeichen] blocking {block_s:5.2f}s ({audio_s:.1f}s Audio)"
            f" | stream: erster Ton {erster:5.2f}s, fertig {stream_s:5.2f}s"
            f" ({stream_audio_s:.1f}s Audio)"
        )


if __name__ == "__main__":
    main()
