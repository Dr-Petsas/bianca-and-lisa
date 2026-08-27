from lisa.tts import pcm16_wav


def test_wav_header_und_lauter():
    leise = (80).to_bytes(2, "little", signed=True) * 8
    wav = pcm16_wav(leise, rate=24000, gain=3.2)
    assert wav[:4] == b"RIFF"
    assert wav[8:12] == b"WAVE"
    data = wav[44:]
    probe = int.from_bytes(data[:2], "little", signed=True)
    assert probe == int(80 * 3.2)


def test_clip_nicht_ueber_int16():
    voll = (20000).to_bytes(2, "little", signed=True) * 4
    wav = pcm16_wav(voll, gain=3.2)
    probe = int.from_bytes(wav[44:46], "little", signed=True)
    assert probe == 32767
