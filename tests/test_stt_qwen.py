"""W-STT-QWEN-PARALLEL: 5090-Parakeet bleibt schnell, Qwen prueft parallel.

Alle Tests laufen ohne Netz. Sie beweisen insbesondere: plausible Texte
warten nicht, auffaellige Texte haben einen kleinen harten Zusatzdeckel,
Qwen staut keine Zuege und Whisper/ElevenLabs bleiben aus diesem Pfad draussen.
"""

from __future__ import annotations

import threading
import time

import kern.stt as stt


class _Antwort:
    status_code = 200

    def __init__(self, text: str):
        self.text = text

    def json(self):
        return {"text": self.text}


class _FakeLokal:
    def __init__(self, text: str = "Ich möchte zu Doktor Petsas."):
        self.text = text
        self.aufrufe = []

    def post(self, url, files=None, data=None, **kwargs):
        self.aufrufe.append((url, files or {}, data or {}, kwargs))
        return _Antwort(self.text)


BLOB = b"x" * 2000


def _kandidat(text: str, *, source: str = "qwen", authoritative: bool = True):
    return {
        "text": text,
        "source": source,
        "authoritative": authoritative,
        "reason": "",
    }


def _umgebung(
    fn,
    *,
    qwen_candidate,
    lokal_text="Ich möchte zu Doktor Petsas.",
    stt_base="http://parakeet:8212",
    grace=0.03,
    live_ohr=False,
):
    fake_lokal = _FakeLokal(lokal_text)
    alt = (
        stt.STT_QWEN_BASE,
        stt.STT_QWEN_FINAL_BASE,
        stt.STT_QWEN_KEY,
        stt.STT_QWEN_GRACE_S,
        stt.QWEN_LIVE_OHR,
        stt.STT_WHISPER_BASE,
        stt.STT_BASE,
        stt.ELEVENLABS_API_KEY,
        stt._CLIENT,
        stt._qwen_pause_bis,
        stt._qwen_future,
        stt._qwen_candidate,
        stt._whisper_ws,
        stt._pcm16k,
    )
    stt.STT_QWEN_BASE = "ws://3060-test:8222"
    stt.STT_QWEN_FINAL_BASE = ""
    stt.STT_QWEN_KEY = "qwen-test-token"
    stt.STT_QWEN_GRACE_S = grace
    stt.QWEN_LIVE_OHR = live_ohr
    stt.STT_WHISPER_BASE = "ws://whisper-darf-nicht-laufen:8092"
    stt.STT_BASE = stt_base
    stt.ELEVENLABS_API_KEY = "eleven-darf-nicht-laufen"
    stt._CLIENT = fake_lokal
    stt._qwen_pause_bis = 0.0
    stt._qwen_future = None
    stt._qwen_offen.clear()
    stt._qwen_candidate = qwen_candidate
    stt._pcm16k = lambda audio, mime: b"p" * 4000

    def _whisper_alarm(*args, **kwargs):
        raise AssertionError("Qwen-Modus hat Whisper aufgerufen")

    stt._whisper_ws = _whisper_alarm
    try:
        fn(fake_lokal)
        if stt._qwen_future is not None:
            stt._qwen_future.result(timeout=1)
        for f in list(stt._qwen_offen):
            f.result(timeout=1)
        stt._qwen_offen.clear()
    finally:
        (
            stt.STT_QWEN_BASE,
            stt.STT_QWEN_FINAL_BASE,
            stt.STT_QWEN_KEY,
            stt.STT_QWEN_GRACE_S,
            stt.QWEN_LIVE_OHR,
            stt.STT_WHISPER_BASE,
            stt.STT_BASE,
            stt.ELEVENLABS_API_KEY,
            stt._CLIENT,
            stt._qwen_pause_bis,
            stt._qwen_future,
            stt._qwen_candidate,
            stt._whisper_ws,
            stt._pcm16k,
        ) = alt


def test_plausibles_parakeet_wartet_nicht_auf_qwen():
    release = threading.Event()

    def slow_qwen(_pcm, _keywords=""):
        release.wait(timeout=0.3)
        return _kandidat("Ich möchte zu Doktor Petsas.")

    def lauf(fake_lokal):
        started = time.perf_counter()
        text = stt.transcribe(BLOB, keywords="Petsas,Patrikis")
        elapsed = time.perf_counter() - started
        release.set()
        assert text == "Ich möchte zu Doktor Petsas."
        assert elapsed < 0.1
        assert fake_lokal.aufrufe

    _umgebung(lauf, qwen_candidate=slow_qwen, grace=0.25)


def test_auffaelliges_parakeet_uebernimmt_rechtzeitiges_qwen():
    """Live-Ohr-Pfad (QWEN_LIVE_OHR=1): auffaelliges Parakeet uebernimmt ein
    rechtzeitiges Qwen. Default ist AUS (siehe
    test_korrektor_default_uebernimmt_nie_live)."""
    def lauf(fake_lokal):
        text = stt.transcribe(BLOB, keywords="Röntgenbild")
        assert text == "Ein Röntgenbild."
        assert fake_lokal.aufrufe

    _umgebung(
        lauf,
        lokal_text="Ein Rhön Biepfeld.",
        qwen_candidate=lambda _pcm, _keywords="": _kandidat("Ein Röntgenbild."),
        live_ohr=True,
    )


def test_auffaelliges_parakeet_hat_harten_zusatzdeckel():
    def slow_qwen(_pcm, _keywords=""):
        time.sleep(0.12)
        return _kandidat("Ein Röntgenbild.")

    def lauf(_fake_lokal):
        started = time.perf_counter()
        text = stt.transcribe(BLOB, keywords="Röntgenbild")
        elapsed = time.perf_counter() - started
        assert text == "Bröntgempelt."
        assert elapsed < 0.08

    _umgebung(
        lauf,
        lokal_text="Bröntgempelt.",
        qwen_candidate=slow_qwen,
        grace=0.02,
        live_ohr=True,
    )


def test_qwen_ausfall_laesst_parakeet_sofort_stehen_und_pausiert():
    def kaputt(_pcm, _keywords=""):
        raise RuntimeError("qwen_timeout")

    def lauf(_fake_lokal):
        assert stt.transcribe(BLOB) == "Ich möchte zu Doktor Petsas."
        assert stt._qwen_future is not None
        stt._qwen_future.result(timeout=1)
        assert stt._qwen_pause_bis > time.time()

    _umgebung(lauf, qwen_candidate=kaputt)


def test_laufendes_qwen_staut_keinen_naechsten_zug():
    """Deckel STT_QWEN_PARALLEL=1: solange ein Qwen-Lauf offen ist, geht der
    naechste Zug ohne Qwen — nie aufstauen."""
    release = threading.Event()
    started = threading.Event()
    calls = []

    def slow_qwen(_pcm, _keywords=""):
        calls.append(1)
        started.set()
        release.wait(timeout=0.3)
        return _kandidat("Qwen.")

    def lauf(_fake_lokal):
        alt = stt.STT_QWEN_PARALLEL
        stt.STT_QWEN_PARALLEL = 1
        try:
            assert stt.transcribe(BLOB) == "Ich möchte zu Doktor Petsas."
            assert started.wait(timeout=0.2)
            assert stt.transcribe(BLOB) == "Ich möchte zu Doktor Petsas."
            release.set()
            assert len(calls) == 1
        finally:
            stt.STT_QWEN_PARALLEL = alt

    _umgebung(lauf, qwen_candidate=slow_qwen)


def test_zwei_qwen_laeufe_parallel_dritter_faellt_aus():
    """W-QWEN-KORREKTOR (13.09.2026): der Korrektor braucht JEDEN Zug — mit
    STT_QWEN_PARALLEL=2 startet der zweite Zug seinen eigenen Qwen-Lauf,
    waehrend der erste (Kaltstart) noch rechnet; erst der dritte faellt aus."""
    release = threading.Event()
    gestartet: list[threading.Event] = [threading.Event(), threading.Event()]
    calls = []

    def slow_qwen(_pcm, _keywords=""):
        n = len(calls)
        calls.append(1)
        if n < 2:
            gestartet[n].set()
        release.wait(timeout=0.5)
        return _kandidat("Qwen.")

    def lauf(_fake_lokal):
        alt = stt.STT_QWEN_PARALLEL
        stt.STT_QWEN_PARALLEL = 2
        try:
            assert stt.transcribe(BLOB) == "Ich möchte zu Doktor Petsas."
            assert gestartet[0].wait(timeout=0.2)
            assert stt.transcribe(BLOB) == "Ich möchte zu Doktor Petsas."
            assert gestartet[1].wait(timeout=0.2)
            assert stt.transcribe(BLOB) == "Ich möchte zu Doktor Petsas."
            release.set()
            for f in list(stt._qwen_offen):
                f.result(timeout=1)
            assert len(calls) == 2
        finally:
            stt.STT_QWEN_PARALLEL = alt

    _umgebung(lauf, qwen_candidate=slow_qwen)


def test_spaetes_qwen_wird_nachgetragen_statt_verworfen():
    """W-QWEN-KORREKTOR: kommt Qwen nach dem Live-Deckel, landet sein Text
    ueber `nachtrag` beim Korrektor — mit Parakeets Fassung und dem Marker
    spaet=True. Der Live-Zug selbst wartet nicht."""
    release = threading.Event()
    angekommen = threading.Event()
    nachtraege: list[dict] = []

    def slow_qwen(_pcm, _keywords=""):
        release.wait(timeout=0.5)
        return _kandidat("Ein Röntgenbild.")

    def nachtrag(info: dict) -> None:
        nachtraege.append(info)
        angekommen.set()

    def lauf(_fake_lokal):
        started = time.perf_counter()
        text = stt.transcribe(BLOB, keywords="Röntgenbild", nachtrag=nachtrag)
        assert time.perf_counter() - started < 0.1
        assert text == "Bröntgempelt."
        release.set()
        assert angekommen.wait(timeout=1.0)
        n = nachtraege[0]
        assert n["text"] == "Ein Röntgenbild."
        assert n["parakeet"] == "Bröntgempelt."
        assert n["authoritative"] is True
        assert n["spaet"] is True

    _umgebung(lauf, lokal_text="Bröntgempelt.", qwen_candidate=slow_qwen, grace=0.02)


def test_abgelehntes_qwen_wird_ebenfalls_nachgetragen():
    """Qwen war rechtzeitig, durfte aber nicht uebernehmen (abweichende
    Ziffernfolge — Sicherheitsregel des Live-Ohrs): der Korrektor bekommt es
    trotzdem (spaet=False) — als Zweitmeinung fuer den Fall, dass der Anrufer
    widerspricht. (Der Korrektor selbst lernt aus Ziffern-Abweichungen nie.)"""
    nachtraege: list[dict] = []
    angekommen = threading.Event()
    qwen_fertig = threading.Event()
    parakeet_text = "Meine Nummer ist null eins sieben sieben."
    qwen_text = "Meine Nummer ist null eins sieben acht."

    def qwen(_pcm, _keywords=""):
        qwen_fertig.set()
        return _kandidat(qwen_text)

    def nachtrag(info: dict) -> None:
        nachtraege.append(info)
        angekommen.set()

    def lauf(fake_lokal):
        # Parakeet wartet, bis Qwen fertig ist — so ist der Kandidat beim
        # Entscheid sicher da (rechtzeitig, aber abgelehnt).
        echt = fake_lokal.post

        def langsam(url, files=None, data=None, **kwargs):
            qwen_fertig.wait(timeout=0.5)
            time.sleep(0.02)
            return echt(url, files=files, data=data, **kwargs)

        fake_lokal.post = langsam
        text = stt.transcribe(BLOB, keywords="Petsas", nachtrag=nachtrag)
        assert text == parakeet_text
        assert angekommen.wait(timeout=1.0)
        assert nachtraege[0]["spaet"] is False
        assert nachtraege[0]["text"] == qwen_text
        assert nachtraege[0]["parakeet"] == parakeet_text

    _umgebung(lauf, lokal_text=parakeet_text, qwen_candidate=qwen)


def test_live_sperre_laesst_rechtzeitiges_qwen_nicht_gewinnen():
    """W-QWEN-SICHER (14.09.2026, Anruf 48d3ac3f): der Aufrufer meldet ueber
    `qwen_sperre`, dass der Anrufer gerade auf die NACHNAMEN-Frage antwortet.
    Qwen ist rechtzeitig und wuerde das auffaellige Parakeet sonst
    ueberstimmen — bleibt aber Zweit-Ohr: Parakeets Text gilt, der Kandidat
    geht mit dem Sperr-Grund in den Nachtrag."""
    nachtraege: list[dict] = []
    angekommen = threading.Event()
    qwen_fertig = threading.Event()
    gefragt: list[str] = []

    def qwen(_pcm, _keywords=""):
        qwen_fertig.set()
        return _kandidat("Ein Röntgenbild.")

    def nachtrag(info: dict) -> None:
        nachtraege.append(info)
        angekommen.set()

    def sperre(lokal: str) -> str:
        gefragt.append(lokal)
        return "namensfrage:nachname"

    def lauf(fake_lokal):
        echt = fake_lokal.post

        def langsam(url, files=None, data=None, **kwargs):
            qwen_fertig.wait(timeout=0.5)
            time.sleep(0.02)
            return echt(url, files=files, data=data, **kwargs)

        fake_lokal.post = langsam
        text = stt.transcribe(BLOB, keywords="Röntgenbild", nachtrag=nachtrag,
                              qwen_sperre=sperre)
        assert text == "Ein Rhön Biepfeld."
        assert gefragt == ["Ein Rhön Biepfeld."]  # die Sperre sieht Parakeets Text
        assert angekommen.wait(timeout=1.0)
        n = nachtraege[0]
        assert n["text"] == "Ein Röntgenbild." and n["parakeet"] == "Ein Rhön Biepfeld."
        assert n["spaet"] is False
        assert n["reason"] == "live_gesperrt:namensfrage:nachname"

    _umgebung(lauf, lokal_text="Ein Rhön Biepfeld.", qwen_candidate=qwen,
              live_ohr=True)


def test_live_sperre_wartet_nicht_auf_langsames_qwen():
    """Gesperrter Zug = kein Grace-Warten, auch wenn Parakeet auffaellig ist
    (sonst zahlte jeder Namens-Zug den Zusatzdeckel umsonst). Das spaete
    Qwen landet trotzdem im Nachtrag."""
    release = threading.Event()
    angekommen = threading.Event()
    nachtraege: list[dict] = []

    def slow_qwen(_pcm, _keywords=""):
        release.wait(timeout=0.5)
        return _kandidat("Ein Röntgenbild.")

    def nachtrag(info: dict) -> None:
        nachtraege.append(info)
        angekommen.set()

    def lauf(_fake_lokal):
        started = time.perf_counter()
        text = stt.transcribe(BLOB, keywords="Röntgenbild", nachtrag=nachtrag,
                              qwen_sperre=lambda lokal: "diktat:telefon")
        elapsed = time.perf_counter() - started
        assert text == "Bröntgempelt."
        assert elapsed < 0.1  # trotz grace=0.25 kein Warten
        release.set()
        assert angekommen.wait(timeout=1.0)
        assert nachtraege[0]["spaet"] is True
        assert nachtraege[0]["text"] == "Ein Röntgenbild."

    _umgebung(lauf, lokal_text="Bröntgempelt.", qwen_candidate=slow_qwen, grace=0.25,
              live_ohr=True)


def test_sperre_ohne_grund_aendert_nichts():
    """Leerer Sperr-Grund = Verhalten wie ohne Parameter: auffaelliges
    Parakeet uebernimmt rechtzeitiges Qwen; eine werfende Sperre stoert das
    Ohr nie."""
    def lauf(_fake_lokal):
        assert stt.transcribe(BLOB, keywords="Röntgenbild",
                              qwen_sperre=lambda lokal: "") == "Ein Röntgenbild."

    _umgebung(lauf, lokal_text="Ein Rhön Biepfeld.",
              qwen_candidate=lambda _pcm, _keywords="": _kandidat("Ein Röntgenbild."),
              live_ohr=True)

    def kaputt(lokal: str) -> str:
        raise ValueError("sperre kaputt")

    def lauf2(_fake_lokal):
        assert stt.transcribe(BLOB, keywords="Röntgenbild", qwen_sperre=kaputt) == "Ein Röntgenbild."

    _umgebung(lauf2, lokal_text="Ein Rhön Biepfeld.",
              qwen_candidate=lambda _pcm, _keywords="": _kandidat("Ein Röntgenbild."),
              live_ohr=True)


def test_qwen_only_ohne_parakeet_bleibt_moeglich():
    def lauf(fake_lokal):
        assert stt.transcribe(BLOB) == "Nur Qwen."
        assert not fake_lokal.aufrufe

    _umgebung(
        lauf,
        stt_base="",
        qwen_candidate=lambda _pcm, _keywords="": _kandidat("Nur Qwen."),
    )


def test_kritischer_ziffernkonflikt_bleibt_bei_parakeet():
    assert not stt._qwen_darf_uebernehmen(
        "Meine Nummer ist null eins sieben sieben.",
        _kandidat("Meine Nummer ist null eins sieben acht."),
        True,
    )


def test_direkter_qwen_final_endpoint_traegt_nur_vocabular():
    fake = _FakeLokal("Direktes Qwen.")
    alt = (
        stt.STT_QWEN_FINAL_BASE,
        stt.STT_QWEN_KEY,
        stt._CLIENT,
    )
    try:
        stt.STT_QWEN_FINAL_BASE = "http://3060-test:8223"
        stt.STT_QWEN_KEY = "secret"
        stt._CLIENT = fake
        result = stt._qwen_final_message(b"\x00\x01" * 1000, "Petsas,Röntgen")
    finally:
        stt.STT_QWEN_FINAL_BASE, stt.STT_QWEN_KEY, stt._CLIENT = alt

    url, _files, data, kwargs = fake.aufrufe[0]
    assert url == "http://3060-test:8223/final"
    assert data == {"context": "Vokabular: Petsas, Röntgen."}
    assert kwargs["headers"]["X-Internal-Token"] == "secret"
    assert result["source"] == "qwen"


def test_korrektor_default_uebernimmt_nie_live_speist_aber_nachtrag():
    """Neuer Default (QWEN_LIVE_OHR=0, Chef 18.09.2026): auch ein
    rechtzeitiges, auffaelliges Qwen uebernimmt NIE live — Parakeet ist der
    gesprochene Zug. Der Qwen-Lauf geht trotzdem an den Korrektor (nachtrag)."""
    nachtraege: list[dict] = []
    angekommen = threading.Event()
    qwen_fertig = threading.Event()

    def qwen(_pcm, _keywords=""):
        qwen_fertig.set()
        return _kandidat("Ein Röntgenbild.")

    def nachtrag(info: dict) -> None:
        nachtraege.append(info)
        angekommen.set()

    def lauf(fake_lokal):
        echt = fake_lokal.post

        def langsam(url, files=None, data=None, **kwargs):
            qwen_fertig.wait(timeout=0.5)
            time.sleep(0.02)
            return echt(url, files=files, data=data, **kwargs)

        fake_lokal.post = langsam
        started = time.perf_counter()
        # auffaellig + rechtzeitiges Qwen — im Live-Ohr-Modus wuerde es
        # uebernehmen; als Korrektor bleibt Parakeet stehen.
        text = stt.transcribe(BLOB, keywords="Röntgenbild", nachtrag=nachtrag)
        assert time.perf_counter() - started < 0.2
        assert text == "Ein Rhön Biepfeld."  # Parakeet, NICHT Qwen
        assert angekommen.wait(timeout=1.0)
        assert nachtraege[0]["text"] == "Ein Röntgenbild."
        assert nachtraege[0]["parakeet"] == "Ein Rhön Biepfeld."

    _umgebung(lauf, lokal_text="Ein Rhön Biepfeld.", qwen_candidate=qwen)


def test_korrektor_default_wartet_nie_auf_qwen():
    """Als Korrektor gibt es kein Grace-Warten — auch nicht bei auffaelligem
    Parakeet und langsamem Qwen. Das spaete Qwen landet im Nachtrag."""
    release = threading.Event()
    angekommen = threading.Event()
    nachtraege: list[dict] = []

    def slow_qwen(_pcm, _keywords=""):
        release.wait(timeout=0.5)
        return _kandidat("Ein Röntgenbild.")

    def nachtrag(info: dict) -> None:
        nachtraege.append(info)
        angekommen.set()

    def lauf(_fake_lokal):
        started = time.perf_counter()
        text = stt.transcribe(BLOB, keywords="Röntgenbild", nachtrag=nachtrag)
        assert time.perf_counter() - started < 0.1  # trotz grace=0.25 kein Warten
        assert text == "Bröntgempelt."
        release.set()
        assert angekommen.wait(timeout=1.0)
        assert nachtraege[0]["spaet"] is True

    _umgebung(lauf, lokal_text="Bröntgempelt.", qwen_candidate=slow_qwen, grace=0.25)


def test_qwen_url_und_health_anzeige():
    alt = (
        stt.STT_QWEN_BASE,
        stt.STT_QWEN_FINAL_BASE,
        stt.QWEN_LIVE_OHR,
        stt.STT_WHISPER_BASE,
        stt.STT_BASE,
        stt._qwen_pause_bis,
    )
    try:
        stt.STT_QWEN_BASE = "https://paraqwenstt.pickadoc-tunnel.com/"
        stt.STT_QWEN_FINAL_BASE = ""
        stt.STT_WHISPER_BASE = "ws://whisper:8092"
        stt.STT_BASE = "http://parakeet:8212"
        stt._qwen_pause_bis = 0.0
        assert stt._qwen_ws_url() == (
            "wss://paraqwenstt.pickadoc-tunnel.com/stream"
        )
        assert stt.bereit()
        # Default: Qwen ist Korrektor (offline), nicht Live-Ohr.
        stt.QWEN_LIVE_OHR = False
        assert stt.engine_anzeige() == (
            "Parakeet (lokal) + Qwen3-ASR Korrektor (3060, offline)"
        )
        # Alt-Verhalten mit QWEN_LIVE_OHR=1.
        stt.QWEN_LIVE_OHR = True
        assert stt.engine_anzeige() == (
            "Parakeet (lokal) + Qwen3-ASR parallel (3060)"
        )
        stt._qwen_pause_bis = time.time() + 10
        assert stt.engine_anzeige() == "Parakeet (lokal, Qwen pausiert)"
    finally:
        (
            stt.STT_QWEN_BASE,
            stt.STT_QWEN_FINAL_BASE,
            stt.QWEN_LIVE_OHR,
            stt.STT_WHISPER_BASE,
            stt.STT_BASE,
            stt._qwen_pause_bis,
        ) = alt
