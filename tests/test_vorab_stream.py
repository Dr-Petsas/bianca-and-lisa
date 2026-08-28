"""Vorab-Satz ueber den Chunk-Stream (kern/dienst.py, 28.08.2026):

Der erste Satz aus dem LLM-Stream ging bisher IMMER als blockierender
/speak raus — bei lokalem TTS stand der Anrufer damit die volle
Satz-Synthese (1,2-2 s) in der Stille, obwohl der Container streamen kann.
Jetzt gehen schon die Teilstuecke des ersten Satzes raus, sobald sie da
sind; faellt der Stream aus, uebernimmt wie vorher das Blocking.
"""

from __future__ import annotations

import json

from kern import tts
from kern.dienst import Dienst

ERSTER = "Einen Moment, ich schaue kurz nach."
REST = "Am Donnerstag um drei ist noch ein Platz frei."


class _StreamEngine:
    name = "lokal"

    def __init__(self, wavs: list[bytes]):
        self.wavs = wavs
        self.texte: list[str] = []

    def kann_stream(self) -> bool:
        return True

    def speak_stream(self, text: str):
        self.texte.append(text)
        yield from self.wavs


class _KaputtEngine(_StreamEngine):
    def speak_stream(self, text: str):
        self.texte.append(text)
        raise RuntimeError("tts_lokal_stream_http_503")
        yield  # pragma: no cover


def _dienst(gemerkt: list[str]) -> Dienst:
    def turn_fn(sit, text, melde=None, vorab=None):
        # nachgebaut wie llm.chat_stream: erster Satz feuert waehrend des
        # Streams, der Gesamttext kommt am Ende.
        if vorab:
            vorab(ERSTER)
        return {"text": f"{ERSTER} {REST}"}

    d = Dienst(name="test", start_fn=lambda sit: {"text": ""}, turn_fn=turn_fn)
    d.stimme = lambda text: (gemerkt.append(text) or f"/api/audio/{len(gemerkt)}.wav", 0.1)
    return d


def _zeilen(d: Dienst, sit: dict) -> list[dict]:
    return [json.loads(z) for z in d.zug_stream(sit, art="turn", text_in="hallo")]


def _mit_engine(eng, fn) -> None:
    alt = (tts.engine, tts.bereit, tts.im_cache)
    tts.engine = lambda: eng
    tts.bereit = lambda: True
    tts.im_cache = lambda text: False
    try:
        fn()
    finally:
        (tts.engine, tts.bereit, tts.im_cache) = alt


def test_vorab_satz_streamt_teilstuecke_sofort():
    gemerkt: list[str] = []
    d = _dienst(gemerkt)
    eng = _StreamEngine([b"RIFF1", b"RIFF2"])

    def lauf():
        zeilen = _zeilen(d, {})
        filler = [z for z in zeilen if z["type"] == "filler"]
        reply = [z for z in zeilen if z["type"] == "reply"][0]
        assert not gemerkt, "kein blockierender /speak, wenn der Container streamt"
        assert eng.texte == [ERSTER, REST], "erst der Vorab-Satz, dann der Rest — je EIN Stream"
        assert len(filler) == 4, "alle Teilstuecke (2 je Stream) sofort raus"
        assert reply["text"] == f"{ERSTER} {REST}"
        assert reply["audioUrl"] == "", "alles schon gesprochen — kein Extra-Audio"

    _mit_engine(eng, lauf)


def test_stream_tot_faellt_auf_blocking_zurueck():
    gemerkt: list[str] = []
    d = _dienst(gemerkt)
    eng = _KaputtEngine([])

    def lauf():
        zeilen = _zeilen(d, {})
        filler = [z for z in zeilen if z["type"] == "filler"]
        reply = [z for z in zeilen if z["type"] == "reply"][0]
        assert gemerkt == [ERSTER, REST], "Blocking uebernimmt Satz fuer Satz"
        assert len(filler) == 1, "der Vorab-Satz kommt als blockierendes Haeppchen"
        assert reply["audioUrl"], "der Rest bleibt das reply-Audio"

    _mit_engine(eng, lauf)


def test_gecachter_vorab_satz_bleibt_blocking_ram_treffer():
    gemerkt: list[str] = []
    d = _dienst(gemerkt)
    eng = _StreamEngine([b"RIFF1"])

    def lauf():
        alt = tts.im_cache
        tts.im_cache = lambda text: text == ERSTER
        try:
            _zeilen(d, {})
        finally:
            tts.im_cache = alt
        assert gemerkt[0] == ERSTER, "Cache-Treffer nicht durch den Stream jagen"
        assert eng.texte == [REST], "nur der Rest laeuft ueber den Stream"

    _mit_engine(eng, lauf)


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
    print("test_vorab_stream: alle gruen")
