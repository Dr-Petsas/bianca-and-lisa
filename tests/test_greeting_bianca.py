"""Bianca-Begruessung: Was (nicht Wem) kann ich fuer Sie tun."""

from bianca.greeting import begruessung, gruss_saeubern


def test_begruessung_fragt_was_nicht_wem():
    t = begruessung("Med Dent Zahnklinik")
    assert "Was kann ich für Sie tun?" in t
    assert "Wem kann ich" not in t


def test_gruss_saeubert_wem_zu_was():
    assert "Was kann ich" in gruss_saeubern(
        "Med Dent, guten Tag! Mein Name ist Bianca. Wem kann ich für Sie tun?"
    )
