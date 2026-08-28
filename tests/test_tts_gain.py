"""Pegel-Vertrag von kern.tts.pcm16_wav (Lautheits-Angleichung, 28.08.2026).

Jede Äußerung wird auf dieselbe Sprach-Lautheit gezogen (RMS über aktive
Samples auf ZIEL_RMS, anheben UND absenken), gedeckelt über PEAK_DECKEL und
MIN_/MAX_GAIN. Stille und Kurzst-Stücke bleiben byte-identisch — gegen das
"Pumpen" zwischen Sätzen bei lokalem TTS (Chef 28.08.2026).
"""

from lisa.tts import pcm16_wav
from kern.tts import (
    AKTIV_SCHWELLE,
    MIN_AKTIV_SAMPLES,
    MIN_GAIN,
    MAX_GAIN,
    PEAK_DECKEL,
    ZIEL_RMS,
)


def _probe(wav: bytes, offset: int = 44) -> int:
    return int.from_bytes(wav[offset : offset + 2], "little", signed=True)


def _block(wert: int, anzahl: int) -> bytes:
    return wert.to_bytes(2, "little", signed=True) * anzahl


def test_leiser_satz_wird_auf_ziel_lautheit_gehoben():
    leise = _block(2000, MIN_AKTIV_SAMPLES * 2)
    wav = pcm16_wav(leise, rate=24000)
    erwartet = int(2000 * min(MAX_GAIN, ZIEL_RMS * 32767.0 / 2000))
    assert _probe(wav) == erwartet, "RMS 2000 muss auf ZIEL_RMS hochgezogen werden"


def test_lauter_satz_wird_abgesenkt():
    laut = _block(20000, MIN_AKTIV_SAMPLES * 2)
    wav = pcm16_wav(laut, rate=24000)
    erwartet = int(20000 * max(MIN_GAIN, ZIEL_RMS * 32767.0 / 20000))
    assert _probe(wav) == erwartet, "zu laute Sätze müssen RUNTER — sonst pumpt es"


def test_atmen_und_kurzstuecke_bleiben_unangetastet():
    atmen = _block(AKTIV_SCHWELLE - 50, MIN_AKTIV_SAMPLES * 2)
    assert _probe(pcm16_wav(atmen, rate=24000)) == AKTIV_SCHWELLE - 50, "Atmen nie anfassen"
    kurz = _block(2000, MIN_AKTIV_SAMPLES // 2)
    assert _probe(pcm16_wav(kurz, rate=24000)) == 2000, "unter ~50 ms Sprache: Stille-Regel"


def test_peak_deckel_verhindert_klirren():
    # Leises Grundsignal mit einem einzelnen lauten Ausreisser: der Gain darf
    # den Peak nicht über PEAK_DECKEL schieben.
    grund = bytearray(_block(2000, MIN_AKTIV_SAMPLES * 2))
    grund[0:2] = (20000).to_bytes(2, "little", signed=True)
    wav = pcm16_wav(bytes(grund), rate=24000)
    spitze = _probe(wav)
    assert spitze <= int(PEAK_DECKEL * 32767.0) + 1, "Peak nach Gain über dem Deckel"


def test_hohe_spitze_haelt_den_satz_nicht_leise():
    """Qwen: Peak 0,68 / RMS 0,08 — der alte Peak-Deckel auf den Gain
    liess Clara-Lautheit nicht zu. Der Sprachkörper muss auf ZIEL_RMS."""
    n = MIN_AKTIV_SAMPLES * 2
    grund = bytearray(_block(2000, n))
    grund[0:2] = (22000).to_bytes(2, "little", signed=True)
    wav = pcm16_wav(bytes(grund), rate=24000)
    # Mitte des Körpers, nicht die Spitze. RMS zählt die eine Spitze mit,
    # Gain liegt deshalb knapp unter dem reinen 2000-Satz.
    koerper = _probe(wav, offset=44 + (n // 2) * 2)
    rms = ((22000.0 ** 2 + (n - 1) * 2000.0 ** 2) / n) ** 0.5
    erwartet = int(2000 * min(MAX_GAIN, ZIEL_RMS * 32767.0 / rms))
    assert abs(koerper - erwartet) <= 2, (koerper, erwartet)
    assert _probe(wav) <= int(PEAK_DECKEL * 32767.0) + 1


def test_gain_grenzen():
    # Extrem leise Sprache: Faktor endet bei MAX_GAIN, nicht darüber.
    sehr_leise = _block(400, MIN_AKTIV_SAMPLES * 2)
    wav = pcm16_wav(sehr_leise, rate=24000)
    assert _probe(wav) == int(400 * MAX_GAIN), "kaputte Stücke nicht über MAX_GAIN retten"


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
    print("test_tts_gain: alle gruen")
