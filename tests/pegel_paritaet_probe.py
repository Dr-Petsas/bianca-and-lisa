"""Pegel-Parität mit Demo Clara (Chef 27.08.2026, zweite Runde).

Messbefund: ElevenLabs liefert Peaks bei −0,4 bis −0,8 dBFS — Demo Clara
(worker_speech_out._demo_pcm_pegel: Ziel 0,82 FS, Faktor max. 1,8, nie
absenken, Stille-Schutz) reicht solches Audio UNVERÄNDERT durch. Parität
heißt also: unsere Stufe verhält sich byte-identisch zur Demo-Formel —
Lautes bleibt unangetastet, nur Leises wird moderat angehoben, nichts wird
gekappt oder leiser gemacht.

Die Probe holt für repräsentative Äußerungen einmal das rohe PCM und prüft:
  1. Unsere Stufe == Demo-Formel (byte-identisch), auch für einen künstlich
     leisen Fall (Roh × 0,2) und für Fast-Stille.
  2. Nichts wird leiser, nichts übersteuert.
"""

from __future__ import annotations

import array
import math
import sys

sys.path.insert(0, ".")

from kern import tts  # noqa: E402
from kern.config import ELEVENLABS_TTS_MODEL  # noqa: E402

TEXTE = [
    "Einen Moment bitte.",
    "Ich schaue kurz in den Kalender.",
    "Danke.",
    "Zahnärzte im Medical Center, guten Tag! Mein Name ist Bianca. Was kann ich für Sie tun?",
    "Frei ist morgen um zehn Uhr fünfundvierzig; oder morgen um dreizehn Uhr fünfzehn. Welcher passt Ihnen?",
    "Der Termin morgen um zehn Uhr fünfundvierzig ist fest eingetragen. Die Bestätigung kommt gleich per SMS.",
]


def _roh_pcm(text: str) -> bytes:
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{tts._VOICE_ID}/stream"
    r = tts._client().post(
        url,
        params={"optimize_streaming_latency": "3", "output_format": "pcm_24000"},
        headers={"Accept": "application/octet-stream", "Content-Type": "application/json"},
        json={
            "text": text,
            "model_id": ELEVENLABS_TTS_MODEL,
            **({"language_code": "de"} if ("v2_5" in ELEVENLABS_TTS_MODEL or "_v3" in ELEVENLABS_TTS_MODEL) else {}),
            "voice_settings": {"stability": 0.45, "similarity_boost": 0.85, "use_speaker_boost": True},
        },
    )
    r.raise_for_status()
    return r.content


def _demo_formel(pcm: bytes) -> bytes:
    """Byte-genaue Nachbildung von Demo Claras _demo_pcm_pegel (float32-Pfad,
    Ziel 0,82, Faktor max. 1,8, peak<80 oder schon laut -> unverändert)."""
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) // 2 * 2])
    if not samples:
        return b""
    spitze = float(max(abs(s) for s in samples))
    ziel = 0.82 * 32767.0
    if spitze < 80 or spitze >= ziel:
        return samples.tobytes()
    faktor = min(ziel / spitze, 1.8)
    out = array.array("h", bytes(len(samples) * 2))
    for i, s in enumerate(samples):
        v = int(s * faktor)
        out[i] = max(-32768, min(32767, v))
    return out.tobytes()


def _unsere_stufe(pcm: bytes) -> bytes:
    """kern.tts.pcm16_wav ohne WAV-Header — die Nutzdaten zum Vergleich."""
    wav = tts.pcm16_wav(pcm)
    return wav[44:] if len(wav) > 44 else b""


def _leiser(pcm: bytes, faktor: float) -> bytes:
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) // 2 * 2])
    out = array.array("h", (int(s * faktor) for s in samples))
    return out.tobytes()


def _dbfs(pcm: bytes) -> tuple[float, float]:
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) // 2 * 2])
    if not samples:
        return -120.0, -120.0
    spitze = max(abs(s) for s in samples) / 32767.0
    # RMS nur über hörbares Material (|s| > 300), sonst drücken Pausen den Wert.
    laut = [s / 32767.0 for s in samples if abs(s) > 300]
    rms = math.sqrt(sum(x * x for x in laut) / len(laut)) if laut else 0.0
    todb = lambda v: 20.0 * math.log10(v) if v > 0 else -120.0  # noqa: E731
    return todb(spitze), todb(rms)


def _max_abweichung(a: bytes, b: bytes) -> int:
    xs = array.array("h"); xs.frombytes(a)
    ys = array.array("h"); ys.frombytes(b)
    if len(xs) != len(ys):
        return 32767
    return max((abs(x - y) for x, y in zip(xs, ys)), default=0)


def main() -> int:
    ok = True
    for text in TEXTE:
        roh = _roh_pcm(text)
        faelle = [("roh", roh), ("leise (x0,2)", _leiser(roh, 0.2)), ("fast still (x0,001)", _leiser(roh, 0.001))]
        for name, quelle in faelle:
            unsere = _unsere_stufe(quelle)
            demo = _demo_formel(quelle)
            pq, rq = _dbfs(quelle)
            pu, ru = _dbfs(unsere)
            diff = _max_abweichung(unsere, demo)
            zeile = (f"  {text[:38]!r:42} {name:20} roh: peak {pq:6.1f} rms {rq:6.1f}"
                     f" -> neu: peak {pu:6.1f} rms {ru:6.1f} dBFS | Abw. zur Demo-Formel: {diff} LSB")
            print(zeile)
            if diff > 1:
                print("    ROT: weicht von Demo Claras Pegel-Formel ab.")
                ok = False
            if ru < rq - 0.05:
                print("    ROT: Stufe macht das Audio leiser — Demo senkt nie ab.")
                ok = False
            if pu > max(pq, 20.0 * math.log10(0.82)) + 0.05:
                print("    ROT: Stufe uebersteuert ueber Roh- und Demo-Ziel hinaus.")
                ok = False
    print("\nPEGEL-PROBE " + ("GRUEN — byte-gleich mit Demo Claras Pegel-Stufe." if ok else "ROT"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
