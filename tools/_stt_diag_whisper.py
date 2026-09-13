"""Diagnose: Whisper (Kiriakos) vs Parakeet-Rueckfall, nur Messung."""
from __future__ import annotations

import json
import socket
import time
from pathlib import Path

from kern import stt
from kern.config import STT_BASE, STT_WHISPER_BASE


def tcp(host: str, port: int, timeout: float = 3.0) -> str:
    t0 = time.perf_counter()
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        return f"ok {round((time.perf_counter() - t0) * 1000)}ms"
    except Exception as e:
        return f"FAIL {type(e).__name__}: {e} ({round((time.perf_counter() - t0) * 1000)}ms)"
    finally:
        s.close()


print("=== config ===")
print("STT_WHISPER_BASE", STT_WHISPER_BASE)
print("STT_BASE", STT_BASE)
print("engine_anzeige", stt.engine_anzeige())
print("whisper_aktiv", stt._whisper_aktiv())

# parse host/port from whisper base
base = (STT_WHISPER_BASE or "").replace("ws://", "").replace("wss://", "").replace("http://", "").replace("https://", "")
hostport = base.split("/")[0]
if ":" in hostport:
    whost, wport_s = hostport.rsplit(":", 1)
    wport = int(wport_s)
else:
    whost, wport = hostport, 80
print("whisper_tcp", whost, wport, tcp(whost, wport))

# Parakeet host
if STT_BASE:
    from urllib.parse import urlparse
    u = urlparse(STT_BASE)
    print("parakeet_tcp", u.hostname, u.port, tcp(u.hostname or "", int(u.port or 80)))

# find sample audio from recent call
base_dir = Path("/app/.data/anrufe/bianca")
sample = None
for p in sorted(base_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)[:30]:
    for f in sorted(p.iterdir()):
        n = f.name.lower()
        if f.suffix.lower() in {".wav", ".webm", ".m4a"} and ("anrufer" in n or n.startswith("z")):
            if f.stat().st_size > 2000:
                sample = f
                break
    if sample:
        break

print("=== sample ===")
print("sample", sample)
if not sample:
    raise SystemExit(0)

audio = sample.read_bytes()
mime = "audio/wav" if sample.suffix.lower() == ".wav" else (
    "audio/webm" if sample.suffix.lower() == ".webm" else "audio/mp4"
)
print("bytes", len(audio), "mime", mime)

# Whisper alone, 3 runs
print("=== whisper x3 ===")
for i in range(3):
    t0 = time.perf_counter()
    try:
        text = stt._whisper(audio, mime=mime, keywords="Petsas,Patrikis")
        dt = time.perf_counter() - t0
        print(f"  #{i+1} {dt:.3f}s text={repr((text or '')[:60])}")
    except Exception as e:
        dt = time.perf_counter() - t0
        print(f"  #{i+1} FAIL {dt:.3f}s {type(e).__name__}: {e}")

# Parakeet alone, 3 runs
print("=== parakeet x3 ===")
for i in range(3):
    t0 = time.perf_counter()
    try:
        text = stt._lokal(audio, mime=mime, name=sample.name, keywords="Petsas,Patrikis")
        dt = time.perf_counter() - t0
        print(f"  #{i+1} {dt:.3f}s text={repr((text or '')[:60])}")
    except Exception as e:
        dt = time.perf_counter() - t0
        print(f"  #{i+1} FAIL {dt:.3f}s {type(e).__name__}: {e}")

# Full production path once
print("=== transcribe (prod path) x1 ===")
t0 = time.perf_counter()
try:
    text = stt.transcribe(audio, mime=mime, name=sample.name, keywords="Petsas,Patrikis")
    print(f"  {time.perf_counter()-t0:.3f}s text={repr(text[:60])}")
except Exception as e:
    print(f"  FAIL {time.perf_counter()-t0:.3f}s {type(e).__name__}: {e}")

# Today's STT distribution for the slow evening call
print("=== last call turn STTs ===")
last = Path("/app/.data/bianca_last_call.json")
if last.exists():
    d = json.loads(last.read_text(encoding="utf-8"))
    print("session", d.get("sessionId"), "started", (d.get("startedAt") or "")[:19])
    for i, z in enumerate(d.get("zuege") or []):
        if z.get("art") != "listen":
            continue
        t = z.get("timings") or {}
        print(
            f"  {i:02d} stt={t.get('stt')} llm={t.get('llm')} total={t.get('total')} "
            f"in={repr((z.get('textIn') or '')[:35])}"
        )
