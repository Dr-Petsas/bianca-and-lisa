"""W-STT-WHISPER (30.08.2026): Whisper-GPU-Container auf dem Dev-Rechner
zuerst, bei Nicht-Erreichbarkeit automatischer Rueckfall auf Parakeet
(STT_BASE) — NIE still auf ElevenLabs. Alle Faelle offline (WS und
Parakeet-Client gefaked), nur die WAV-Direktspur nutzt echtes wave."""

from __future__ import annotations

import io
import threading
import time
import wave

import kern.stt as stt


class _Antwort:
    def __init__(self, status_code: int = 200, daten: dict | None = None):
        self.status_code = status_code
        self._daten = daten or {}

    def json(self):
        return self._daten


class _FakeLokal:
    def __init__(self, antwort: _Antwort):
        self.antwort = antwort
        self.aufrufe: list[tuple[str, dict, dict]] = []

    def post(self, url, files=None, data=None, **kw):
        self.aufrufe.append((url, files or {}, data or {}))
        return self.antwort


BLOB = b"x" * 2000


def _wav16k(ms: int = 400) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x01\x00" * (16 * ms))
    return buf.getvalue()


def _umgebung(fn, *, whisper_base="ws://dev-test:8092", stt_base="http://stt-test:8100",
              fake_lokal=None, whisper_ws=None, pcm=b"p" * 4000, eleven_key="",
              qwen_base=""):
    """Modul-Zustand setzen, ElevenLabs verwanzen, danach alles zuruecklegen."""
    alt = (stt.STT_WHISPER_BASE, stt.STT_BASE, stt.STT_QWEN_BASE, stt.ELEVENLABS_API_KEY,
           stt._CLIENT, stt._whisper_pause_bis, stt._whisper_ws, stt._pcm16k,
           stt.httpx.post)
    stt.STT_WHISPER_BASE = whisper_base
    stt.STT_BASE = stt_base
    stt.STT_QWEN_BASE = qwen_base  # Whisper-Tests nie ueber Qwen
    stt.ELEVENLABS_API_KEY = eleven_key
    stt._CLIENT = fake_lokal
    stt._whisper_pause_bis = 0.0
    if whisper_ws is not None:
        stt._whisper_ws = whisper_ws
    if pcm is not None:
        stt._pcm16k = lambda audio, mime: pcm

    def _alarm(*a, **kw):
        raise AssertionError("ElevenLabs angefasst — der Rueckfall ist Parakeet, nie Scribe!")

    stt.httpx.post = _alarm
    try:
        fn()
    finally:
        (stt.STT_WHISPER_BASE, stt.STT_BASE, stt.STT_QWEN_BASE, stt.ELEVENLABS_API_KEY,
         stt._CLIENT, stt._whisper_pause_bis, stt._whisper_ws, stt._pcm16k,
         stt.httpx.post) = alt


def test_whisper_leeres_final_faellt_auf_parakeet_ohne_pause():
    fake = _FakeLokal(_Antwort(200, {"text": "Ja"}))

    def leer(pcm, keywords=""):
        return ""

    def lauf():
        assert stt.transcribe(BLOB) == "Ja"
        assert fake.aufrufe, "leeres Whisper-Final muss Parakeet gegenhoeren"
        assert stt._whisper_pause_bis <= time.time(), (
            "leeres Final darf Whisper NICHT pausieren"
        )

    _umgebung(lauf, fake_lokal=fake, whisper_ws=leer)


def test_whisper_budget_default_spart_weitere_300_ms_bis_zum_ersten_ton():
    # Live 22:18: Whisper-Deckel 1,714 s + serieller Parakeet 0,210 s =
    # 1,883 s. Der 1,55-s-Deckel plus vorgezogener Rueckfall spart im
    # gemessenen Hängefall gut 300 ms; der Morgen-p90 (~1,2 s) bleibt davor.
    assert stt._whisper_budget_s() == 1.55 or stt.STT_WHISPER_BUDGET_S == 1.55
    alt = stt.STT_WHISPER_BUDGET_S
    try:
        stt.STT_WHISPER_BUDGET_S = 0
        assert stt._whisper_budget_s() == 15.0
        stt.STT_WHISPER_BUDGET_S = 1.5
        assert stt._whisper_budget_s() == 1.5
    finally:
        stt.STT_WHISPER_BUDGET_S = alt


def test_parakeet_startet_vor_whisper_timeout_und_ist_sofort_bereit():
    lokal_gestartet = threading.Event()

    class _SignalLokal(_FakeLokal):
        def post(self, url, files=None, data=None, **kw):
            lokal_gestartet.set()
            return super().post(url, files=files, data=data, **kw)

    fake = _SignalLokal(_Antwort(200, {"text": "Parakeet bereit"}))
    alt = (stt.STT_WHISPER_BUDGET_S, stt.WHISPER_FALLBACK_LEAD_S)

    def langsam_kaputt(pcm, keywords=""):
        assert lokal_gestartet.wait(0.5), (
            "Parakeet muss bereits VOR dem Whisper-Fehler anlaufen"
        )
        raise RuntimeError("stt_whisper_timeout")

    def lauf():
        assert stt.transcribe(BLOB) == "Parakeet bereit"
        assert fake.aufrufe
        assert stt._whisper_pause_bis > time.time()

    try:
        stt.STT_WHISPER_BUDGET_S = 0.14
        stt.WHISPER_FALLBACK_LEAD_S = 0.08
        _umgebung(lauf, fake_lokal=fake, whisper_ws=langsam_kaputt)
    finally:
        stt.STT_WHISPER_BUDGET_S, stt.WHISPER_FALLBACK_LEAD_S = alt


def test_knappes_whisper_final_gewinnt_trotz_laufendem_parakeet():
    lokal_gestartet = threading.Event()

    class _SignalLokal(_FakeLokal):
        def post(self, url, files=None, data=None, **kw):
            lokal_gestartet.set()
            return super().post(url, files=files, data=data, **kw)

    fake = _SignalLokal(_Antwort(200, {"text": "Parakeet"}))
    alt = (stt.STT_WHISPER_BUDGET_S, stt.WHISPER_FALLBACK_LEAD_S)

    def knapp(pcm, keywords=""):
        assert lokal_gestartet.wait(0.5)
        return "Whisper genauer"

    def lauf():
        assert stt.transcribe(BLOB) == "Whisper genauer"
        assert stt._whisper_pause_bis <= time.time()

    try:
        stt.STT_WHISPER_BUDGET_S = 0.14
        stt.WHISPER_FALLBACK_LEAD_S = 0.08
        _umgebung(lauf, fake_lokal=fake, whisper_ws=knapp)
    finally:
        stt.STT_WHISPER_BUDGET_S, stt.WHISPER_FALLBACK_LEAD_S = alt


def test_whisper_zuerst_parakeet_bleibt_unberuehrt():
    fake = _FakeLokal(_Antwort(200, {"text": "sollte nie gefragt werden"}))

    def lauf():
        text = stt.transcribe(BLOB, keywords="Petsas")
        assert text == "Ich haette gern einen Termin."
        assert not fake.aufrufe, "Whisper war gesund — Parakeet darf nicht angefragt werden"

    _umgebung(lauf, fake_lokal=fake,
              whisper_ws=lambda pcm, keywords="": "  Ich   haette gern einen Termin. ")


def test_whisper_ausfall_faellt_auf_parakeet_und_pausiert():
    fake = _FakeLokal(_Antwort(200, {"text": "Parakeet hat uebernommen"}))

    def kaputt(pcm, keywords=""):
        raise RuntimeError("stt_whisper_timeout")

    def lauf():
        text = stt.transcribe(BLOB)
        assert text == "Parakeet hat uebernommen"
        assert fake.aufrufe, "Rueckfall muss den Parakeet-Container fragen"
        assert stt._whisper_pause_bis > time.time(), "Ausfall muss die Whisper-Pause setzen"

    _umgebung(lauf, fake_lokal=fake, whisper_ws=kaputt)


def test_whisper_pause_geht_direkt_zu_parakeet():
    fake = _FakeLokal(_Antwort(200, {"text": "direkt Parakeet"}))

    def nie(pcm, keywords=""):
        raise AssertionError("Whisper darf in der Pause nicht angefasst werden")

    def lauf():
        stt._whisper_pause_bis = time.time() + 10
        assert stt.transcribe(BLOB) == "direkt Parakeet"

    _umgebung(lauf, fake_lokal=fake, whisper_ws=nie)


def test_whisper_ausfall_ohne_parakeet_wirft_statt_scribe():
    def kaputt(pcm, keywords=""):
        raise RuntimeError("stt_whisper_timeout")

    def lauf():
        try:
            stt.transcribe(BLOB)
            raise AssertionError("RuntimeError erwartet")
        except RuntimeError as e:
            assert "stt_whisper" in str(e)

    _umgebung(lauf, stt_base="", eleven_key="key-vorhanden", whisper_ws=kaputt)


def test_nachkorrektur_laeuft_auf_dem_whisper_pfad():
    def lauf():
        text = stt.transcribe(BLOB, keywords="Petsas,Nikolaou,Patrikis")
        assert "Petsas" in text, text

    _umgebung(lauf, whisper_ws=lambda pcm, keywords="": "Ich moechte zu Doktor Betsas bitte")


def test_kyrillische_halluzination_auch_bei_whisper_verworfen():
    def lauf():
        assert stt.transcribe(BLOB) == ""

    # ohne Parakeet-Gegenhoeren: nur Whisper-Wache pruefen
    _umgebung(lauf, stt_base="",
              whisper_ws=lambda pcm, keywords="": "Продолжение следует")


def test_ws_url_normalisierung():
    alt = stt.STT_WHISPER_BASE
    try:
        for basis, soll in [
            ("http://100.81.214.94:8092", "ws://100.81.214.94:8092/stream"),
            ("https://stt.beispiel.de", "wss://stt.beispiel.de/stream"),
            ("ws://dev:8092/", "ws://dev:8092/stream"),
            ("100.81.214.94:8092", "ws://100.81.214.94:8092/stream"),
        ]:
            stt.STT_WHISPER_BASE = basis
            assert stt._ws_url() == soll, (basis, stt._ws_url())
    finally:
        stt.STT_WHISPER_BASE = alt


def test_pcm_passendes_wav_geht_ohne_ffmpeg():
    blob = _wav16k(400)
    alt = stt.subprocess.run

    def _alarm(*a, **kw):
        raise AssertionError("ffmpeg angeworfen, obwohl das WAV schon passt")

    stt.subprocess.run = _alarm
    try:
        pcm = stt._pcm16k(blob, "audio/wav")
        assert pcm == b"\x01\x00" * (16 * 400)
    finally:
        stt.subprocess.run = alt


def test_winzige_pcm_spur_hoert_nichts():
    def nie(pcm, keywords=""):
        raise AssertionError("unter 50 ms darf der Container nicht gefragt werden")

    def lauf():
        assert stt.transcribe(BLOB) == ""

    _umgebung(lauf, whisper_ws=nie, pcm=b"p" * 100, stt_base="")


def test_bereit_und_anzeige_mit_whisper():
    alt = (stt.STT_WHISPER_BASE, stt.STT_BASE, stt.ELEVENLABS_API_KEY,
           stt._whisper_pause_bis)
    try:
        stt.STT_WHISPER_BASE = "ws://dev-test:8092"
        stt.STT_BASE = ""
        stt.ELEVENLABS_API_KEY = ""
        stt._whisper_pause_bis = 0.0
        assert stt.bereit(), "STT_WHISPER_BASE allein muss reichen"
        assert "Whisper" in stt.engine_anzeige()
        stt.STT_BASE = "http://stt-test:8100"
        assert "Rueckfall" in stt.engine_anzeige()
        stt._whisper_pause_bis = time.time() + 10
        assert "pausiert" in stt.engine_anzeige()
    finally:
        (stt.STT_WHISPER_BASE, stt.STT_BASE, stt.ELEVENLABS_API_KEY,
         stt._whisper_pause_bis) = alt


if __name__ == "__main__":
    test_whisper_zuerst_parakeet_bleibt_unberuehrt()
    test_whisper_ausfall_faellt_auf_parakeet_und_pausiert()
    test_whisper_pause_geht_direkt_zu_parakeet()
    test_whisper_ausfall_ohne_parakeet_wirft_statt_scribe()
    test_whisper_leeres_final_faellt_auf_parakeet_ohne_pause()
    test_whisper_budget_default_spart_weitere_300_ms_bis_zum_ersten_ton()
    test_parakeet_startet_vor_whisper_timeout_und_ist_sofort_bereit()
    test_knappes_whisper_final_gewinnt_trotz_laufendem_parakeet()
    test_nachkorrektur_laeuft_auf_dem_whisper_pfad()
    test_kyrillische_halluzination_auch_bei_whisper_verworfen()
    test_ws_url_normalisierung()
    test_pcm_passendes_wav_geht_ohne_ffmpeg()
    test_winzige_pcm_spur_hoert_nichts()
    test_bereit_und_anzeige_mit_whisper()
    print("test_stt_whisper: alle Faelle bestanden")
