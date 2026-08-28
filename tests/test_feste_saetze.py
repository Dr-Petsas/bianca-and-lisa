"""Feste Maschinen-Sätze im TTS-Platten-Cache (bianca/gehirn.feste_saetze,
28.08.2026): jede wörtliche Frage aus naechste_frage muss in der Warm-Liste
stehen — sonst spricht die Maschine live mit voller Synthese-Latenz (~1,2 s
lokal) statt aus dem Cache (~0,2 s). Quelltext-Abgleich als Drift-Wache.
"""

from __future__ import annotations

import inspect
import re

from bianca import gehirn
from kern.sprech import sanitize


def test_alle_woertlichen_fragen_sind_gewarmt():
    quelle = inspect.getsource(gehirn.naechste_frage)
    literale = re.findall(r'return\s+"[a-z_]+",\s+"([^"]+)"', quelle)
    assert len(literale) >= 10, "Quelltext-Scan findet die Fragen nicht mehr"
    fest = set(gehirn.feste_saetze())
    for satz in literale:
        assert satz in fest, f"nicht in feste_saetze() gewarmt: {satz}"


def test_varianten_sind_gewarmt():
    fest = set(gehirn.feste_saetze())
    for formen in gehirn.FRAGE_VARIANTEN.values():
        for f in formen:
            assert f in fest, f


def test_sanitize_ist_stabil_fuer_den_cache_key():
    # Gewarmt wird sanitize(satz); der Zug spricht sanitize(antwort).
    # Idempotenz stellt sicher, dass beide denselben Cache-Key treffen.
    for s in gehirn.feste_saetze():
        einmal = sanitize(s)
        assert sanitize(einmal) == einmal, s


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
    print("test_feste_saetze: alle gruen")
