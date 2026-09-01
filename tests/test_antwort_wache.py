"""Antwort-Wache (kern/antwort_wache.py) — phone_agent-Gates offline."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kern import antwort_wache


def test_collapse_stacked_identity():
    text = "Gut. Wie lautet Ihr Vorname? Und Ihr Nachname? Und Ihre Handynummer?"
    raus = antwort_wache.collapse_stacked_identity_ask(text)
    assert "Vorname" in raus
    assert raus.count("?") == 1
    assert "Handynummer" not in raus or "Nachname" not in raus


def test_strip_repeated_greeting():
    begr = "Thaler Zahnmedizin. Sie sprechen mit Bianca die KI Telefonassistentin."
    mid = "Thaler Zahnmedizin, Sie sprechen mit Bianca. Wann passt es Ihnen?"
    raus = antwort_wache.strip_repeated_greeting(mid, begr)
    assert "Wann passt" in raus
    assert "Telefonassistentin" not in raus or "Thaler" not in raus.split("Wann")[0]


def test_saeubern_sit():
    sit = {
        "messages": [
            {"role": "assistant", "content": "MedDent. Sie sprechen mit Bianca."},
        ],
    }
    text = "MedDent, Sie sprechen mit Bianca. Wie lautet Ihr Vorname? Und Ihre Handynummer?"
    raus = antwort_wache.saeubern(sit, text)
    assert "Vorname" in raus or "Handynummer" in raus
    assert raus.count("?") <= 1
