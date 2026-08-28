"""Ziffern-Probe fuer die aktive TTS-Engine (Pflicht vor jedem Engine-Wechsel).

Die Nummern-Rueckbestaetigung ist sicherheitskritisch: sie muss WORTGETREU
gesprochen werden. CosyVoice-Turbo fiel hier am 29.08.2026 durch (Nullen
verschluckt, Abbrueche mitten in der Nummer, Babble auf Kurztexten) — Qwen3
sprach 5/5 vollstaendig. Diese Probe rendert die Rueckbestaetigung fuenfmal
blocking am Container aus der .env und laesst den Parakeet-Container (8212)
gegenhoeren. Abnahme: 5/5 Laeufe mit vollstaendiger Nummer 01776004600
(Gruppierung/Interpunktion egal).

Aufruf: .venv\\Scripts\\python tests\\tts_ziffern_probe.py
Schreibt nichts, bucht nichts — nur /speak + /transcribe.
"""
import io
import re
import time
import wave

import httpx

from kern.config import STT_BASE, TTS_BASE
from kern.tts import _ziffern_einzeln

# Wortform wie im Gespraechstext — die Probe schickt sie durch dieselbe
# Ziffern-Transformation wie der Live-Pfad (kern/tts.LokalTts.speak).
TEXT = _ziffern_einzeln(
    "Ich wiederhole die Nummer: null eins sieben sieben, "
    "sechs null null, vier sechs, null null. Stimmt das so?")
SOLL = "01776004600"
KURZ = [_ziffern_einzeln("null null."), _ziffern_einzeln("sechs null null,"),
        "Ich wiederhole die Nummer:"]


def wav_von(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(pcm)
    return buf.getvalue()


def main() -> int:
    if not TTS_BASE or not STT_BASE:
        print("TTS_BASE/STT_BASE nicht gesetzt — Probe braucht beide Container.")
        return 2
    c = httpx.Client(timeout=120)
    print("Engine:", TTS_BASE)
    gruen = 0
    for i in range(5):
        t0 = time.perf_counter()
        pcm = c.post(f"{TTS_BASE}/speak", json={"text": TEXT, "voice": "bianca"}).content
        dt = time.perf_counter() - t0
        tr = c.post(f"{STT_BASE}/transcribe",
                    files={"file": (f"p{i}.wav", wav_von(pcm), "audio/wav")}).json().get("text", "")
        ziffern = re.sub(r"\D", "", tr)
        ok = SOLL in ziffern
        gruen += ok
        print(f"[{i}] {'OK ' if ok else 'ROT'} synth={dt:.2f}s audio={len(pcm)/2/24000:.1f}s gehoert={tr!r}")
    for text in KURZ:
        pcm = c.post(f"{TTS_BASE}/speak", json={"text": text, "voice": "bianca"}).content
        tr = c.post(f"{STT_BASE}/transcribe",
                    files={"file": ("k.wav", wav_von(pcm), "audio/wav")}).json().get("text", "")
        print(f"kurz {text!r}: gehoert={tr!r}")
    print(f"\n{gruen}/5 vollstaendig — Abnahme braucht 5/5.")
    return 0 if gruen == 5 else 1


if __name__ == "__main__":
    raise SystemExit(main())
