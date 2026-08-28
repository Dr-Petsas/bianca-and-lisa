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


def _dienst(gemerkt: list[str]) -> Dienst:
    d = Dienst(
        name="test",
        start_fn=lambda sit: {"text": ""},
        turn_fn=lambda sit, text, melde=None, vorab=None: {"text": LANG},
    )
    d.stimme = lambda text: (gemerkt.append(text) or f"/api/audio/{len(gemerkt)}.wav", 0.1)
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


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
    print("test_haeppchen: alle gruen")
