# -*- coding: utf-8 -*-
"""W-SIP-KURZJA (30.08.2026): kurze laute Antworten ("Ja") duerfen nicht
mehr im Knacser-Filter oder im Echo-Sperr-Schwanz der SIP-Bruecke
verhungern. Offline-Tests direkt gegen die VAD-Rahmenlogik — kein Socket,
kein Bianca-Server.

Live-Befund 30.08. 16:23 (Session 141518235d04e572): Anrufer sagte auf
"Waren Sie schon einmal bei uns?" mehrfach "Ja" — Log zeigte
"bruecke-zug verworfen (5 Sprach-Frames)" und Echo-gesperrte Wortanfaenge;
kein Zug erreichte Bianca, zwei Stupse, Anrufer legte auf.
"""

import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest.importorskip("audioop")

from sip_bridge import server as srv  # noqa: E402


def _frame(pegel: int) -> bytes:
    """20-ms-Rahmen (FRAME_B Bytes) mit konstantem int16-Pegel = RMS."""
    n = srv.FRAME_B // 2
    return struct.pack(f"<{n}h", *([pegel] * n))


class _Uhr:
    """Fake-Monotonic: 20 ms je Tick, damit die Stille-Zeiten der VAD
    deterministisch laufen (echte Wanduhr waere im Test quasi 0)."""

    def __init__(self) -> None:
        self.t = 1000.0

    def tick(self) -> None:
        self.t += srv.FRAME_MS / 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture()
def anruf(monkeypatch):
    uhr = _Uhr()
    monkeypatch.setattr(srv.time, "monotonic", uhr)
    a = srv.Anruf(reader=None, writer=None)
    a._uhr = uhr  # fuer die Tests
    return a


def _fuettern(a, rahmen_liste):
    for r in rahmen_liste:
        a._uhr.tick()
        a._vad_rahmen(r)


def test_kurzes_lautes_ja_liefert_zug(anruf):
    """6 Sprach-Frames (120 ms) mit Sprach-Spitzenpegel => Zug kommt an,
    obwohl MIN_SPRACHE_FRAMES (12) nicht erreicht ist."""
    _fuettern(anruf, [_frame(0)] * 20)                 # Leitung ruhig
    _fuettern(anruf, [_frame(2400)] * 6)               # "Ja"
    _fuettern(anruf, [_frame(0)] * 40)                 # Stille bis Zugende
    assert anruf.zuege.qsize() == 1


def test_knacser_bleibt_verworfen(anruf):
    """2 laute Frames (40 ms) sind ein Leitungs-Knacser — kein Zug."""
    _fuettern(anruf, [_frame(0)] * 20)
    _fuettern(anruf, [_frame(5000)] * 3)               # Aufnahme startet ...
    _fuettern(anruf, [_frame(0)] * 40)
    assert anruf.zuege.qsize() == 0                    # ... wird aber verworfen


def test_kurzer_leiser_zug_bleibt_verworfen(anruf):
    """Kurz UND unter Sprach-Spitzenpegel (KURZ_PEAK) => weiterhin weg."""
    _fuettern(anruf, [_frame(0)] * 20)
    _fuettern(anruf, [_frame(600)] * 6)                # leises Brummen
    _fuettern(anruf, [_frame(0)] * 40)
    assert anruf.zuege.qsize() == 0


def test_langer_zug_wie_bisher(anruf):
    """Normale Antwort (>= 240 ms Sprachanteil) unveraendert."""
    _fuettern(anruf, [_frame(0)] * 20)
    _fuettern(anruf, [_frame(2000)] * 20)
    _fuettern(anruf, [_frame(0)] * 40)
    assert anruf.zuege.qsize() == 1


def test_echo_referenz_klingt_ab(monkeypatch):
    """Nach dem Sprechende faellt die Echo-Referenz: voll bis ECHO_VOLL_S,
    linear gegen 0 am Ende des Nachlauf-Fensters."""
    async def _schreib(_b):
        pass

    w = srv.Wiedergabe(_schreib)
    w._sende_rms.append(12000)                         # lauter Sende-Schwanz
    w._sende_rms.extend([0] * 5)                       # 100 ms alt: voll
    assert w.echo_pegel() == 12000
    w._sende_rms.extend([0] * 20)                      # jetzt 500 ms alt
    ref = w.echo_pegel()
    assert 0 < ref < 12000                             # abklingend ...
    voll_frames = int(srv.ECHO_VOLL_S * 1000 / srv.FRAME_MS)
    erwartet = 12000 * (1 - ((25 * srv.FRAME_MS / 1000) - srv.ECHO_VOLL_S)
                        / (srv.ECHO_NACHLAUF * srv.FRAME_MS / 1000 - srv.ECHO_VOLL_S))
    assert abs(ref - erwartet) <= 1
    w._sende_rms.extend([0] * srv.ECHO_NACHLAUF)       # aus dem Fenster raus
    assert w.echo_pegel() == 0
    assert voll_frames >= 1                            # Konstanten-Sanity


def test_schnelle_antwort_nach_sprechende(anruf):
    """Der Klassiker: Bianca hat gerade zu Ende gesprochen (lauter
    Sende-Schwanz in der Echo-Historie), der Anrufer antwortet ~700 ms
    spaeter kurz mit "Ja" — frueher lag das noch in der harten 800-ms-
    Echo-Sperre (ref 9000, Schwelle 11700), jetzt ist die Referenz
    abgeklungen und der Zug kommt an."""
    anruf.wiedergabe._sende_rms.extend([9000] * 10)    # Frage-Ende
    # Stille-Rahmen altern die Sende-Historie (lauf() sendet Dauer-Stille)
    anruf.wiedergabe._sende_rms.extend([0] * 35)       # 700 ms Denkpause
    _fuettern(anruf, [_frame(0)] * 35)
    assert anruf.wiedergabe.echo_pegel() * srv.ECHO_FAKTOR < 2400
    _fuettern(anruf, [_frame(2400)] * 7)               # "Ja"
    _fuettern(anruf, [_frame(0)] * 40)
    assert anruf.zuege.qsize() == 1
