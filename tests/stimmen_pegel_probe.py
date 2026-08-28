"""Roh-Pegel beider Stimmen direkt am Container messen (ohne Gain-Schicht).

Verdacht 28.08.2026: Biancas Klon liefert deutlich leiseres Roh-PCM als
Lisas — feste Stille-Schwellen (300) halten dann leise Sprache fuer Pause.
Aufruf: python tests/stimmen_pegel_probe.py
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kern.config import TTS_BASE  # noqa: E402

TEXT = "Guten Tag, hier spricht die Praxis. Wie kann ich Ihnen helfen?"


def main() -> None:
    for stimme in ("lisa", "bianca"):
        r = httpx.post(f"{TTS_BASE}/speak", json={"text": TEXT, "voice": stimme}, timeout=60)
        pcm = r.content
        n = len(pcm) // 2
        samples = struct.unpack(f"<{n}h", pcm[: n * 2])
        fenster = 720
        rmse = []
        for i in range(0, n - fenster, 360):
            block = samples[i:i + fenster]
            rmse.append((sum(s * s for s in block) / fenster) ** 0.5)
        rmse_sortiert = sorted(rmse)
        p = lambda q: rmse_sortiert[int(q * (len(rmse_sortiert) - 1))]
        unter300 = 100.0 * sum(1 for x in rmse if x < 300) / max(1, len(rmse))
        print(f"{stimme:6s}: {n/24000:5.2f}s  fenster-RMS p10={p(0.1):5.0f} p50={p(0.5):5.0f} "
              f"p90={p(0.9):5.0f} max={max(rmse):5.0f}  unter300={unter300:4.1f}%  peak={max(abs(s) for s in samples)}")


if __name__ == "__main__":
    main()
