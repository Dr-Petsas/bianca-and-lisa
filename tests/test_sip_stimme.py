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


@pytest.fixture(autouse=True)
def _kette_an(monkeypatch):
    """Die Filtertests pruefen die Kette selbst — Default ist seit 07.10. aus."""
    monkeypatch.setattr(stim, "BRIDGE_STIMME", True)


def test_kette_ist_im_code_default_aus(monkeypatch):
    import importlib

    monkeypatch.delenv("BRIDGE_STIMME", raising=False)
    monkeypatch.delenv("BRIDGE_RESAMPLER", raising=False)
    frisch = importlib.reload(stim)
    try:
        assert frisch.BRIDGE_STIMME is False
        assert frisch.BRIDGE_RESAMPLER == "soxr"
    finally:
        importlib.reload(stim)


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


def test_leise_nebenstimme_wird_vor_makeup_gegatet():
    """Feldbefund 02.10.: FFmpeg-Makeup ist linear, nicht in dB.

    ``makeup=8`` hob eine leise Nebenstimme um rund 18 dB an, bevor das
    nachgeschaltete Gate sie beurteilen konnte. Eine klare Telefonstimme
    muss erhalten bleiben, der leise Sprachton dagegen unter dem
    Grundrausch-Niveau bleiben.
    """
    leise = stim.filtern(_sinus(900, amp=200), RATE)
    vorn = stim.filtern(_sinus(900, amp=1000), RATE)

    assert _rms(leise) < 80
    assert _rms(vorn) > 1000
    assert _rms(vorn) > _rms(leise) * 20


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


def _sinus_rate(freq: float, rate: int, sek: float = 0.5, amp: int = 8000) -> bytes:
    n = int(rate * sek)
    return struct.pack(
        f"<{n}h",
        *[int(amp * math.sin(2 * math.pi * freq * i / rate)) for i in range(n)],
    )


def _pegel(pcm: bytes, freq: float, rate: int) -> float:
    """Goertzel-Amplitude einer Frequenz (Rand von je 20 % weggelassen)."""
    n = len(pcm) // 2
    x = struct.unpack(f"<{n}h", pcm[: n * 2])
    x = x[n // 5: n - n // 5]
    k = 2 * math.cos(2 * math.pi * freq / rate)
    s1 = s2 = 0.0
    for v in x:
        s1, s2 = v + k * s1 - s2, s1
    leistung = s1 * s1 + s2 * s2 - k * s1 * s2
    return math.sqrt(max(leistung, 0.0)) * 2 / len(x)


def test_fuer_stt_verdoppelt_die_rate(monkeypatch):
    monkeypatch.setattr(stim, "BRIDGE_STIMME", False)
    roh = _sinus_rate(1000, 8000, 0.5)
    aus = stim.fuer_stt(roh, 8000, 16000)
    assert abs(len(aus) - 2 * len(roh)) <= 2 * 64


def test_fuer_stt_erzeugt_keine_spiegelbilder(monkeypatch):
    """W-RESAMPLE: ein 3-kHz-Ton im Telefonband darf nach 8 -> 16 kHz weder
    leiser werden (lineare Interpolation: -4 dB) noch als 5-kHz-Spiegel
    (8 kHz - 3 kHz) im oberen Band auftauchen — den sieht Parakeet als
    Zischlaut, den es nie gab."""
    monkeypatch.setattr(stim, "BRIDGE_STIMME", False)
    aus = stim.fuer_stt(_sinus_rate(3000, 8000), 8000, 16000)
    nutz = _pegel(aus, 3000, 16000)
    spiegel = _pegel(aus, 5000, 16000)
    assert nutz > 8000 * 0.89, f"3 kHz gedaempft: {nutz:.0f}"
    assert spiegel < nutz * 0.001, f"Spiegel {spiegel:.1f} bei Nutz {nutz:.0f}"


def test_fuer_stt_mit_sprachkette_haelt_den_filter(monkeypatch):
    """Resampling und Sprachkette laufen in einem ffmpeg-Aufruf — das
    Stimmband bleibt gegenueber Rumpeln angehoben wie bei filtern()."""
    monkeypatch.setattr(stim, "BRIDGE_STIMME", True)
    rumpel = stim.fuer_stt(_sinus_rate(80, 8000, 0.4, 4000), 8000, 16000)
    stimme = stim.fuer_stt(_sinus_rate(1800, 8000, 0.4, 4000), 8000, 16000)
    assert _rms(stimme) > _rms(rumpel) * 1.4


def test_fuer_stt_notaus_linear(monkeypatch):
    aufrufe = []
    monkeypatch.setattr(stim, "BRIDGE_RESAMPLER", "linear")
    monkeypatch.setattr(stim, "BRIDGE_STIMME", False)
    monkeypatch.setattr(stim, "_ffmpeg", lambda *a: aufrufe.append(a) or b"x")
    monkeypatch.setattr(stim, "_linear", lambda pcm, a, b: b"L" + pcm)
    assert stim.fuer_stt(b"\x01\x00", 8000, 16000) == b"L\x01\x00"
    assert aufrufe == []


def test_fuer_stt_faellt_bei_ffmpeg_fehler_auf_den_alten_weg(monkeypatch):
    monkeypatch.setattr(stim, "BRIDGE_RESAMPLER", "soxr")
    monkeypatch.setattr(stim, "BRIDGE_STIMME", True)
    monkeypatch.setattr(stim, "_ffmpeg", lambda *a: b"")
    monkeypatch.setattr(stim, "_linear", lambda pcm, a, b: b"L" + pcm)
    # Sprachkette scheitert ebenfalls -> unverändert linear hochgerechnet
    assert stim.fuer_stt(b"\x01\x00", 8000, 16000) == b"L\x01\x00"


def test_ohr_kompakt_notaus(monkeypatch):
    monkeypatch.setattr(stim, "STT_OHR_KOMPAKT", False)
    sprache = _sinus(900, 0.4)
    roh = sprache + b"\x00\x00" * (RATE * 3) + sprache
    assert stim.ohr_kompakt(roh, RATE) == roh
