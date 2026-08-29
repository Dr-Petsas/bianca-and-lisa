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


def test_ziffernketten_gehen_als_einzelziffern_an_den_container():
    """CosyVoice verschmilzt wiederholte Zahlwoerter ('null null' -> ein
    'null') — live 29.08.2026 verlor die Nummern-Rueckbestaetigung Ziffern.
    Der lokale Mund bekommt Ketten deshalb als Einzelziffern ('0 1 7 7');
    Uhrzeiten und Einzel-Zahlwoerter bleiben unberuehrt."""
    assert tts._ziffern_einzeln(
        "Ich wiederhole die Nummer: null eins sieben sieben, sechs null null, "
        "vier sechs, null null. Stimmt das so?"
    ) == "Ich wiederhole die Nummer: 0 1 7 7, 6 0 0, 4 6, 0 0. Stimmt das so?"
    assert tts._ziffern_einzeln("Ihr Termin ist um neun Uhr fünfzehn.") == \
        "Ihr Termin ist um neun Uhr fünfzehn."
    assert tts._ziffern_einzeln("Es ist nur eins frei.") == "Es ist nur eins frei."

    from kern import config as cfg

    leise = (2000).to_bytes(2, "little", signed=True) * (tts.MIN_AKTIV_SAMPLES * 2)
    fake = _FakeLokal(_Antwort(200, leise))

    def lauf():
        alt = cfg.STT_BASE
        cfg.STT_BASE = ""  # ohne lokales STT: kein Nachhoeren, genau EIN Post
        try:
            tts.LokalTts().speak("Die Nummer lautet null eins sieben sieben.")
        finally:
            cfg.STT_BASE = alt
        _, payload = fake.aufrufe[0]
        assert payload["text"] == "Die Nummer lautet 0 1 7 7."
        assert len(fake.aufrufe) == 1

    _mit_lokal(fake, lauf)


def test_ziffern_nachhoeren_rendert_neu_bis_alle_ziffern_da_sind():
    """Nachhoer-Waechter (29.08.2026): riss die gesprochene Nummer ab (E2E:
    '017760' statt 01776004600), wird neu gerendert — erst der Wurf, den
    Parakeet vollstaendig gegenhoert, geht raus."""
    from kern import config as cfg
    from kern import stt as stt_mod

    leise = (2000).to_bytes(2, "little", signed=True) * (tts.MIN_AKTIV_SAMPLES * 2)
    fake = _FakeLokal(_Antwort(200, leise))
    gehoert = iter(["null eins sieben sieben, sechs null", "0177 600 4600"])

    def lauf():
        alt_base, alt_tr = cfg.STT_BASE, stt_mod.transcribe
        cfg.STT_BASE = "http://stt-test:8212"
        stt_mod.transcribe = lambda *a, **k: next(gehoert)
        try:
            wav = tts.LokalTts().speak(
                "Ich wiederhole die Nummer: null eins sieben sieben, "
                "sechs null null, vier sechs, null null.")
        finally:
            cfg.STT_BASE, stt_mod.transcribe = alt_base, alt_tr
        assert len(fake.aufrufe) == 2, "erster Wurf unvollstaendig -> genau ein zweiter"
        assert wav[:4] == b"RIFF"

    _mit_lokal(fake, lauf)


def test_warm_gegenhoeren_score():
    """Warm-Abnahme (29.08.2026): Parakeet hoert Warm-Renders gegen — Babble
    ('hissio') faellt durch, ein korrekter Render besteht, ohne lokales STT
    wird nicht geprueft (None)."""
    from kern import config as cfg
    from kern import stt as stt_mod

    alt_base, alt_tr = cfg.STT_BASE, stt_mod.transcribe
    wav = tts._wav_header(4, tts.PCM_RATE) + b"\x00\x00\x00\x00"
    satz = "Waren Sie denn schon einmal bei uns in der Praxis?"
    try:
        cfg.STT_BASE = "http://stt-test:8212"
        stt_mod.transcribe = lambda *a, **k: "waren sie denn schon einmal bei uns in der praxis"
        assert tts._warm_score(satz, wav) >= 0.99
        stt_mod.transcribe = lambda *a, **k: "hissio hissio was"
        assert tts._warm_score(satz, wav) < tts._WARM_CHECK_MIN
        cfg.STT_BASE = ""
        assert tts._warm_score(satz, wav) is None, "ohne lokales STT keine Pruefung"
    finally:
        cfg.STT_BASE, stt_mod.transcribe = alt_base, alt_tr


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


class _StreamAntwort:
    def __init__(self, status_code: int, stuecke: list[bytes]):
        self.status_code = status_code
        self._stuecke = stuecke

    def iter_bytes(self):
        yield from self._stuecke

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_wav_header_offen_fuer_progressive_wiedergabe():
    """Phase 2 (29.08.2026): der Stream-WAV traegt UNBEKANNTE Laengen
    (0xFFFFFFFF) — Browser spielen ihn, waehrend noch Daten kommen."""
    h = tts.wav_header_offen()
    assert h[:4] == b"RIFF" and h[8:12] == b"WAVE"
    assert h[4:8] == b"\xff\xff\xff\xff" and h[-4:] == b"\xff\xff\xff\xff"
    assert int.from_bytes(h[24:28], "little") == tts.PCM_RATE
    assert len(h) == 44


def test_ziffern_satz_erkennt_readbacks():
    """Ziffern-Saetze bleiben blocking (Nachhoer-Waechter braucht das ganze
    Audio) — alles andere darf streamen."""
    assert tts.ziffern_satz("Ich wiederhole die Nummer: null eins sieben sieben, sechs null null.")
    assert not tts.ziffern_satz("Waren Sie denn schon einmal bei uns in der Praxis?")
    assert not tts.ziffern_satz("Ihr Termin ist um neun Uhr fünfzehn.")


def test_speak_stream_liefert_stuecke_und_fuellt_den_cache():
    """Audio-Chunk-Streaming: Stuecke kommen sample-sauber (gerade Bytes)
    raus, der fertige Satz liegt danach als EIN WAV im LRU — die
    Wiederholung kostet keinen zweiten Container-Aufruf."""
    pcm = (1500).to_bytes(2, "little", signed=True) * 4  # 8 Bytes = 4 Samples
    fake = _FakeLokal(_Antwort(200, pcm))
    fake.stream_aufrufe = []

    def stream(methode, url, json=None, **kw):
        fake.stream_aufrufe.append((url, json or {}))
        # ungerader Schnitt: 3 + 5 Bytes — der Rest-Uebertrag muss die
        # Sample-Grenze wiederherstellen
        return _StreamAntwort(200, [pcm[:3], pcm[3:]])

    fake.stream = stream

    def lauf():
        eng = tts.LokalTts()
        stuecke = list(eng.speak_stream("Passt Ihnen der Termin am Montag?"))
        assert b"".join(stuecke) == pcm, "alle Samples, nichts verschluckt"
        assert all(len(s) % 2 == 0 for s in stuecke), "nie mitten im Sample schneiden"
        assert len(fake.stream_aufrufe) == 1
        # Wiederholung: kommt als EIN Stueck aus dem Cache, kein neuer Aufruf
        wieder = list(eng.speak_stream("Passt Ihnen der Termin am Montag?"))
        assert len(fake.stream_aufrufe) == 1 and len(fake.aufrufe) == 0
        assert b"".join(wieder) == pcm

    _mit_lokal(fake, lauf)


def test_stimme_stream_dienst_pfad_und_blocking_rueckfall():
    """Dienst.stimme_stream: mit stream-faehigem Container kommt SOFORT eine
    /api/audio-stream/-URL, der Feeder fuellt den Slot im Hintergrund und
    audio_stream_iter liefert Header + alle Stuecke. Ohne Stream-Faehigkeit
    faellt alles auf den blocking Pfad (/api/audio/) zurueck."""
    from kern import dienst as dienst_mod

    d = dienst_mod.Dienst(name="test", start_fn=lambda sit: {}, turn_fn=lambda sit, t, **k: {})
    pcm = (1500).to_bytes(2, "little", signed=True) * 8

    class _EngineFake:
        def speak(self, text):
            return tts._wav_header(len(pcm), tts.PCM_RATE) + pcm

        def speak_stream(self, text):
            yield pcm[:6]
            yield pcm[6:]

    alt = (tts.TTS_BASE, tts.stream_bereit, tts.engine, tts.im_cache)
    tts.TTS_BASE = "http://tts-test:8100"
    tts.engine = lambda: _EngineFake()
    tts.im_cache = lambda text: False
    try:
        tts.stream_bereit = lambda: True
        url, _ = d.stimme_stream("Passt Ihnen der Termin am Montag? Oder lieber Dienstag?")
        assert url.startswith("/api/audio-stream/") and url.endswith(".wav")
        gen = d.audio_stream_iter(url.rsplit("/", 1)[1])
        teile = list(gen)
        assert teile[0][:4] == b"RIFF", "erstes Stueck ist der offene Header"
        assert b"".join(teile[1:]) == pcm + pcm, "beide Saetze vollstaendig im Strom"
        assert d.audio_stream_iter("gibtsnicht.wav") is None

        tts.stream_bereit = lambda: False
        url2, _ = d.stimme_stream("Passt Ihnen der Termin am Montag?")
        assert url2.startswith("/api/audio/"), "ohne Container-Stream: blocking wie bisher"
    finally:
        (tts.TTS_BASE, tts.stream_bereit, tts.engine, tts.im_cache) = alt


def test_stimme_stream_ziffern_satz_bleibt_verifiziert_blocking():
    """Ein Readback-Satz MITTEN im Text laeuft weiter durch speak() (mit
    Nachhoer-Waechter) und wird als fertiges Stueck in den Strom gelegt —
    gestreamt wird nur der Rest."""
    from kern import dienst as dienst_mod

    d = dienst_mod.Dienst(name="test", start_fn=lambda sit: {}, turn_fn=lambda sit, t, **k: {})
    pcm = (1500).to_bytes(2, "little", signed=True) * 8
    rufe: list[str] = []

    class _EngineFake:
        def speak(self, text):
            rufe.append(("speak", text))
            return tts._wav_header(len(pcm), tts.PCM_RATE) + pcm

        def speak_stream(self, text):
            rufe.append(("stream", text))
            yield pcm

    alt = (tts.TTS_BASE, tts.stream_bereit, tts.engine, tts.im_cache)
    tts.TTS_BASE = "http://tts-test:8100"
    tts.engine = lambda: _EngineFake()
    tts.im_cache = lambda text: False
    try:
        tts.stream_bereit = lambda: True
        url, _ = d.stimme_stream(
            "Ich wiederhole die Nummer: null eins sieben sieben, sechs null null. "
            "Stimmt das so?")
        assert url.startswith("/api/audio-stream/")
        list(d.audio_stream_iter(url.rsplit("/", 1)[1]))  # Feeder zu Ende laufen lassen
        arten = {art for art, _ in rufe}
        assert ("speak", "Ich wiederhole die Nummer: null eins sieben sieben, sechs null null.") in rufe
        assert any(art == "stream" for art in arten), "der Nicht-Ziffern-Satz streamt"
        for art, text in rufe:
            if "null eins" in text:
                assert art == "speak", "Readback NIE am Waechter vorbei streamen"
    finally:
        (tts.TTS_BASE, tts.stream_bereit, tts.engine, tts.im_cache) = alt


def test_stimme_stream_readback_vorsatz_spielt_sofort():
    """P1 Readback-Parallelisierung (29.08.2026): Vorsatz und Schlussfrage
    liegen im Pin-Cache, der Ziffern-Satz wird verifiziert nachgeschoben —
    der Text streamt TROTZDEM (frueher: komplett blocking, 1,5-2,3 s bis
    zum ersten Ton). Ein Text, der direkt mit dem Ziffern-Satz beginnt,
    bleibt auf dem bewaehrten Blocking-Pfad."""
    from bianca import gehirn
    from kern import dienst as dienst_mod

    d = dienst_mod.Dienst(name="test", start_fn=lambda sit: {}, turn_fn=lambda sit, t, **k: {})
    pcm = (1500).to_bytes(2, "little", signed=True) * 8
    rufe: list[tuple[str, str]] = []

    class _EngineFake:
        def speak(self, text):
            rufe.append(("speak", text))
            return tts._wav_header(len(pcm), tts.PCM_RATE) + pcm

        def speak_stream(self, text):
            rufe.append(("stream", text))
            yield pcm

    gecacht = {"Ich wiederhole die Nummer.", "Stimmt das so?"}
    alt = (tts.TTS_BASE, tts.stream_bereit, tts.engine, tts.im_cache)
    tts.TTS_BASE = "http://tts-test:8100"
    tts.engine = lambda: _EngineFake()
    tts.im_cache = lambda text: text in gecacht
    try:
        tts.stream_bereit = lambda: True
        text = gehirn.readback_text("01776004600")
        url, _ = d.stimme_stream(text)
        assert url.startswith("/api/audio-stream/"), "Vorsatz im Cache => Strom lohnt"
        list(d.audio_stream_iter(url.rsplit("/", 1)[1]))  # Feeder zu Ende laufen lassen
        assert rufe and rufe[0] == ("speak", "Ich wiederhole die Nummer."), \
            "der gewaermte Vorsatz spielt ZUERST"
        for art, t in rufe:
            if "eins" in t.lower():
                assert art == "speak", "Ziffern NIE am Waechter vorbei streamen"

        # Nur der Ziffern-Satz allein: kein Gewinn durch den Strom => blocking.
        rufe.clear()
        url2, _ = d.stimme_stream("Null eins sieben sieben, sechs null null.")
        assert url2.startswith("/api/audio/")
    finally:
        (tts.TTS_BASE, tts.stream_bereit, tts.engine, tts.im_cache) = alt


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
    print("test_tts_lokal: alle gruen")
