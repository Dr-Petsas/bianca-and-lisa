"""Paket 3: der Live-Replay-Korpus ist vollständig, anonym und konsistent.

Die VERHALTENS-Assertions gegen Bianca liegen bewusst in den reparierenden
Paketen (4–9). Hier wird nur der Korpus selbst festgenagelt, damit keine
Fehlerklasse verloren geht und keine echten Patientendaten ins Repo geraten.
"""
from __future__ import annotations

import re

import pytest

from tests.live_replays import KLASSEN, REPLAYS, replay, replays_der_klasse

_PAKETE = {
    "harden-names-search",
    "separate-noise-silence",
    "stabilize-dialog-state",
    "support-multiple-patients",
    "tighten-intents",
    "enforce-grounded-claims",
}
_TENANTS = {"blessing", "meddent", "thaler", "ruether"}


def test_jede_fehlerklasse_hat_mindestens_einen_replay():
    for klasse in KLASSEN:
        assert replays_der_klasse(klasse), f"Keine Replay für {klasse}"


def test_jede_klasse_zeigt_auf_ein_bekanntes_paket():
    for klasse, paket in KLASSEN.items():
        assert paket in _PAKETE, f"{klasse} -> unbekanntes Paket {paket}"


def test_replays_sind_konsistent_zu_den_klassen():
    for r in REPLAYS:
        assert r.klasse in KLASSEN, f"{r.sid}: unbekannte Klasse {r.klasse}"
        assert r.paket == KLASSEN[r.klasse], f"{r.sid}: Paket weicht ab"
        assert r.tenant in _TENANTS, f"{r.sid}: fremder Mandant {r.tenant}"
        assert r.anrufer, f"{r.sid}: keine Auslöser-Sätze"
        assert r.soll.strip(), f"{r.sid}: kein Soll-Verhalten"
        if r.gegenprobe:
            assert r.gegenprobe_soll.strip(), f"{r.sid}: Gegenprobe ohne Soll"


def test_replay_lookup_funktioniert():
    assert replay("blessing-fusion").klasse == "nachname_fusion"
    with pytest.raises(KeyError):
        replay("gibt-es-nicht")


# --- Anonymisierung: keine echten Patientendaten im Repo -------------------

# Die Klarnamen aus den echten Tagesmanifesten dürfen NICHT im Korpus stehen.
_ECHTE_NAMEN = (
    "bayer", "graf", "popa", "grigorian", "engelt", "kalil", "menek",
    "samschitzki", "heinzelmann", "sittenauer", "forchermann", "vorhammer",
    "gussinde", "runft", "alamari",
)
_TELEFON_RE = re.compile(r"\d[\d\s.\-/]{8,}\d")  # 10+-stellige Ziffernfolgen
_GEBURT_RE = re.compile(r"\b\d{1,2}\.\d{1,2}\.(?:19|20)\d{2}\b")


def _korpus_text() -> str:
    teile: list[str] = []
    for r in REPLAYS:
        teile.extend(r.anrufer)
        teile.append(r.gegenprobe_soll)
        teile.extend(r.gegenprobe)
    return "\n".join(teile).lower()


def test_keine_echten_klarnamen_im_korpus():
    text = _korpus_text()
    gefunden = [n for n in _ECHTE_NAMEN if n in text]
    assert not gefunden, f"Echte Namen im Korpus: {gefunden}"


def test_keine_echten_rufnummern_oder_geburtsdaten():
    text = _korpus_text()
    assert not _TELEFON_RE.search(text), "Telefonnummer-artige Ziffernfolge"
    assert not _GEBURT_RE.search(text), "Geburtsdatum-artiges Muster"
