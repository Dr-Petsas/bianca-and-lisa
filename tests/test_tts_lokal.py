"""LokalTts (kern/tts.py): Container-Anbindung ohne ElevenLabs-Rueckfall.

Vertrag (Chef 27.08.2026): Ist TTS_BASE gesetzt, spricht NUR der lokale
Container. Schlaegt er fehl, fliegt RuntimeError — es gibt KEINEN stillen
Rueckfall auf ElevenLabs, der Fehler soll in der Testphase hoerbar sein.
"""

from __future__ import annotations

from kern import tts


class _Antwort:
    def __init__(self, status_code: int = 200, content: bytes = b""):
        self.status_code = status_code
        self.content = content
        self.text = ""


class _FakeLokal:
    def __init__(self, antwort: _Antwort):
        self.antwort = antwort
        self.aufrufe: list[tuple[str, dict]] = []

    def post(self, url, json=None, **kw):
        self.aufrufe.append((url, json or {}))
        return self.antwort


class _ElevenWaechter:
    """Schlaegt Alarm, wenn der ElevenLabs-Client trotz TTS_BASE benutzt wird."""

    def post(self, *a, **kw):
        raise AssertionError("ElevenLabs angefasst, obwohl TTS_BASE gesetzt ist (kein Fallback!)")


def _mit_lokal(fake: _FakeLokal, fn) -> None:
    alt = (tts.TTS_BASE, tts._LOKAL_CLIENT, tts._CLIENT, tts._VOICE_NAME, tts._VOICE_ID)
    tts.TTS_BASE = "http://tts-test:8100"
    tts._LOKAL_CLIENT = fake
    tts._CLIENT = _ElevenWaechter()
    tts._CACHE.clear()
    tts._CACHE_ORD.clear()
    try:
        fn()
    finally:
        (tts.TTS_BASE, tts._LOKAL_CLIENT, tts._CLIENT, tts._VOICE_NAME, tts._VOICE_ID) = alt
        tts._CACHE.clear()
        tts._CACHE_ORD.clear()


def test_engine_wahl_und_bereit():
    alt = tts.TTS_BASE
    try:
        tts.TTS_BASE = ""
        assert tts.engine().name == "elevenlabs"
        tts.TTS_BASE = "http://tts-test:8100"
        assert tts.engine().name == "lokal"
        assert tts.bereit(), "TTS_BASE allein muss reichen (auch ohne ElevenLabs-Key)"
    finally:
        tts.TTS_BASE = alt


def test_speak_postet_stimme_und_pegelt():
    leise = (2000).to_bytes(2, "little", signed=True) * 8
    fake = _FakeLokal(_Antwort(200, leise))

    def lauf():
        tts.set_voice("egal-id", name="bianca")
        wav = tts.LokalTts().speak("Guten Tag, was kann ich für Sie tun?")
        url, payload = fake.aufrufe[0]
        assert url == "http://tts-test:8100/speak"
        assert payload["voice"] == "bianca"
        assert payload["text"].startswith("Guten Tag")
        assert wav[:4] == b"RIFF", "Rueckgabe ist WAV (fuer die Audio-Ablage)"
        probe = int.from_bytes(wav[44:46], "little", signed=True)
        assert probe == int(2000 * tts.MAX_ANHEBUNG), "Demo-Clara-Pegel auch fuer lokale Zuege"

    _mit_lokal(fake, lauf)


def test_fehler_wirft_und_faellt_nie_auf_elevenlabs_zurueck():
    fake = _FakeLokal(_Antwort(503, b""))

    def lauf():
        try:
            tts.LokalTts().speak("Hallo?")
            raise AssertionError("503 muss RuntimeError werden")
        except RuntimeError as e:
            assert "tts_lokal_http_503" in str(e)

    _mit_lokal(fake, lauf)


def test_cache_erspart_zweiten_aufruf():
    pcm = (12000).to_bytes(2, "little", signed=True) * 8
    fake = _FakeLokal(_Antwort(200, pcm))

    def lauf():
        eng = tts.LokalTts()
        a = eng.speak("Einen kleinen Moment bitte.")
        b = eng.speak("Einen kleinen Moment bitte.")
        assert a == b and len(fake.aufrufe) == 1, "zweiter Satz kommt aus dem Cache"

    _mit_lokal(fake, lauf)


def test_aussprache_umschrift_auch_lokal():
    pcm = (12000).to_bytes(2, "little", signed=True) * 8
    fake = _FakeLokal(_Antwort(200, pcm))

    def lauf():
        tts.LokalTts().speak("Sie sind bei Doktor Michael Petsas eingetragen.")
        _, payload = fake.aufrufe[0]
        assert "Micha-el" in payload["text"], "deutsche Silbentrennung auch am lokalen TTS"

    _mit_lokal(fake, lauf)


def test_dauerhaft_cache_ueberlebt_neustart(tmp_path=None):
    """Fueller werden EINMAL synthetisiert; nach Prozess-Neustart (RAM-Cache
    leer) kommen sie von der Platte — kein zweiter /speak-Aufruf."""
    import tempfile
    from pathlib import Path

    pcm = (12000).to_bytes(2, "little", signed=True) * 8
    fake = _FakeLokal(_Antwort(200, pcm))

    def lauf():
        with tempfile.TemporaryDirectory() as d:
            alt_dir = tts._DISK_DIR
            tts._DISK_DIR = Path(d)
            try:
                a = tts.speak_dauerhaft("Einen Moment bitte.")
                assert len(fake.aufrufe) == 1 and a[:4] == b"RIFF"
                dateien = list(Path(d).glob("*.wav"))
                assert len(dateien) == 1, "Blob liegt als WAV auf der Platte"
                # Neustart simulieren: RAM-Cache weg, Platte bleibt.
                tts._CACHE.clear()
                tts._CACHE_ORD.clear()
                b = tts.speak_dauerhaft("Einen Moment bitte.")
                assert b == a, "identisches Audio von der Platte"
                assert len(fake.aufrufe) == 1, "KEINE zweite Synthese nach Neustart"
            finally:
                tts._DISK_DIR = alt_dir

    _mit_lokal(fake, lauf)


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
    print("test_tts_lokal: alle gruen")
