"""Live: Whisper vs Parakeet Latenz gegen echtes Anrufer-Audio."""
from __future__ import annotations

import time
from pathlib import Path

from kern import stt

base = Path("/app/.data/anrufe/bianca")
sample = None
for p in sorted(base.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)[:20]:
    for f in p.iterdir():
        name = f.name.lower()
        if f.suffix.lower() in {".wav", ".webm", ".m4a"} and ("anrufer" in name or name.startswith("z")):
            sample = f
            break
    if sample:
        break

print("sample", sample)
if not sample:
    raise SystemExit(0)

audio = sample.read_bytes()
mime = "audio/wav" if sample.suffix.lower() == ".wav" else "audio/webm"
print("bytes", len(audio), "mime", mime)

# Direct Parakeet
t0 = time.perf_counter()
try:
    text_p = stt._lokal(audio, mime=mime, name=sample.name, keywords="Petsas,Patrikis")
    print("parakeet", round(time.perf_counter() - t0, 3), "s", repr(text_p[:80]))
except Exception as e:
    print("parakeet FAIL", type(e).__name__, e)

# Direct Whisper
t0 = time.perf_counter()
try:
    text_w = stt._whisper(audio, mime=mime, keywords="Petsas,Patrikis")
    print("whisper", round(time.perf_counter() - t0, 3), "s", repr((text_w or "")[:80]))
except Exception as e:
    print("whisper FAIL", type(e).__name__, e, "elapsed", round(time.perf_counter() - t0, 3))

# Full transcribe path (current production)
t0 = time.perf_counter()
try:
    text = stt.transcribe(audio, mime=mime, name=sample.name, keywords="Petsas,Patrikis")
    print("transcribe", round(time.perf_counter() - t0, 3), "s", repr(text[:80]))
except Exception as e:
    print("transcribe FAIL", type(e).__name__, e, "elapsed", round(time.perf_counter() - t0, 3))

print("whisper_active", stt._whisper_aktiv())
print("engine", stt.engine_anzeige())
