"""Chatterbox-Nachbearbeitung (tts_serve/chatterbox/pegel.py, 28.08.2026):
Rand-Stille kappen und Runaway-Babble erkennen — gegen die live gehoerten
halb leeren Nuschel-Haeppchen (54-69 % Stille) und 27-s-Ausreisser.

Das Modul ist pur (kein torch) und wird direkt aus dem Container-Ordner
geladen — der Container selbst baut nur aus tts_serve/chatterbox/.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tts_serve" / "chatterbox"))

import pegel  # noqa: E402

RATE = pegel.RATE


def _ton(s: float, wert: int = 6000) -> bytes:
    return wert.to_bytes(2, "little", signed=True) * int(s * RATE)


def _stille(s: float) -> bytes:
    return b"\x00\x00" * int(s * RATE)


def test_rand_trim_kappt_fuehrende_und_folgende_stille():
    pcm = _stille(1.0) + _ton(2.0) + _stille(1.5)
    out = pegel.rand_trim(pcm)
    dauer = len(out) / 2 / RATE
    # 2 s Ton + je hoechstens ~0,15 s Polster + Fensterraster-Unschaerfe
    assert 2.0 <= dauer <= 2.45, f"Rand-Stille nicht gekappt: {dauer:.2f}s"
    # Ton selbst bleibt unangetastet (keine Samples aus der Mitte verloren)
    assert out.count((6000).to_bytes(2, "little", signed=True) * 100) > 0


def test_rand_trim_laesst_innere_pausen_stehen():
    pcm = _ton(1.0) + _stille(0.5) + _ton(1.0)
    out = pegel.rand_trim(pcm)
    assert len(out) == len(pcm), "innere Pause gehoert zum Sprechrhythmus"


def test_rand_trim_komplett_stille_wird_kurzes_polster():
    pcm = _stille(3.0)
    out = pegel.rand_trim(pcm)
    assert len(out) / 2 / RATE <= 0.2, "leeres Stueck darf keine 3 s belegen"


def test_rand_trim_kurzes_stueck_unangetastet():
    pcm = _ton(0.05)
    assert pegel.rand_trim(pcm) == pcm


def test_runaway_grenzen():
    # 50 Zeichen: erwartet ~4,9 s => 27 s (Vorfall 27.08.) ist klar Runaway,
    # eine normale 6-s-Ansage (120 ms/Z waere schon traege) gerade noch nicht.
    text = "x" * 50
    assert pegel.ist_runaway(text, 27.0)
    assert not pegel.ist_runaway(text, 6.0)
    # Kurztext: "Einen Moment," spricht in ~1 s — 2,5 s noch ok, 3 s Babble.
    kurz = "Einen Moment,"
    assert not pegel.ist_runaway(kurz, 2.5)
    assert pegel.ist_runaway(kurz, 3.0)
    # Cache-Befunde 28.08., die das Gate fangen MUSS (beide echte Renders):
    # 5,88 s fuer "Wie lautet der Nachname?" (245 ms/Z, rutschte durch 2,0),
    # 6,04 s fuer die Handynummer-Frage (144 ms/Z, rutschte durch 1,6).
    assert pegel.ist_runaway("Wie lautet der Nachname?", 5.88)
    assert pegel.ist_runaway("Sagen Sie mir bitte noch Ihre Handynummer?", 6.04)
    # Gute Renders derselben Messung bleiben unangetastet (Beispiele echt):
    assert not pegel.ist_runaway("Waren Sie denn schon einmal bei uns in der Praxis?", 2.48)
    assert not pegel.ist_runaway("Darf ich den Termin so eintragen?", 3.64)
    assert not pegel.ist_runaway("Wann passt es Ihnen am besten — eher vormittags oder nachmittags? Und ab welchem Tag?", 5.84)
