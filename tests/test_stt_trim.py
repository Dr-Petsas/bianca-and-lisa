# -*- coding: utf-8 -*-
"""W-STT-SCHWANZ (30.08.2026): Schnitt-Grenzen von _stille_trimmen.

Kollegen-Befund: beim Transkribieren wurden manchmal die letzten Ziffern
verschluckt. Eine Ursache sass im Stille-Trim des STT-Containers — die
strenge 5-%-vom-Peak-Schwelle bestimmte auch die SCHNITT-Grenzen, und ein
leise ausklingendes Nummern-Ende (Stimme senkt sich am Satzende um
10-20 dB) laenger als die 320-ms-Marge wurde mit weggeschnitten, bevor
Parakeet es je sah. Seitdem: Schnitt-Grenzen ueber die zarte Schwelle
(1,5 % vom Peak), Verwerfen-Gates weiter ueber die strenge.

Offline gegen die Funktion selbst — kein Container, kein Modell.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types

import pytest

pytest.importorskip("numpy")

import numpy as np  # noqa: E402

_STT_SERVE = pathlib.Path(__file__).resolve().parents[1] / "stt_serve"


def _fake_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


def _modul():
    """stt_serve/server.py laden. Die Container-Abhaengigkeiten (fastapi mit
    python-multipart, uvicorn, postcorrect) leben nur im Docker-Image — fuer
    die reine Trim-Funktion reichen Stubs, numpy bleibt echt."""

    class _FakeApp:
        def __init__(self, *a, **k):
            pass

        def post(self, *a, **k):
            return lambda f: f

        def get(self, *a, **k):
            return lambda f: f

    fakes = {
        "fastapi": _fake_module(
            "fastapi", FastAPI=_FakeApp, File=lambda *a, **k: None,
            Form=lambda *a, **k: None, UploadFile=object,
        ),
        "uvicorn": _fake_module("uvicorn", run=lambda *a, **k: None),
        "postcorrect": _fake_module(
            "postcorrect",
            assess_name_certainty=lambda *a, **k: {},
            correct_transcript=lambda text, kw: (text, []),
        ),
    }
    alt = {name: sys.modules.get(name) for name in fakes}
    sys.modules.update(fakes)
    try:
        spec = importlib.util.spec_from_file_location(
            "stt_serve_server_test", _STT_SERVE / "server.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        for name, m in alt.items():
            if m is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = m


srv = _modul()
FENSTER = srv.SAMPLE_RATE * srv._TRIM_FENSTER_MS // 1000


def _signal(*bloecke: tuple[float, int]) -> np.ndarray:
    """[(pegel, fenster_anzahl), ...] -> float32-Audio in Fenster-Rastern."""
    teile = [np.full(n * FENSTER, pegel, dtype="float32") for pegel, n in bloecke]
    return np.concatenate(teile)


def test_leiser_auslauf_bleibt_im_segment():
    """Lauter Satz + 600 ms leiser Auslauf (ueber zart, unter streng):
    der Auslauf ueberlebt den Trim KOMPLETT — frueher schnitt die strenge
    Schwelle 320 ms nach dem letzten lauten Fenster, 280 ms Ziffern-Ende
    fehlten."""
    audio = _signal((0.0, 50), (0.3, 25), (0.012, 30), (0.0, 50))
    getrimmt, grund = srv._stille_trimmen(audio)
    assert grund and "->" in grund            # es wurde geschnitten ...
    # ... aber Rand-vorn + Sprache + kompletter Auslauf sind noch da.
    assert getrimmt.size >= (srv._TRIM_RAND_VORN + 25 + 30) * FENSTER
    # Nachweis am Inhalt: das letzte Auslauf-Fenster steckt im Ergebnis.
    assert float(np.abs(getrimmt[-1 - srv._TRIM_RAND_HINTEN * FENSTER])) >= 0.01


def test_weicher_anlaut_bleibt_im_segment():
    """Auch vorn schneidet die zarte Schwelle: ein leiser Anlaut laenger
    als die 160-ms-Marge wird nicht mehr gekoepft."""
    audio = _signal((0.0, 50), (0.012, 20), (0.3, 25), (0.0, 50))
    getrimmt, _ = srv._stille_trimmen(audio)
    assert getrimmt.size >= (20 + 25 + srv._TRIM_RAND_HINTEN) * FENSTER


def test_verwerfen_gates_unveraendert():
    """Die Gates urteilen weiter ueber die STRENGE Schwelle: reine Stille
    und Transienten (Knackser) werden verworfen wie seit W-STT-TRIM."""
    stille, grund = srv._stille_trimmen(_signal((0.0, 100)))
    assert stille.size == 0 and "reine stille" in grund
    knack, grund = srv._stille_trimmen(_signal((0.0, 30), (0.5, 3), (0.0, 30)))
    assert knack.size == 0 and "transient" in grund
