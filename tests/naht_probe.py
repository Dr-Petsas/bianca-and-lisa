"""Naht-Probe gegen den echten Container: liegen die Haeppchen-Grenzen in
Sprechpausen, und wann kommt der erste Ton?

Aufruf: python tests/naht_probe.py "Langer Satz ..."
"""
from __future__ import annotations

import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kern import tts  # noqa: E402


def _rms(samples) -> float:
    if not samples:
        return 0.0
    return (sum(s * s for s in samples) / len(samples)) ** 0.5


def _naht_rms(wav: bytes, *, ende: bool) -> float:
    """Leisestes 10-ms-Unterfenster in den naht-nahen 40 ms (2 ms Rampe
    ausgespart). Liegt die Naht in einer Pause, ist dieses Minimum still —
    der Gain (~2,5-4x) hebt auch Pausen-Reste an, daher nicht mit 0 rechnen."""
    pcm = wav[44:]
    n = len(pcm) // 2
    rand = int(0.002 * 24000)
    zone = int(0.04 * 24000)
    if ende:
        ab, bis = max(0, n - rand - zone), max(0, n - rand)
    else:
        ab, bis = min(n, rand), min(n, rand + zone)
    if bis - ab < 240:
        return 0.0
    samples = struct.unpack(f"<{bis - ab}h", pcm[ab * 2: bis * 2])
    sub = int(0.01 * 24000)
    return min(_rms(samples[i:i + sub]) for i in range(0, len(samples) - sub + 1, sub))


def main() -> None:
    text = sys.argv[1] if len(sys.argv) > 1 else (
        "Alles klar, ich schaue kurz in den Kalender. Am Montag hätte ich "
        "vierzehn Uhr dreißig oder sechzehn Uhr fünfzehn frei, am Dienstag "
        "ginge es um neun Uhr. Welcher der Termine passt Ihnen am besten?"
    )
    eng = tts.engine()
    t0 = time.perf_counter()
    erster = 0.0
    stücke = []
    for wav in eng.speak_stream(text):
        if not erster:
            erster = time.perf_counter() - t0
        stücke.append(wav)
    gesamt = time.perf_counter() - t0
    print(f"erster Ton {erster:.2f}s, fertig {gesamt:.2f}s, {len(stücke)} Häppchen")
    for i, wav in enumerate(stücke):
        dauer = (len(wav) - 44) / 2 / 24000
        endr = _naht_rms(wav, ende=True)
        startr = _naht_rms(stücke[i + 1], ende=False) if i + 1 < len(stücke) else None
        naht = "PAUSE" if endr < 1300 and (startr is None or startr < 1300) else \
            f"VERDÄCHTIG (ende={endr:.0f} start={-1 if startr is None else startr:.0f})"
        letzte = "  (Stromende)" if i == len(stücke) - 1 else ""
        print(f"  {i+1}: {dauer:5.2f}s  Naht: {naht}{letzte}")


if __name__ == "__main__":
    main()
