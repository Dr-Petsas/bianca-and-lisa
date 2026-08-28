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
    tts._FEST.clear()
    try:
        fn()
    finally:
        (tts.TTS_BASE, tts._LOKAL_CLIENT, tts._CLIENT, tts._VOICE_NAME, tts._VOICE_ID) = alt
        tts._CACHE.clear()
        tts._CACHE_ORD.clear()
        tts._FEST.clear()


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
    leise = (2000).to_bytes(2, "little", signed=True) * (tts.MIN_AKTIV_SAMPLES * 2)
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
        erwartet = int(2000 * min(tts.MAX_GAIN, tts.ZIEL_RMS * 32767.0 / 2000))
        assert probe == erwartet, "Lautheits-Angleichung auch fuer lokale Zuege"

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


class _FakeStreamAntwort:
    """Nachbau von httpx.Client.stream(...) als Kontextmanager."""

    def __init__(self, status_code: int, chunks: list[bytes]):
        self.status_code = status_code
        self._chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_bytes(self):
        yield from self._chunks


def test_speak_stream_liefert_wav_haeppchen_mit_festem_gain():
    # Zwei Chunks à 1,2 s: erst leise (2000), dann laut (8000). Der Gain wird
    # aus dem ERSTEN sprach-aktiven Stück bestimmt und festgehalten — das
    # zweite Häppchen bekommt DENSELBEN Faktor (kein Pumpen in der Äußerung).
    # Chunk 1 liegt über der Start-Schwelle (0,5 s) und geht sofort raus,
    # Chunk 2 erreicht die Folge-Schwelle (= bisher gesendete 1,2 s) exakt.
    n = int(1.2 * 24000)
    leise = (2000).to_bytes(2, "little", signed=True) * n
    laut = (8000).to_bytes(2, "little", signed=True) * n
    fake = _FakeLokal(_Antwort(200, b""))
    fake.stream = lambda *a, **kw: _FakeStreamAntwort(200, [leise, laut])

    def lauf():
        wavs = list(tts.LokalTts().speak_stream("Ein Satz für den Stream."))
        assert len(wavs) == 2 and all(w[:4] == b"RIFF" for w in wavs)
        gain = min(tts.MAX_GAIN, tts.ZIEL_RMS * 32767.0 / 2000)
        # Probe aus der Stück-MITTE — die Ränder tragen 2-ms-Rampen.
        mitte = 44 + ((n // 2) * 2)
        probe1 = int.from_bytes(wavs[0][mitte:mitte + 2], "little", signed=True)
        probe2 = int.from_bytes(wavs[1][mitte:mitte + 2], "little", signed=True)
        assert probe1 == int(2000 * gain), "Gain aus dem ersten Häppchen"
        assert probe2 == int(8000 * gain), "zweites Häppchen mit DEMSELBEN Gain"
        rand = int.from_bytes(wavs[0][44:46], "little", signed=True)
        assert rand == 0, "Fade-in: erstes Sample still (kein Klick an der Naht)"

    _mit_lokal(fake, lauf)


def test_speak_stream_erstes_haeppchen_klein_dann_verdoppelnd():
    # Fahrplan (28.08.2026): erstes Häppchen ab 0,5 s raus (schneller
    # Sprechstart), danach darf jedes Stück höchstens auf das bisher
    # Gesendete anwachsen — 0,6 s / 0,6 s / 1,2 s statt alles erst bei 1,2 s.
    einzel = (3000).to_bytes(2, "little", signed=True)
    chunk = einzel * int(0.6 * 24000)
    fake = _FakeLokal(_Antwort(200, b""))
    fake.stream = lambda *a, **kw: _FakeStreamAntwort(200, [chunk, chunk, chunk, chunk])

    def lauf():
        wavs = list(tts.LokalTts().speak_stream("Fahrplan-Probe."))
        laengen = [round((len(w) - 44) / 2 / 24000, 2) for w in wavs]
        assert laengen[0] == 0.6, f"erstes Häppchen sofort ab 0,5 s: {laengen}"
        assert laengen == [0.6, 0.6, 1.2], f"verdoppelnd bis zur Zielgröße: {laengen}"

    _mit_lokal(fake, lauf)


def test_speak_stream_schneidet_nie_mitten_im_sample():
    # HTTP-Chunks mit UNGERADEN Grenzen (wie live per TCP): kein Stück darf
    # eine ungerade Byte-Zahl tragen, und ausser hoechstens einem halben
    # Sample am Strom-Ende darf nichts verloren gehen — sonst verschiebt
    # sich der Reststrom um 1 Byte und wird zu Rauschen (live 28.08.2026).
    einzel = (3000).to_bytes(2, "little", signed=True)
    strom = einzel * int(2.0 * 24000)
    grenzen = [14593, 8761, 17519, len(strom) - 14593 - 8761 - 17519]
    chunks, pos = [], 0
    for g in grenzen:
        chunks.append(strom[pos:pos + g])
        pos += g
    fake = _FakeLokal(_Antwort(200, b""))
    fake.stream = lambda *a, **kw: _FakeStreamAntwort(200, chunks)

    def lauf():
        wavs = list(tts.LokalTts().speak_stream("Ungerade Grenzen."))
        nutz = sum(len(w) - 44 for w in wavs)
        assert all((len(w) - 44) % 2 == 0 for w in wavs), "nur ganze Samples je Stück"
        assert nutz >= len(strom) - 2, f"Strom fast verlustfrei: {nutz} von {len(strom)}"
        for w in wavs:
            mitte = 44 + ((len(w) - 44) // 4) * 2
            probe = int.from_bytes(w[mitte:mitte + 2], "little", signed=True)
            assert probe > 0, "kein Byte-Versatz: Samples bleiben positiv (3000er-Strom)"

    _mit_lokal(fake, lauf)


def test_speak_stream_fehler_wirft():
    fake = _FakeLokal(_Antwort(200, b""))
    fake.stream = lambda *a, **kw: _FakeStreamAntwort(503, [])

    def lauf():
        try:
            list(tts.LokalTts().speak_stream("Hallo?"))
            raise AssertionError("503 muss RuntimeError werden")
        except RuntimeError as e:
            assert "tts_lokal_stream_http_503" in str(e)

    _mit_lokal(fake, lauf)


def test_gewarmte_saetze_ueberleben_den_lru_druck():
    """Gepinnter Cache (28.08.2026): dauerhaft gewarmte Sätze (Füller,
    Begrüßung, feste Maschinen-Fragen) dürfen nicht von dynamischen
    Antworten aus dem 48er-LRU gedrängt werden — sonst spricht die Maschine
    mitten im Gespräch wieder mit voller Synthese-Latenz."""
    import tempfile
    from pathlib import Path

    pcm = (12000).to_bytes(2, "little", signed=True) * 8
    fake = _FakeLokal(_Antwort(200, pcm))
    frage = "Waren Sie denn schon einmal bei uns in der Praxis?"

    def lauf():
        with tempfile.TemporaryDirectory() as d:
            alt_dir = tts._DISK_DIR
            tts._DISK_DIR = Path(d)
            try:
                tts.speak_dauerhaft(frage)
                eng = tts.LokalTts()
                for i in range(60):
                    eng.speak(f"Dynamische Antwort Nummer {i}, ganz frisch erzeugt.")
                assert tts.im_cache(frage), "gepinnter Satz fiel aus dem RAM-Cache"
            finally:
                tts._DISK_DIR = alt_dir

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
                # Neustart simulieren: RAM-Cache (LRU UND Pins) weg, Platte bleibt.
                tts._CACHE.clear()
                tts._CACHE_ORD.clear()
                tts._FEST.clear()
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
