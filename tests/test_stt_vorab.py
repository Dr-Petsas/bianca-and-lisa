"""Vorab-Transkript im Stille-Fenster (28.08.2026).

Das Dock schickt den Mitschnitt schon beim Stille-VERDACHT (~150 ms); die
Transkription laeuft, waehrend das Dock die restlichen ~350 ms Stille
bestaetigt. Der Zug (vorab_id) heiratet das Ergebnis — ohne zweiten
STT-Aufruf. Faellt das Vorab aus (falsche Kennung, Fehler, Timeout),
laeuft der bewaehrte Normalpfad mit dem Final-Blob.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import kern.dienst as dienst_mod
from kern.dienst import Dienst


BLOB = b"x" * 4000


def _dienst() -> Dienst:
    d = Dienst(
        name="test",
        start_fn=lambda sit: {"text": "hallo"},
        turn_fn=lambda sit, text, melde=None: {"text": f"echo {text}"},
        schnell_fn=lambda sit: False,
    )
    # Kein echtes TTS im Test: Stimme liefert nichts, Zug traegt nur Text.
    d.stimme = lambda text: ("", 0.0)
    return d


class _FakeStt:
    """Zaehlt Aufrufe und liefert nach optionaler Verzoegerung."""

    def __init__(self, text: str = "Ich haette gern einen Termin", dauer_s: float = 0.05,
                 fehler: Exception | None = None):
        self.text = text
        self.dauer_s = dauer_s
        self.fehler = fehler
        self.aufrufe = 0

    def transcribe(self, blob, *, mime="", name="", keywords=""):
        self.aufrufe += 1
        time.sleep(self.dauer_s)
        if self.fehler:
            raise self.fehler
        return self.text


def _zug_ausfuehren(d: Dienst, sit: dict, vorab_id: str):
    """zug_stream konsumieren, (transcript_text, reply_dict) liefern."""
    gehoert, reply = "", None
    import json
    alt_bereit = dienst_mod.tts.bereit
    dienst_mod.tts.bereit = lambda: False  # kein Live-TTS im Test
    try:
        for zeile in d.zug_stream(sit, art="listen", stt_blob=BLOB, stt_mime="audio/webm",
                                  stt_name="turn.webm", vorab_id=vorab_id):
            ev = json.loads(zeile)
            if ev.get("type") == "transcript":
                gehoert = ev.get("textIn") or ""
            if ev.get("type") == "reply":
                reply = ev
    finally:
        dienst_mod.tts.bereit = alt_bereit
    return gehoert, reply


def test_vorab_wird_geheiratet_ohne_zweiten_stt_aufruf():
    d = _dienst()
    fake = _FakeStt(dauer_s=0.15)
    alt = dienst_mod.stt.transcribe
    dienst_mod.stt.transcribe = fake.transcribe
    try:
        sit = {"id": "s1", "tenant": {"behandler": "Dr. Petsas"}}
        vid = d.hoervorab(sit, blob=BLOB, mime="audio/webm", name="turn.webm")
        assert vid, "Vorab-Kennung erwartet"
        # Wie live: zwischen Vorab-Start und Zug liegen ~350 ms Stille-
        # Bestaetigung + Upload — hier 100 ms bei 150 ms Fake-Transkription.
        time.sleep(0.1)
        gehoert, reply = _zug_ausfuehren(d, sit, vid)
        assert gehoert == "Ich haette gern einen Termin"
        assert reply and reply.get("ok")
        assert fake.aufrufe == 1, f"nur der Vorab-Lauf darf STT rufen, war {fake.aufrufe}"
        assert "_vorabStt" not in sit, "Eintrag muss verbraucht sein"
        # stt-Restwartezeit auf dem kritischen Pfad muss KLEINER sein als die
        # volle Transkriptionsdauer (der Lauf hatte 100 ms Vorsprung).
        stt_s = (reply.get("timings") or {}).get("stt")
        assert stt_s is not None and stt_s < 0.12, f"Restwartezeit zu gross: {stt_s}"
    finally:
        dienst_mod.stt.transcribe = alt


def test_falsche_kennung_faellt_auf_normalpfad():
    d = _dienst()
    fake = _FakeStt()
    alt = dienst_mod.stt.transcribe
    dienst_mod.stt.transcribe = fake.transcribe
    try:
        sit = {"id": "s2", "tenant": {}}
        d.hoervorab(sit, blob=BLOB, mime="audio/webm", name="turn.webm")
        gehoert, reply = _zug_ausfuehren(d, sit, "gibtsnicht")
        assert gehoert == "Ich haette gern einen Termin"
        assert reply and reply.get("ok")
        assert fake.aufrufe == 2, "Vorab-Lauf + Normalpfad = 2 Aufrufe"
    finally:
        dienst_mod.stt.transcribe = alt


def test_vorab_fehler_faellt_auf_normalpfad():
    d = _dienst()

    class _Wackel:
        def __init__(self):
            self.aufrufe = 0

        def transcribe(self, blob, *, mime="", name="", keywords=""):
            self.aufrufe += 1
            if self.aufrufe == 1:
                raise RuntimeError("stt_lokal_http_500")
            return "Zweiter Versuch klappt"

    fake = _Wackel()
    alt = dienst_mod.stt.transcribe
    dienst_mod.stt.transcribe = fake.transcribe
    try:
        sit = {"id": "s3", "tenant": {}}
        vid = d.hoervorab(sit, blob=BLOB, mime="audio/webm", name="turn.webm")
        gehoert, reply = _zug_ausfuehren(d, sit, vid)
        assert gehoert == "Zweiter Versuch klappt"
        assert reply and reply.get("ok")
        assert fake.aufrufe == 2
    finally:
        dienst_mod.stt.transcribe = alt


def test_notaus_liefert_keine_kennung():
    d = _dienst()
    alt = dienst_mod.STT_VORAB
    dienst_mod.STT_VORAB = False
    try:
        sit = {"id": "s4", "tenant": {}}
        assert d.hoervorab(sit, blob=BLOB, mime="audio/webm", name="turn.webm") == ""
        assert "_vorabStt" not in sit
    finally:
        dienst_mod.STT_VORAB = alt


if __name__ == "__main__":
    test_vorab_wird_geheiratet_ohne_zweiten_stt_aufruf()
    test_falsche_kennung_faellt_auf_normalpfad()
    test_vorab_fehler_faellt_auf_normalpfad()
    test_notaus_liefert_keine_kennung()
    print("test_stt_vorab: alle Faelle bestanden")
