"""Pausen-Straffung fuer gewarmte Ansagen (kern/tts.pausen_straffen,
29.08.2026): Anlauf max 120 ms, Satz-Pausen max 350 ms, Ausklang max 250 ms.
Offline, ohne Netz — synthetische PCM16-WAVs.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kern import tts

_LAUT = (8000).to_bytes(2, "little", signed=True)


def _wav(*teile: tuple[int, bool]) -> bytes:
    """(ms, laut)-Stuecke zu einem eigenen PCM16-WAV fuegen."""
    pcm = b""
    for ms, laut in teile:
        n = tts.PCM_RATE * ms // 1000
        pcm += (_LAUT if laut else b"\x00\x00") * n
    return tts._wav_header(len(pcm), tts.PCM_RATE) + pcm


def _dauer_ms(blob: bytes) -> float:
    return (len(blob) - 44) / 2 / tts.PCM_RATE * 1000


def _aktive_samples(blob: bytes) -> int:
    import array

    a = array.array("h")
    a.frombytes(blob[44:])
    return sum(1 for s in a if abs(s) >= tts.AKTIV_SCHWELLE)


def test_lange_pausen_werden_gekappt():
    rein = _wav((500, False), (400, True), (1200, False), (400, True), (900, False))
    raus = tts.pausen_straffen(rein)
    # 120 Anlauf + 400 Sprache + 350 Pause + 400 Sprache + 250 Ausklang
    assert _dauer_ms(raus) == 1520, _dauer_ms(raus)
    # Die Sprache selbst bleibt Sample-identisch erhalten.
    assert _aktive_samples(raus) == _aktive_samples(rein)


def test_kurze_pausen_bleiben_unangetastet():
    rein = _wav((300, True), (200, False), (300, True))
    assert tts.pausen_straffen(rein) == rein


def test_notaus_laesst_alles_stehen():
    os.environ["TTS_PAUSEN"] = "0"
    try:
        rein = _wav((300, True), (1500, False), (300, True))
        assert tts.pausen_straffen(rein) == rein
    finally:
        os.environ.pop("TTS_PAUSEN", None)


def test_fremdformate_gehen_unveraendert_zurueck():
    mp3 = b"ID3\x04\x00" + b"\x00" * 200
    assert tts.pausen_straffen(mp3) == mp3
    assert tts.pausen_straffen(b"") == b""
    winzig = _wav((20, True))
    assert tts.pausen_straffen(winzig) == winzig


if __name__ == "__main__":
    fehler = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"OK   {name}")
            except AssertionError as e:
                fehler += 1
                print(f"ROT  {name}: {e}")
    raise SystemExit(1 if fehler else 0)
