"""Kurze Live-Probe gegen den lokalen Qwen3-Container."""
import json
import time
import urllib.request

base = "http://127.0.0.1:8213"
for voice in ("lisa", "bianca"):
    text = (
        "Guten Tag, Praxis MedDent, hier ist "
        + voice.capitalize()
        + ". Wie lautet Ihr Nachname?"
    )
    t0 = time.perf_counter()
    req = urllib.request.Request(
        base + "/speak",
        data=json.dumps({"text": text, "voice": voice}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        pcm = r.read()
        dauer = r.headers.get("X-Dauer-S")
        rate = r.headers.get("X-Sample-Rate")
    s = time.perf_counter() - t0
    audio_s = (len(pcm) // 2) / 24000
    print(
        voice,
        "http=%.2fs" % s,
        "header=%ss" % dauer,
        "audio=%.2fs" % audio_s,
        "bytes=%d" % len(pcm),
        "rate=%s" % rate,
    )
