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


def test_ohr_kompakt_entfernt_nur_lange_interne_pause():
    """Live 10.09.: 5,18 s Leere zwischen zwei Sprachinseln machte aus
    einem Ohr-Zug 8,76 s Modellkontext. Die Sprachsamples bleiben exakt."""
    rand = b"\x00\x00" * (RATE // 2)
    stimme = _sinus(900, 0.4)
    pause = b"\x00\x00" * (RATE * 3)
    roh = rand + stimme + pause + stimme + rand

    aus = stim.ohr_kompakt(roh, RATE)

    assert len(aus) < len(roh) - RATE * 2 * 2
    assert aus.startswith(rand + stimme)
    assert aus.endswith(stimme + rand)


def test_ohr_kompakt_laesst_kurze_antwort_mit_viel_rand_unveraendert():
    """Ein kurzes Ja nach langer Denkpause hat nur EINE Sprachinsel.
    Vor-/Nachlauf bleiben Sache des bewaehrten Container-Trims."""
    rand = b"\x00\x00" * (RATE * 3)
    ja = _sinus(900, 0.2)
    roh = rand + ja + rand
    assert stim.ohr_kompakt(roh, RATE) == roh


def test_ohr_kompakt_laesst_normale_sprachpause_unveraendert():
    sprache = _sinus(900, 1.6)
    pause = b"\x00\x00" * (RATE // 2)
    roh = sprache + pause + sprache
    assert stim.ohr_kompakt(roh, RATE) == roh


def test_ohr_kompakt_laesst_mehrteiligen_abschied_unveraendert():
    """Reales A/B: Bei zwei langen Pausen wurde korrektes 'Wiederhören'
    schlechter. Mehrteilige Äußerungen bleiben deshalb bewusst original."""
    stimme = _sinus(900, 0.35)
    pause = b"\x00\x00" * (RATE * 2)
    roh = stimme + pause + stimme + pause + stimme
    assert stim.ohr_kompakt(roh, RATE) == roh


def test_ohr_kompakt_notaus(monkeypatch):
    monkeypatch.setattr(stim, "STT_OHR_KOMPAKT", False)
    sprache = _sinus(900, 0.4)
    roh = sprache + b"\x00\x00" * (RATE * 3) + sprache
    assert stim.ohr_kompakt(roh, RATE) == roh
