"""Rückfrage statt Raten bei zerhacktem STT."""

from kern import gehoer
from bianca import flow, gehirn
from kern.tenants import laden


def _sit() -> dict:
    return {"tenant": laden("meddent"), "messages": [{"role": "system", "content": "x"}]}


def test_wacklig_einzelbuchstabe():
    assert gehoer.wacklig("x")
    assert gehoer.wacklig("ä.")


def test_wacklig_zerhackt():
    assert gehoer.wacklig("a b c d e")


def test_wacklig_laesst_ja_nein_und_namen():
    assert not gehoer.wacklig("Ja")
    assert not gehoer.wacklig("Nein.")
    assert not gehoer.wacklig("Okay")
    assert not gehoer.wacklig("Müller Peter")
    assert not gehoer.wacklig("Petsas")


def test_wacklig_nicht_beim_buchstabieren():
    assert not gehoer.wacklig("B E R G E R", frage="buchstabieren")
    assert not gehoer.wacklig("0177", frage="telefon")


def test_rueckfrage_je_lage():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": True, "frage": "grund"})
    assert "neuen Termin" in gehoer.rueckfrage(sit)
    s["phase"] = "bestaetigen"
    assert "Ja oder ein Nein" in gehoer.rueckfrage(sit)


def test_fluss_fragt_nach_statt_zu_raten():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": None, "frage": "schonmal"})
    z = flow.zug(sit, "x")
    assert z and "verstanden" in z["text"].lower()
    assert s["warSchonMal"] is None


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
    print("test_gehoer: alle gruen")
