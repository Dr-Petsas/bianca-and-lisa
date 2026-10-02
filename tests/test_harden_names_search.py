"""Paket 9: Nachnamenfusion sicher aufloesen, saubere Ketten erhalten.

Replay ``blessing-fusion``: der gesprochene Name und seine Buchstabierkette
verschmolzen live zu „Grafgrafgras"/„Bayerbayerr". Der buchstabierte Nachname
muss genau der Name bleiben; eine einzelne saubere Kette darf NICHT kollabieren.
"""
from __future__ import annotations

import pytest

from bianca import gehirn
from bianca.gehirn import _entdoppelter_name
from kern import hirn
from kern.tenants import laden
from tests.live_replays import replay


# ---- Einheit: die Entdopplungs-Heuristik ---------------------------------
@pytest.mark.parametrize("roh, alt, soll", [
    ("grafgraf", "Graf", "Graf"),
    ("grafgrafgras", "Graf", "Graf"),
    ("bayerbayerr", "Bayer", "Bayer"),
    ("maiermaier", "Maier", "Maier"),
])
def test_fusion_wird_kollabiert(roh, alt, soll):
    assert _entdoppelter_name(roh, alt).casefold() == soll.casefold()


@pytest.mark.parametrize("roh, alt", [
    ("Anna", ""),          # echter Doppel-Buchstabe
    ("Maier", ""),         # saubere Kette, kein Vorname bekannt
    ("Maier", "Maier"),    # Kette bestaetigt den Namen
    ("Schulze", ""),
    ("Baumgartner", ""),
    ("Schmidtbauer", ""),  # echter zusammengesetzter Name
])
def test_saubere_namen_bleiben(roh, alt):
    assert _entdoppelter_name(roh, alt).casefold() == roh.casefold()


# ---- Integration: einsammeln ueber den Blessing-Flow ----------------------
def _sit():
    sit = {
        "id": "fus", "stimme": "Bianca", "tenant": laden("blessing"),
        "messages": [
            {"role": "system", "content": "t"},
            {"role": "assistant", "content": "Buchstabieren Sie den Nachnamen bitte."},
        ],
        "booking": {}, "tools": [], "zuege": [],
    }
    hirn.init(sit)
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen", "phase": "", "frage": "nachname", "warSchonMal": True,
        "arzt": {"typ": "genannt", "calendarId": "c",
                 "calendarName": "Doktor Charlotte Blessing"},
        "grund": "Kontrolle", "grundWortlaut": "Kontrolle",
        "motivId": "m", "motivName": "Kontrolle",
        "wunsch": {}, "vorname": "", "nachname": "", "buchstabiert": False,
    })
    return sit, s


_SPELL = ("M wie Martha, A wie Anton, I wie Ida, E wie Emil, "
          "R wie Richard, fertig.")


def test_gesprochen_dann_buchstabiert_bleibt_sauber():
    """Replay blessing-fusion: „Maier" + Buchstabierkette = genau „Maier"."""
    sit, s = _sit()
    gehirn.einsammeln(sit, "Der Nachname heißt Maier.")
    assert s["nachname"] == "Maier"
    s["frage"] = "buchstabieren"
    gehirn.einsammeln(sit, _SPELL)
    assert s["nachname"] == "Maier"
    assert "maiermaier" not in s["nachname"].casefold()


def test_fusion_im_fertig_commit_wird_aufgeloest():
    """Teilstueck traegt bereits den gehoerten Namen; die Kette wiederholt ihn
    (verhoert). Der Fertig-Commit darf daraus nicht „Maiermaier" machen."""
    sit, s = _sit()
    s["nachname"] = "Maier"
    s["frage"] = "buchstabieren"
    s["buchstabenTeil"] = "maier"   # Vorsatz = schon gehoerter Name
    gehirn.einsammeln(sit, _SPELL)   # Kette "maier" + fertig
    assert s["nachname"].casefold() == "maier"


def test_saubere_einzelkette_ohne_vorerwaehnung():
    """Gegenprobe: eine einzelne saubere Kette ergibt „Maier", nicht kollabiert."""
    sit, s = _sit()
    s["frage"] = "buchstabieren"
    gehirn.einsammeln(sit, _SPELL)
    assert s["nachname"] == "Maier"


def test_replay_fusion_metadaten():
    r = replay("blessing-fusion")
    assert r.tenant == "blessing"
    assert r.klasse == "nachname_fusion"
    assert r.gegenprobe  # eine saubere Kette als Gegenprobe
