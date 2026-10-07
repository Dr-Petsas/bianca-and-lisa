"""W-JA-RETTUNG (07.10.2026): Parakeet hoert ein deutsches "Ja" als "Yeah."

Am 06.10. verwarf die Sprachwache 451 Zuege, die meisten auf Ja/Nein-Fragen
— daraus entstanden die doppelten Identitaetsfragen ("Habe ich Sie richtig
erkannt?" dreimal). Qwen hoerte dieselben Aufnahmen als "ja". Gerettet wird
nur im Ja/Nein-Kontext und nur mit Qwens eigenem deutschem Text; die
Gegenproben (Englisch bleibt verworfen, nichts wird uebersetzt oder gelernt)
sind der wichtigere Teil.
"""

from __future__ import annotations

import time

import kern.stt as stt
import kern.stt_spur as stt_spur
from tests.test_stt_qwen import BLOB, _kandidat, _umgebung


def _qwen(text: str, pause: float = 0.0):
    def f(_pcm, _keywords=""):
        if pause:
            time.sleep(pause)
        return _kandidat(text)
    return f


def test_yeah_auf_ja_nein_frage_wird_qwens_deutsches_ja():
    nachtraege: list[dict] = []

    def lauf(_fake):
        text = stt.transcribe(BLOB, nachtrag=nachtraege.append, sprachkontext="ja_nein")
        assert text == "Ja."
        assert stt.sprachwache_grund() == ""
        assert stt.sprachwache_rettung() == "qwen-ja-nein"

    _umgebung(lauf, lokal_text="Yeah.", qwen_candidate=_qwen("Ja."))
    assert nachtraege == []


def test_no_wird_qwens_nein_und_kurzer_zusatz_bleibt():
    def lauf(_fake):
        assert stt.transcribe(BLOB, sprachkontext="ja_nein") == "Nein, das bin ich nicht."

    _umgebung(lauf, lokal_text="No.", qwen_candidate=_qwen("Nein, das bin ich nicht."))


def test_ohne_ja_nein_kontext_bleibt_yeah_verworfen():
    def lauf(_fake):
        assert stt.transcribe(BLOB) == ""
        assert stt.sprachwache_grund() == "englisch-oder-stille"
        assert stt.sprachwache_rettung() == ""

    _umgebung(lauf, lokal_text="Yeah.", qwen_candidate=_qwen("Ja."))


def test_anderes_englisch_wird_nie_gerettet():
    def lauf(_fake):
        assert stt.transcribe(BLOB, sprachkontext="ja_nein") == ""
        assert stt.sprachwache_grund() == "englisch-oder-stille"

    _umgebung(lauf, lokal_text="Damn it.", qwen_candidate=_qwen("Ja."))


def test_qwen_mit_anderem_inhalt_rettet_nicht():
    """Qwen darf nur ein Ja/Nein liefern — einen ganzen Satz uebernimmt die
    Rettung nie (sonst waere sie ein Uebersetzer)."""
    def lauf(_fake):
        assert stt.transcribe(BLOB, sprachkontext="ja_nein") == ""

    _umgebung(lauf, lokal_text="Yeah.",
              qwen_candidate=_qwen("Ich möchte einen Termin am Dienstag."))


def test_qwen_zu_spaet_rettet_nicht(monkeypatch):
    monkeypatch.setenv("SPRACHWACHE_QWEN_S", "0.05")

    def lauf(_fake):
        t0 = time.perf_counter()
        assert stt.transcribe(BLOB, sprachkontext="ja_nein") == ""
        assert time.perf_counter() - t0 < 0.3

    _umgebung(lauf, lokal_text="Yeah.", qwen_candidate=_qwen("Ja.", pause=0.25))


def test_shadow_und_off_aendern_nichts(monkeypatch):
    for modus in ("shadow", "off"):
        monkeypatch.setenv("SPRACHWACHE_QWEN", modus)

        def lauf(_fake):
            assert stt.transcribe(BLOB, sprachkontext="ja_nein") == ""
            assert stt.sprachwache_grund() == "englisch-oder-stille"

        _umgebung(lauf, lokal_text="Yeah.", qwen_candidate=_qwen("Ja."))


def test_deutsches_ja_von_parakeet_bleibt_parakeet():
    def lauf(_fake):
        assert stt.transcribe(BLOB, sprachkontext="ja_nein") == "Ja."
        assert stt.sprachwache_rettung() == ""

    _umgebung(lauf, lokal_text="Ja.", qwen_candidate=_qwen("Nein."))


def test_spur_zeigt_rettung_und_nie_den_englischen_text():
    def lauf(_fake):
        text, info = stt_spur.transcribe(BLOB, sprachkontext="ja_nein")
        assert text == "Ja."
        assert info.get("rettung") == "qwen-ja-nein"
        assert info["winner"] == "qwen"
        assert "filter" not in info
        assert "yeah" not in str(info).lower()

    _umgebung(lauf, lokal_text="Yeah.", qwen_candidate=_qwen("Ja."))
