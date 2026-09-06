"""W-TEMPO / W-SVETLANA: Sprechtempo verdrahten — nie nach 350 ms schneiden."""

from kern import tempo


def test_unbekannt_nie_unter_800():
    sit = {}
    assert tempo.pause_ms(350, sit) == 800
    assert tempo.pause_ms(500, sit) == 800
    assert tempo.pause_ms(1500, sit) == 1500


def test_langsam_nach_gehaltenen_zuegen():
    sit = {}
    tempo.merken(sit, "Also.", gehalten=True)
    tempo.merken(sit, "Ich wollte", gehalten=True)
    assert tempo.lage(sit) == tempo.LANGSAM
    assert tempo.pause_ms(350, sit) == 1100
    assert tempo.warte_ms(sit) == 1400


def test_schnell_bei_kurzen_antworten():
    sit = {}
    tempo.merken(sit, "Ja.")
    tempo.merken(sit, "Genau.")
    assert tempo.lage(sit) == tempo.SCHNELL
    assert tempo.pause_ms(350, sit) == 350


def test_bianca_stille_fn_nutzt_tempo():
    from bianca import gehirn
    from kern.dienst import Dienst

    d = Dienst(
        name="t",
        start_fn=lambda sit: {},
        turn_fn=lambda sit, t, **k: {},
        stille_fn=lambda sit: tempo.pause_ms(gehirn.stille_ms(gehirn.sammler(sit)), sit),
    )
    sit = {"sammler": {"frage": "schonmal"}}
    assert d._stille_feld(sit) == {"stilleMs": 800}  # unbekannt -> grosszuegig
