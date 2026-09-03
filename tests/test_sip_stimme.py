# -*- coding: utf-8 -*-
"""W-STIMME-EQ (04.09.2026): Sprachband-Filter vor dem STT.

Chef: "noise filter, kompressoren mit verstärkung der stimmfrequenzen
und unterdrueckung des rests mit eq" — nach dem Flughafen-Anruf.
Offline: Sinus im Stimmband muss nach dem Filter lauter sein als
Rumpeln (80 Hz). Ohne ffmpeg wird uebersprungen.
"""

import math
import struct
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sip_bridge import stimme as stim  # noqa: E402

RATE = 16000


def _ffmpeg_da() -> bool:
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True, timeout=3, check=False,
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


pytestmark = pytest.mark.skipif(not _ffmpeg_da(), reason="kein ffmpeg")


def _sinus(freq: float, sek: float = 0.4, amp: int = 4000) -> bytes:
    n = int(RATE * sek)
    return struct.pack(
        f"<{n}h",
        *[int(amp * math.sin(2 * math.pi * freq * i / RATE)) for i in range(n)],
    )


def _rms(pcm: bytes) -> float:
    if len(pcm) < 4:
        return 0.0
    n = len(pcm) // 2
    samples = struct.unpack(f"<{n}h", pcm[: n * 2])
    return (sum(x * x for x in samples) / n) ** 0.5


def test_stimmband_wird_gegenueber_rumpeln_angehoben():
    rumpel = stim.filtern(_sinus(80), RATE)
    stimme = stim.filtern(_sinus(1800), RATE)
    assert _rms(stimme) > _rms(rumpel) * 1.4, (
        f"Stimme-RMS={_rms(stimme):.0f} Rumpel-RMS={_rms(rumpel):.0f}"
    )


def test_stille_bleibt_nahe_stille():
    roh = b"\x00\x00" * RATE  # 1 s Nullen
    aus = stim.filtern(roh, RATE)
    assert _rms(aus) < 80


def test_aus_laesst_original(monkeypatch):
    monkeypatch.setattr(stim, "BRIDGE_STIMME", False)
    roh = _sinus(1800, 0.2)
    assert stim.filtern(roh, RATE) == roh
