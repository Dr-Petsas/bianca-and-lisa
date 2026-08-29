"""Barge-in mit Fortsetzung (kern/unterbrechung.py, W-BARGE 29.08.2026):
Satz-Karte -> Eingang (Rest + Protokoll-Stutzen) -> Fortsetzen/Wiederaufnahme.
Offline, ohne LLM, ohne Netz.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kern import unterbrechung

S1 = "Ich habe drei Termine gefunden."
S2 = "Am Donnerstag um zehn Uhr wäre etwas frei."
S3 = "Alternativ am Freitag um vierzehn Uhr."


def _sit(*, vorab: str = "", vorab_url: str = "") -> dict:
    sit = {
        "messages": [
            {"role": "system", "content": "..."},
            {"role": "user", "content": "Welche Termine gibt es?"},
            {"role": "assistant", "content": f"{vorab} {S1} {S2} {S3}".strip()},
        ],
    }
    karte = {"saetze": [S1, S2, S3], "endenMs": [1000, 2500, 4000]}
    unterbrechung.merken(sit, url="/api/audio-stream/abc.wav", karte=karte,
                         text=f"{S1} {S2} {S3}", vorab_text=vorab, vorab_url=vorab_url)
    return sit


# ---------------------------------------------------------------------------
# Eingang: Rest bestimmen + Protokoll stutzen
# ---------------------------------------------------------------------------

def test_eingang_mitten_im_zweiten_satz():
    sit = _sit()
    assert unterbrechung.eingang(sit, "/api/audio-stream/abc.wav", 1800)
    u = sit["unterbrochen"]
    assert u["rest"] == [S2, S3], "der angespielte Satz zwei gehört komplett in den Rest"
    assert u["gesprochen"] == S1
    assert sit["messages"][-1]["content"] == S1, "Protokoll = wirklich Gesagtes"


def test_eingang_vor_dem_ersten_satz():
    sit = _sit()
    assert unterbrechung.eingang(sit, "/api/audio-stream/abc.wav", 0)
    assert sit["unterbrochen"]["rest"] == [S1, S2, S3]
    assert sit["messages"][-1]["content"] == unterbrechung.ABGEBROCHEN


def test_eingang_nach_dem_ende_kein_rest():
    sit = _sit()
    assert not unterbrechung.eingang(sit, "/api/audio-stream/abc.wav", 4200)
    assert "unterbrochen" not in sit
    assert S3 in sit["messages"][-1]["content"], "Protokoll bleibt unangetastet"


def test_eingang_fremde_url_tut_nichts():
    sit = _sit()
    assert not unterbrechung.eingang(sit, "/api/audio/filler123.wav", 500)
    assert "unterbrochen" not in sit


def test_eingang_vorab_satz_unterbrochen():
    sit = _sit(vorab="Einen Moment bitte.", vorab_url="/api/audio/vorab1.wav")
    assert unterbrechung.eingang(sit, "/api/audio/vorab1.wav", 300)
    assert sit["unterbrochen"]["rest"] == ["Einen Moment bitte.", S1, S2, S3]
    assert sit["messages"][-1]["content"] == unterbrechung.ABGEBROCHEN


def test_eingang_vorab_gilt_als_gesprochen():
    sit = _sit(vorab="Einen Moment bitte.", vorab_url="/api/audio/vorab1.wav")
    assert unterbrechung.eingang(sit, "/api/audio-stream/abc.wav", 1200)
    u = sit["unterbrochen"]
    assert u["gesprochen"] == f"Einen Moment bitte. {S1}"
    assert u["rest"] == [S2, S3]


def test_eingang_fehlender_endwert_zaehlt_als_ungesprochen():
    sit = _sit()
    sit["ausspr"]["endenMs"] = [1000, None]  # Satz 2 Render-Fehler, Satz 3 noch offen
    assert unterbrechung.eingang(sit, "/api/audio-stream/abc.wav", 3500)
    assert sit["unterbrochen"]["rest"] == [S2, S3]


def test_eingang_notaus():
    os.environ["BARGE_WEITER"] = "0"
    try:
        sit = _sit()
        assert not unterbrechung.eingang(sit, "/api/audio-stream/abc.wav", 1800)
        assert "unterbrochen" not in sit
        assert S3 in sit["messages"][-1]["content"]
    finally:
        os.environ.pop("BARGE_WEITER", None)


# ---------------------------------------------------------------------------
# Fortsetzen nach dem Einwand-Zug
# ---------------------------------------------------------------------------

def test_fortsetzen_haengt_bruecke_und_rest_an():
    sit = _sit()
    unterbrechung.eingang(sit, "/api/audio-stream/abc.wav", 1800)
    sit["messages"].append({"role": "user", "content": "Moment, wie teuer ist das?"})
    sit["messages"].append({"role": "assistant", "content": "Die Kontrolle übernimmt die Kasse."})
    out = unterbrechung.fortsetzen(sit, "Die Kontrolle übernimmt die Kasse.", {"book": None})
    assert out.startswith("Die Kontrolle übernimmt die Kasse.")
    assert S2 in out and S3 in out
    assert any(out.count(b) for b in unterbrechung.BRUECKEN), "Brücke fehlt"
    assert S3 in sit["messages"][-1]["content"], "Rest ist im Protokoll nachgetragen"
    assert "unterbrochen" not in sit


def test_fortsetzen_bruecken_rotieren():
    gesehen = []
    for _ in range(2):
        sit = _sit()
        sit["brueckeNr"] = len(gesehen)
        unterbrechung.eingang(sit, "/api/audio-stream/abc.wav", 1800)
        out = unterbrechung.fortsetzen(sit, "Gut, dass Sie fragen.", None)
        gesehen.append(next(b for b in unterbrechung.BRUECKEN if b in out))
    assert gesehen[0] != gesehen[1], "nie zweimal dieselbe Brücke in Folge"


def test_fortsetzen_verwirft_bei_frage():
    sit = _sit()
    unterbrechung.eingang(sit, "/api/audio-stream/abc.wav", 1800)
    out = unterbrechung.fortsetzen(sit, "Passt Ihnen Freitag um fünfzehn Uhr?", None)
    assert S2 not in out and S3 not in out, "neue Frage = Maschine treibt neu, Rest veraltet"
    assert "unterbrochen" not in sit


def test_fortsetzen_verwirft_bei_buchung():
    sit = _sit()
    unterbrechung.eingang(sit, "/api/audio-stream/abc.wav", 1800)
    out = unterbrechung.fortsetzen(sit, "Der Termin ist eingetragen.", {"book": {"booked": True}})
    assert S2 not in out


def test_ist_abbruch_erkennung():
    for t in ("Stopp.", "Stop!", "Halt", "Hör auf!", "Hören Sie bitte auf.",
              "Sei still!", "Seien Sie bitte leise.", "Lass das.",
              "Schluss jetzt.", "Genug davon.", "Stopp mal kurz"):
        assert unterbrechung.ist_abbruch(t), t
    for t in ("Moment, wie teuer ist das?", "Ich halte das für eine gute Idee",
              "Das ist halt so bei uns in der Familie", "Nein danke",
              "Können wir weitermachen?", ""):
        assert not unterbrechung.ist_abbruch(t), t


def test_fortsetzen_verwirft_bei_stopp():
    """Live 29.08.2026: auf 'Stopp.' sagte Bianca 'Alles klar, ich höre auf …
    Also, wo war ich: …' und wiederholte die komplette Ansage. Ein
    Abbruch-Befehl verwirft den Rest."""
    sit = _sit()
    unterbrechung.eingang(sit, "/api/audio-stream/abc.wav", 1800)
    out = unterbrechung.fortsetzen(sit, "Alles klar, ich höre auf. Ich bin ganz Ohr.",
                                   None, gesagt="Stopp.")
    assert out == "Alles klar, ich höre auf. Ich bin ganz Ohr."
    assert S2 not in out and S3 not in out
    assert "unterbrochen" not in sit, "Rest ist verworfen, nicht aufgehoben"


def test_fortsetzen_filtert_wortgleiche_saetze():
    sit = _sit()
    unterbrechung.eingang(sit, "/api/audio-stream/abc.wav", 1800)
    out = unterbrechung.fortsetzen(sit, f"Gerne. {S2}", None)
    assert out.count("Donnerstag") == 1, "wortgleicher Rest-Satz fällt weg"
    assert S3 in out


def test_fortsetzen_ohne_unterbrechung_ist_durchreiche():
    sit = {"messages": []}
    assert unterbrechung.fortsetzen(sit, "Alles klar.", None) == "Alles klar."


# ---------------------------------------------------------------------------
# Fehlalarm: Echo + Wiederaufnahme
# ---------------------------------------------------------------------------

def test_ist_echo_eigene_worte():
    sit = _sit()
    unterbrechung.eingang(sit, "/api/audio-stream/abc.wav", 1800)
    assert unterbrechung.ist_echo(sit, "Ich habe drei Termine gefunden")
    assert not unterbrechung.ist_echo(sit, "Ich brauche drei neue Termine")


def test_ist_echo_schluckt_keine_kurzen_antworten():
    sit = _sit()
    unterbrechung.eingang(sit, "/api/audio-stream/abc.wav", 1800)
    for kurz in ("Ja.", "Nein!", "Stopp", "Termine gefunden"):
        assert not unterbrechung.ist_echo(sit, kurz), kurz


def test_wiederaufnahme_spricht_den_rest():
    sit = _sit()
    unterbrechung.eingang(sit, "/api/audio-stream/abc.wav", 1800)
    text = unterbrechung.wiederaufnahme(sit)
    assert text == f"{S2} {S3}"
    assert "unterbrochen" not in sit
    assert sit["messages"][-1]["content"] == f"{S1} {S2} {S3}", (
        "Protokoll ist nach der Wiederaufnahme wieder vollständig")


def test_wiederaufnahme_ohne_zustand_leer():
    assert unterbrechung.wiederaufnahme({"messages": []}) == ""


if __name__ == "__main__":
    fehler = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"OK   {name}")
            except AssertionError as e:
                fehler += 1
                print(f"ROT  {name}: {e}")
    raise SystemExit(1 if fehler else 0)
