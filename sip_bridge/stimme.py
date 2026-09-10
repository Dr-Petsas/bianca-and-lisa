"""W-STIMME-EQ (04.09.2026): Sprachband-EQ + Kompressor + Gate.

Chef nach dem Flughafen-Anruf: „noise filter, kompressoren mit
verstärkung der stimmfrequenzen und unterdrückung des rests mit eq".

Nur das Anrufer-PCM vor dem STT. Kein Eingriff in STT/TTS/Ports.
Aus: BRIDGE_STIMME=0. Ohne ffmpeg: Original zurück (nie den Zug killen).
"""

from __future__ import annotations

import math
import os
import subprocess
from array import array

BRIDGE_STIMME = os.environ.get("BRIDGE_STIMME", "1").strip() != "0"
# W-STT-OHR-KOMPAKT (10.09.2026): Das stille Ohr kann mehrere Sekunden
# interne Pause zwischen zwei echten Sprachinseln enthalten. Parakeet
# normalisiert ueber das ganze Segment und lieferte daraus live Muell
# (8,76 s Audio, nur 19 % Sprache, 5,18 s interne Leere). Wir entfernen
# ausschliesslich den MITTLEREN Teil solcher Pausen; Sprachsamples,
# Vor-/Nachlauf, normale Zuege und kurze Ja/Nein-Antworten bleiben
# byte-identisch. Notaus: STT_OHR_KOMPAKT=0.
STT_OHR_KOMPAKT = os.environ.get("STT_OHR_KOMPAKT", "1").strip().lower() not in {
    "0", "false", "no", "off",
}
_OHR_FRAME_MS = 20
_OHR_MIN_MS = 4000
_OHR_GAP_MS = 1200
_OHR_GAP_RAND_MS = 160
_OHR_MAX_DICHTE = 0.25

# Hochpass/Tiefpass = Telefon-Sprachband. afftdn = Rauschen.
# EQ: 250 Hz runter (Rumpeln/PA), 900+1800 Hz hoch (Formanten),
# 3,5 kHz leicht runter (Klirren). Kompressor holt die Stimme nach vorn,
# Gate macht den Rest leise.
_STIMME_AF = (
    "highpass=f=160:poles=2,"
    "lowpass=f=4500:poles=2,"
    "afftdn=nf=-25:nt=w:nr=12,"
    "equalizer=f=250:t=q:w=1.2:g=-8,"
    "equalizer=f=900:t=q:w=1.2:g=7,"
    "equalizer=f=1800:t=q:w=1.1:g=9,"
    "equalizer=f=3500:t=q:w=1.0:g=-5,"
    "acompressor=threshold=-28dB:ratio=4:attack=6:release=90:makeup=8:knee=6,"
    "agate=threshold=-40dB:ratio=4:attack=3:release=70"
)


def _frame_rms(pcm: bytes, frame_b: int) -> list[float]:
    pegel: list[float] = []
    for start in range(0, len(pcm) - frame_b + 1, frame_b):
        samples = array("h")
        samples.frombytes(pcm[start:start + frame_b])
        if not samples:
            pegel.append(0.0)
            continue
        pegel.append(math.sqrt(sum(x * x for x in samples) / len(samples)))
    return pegel


def ohr_kompakt(pcm: bytes, rate: int = 16000) -> bytes:
    """Sehr lange interne Ruhe in einem Ohr-Zug konservativ kuerzen.

    Der Nutzton wird nie gefiltert oder neu kodiert. Nur bei langen, duennen
    Segmenten und mindestens 1,2 s echter interner Pause bleibt je Pausenrand
    160 ms stehen. Eine einzelne kurze Antwort mit langem Vor-/Nachlauf hat
    keine interne Pause und bleibt deshalb vollstaendig unveraendert.
    """
    if not STT_OHR_KOMPAKT or not pcm or rate <= 0:
        return pcm
    frame_b = max(2, rate * 2 * _OHR_FRAME_MS // 1000)
    n = len(pcm) // frame_b
    if n * _OHR_FRAME_MS < _OHR_MIN_MS:
        return pcm
    pegel = _frame_rms(pcm, frame_b)
    if not pegel:
        return pcm
    peak = max(pegel)
    schwelle = max(peak * 0.05, 32768.0 * 0.003)
    aktiv = [p > schwelle for p in pegel]
    aktive_ids = [i for i, ist_aktiv in enumerate(aktiv) if ist_aktiv]
    if len(aktive_ids) < 2 or len(aktive_ids) / len(aktiv) > _OHR_MAX_DICHTE:
        return pcm

    gap_frames = max(1, _OHR_GAP_MS // _OHR_FRAME_MS)
    rand_frames = max(1, _OHR_GAP_RAND_MS // _OHR_FRAME_MS)
    schnitte: list[tuple[int, int]] = []
    run_start: int | None = None
    for i in range(aktive_ids[0], aktive_ids[-1] + 1):
        if not aktiv[i] and run_start is None:
            run_start = i
        elif aktiv[i] and run_start is not None:
            if i - run_start >= gap_frames:
                a, b = run_start + rand_frames, i - rand_frames
                if b > a:
                    schnitte.append((a, b))
            run_start = None
    # Mehrere lange Pausen gehoeren oft zu einer bewusst mehrteiligen
    # Verabschiedung. Der reale A/B-Test verschlechterte dort ein korrektes
    # "Wiederhoeren". Deshalb nur den eng belegten EIN-Gap-Fall verdichten.
    if len(schnitte) != 1:
        return pcm

    out = bytearray()
    cursor = 0
    entfernt = 0
    for a, b in schnitte:
        start, ende = a * frame_b, b * frame_b
        out.extend(pcm[cursor:start])
        entfernt += ende - start
        cursor = ende
    out.extend(pcm[cursor:])
    if not entfernt:
        return pcm
    vorher_ms = round(len(pcm) / (rate * 2) * 1000)
    nachher_ms = round(len(out) / (rate * 2) * 1000)
    dichte = len(aktive_ids) / len(aktiv)
    print(
        f"bruecke-ohr-kompakt {vorher_ms}->{nachher_ms} ms "
        f"(dichte={dichte:.2f}, pausen={len(schnitte)})",
        flush=True,
    )
    return bytes(out)


def filtern(pcm: bytes, rate: int = 16000) -> bytes:
    """PCM16-mono durch die Sprachkette. Bei Fehler: unverändertes Original."""
    if not BRIDGE_STIMME or not pcm:
        return pcm
    try:
        proc = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-f", "s16le", "-ar", str(rate), "-ac", "1", "-i", "pipe:0",
                "-af", _STIMME_AF,
                "-f", "s16le", "-ar", str(rate), "-ac", "1", "pipe:1",
            ],
            input=pcm, capture_output=True, timeout=4,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"bruecke-stimme-filter skip {type(e).__name__}", flush=True)
        return pcm
    if proc.returncode != 0 or not proc.stdout:
        err = (proc.stderr or b"")[:180]
        print(f"bruecke-stimme-filter fail rc={proc.returncode} {err!r}", flush=True)
        return pcm
    return proc.stdout
