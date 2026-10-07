"""Verwaiste GPU-Sperre (Vorfall 07.10.2026 18:19) — ohne GPU, ohne Modell.

Ein /speak-stream, dessen Client nach dem ersten Stueck verschwindet (Barge-in),
darf die Sperre nicht festhalten. Aufruf: python tts_serve/qwen3/test_sperre.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ["TTS_SPERRE_WARTEN_S"] = "2"
os.environ["TTS_SPERRE_WAECHTER_S"] = "0"

import server  # noqa: E402
from fastapi import HTTPException  # noqa: E402


class _FakeModell:
    def generate_voice_clone_streaming(self, **_kw):
        for _ in range(5):
            time.sleep(0.05)
            yield np.zeros(2400, dtype=np.float32), 24000, None

    def generate_voice_clone(self, **_kw):
        return [np.zeros(2400, dtype=np.float32)], 24000


def _vorbereiten() -> None:
    ref = Path(tempfile.mkdtemp()) / "clara.wav"
    ref.write_bytes(b"")
    server._MODEL = _FakeModell()
    server._VOICES.clear()
    server._VOICES["clara"] = ref
    server._TRANSKRIPT["clara"] = ""
    server.StreamingResponse = lambda inhalt, **_kw: inhalt


def test_abgebrochener_stream_gibt_sperre_frei() -> None:
    liegengelassen = server.speak_stream(server.SpeakIn(text="Hallo.", voice="clara"))
    assert next(liegengelassen)
    t0 = time.monotonic()
    antwort = server.speak(server.SpeakIn(text="Naechster Satz.", voice="clara"))
    assert antwort.status_code == 200
    assert time.monotonic() - t0 < 1.5, "Folgesatz wartete auf die verwaiste Sperre"
    assert not server._LOCK.locked()
    assert server._belegt_s() == 0.0


def test_belegte_sperre_gibt_503_statt_ewig() -> None:
    server._LOCK.acquire()
    try:
        t0 = time.monotonic()
        try:
            server.speak(server.SpeakIn(text="Hallo.", voice="clara"))
        except HTTPException as e:
            assert e.status_code == 503
        else:
            raise AssertionError("kein 503 bei belegter Sperre")
        assert time.monotonic() - t0 < 3.0
    finally:
        server._LOCK.release()


def test_stream_liefert_alles_und_gibt_frei() -> None:
    stuecke = list(server.speak_stream(server.SpeakIn(text="Hallo.", voice="clara")))
    assert len(stuecke) == 5
    time.sleep(0.05)
    assert not server._LOCK.locked()


def test_parallele_streams_alle_fertig() -> None:
    fertig: list[int] = []

    def holen(i: int) -> None:
        list(server.speak_stream(server.SpeakIn(text=f"Satz {i}.", voice="clara")))
        fertig.append(i)

    faeden = [threading.Thread(target=holen, args=(i,)) for i in range(4)]
    for f in faeden:
        f.start()
    for f in faeden:
        f.join(timeout=5)
    assert sorted(fertig) == [0, 1, 2, 3]
    time.sleep(0.05)
    assert not server._LOCK.locked()


if __name__ == "__main__":
    _vorbereiten()
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)}/{len(tests)} gruen")
