#!/usr/bin/env python3
"""Ziffern-Check auseinandernehmen: TTS -> Whisper vs Parakeet vs stt.transcribe."""
from __future__ import annotations

import os
import re
import time

from kern import config, stt, tts

SATZ = (
    "Ich wiederhole die Nummer. Null eins sieben sieben, sechs null null, "
    "vier sechs, null null. Stimmt das so?"
)


def digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def main() -> None:
    print("TTS_BASE", config.TTS_BASE)
    print("STT_WHISPER_BASE", config.STT_WHISPER_BASE)
    print("STT_BASE", config.STT_BASE)
    print("whisper_aktiv", stt._whisper_aktiv())
    print("whisper_pause_bis", getattr(stt, "_whisper_pause_bis", None), "now", time.time())
    print("engine_anzeige", stt.engine_anzeige())

    payload = tts._ziffern_einzeln(tts._normalisieren(SATZ))
    soll = tts._ziffern_soll(payload)
    print("payload:", payload)
    print("soll:", soll)

    # 1) frischer TTS-Wurf wie LokalTts.speak
    t0 = time.time()
    r = tts._lokal_client().post(
        f"{config.TTS_BASE}/speak",
        json={"text": payload, "voice": tts._VOICE_NAME},
    )
    print(f"tts speak http={r.status_code} bytes={len(r.content)} in {time.time()-t0:.2f}s")
    if r.status_code != 200:
        print(r.text[:300])
        return
    blob = tts.pcm16_wav(r.content)
    open("/tmp/ziffern-wurf.wav", "wb").write(blob)
    print("wav", len(blob), "B -> /tmp/ziffern-wurf.wav")

    # 2) Whisper direkt
    t1 = time.time()
    try:
        w = stt._whisper(blob, mime="audio/wav")
        print(f"WHISPER  took={time.time()-t1:.2f}s text={w!r} digits={digits(w)!r} match={soll in digits(w)}")
    except Exception as e:
        print(f"WHISPER  FAIL {type(e).__name__}: {e} took={time.time()-t1:.2f}s")

    # 3) Parakeet direkt
    t2 = time.time()
    try:
        p = stt._lokal(blob, mime="audio/wav", name="ziffern.wav")
        print(f"PARAKEET took={time.time()-t2:.2f}s text={p!r} digits={digits(p)!r} match={soll in digits(p)}")
    except Exception as e:
        print(f"PARAKEET FAIL {type(e).__name__}: {e} took={time.time()-t2:.2f}s")

    # 4) wie der echte Check: stt.transcribe
    t3 = time.time()
    try:
        g = stt.transcribe(blob, mime="audio/wav", name="ziffern.wav")
        print(f"transcribe took={time.time()-t3:.2f}s text={g!r} digits={digits(g)!r} match={soll in digits(g)}")
        print("nach transcribe whisper_aktiv", stt._whisper_aktiv(), "pause_bis", stt._whisper_pause_bis)
    except Exception as e:
        print(f"transcribe FAIL {type(e).__name__}: {e}")

    # 5) der echte Waechter
    ok = tts._ziffern_gehoert(blob, soll)
    print(f"_ziffern_gehoert -> {ok}")

    # 6) 3 Wuerfe wie live
    print("--- 3 Wuerfe wie LokalTts ---")
    for i in range(3):
        t = time.time()
        r = tts._lokal_client().post(
            f"{config.TTS_BASE}/speak",
            json={"text": payload, "voice": tts._VOICE_NAME},
        )
        b = tts.pcm16_wav(r.content)
        g = stt.transcribe(b, mime="audio/wav", name="ziffern.wav")
        d = digits(g)
        hit = soll in d
        print(f"Wurf {i+1}: tts={time.time()-t:.2f}s gehoert={g!r} digits={d!r} ok={hit} engine_pause={not stt._whisper_aktiv()}")
        open(f"/tmp/ziffern-wurf{i+1}.wav", "wb").write(b)
        if hit:
            break


if __name__ == "__main__":
    main()
