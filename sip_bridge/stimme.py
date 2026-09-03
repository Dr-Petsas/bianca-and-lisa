"""W-STIMME-EQ (04.09.2026): Sprachband-EQ + Kompressor + Gate.

Chef nach dem Flughafen-Anruf: „noise filter, kompressoren mit
verstärkung der stimmfrequenzen und unterdrückung des rests mit eq".

Nur das Anrufer-PCM vor dem STT. Kein Eingriff in STT/TTS/Ports.
Aus: BRIDGE_STIMME=0. Ohne ffmpeg: Original zurück (nie den Zug killen).
"""

from __future__ import annotations

import os
import subprocess

BRIDGE_STIMME = os.environ.get("BRIDGE_STIMME", "1").strip() != "0"

# Hochpass/Tiefpass = Telefon-Sprachband. afftdn = Rauschen.
# EQ: 250 Hz runter (Rumpeln/PA), 900+1800 Hz hoch (Formanten),
# 3,5 kHz leicht runter (Klirren). Kompressor holt die Stimme nach vorn,
# Gate macht den Rest leise.
_STIMME_AF = (
    "highpass=f=160:poles=2,"
    "lowpass=f=4500:poles=2,"
    "afftdn=nf=-25:nt=w:nr=12,"
    "equalizer=f=250:t=q:w=1.2:g=-8,"
    "equalizer=f=900:t=q:w=1.2:g=7,"
    "equalizer=f=1800:t=q:w=1.1:g=9,"
    "equalizer=f=3500:t=q:w=1.0:g=-5,"
    "acompressor=threshold=-28dB:ratio=4:attack=6:release=90:makeup=8:knee=6,"
    "agate=threshold=-40dB:ratio=4:attack=3:release=70"
)


def filtern(pcm: bytes, rate: int = 16000) -> bytes:
    """PCM16-mono durch die Sprachkette. Bei Fehler: unverändertes Original."""
    if not BRIDGE_STIMME or not pcm:
        return pcm
    try:
        proc = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-f", "s16le", "-ar", str(rate), "-ac", "1", "-i", "pipe:0",
                "-af", _STIMME_AF,
                "-f", "s16le", "-ar", str(rate), "-ac", "1", "pipe:1",
            ],
            input=pcm, capture_output=True, timeout=4,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"bruecke-stimme-filter skip {type(e).__name__}", flush=True)
        return pcm
    if proc.returncode != 0 or not proc.stdout:
        err = (proc.stderr or b"")[:180]
        print(f"bruecke-stimme-filter fail rc={proc.returncode} {err!r}", flush=True)
        return pcm
    return proc.stdout
