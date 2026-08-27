"""Pegel-Vertrag von kern.tts.pcm16_wav (Auto-Anhebung wie Demo Clara).

Der alte feste gain-Parameter ist seit der Kern-Auslagerung weg — angehoben
wird automatisch: nur leise Saetze (Ziel 0,82 FS, Faktor max. 1,8), Stille
und Lautes bleiben unangetastet, gekappt wird nie.
"""

from lisa.tts import pcm16_wav
from kern.tts import MAX_ANHEBUNG, STILLE_SPITZE, ZIEL_PEGEL


def test_wav_header_und_leises_wird_angehoben():
    leise = (2000).to_bytes(2, "little", signed=True) * 8
    wav = pcm16_wav(leise, rate=24000)
    assert wav[:4] == b"RIFF"
    assert wav[8:12] == b"WAVE"
    probe = int.from_bytes(wav[44:46], "little", signed=True)
    assert probe == int(2000 * MAX_ANHEBUNG), "leise Spitze muss um max. 1,8 hoch"


def test_stille_bleibt_stille():
    atmen = (STILLE_SPITZE - 10).to_bytes(2, "little", signed=True) * 8
    wav = pcm16_wav(atmen, rate=24000)
    probe = int.from_bytes(wav[44:46], "little", signed=True)
    assert probe == STILLE_SPITZE - 10, "Atmen/Rauschen nie hochziehen"


def test_lautes_bleibt_unveraendert_und_kappt_nie():
    voll = (30000).to_bytes(2, "little", signed=True) * 4
    wav = pcm16_wav(voll, rate=24000)
    probe = int.from_bytes(wav[44:46], "little", signed=True)
    assert probe == 30000, "schon Lautes nie anfassen (nie uebersteuern)"


def test_anhebung_zielt_auf_082_fs():
    # Spitze 16000: Zielfaktor waere 0,82*32767/16000 ≈ 1,68 (< 1,8) — greift.
    mittel = (16000).to_bytes(2, "little", signed=True) * 8
    wav = pcm16_wav(mittel, rate=24000)
    probe = int.from_bytes(wav[44:46], "little", signed=True)
    assert probe == int(16000 * (ZIEL_PEGEL * 32767.0 / 16000))
    assert probe <= 32767


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
    print("test_tts_gain: alle gruen")
