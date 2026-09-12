#!/usr/bin/env python3
from pathlib import Path
import time
from kern import stt

blob = Path("/tmp/last-call.mp3").read_bytes()
print("bytes", len(blob))
t = time.time()
try:
    text = stt.transcribe(blob, mime="audio/mpeg", name="last.mp3")
    print("took", round(time.time() - t, 1), "s")
    print(text)
except Exception as e:
    print("FAIL", type(e).__name__, e)
