"""Satz-Häppchen (kern/dienst.py, 28.08.2026): lange Antworten werden im
Zug-Strom satzweise vertont und sofort ausgespielt, statt als EIN Block nach
der kompletten Synthese — beim lokalen TTS (~1,5 s je Satz) stand sonst nach
dem Vorab-Satz nochmal sekundenlang Stille (Chef: "die latenz ist verdammt
hoch besonders bei lisa").
"""

from __future__ import annotations

from kern import tts
from kern.dienst import Dienst, haeppchen_teile

LANG = (
    "Der erste Satz dieser Antwort ist ordentlich lang geraten. "
    "Auch der zweite Satz bringt genug Inhalt für ein eigenes Häppchen mit. "
    "Und der dritte Satz rundet die Sache würdig ab."
)


def _dienst(gemerkt: list[str], *, stream_aus: bool = True) -> Dienst:
    d = Dienst(
        name="test",
        start_fn=lambda sit: {"text": ""},
        turn_fn=lambda sit, text, melde=None, vorab=None: {"text": LANG},
    )
    d.stimme = lambda text: (gemerkt.append(text) or f"/api/audio/{len(gemerkt)}.wav", 0.1)
    # Hermetisch halten: der echte Stream-Pfad wuerde sonst den ECHTEN
    # Container aus der .env befragen — laeuft dort ein Stream-Faehiger,
    # streamt der Test live statt den Blocking-Pfad zu pruefen. Bewusst nur
    # an DIESER Instanz stummgeschaltet, nicht modulglobal: das alte
    # `tts.bereit = lambda: False` blieb nach dem Modul haengen und liess
    # test_tts_lokal im Sammel-Lauf (lauf_alle) rot werden (28.08.2026).
    # Stream-Tests patchen bereit/engine selbst (mit Ruecksetzung).
    if stream_aus:
        d._stream_haeppchen = lambda text, haeppchen: False
    return d


def test_splitter_trennt_saetze_aber_nie_ordnungszahlen():
    teile = haeppchen_teile(LANG)
    assert len(teile) == 3, f"drei Sätze erwartet, kam {teile}"
    datum = "Ich habe einen Termin am 28. August gefunden, der noch frei wäre. Passt Ihnen dieser Vorschlag gut?"
    teile = haeppchen_teile(datum)
    assert len(teile) == 2 and "28. August" in teile[0], "Ordnungszahl darf nicht splitten"


def test_winzlinge_kleben_am_nachbarn():
    teile = haeppchen_teile("Gut. Dann trage ich den Termin gleich für Sie ein und schicke die Bestätigung.")
    assert len(teile) == 1, f"kurzer Auftakt gehört zum Folgesatz: {teile}"


def test_haeppchen_gehen_sofort_raus_und_reply_traegt_das_letzte():
    gemerkt: list[str] = []
    urls: list[str] = []
    d = _dienst(gemerkt)
    out = d.json_antwort({}, art="turn", text_in="hallo", haeppchen=urls.append)
    assert len(gemerkt) == 3, "drei Sätze = drei Synthesen"
    assert len(urls) == 2, "die ersten zwei Häppchen gehen sofort über den Stream raus"
    assert out["audioUrl"] == "/api/audio/3.wav", "das letzte Stück bleibt das reply-Audio"
    assert abs(out["timings"]["tts"] - 0.3) < 0.01, "tts-Zeit ist die Summe aller Häppchen"


def test_ohne_stream_bleibt_ein_block():
    gemerkt: list[str] = []
    d = _dienst(gemerkt)
    out = d.json_antwort({}, art="turn", text_in="hallo")
    assert len(gemerkt) == 1 and gemerkt[0] == LANG, "ohne haeppchen-Kanal wie bisher EIN Block"
    assert out["audioUrl"] == "/api/audio/1.wav"


def test_gecachte_texte_bleiben_ein_block():
    gemerkt: list[str] = []
    urls: list[str] = []
    d = _dienst(gemerkt)
    alt = tts.im_cache
    tts.im_cache = lambda text: True
    try:
        d.json_antwort({}, art="turn", text_in="hallo", haeppchen=urls.append)
    finally:
        tts.im_cache = alt
    assert len(gemerkt) == 1 and not urls, "Warm-Cache-Treffer nicht zersplittern"


class _StreamEngine:
    """Fake-LokalTts mit Chunk-Streaming (CosyVoice-Turbo)."""

    name = "lokal"

    def __init__(self, wavs: list[bytes]):
        self.wavs = wavs
        self.texte: list[str] = []

    def kann_stream(self) -> bool:
        return True

    def speak_stream(self, text: str):
        self.texte.append(text)
        yield from self.wavs


def test_stream_faehiger_container_bekommt_die_ganze_aeusserung():
    urls: list[str] = []
    gemerkt: list[str] = []
    d = _dienst(gemerkt, stream_aus=False)
    eng = _StreamEngine([b"RIFF1", b"RIFF2", b"RIFF3"])
    alt_engine, alt_bereit = tts.engine, tts.bereit
    tts.engine = lambda: eng
    tts.bereit = lambda: True
    try:
        out = d.json_antwort({}, art="turn", text_in="hallo", haeppchen=urls.append)
    finally:
        tts.engine, tts.bereit = alt_engine, alt_bereit
    assert not gemerkt, "kein blocking-Satz-Rendern, wenn der Container streamt"
    assert eng.texte == [LANG], "EIN Stream-Aufruf mit dem Gesamttext (beste Prosodie)"
    assert len(urls) == 3, "alle Häppchen sofort über den Stream-Kanal raus"
    assert out["audioUrl"] == "", "reply ohne Extra-Audio — alles ist schon gesprochen"


def test_stream_fehlschlag_vor_dem_ersten_haeppchen_faellt_auf_blocking():
    urls: list[str] = []
    gemerkt: list[str] = []
    d = _dienst(gemerkt, stream_aus=False)

    class _Kaputt(_StreamEngine):
        def speak_stream(self, text: str):
            raise RuntimeError("tts_lokal_stream_http_503")
            yield  # pragma: no cover

    alt_engine, alt_bereit = tts.engine, tts.bereit
    tts.engine = lambda: _Kaputt([])
    tts.bereit = lambda: True
    try:
        out = d.json_antwort({}, art="turn", text_in="hallo", haeppchen=urls.append)
    finally:
        tts.engine, tts.bereit = alt_engine, alt_bereit
    assert len(gemerkt) == 3, "Stream tot => satzweises Blocking übernimmt"
    assert len(urls) == 2 and out["audioUrl"], "Häppchen-Verhalten wie ohne Stream"


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
    print("test_haeppchen: alle gruen")
