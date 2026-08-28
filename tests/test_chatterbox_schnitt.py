"""Chatterbox-Stream-Schnitt (tts_serve/chatterbox/schnitt.py, 28.08.2026):
frueh geschnittenes erstes Stueck (erster Ton nach EINER kurzen Synthese),
danach Saetze — nie in Ziffern-Gruppen oder nach Ordnungszahl-Punkt.

Das Modul ist pur (kein torch) und wird hier direkt aus dem Container-Ordner
geladen — der Container selbst baut nur aus tts_serve/chatterbox/.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tts_serve" / "chatterbox"))

import schnitt  # noqa: E402


def _wieder_zusammen(teile: list[str], original: str) -> None:
    """Alle Woerter muessen erhalten bleiben (Kommas duerfen am Schnitt liegen)."""
    a = " ".join(" ".join(teile).replace(",", " ").split())
    b = " ".join(original.replace(",", " ").split())
    assert a == b, f"Woerter verloren/verdoppelt:\n{a}\n{b}"


def test_kurzer_satz_bleibt_ein_stueck():
    assert schnitt.stuecke("Einen kleinen Moment bitte.") == ["Einen kleinen Moment bitte."]


def test_leer_gibt_leer():
    assert schnitt.stuecke("") == []
    assert schnitt.stuecke("   ") == []


def test_langer_erster_satz_wird_am_komma_geschnitten():
    text = ("Ich habe hier einen freien Termin gefunden, und zwar am Donnerstagnachmittag "
            "gegen halb drei bei Doktor Petsas.")
    teile = schnitt.stuecke(text)
    assert len(teile) == 2, teile
    assert teile[0].endswith(","), "Komma bleibt am Kopf (weiterfuehrende Intonation)"
    assert len(teile[0]) <= schnitt.ERSTE_KOMMA_MAX + 1
    _wieder_zusammen(teile, text)


def test_langer_satz_ohne_komma_schneidet_an_wortgrenze():
    text = ("Der Kalender zeigt fuer Donnerstag leider keinen einzigen freien "
            "Platz mehr an diesem Nachmittag bei uns hier")
    teile = schnitt.stuecke(text + ".")
    assert len(teile) == 2, teile
    assert len(teile[0]) <= schnitt.ERSTE_MAX
    assert not teile[0].endswith((" ",)), "sauber getrimmt"
    _wieder_zusammen(teile, text + ".")


def test_folge_saetze_bleiben_ganze_saetze():
    text = ("Guten Tag, hier ist die Praxis. Ich habe Ihren Termin gefunden und "
            "sage ihn Ihnen gern durch. Passt Donnerstag um drei fuer Sie?")
    teile = schnitt.stuecke(text)
    assert teile[-1] == "Passt Donnerstag um drei fuer Sie?"
    _wieder_zusammen(teile, text)


def test_ordnungszahl_punkt_trennt_nie():
    text = "Ihr Termin ist am 28. August um vierzehn Uhr. Bitte bringen Sie die Karte mit."
    teile = schnitt.stuecke(text)
    assert any("28. August" in t for t in teile), teile
    for t in teile:
        assert t != "Ihr Termin ist am 28."


def test_winzlinge_kleben_am_nachbarn():
    teile = schnitt.stuecke("Gut. Dann trage ich den Termin gleich fuer Sie ein.")
    assert len(teile) == 1, teile


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
    print("test_chatterbox_schnitt: alle gruen")
