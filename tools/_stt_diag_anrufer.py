"""Diagnose 2: echte Anrufer-Audio + was timings.stt misst."""
from __future__ import annotations

import time
from pathlib import Path

from kern import stt

call = Path("/app/.data/anrufe/bianca/1e9e1466410c49b6b400d1cccc7d7191")
print("call exists", call.exists())
files = sorted(call.iterdir(), key=lambda p: p.name)
print("files:")
for f in files:
    print(f"  {f.name:40s} {f.stat().st_size:8d}")

anrufer = [f for f in files if "anrufer" in f.name.lower()]
print("anrufer_count", len(anrufer))

# Probe up to 5 caller clips: whisper vs parakeet
for f in anrufer[:8]:
    audio = f.read_bytes()
    mime = "audio/wav" if f.suffix.lower() == ".wav" else (
        "audio/webm" if f.suffix.lower() == ".webm" else "audio/mp4"
    )
    print(f"\n--- {f.name} bytes={len(audio)} mime={mime} ---")
    # duration estimate for wav
    if audio[:4] == b"RIFF" and len(audio) > 44:
        # PCM16 16k mono: (size-44)/32000 seconds
        dur = (len(audio) - 44) / 32000.0
        print(f"  approx_dur_s={dur:.2f}")

    tw = time.perf_counter()
    try:
        text_w = stt._whisper(audio, mime=mime, keywords="Petsas,Patrikis")
        dw = time.perf_counter() - tw
        print(f"  whisper  {dw:.3f}s  {repr((text_w or '')[:70])}")
    except Exception as e:
        dw = time.perf_counter() - tw
        print(f"  whisper  FAIL {dw:.3f}s {type(e).__name__}: {e}")
        text_w = None

    tp = time.perf_counter()
    try:
        text_p = stt._lokal(audio, mime=mime, name=f.name, keywords="Petsas,Patrikis")
        dp = time.perf_counter() - tp
        print(f"  parakeet {dp:.3f}s  {repr((text_p or '')[:70])}")
    except Exception as e:
        dp = time.perf_counter() - tp
        print(f"  parakeet FAIL {dp:.3f}s {type(e).__name__}: {e}")

    # Simulate empty-whisper double path cost
    if text_w == "":
        print(f"  EMPTY whisper -> would add parakeet => ~{(dw if 'dw' in dir() else 0)+dp:.3f}s total")
