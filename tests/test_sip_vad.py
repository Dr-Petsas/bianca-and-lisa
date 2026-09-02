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


# --- W-SIP-VOLLBUF (02.09.2026): Audio erst nach vollem Download ------------

def _arm_check(p: dict) -> bool:
    """Gleiche Arm-Logik wie Wiedergabe.lauf — offline ohne Async-Takt."""
    if p.get("armed"):
        return True
    if p["done"]:
        p["armed"] = True
        return True
    return False


def test_fertig_wav_wartet_auf_done_nicht_auf_teilpuffer():
    """Begruessung /api/audio/: auch 1 s schon im buf darf Playout nicht
    starten — erst wenn done (Download+Resample fertig). Sonst Underrun
    mit Stille-Rahmen = Live-Haken bei sauberer Mitschnitt-WAV."""
    async def _schreib(_b):
        pass

    w = srv.Wiedergabe(_schreib)
    p = w.neu("/api/audio/begruessung.wav")
    assert p["armed"] is False and p["stream"] is False
    p["buf"].extend(b"\x00" * (srv.RATE_IN * 2))  # 1 s Audio, aber noch ladend
    assert _arm_check(p) is False
    p["done"] = True
    assert _arm_check(p) is True


def test_stream_url_wartet_auch_auf_done():
    """Telefon: auch /api/audio-stream/ erst nach done — kein 200-ms-Prefill
    (Live 02.09.: Prefill + HTTP-Luecke = starkes Stocken + ReadError)."""
    async def _schreib(_b):
        pass

    w = srv.Wiedergabe(_schreib)
    p = w.neu("/api/audio-stream/xyz.wav")
    assert p["armed"] is False and p["stream"] is True
    p["buf"].extend(b"\x00" * (srv.RATE_IN * 2 * 500 // 1000))  # 500 ms
    assert _arm_check(p) is False
    p["done"] = True
    assert _arm_check(p) is True


# --- W-STT-SCHWANZ (30.08.2026): Hysterese fuers Zugende ---------------------

def test_leiser_auslauf_haelt_zugende_offen(anruf):
    """Am Satzende senkt sich die Stimme unter die Ein-Schwelle (400),
    bleibt aber ueber der Aus-Schwelle (45 %) — frueher lief still_seit
    mitten im leisen Nummern-Ende los und schnitt die letzten Ziffern ab.
    Jetzt haelt der Auslauf das Zugende offen, bis echte Stille kommt."""
    _fuettern(anruf, [_frame(0)] * 20)                 # Leitung ruhig
    _fuettern(anruf, [_frame(2000)] * 20)              # laute Sprache
    _fuettern(anruf, [_frame(300)] * 40)               # 800 ms leiser Auslauf
    assert anruf.zuege.qsize() == 0                    # Zug laeuft noch
    _fuettern(anruf, [_frame(0)] * 40)                 # echte Stille => Ende
    assert anruf.zuege.qsize() == 1
    pcm = anruf.zuege.get_nowait()
    # Der leise Auslauf steckt mit in der Aufnahme (Vorlauf + laut + Auslauf).
    assert len(pcm) >= (20 + 40) * srv.FRAME_B


def test_auslauf_deckel_beendet_trotz_zwischenpegel(anruf):
    """Dauerpegel ZWISCHEN den Schwellen (z. B. Rauschen) darf die Aufnahme
    nicht endlos offen halten: nach HALTE_MAX_S ab dem letzten lauten
    Rahmen friert _letzte_sprache ein, stille_ms spaeter endet der Zug."""
    _fuettern(anruf, [_frame(0)] * 20)
    _fuettern(anruf, [_frame(2000)] * 20)
    # 2 s Zwischenpegel: Deckel (1,0 s) + stille_ms (0,5 s) => Ende mittendrin
    _fuettern(anruf, [_frame(300)] * 100)
    assert anruf.zuege.qsize() == 1


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


# --- W-VERBINDEN-ECHT (31.08.2026): Transfer-Store + HTTP-Peek ---------------

_UUID_HEX = "ffffffffffffffffffff000000004101"          # wie rahmen[1].hex()
_UUID_DASH = "ffffffff-ffff-ffff-ffff-000000004101"     # wie ${BUUID} im CURL


def test_transfer_store_einmal_abholbar():
    srv._TRANSFERS.clear()
    srv.transfer_merken(_UUID_HEX, "+49171234567")
    # Der Dialplan fragt mit der Bindestrich-Form — Normalisierung matcht.
    assert srv.transfer_holen(_UUID_DASH) == "+49171234567"
    # Einmal abholbar: der naechste Anruf-Zyklus bekommt nichts Altes.
    assert srv.transfer_holen(_UUID_DASH) == ""
    assert srv.transfer_holen("deadbeef" * 4) == ""


def test_transfer_store_ttl_raeumt_reste():
    srv._TRANSFERS.clear()
    srv.transfer_merken(_UUID_HEX, "+49123")
    k = next(iter(srv._TRANSFERS))
    srv._TRANSFERS[k] = (srv.time.monotonic() - srv.TRANSFER_TTL_S - 1, "+49123")
    assert srv.transfer_holen(_UUID_DASH) == ""
    assert not srv._TRANSFERS


def test_transfer_ohne_nummer_oder_uuid_wird_nicht_gemerkt():
    srv._TRANSFERS.clear()
    srv.transfer_merken("", "+49123")
    srv.transfer_merken(_UUID_HEX, "")
    assert not srv._TRANSFERS


def test_http_peek_beantwortet_dialplan_curl():
    """Voller Weg wie live: TCP-Verbindung auf den AudioSocket-Port, erste
    Bytes "GET" => die Bruecke antwortet HTTP mit der vorgemerkten Nummer
    (einmal), danach leer. AudioSocket-Anrufe stoert der Peek nicht — deren
    erste Bytes sind der Rahmenkopf."""
    import asyncio

    async def _abfrage(port: int) -> bytes:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(f"GET /transfer?uuid={_UUID_DASH} HTTP/1.1\r\n"
                     f"Host: x\r\n\r\n".encode("ascii"))
        await writer.drain()
        antwort = await reader.read(1024)
        writer.close()
        return antwort

    async def _lauf() -> tuple[bytes, bytes]:
        srv._TRANSFERS.clear()
        srv.transfer_merken(_UUID_HEX, "+49555666777")
        server = await asyncio.start_server(srv._klient, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        erste = await _abfrage(port)
        zweite = await _abfrage(port)
        server.close()
        await server.wait_closed()
        return erste, zweite

    erste, zweite = asyncio.run(_lauf())
    assert erste.startswith(b"HTTP/1.1 200 OK") and erste.endswith(b"+49555666777")
    assert zweite.endswith(b"\r\n\r\n")  # verbraucht: leerer Body


def test_stream_underrun_gibt_ohr_frei(anruf):
    """W-SIP-OHR: haengender Stream-Posten (done=False, buf leer gespielt)
    darf nach SPIEL_NACHLAUF_S die Aufnahme nicht mehr im Barge-Modus halten.
    Live 02.09.: aktiv klebte True, Anrufer sprach ungehhört."""
    # Fake-Posten wie nach ausgespielt.em Stream-Underrun.
    anruf.wiedergabe.posten = [{
        "url": "/api/audio-stream/x.wav", "buf": bytearray(), "done": False,
        "sent": 0, "armed": True, "stream": True,
    }]
    anruf.wiedergabe.zuletzt_ton = anruf._uhr() - (srv.SPIEL_NACHLAUF_S + 0.2)
    assert anruf.wiedergabe.aktiv is True
    assert anruf.wiedergabe.spielt() is False
    # Normale Sprech-Schwelle (400) + START_FRAMES: kurzes "Ja" reicht.
    _fuettern(anruf, [_frame(1800)] * 6)
    _fuettern(anruf, [_frame(0)] * 40)
    assert anruf.zuege.qsize() == 1
    assert anruf.wiedergabe.posten == []  # Zombie-Stream verworfen


def test_kurzer_stream_gap_bleibt_barge(anruf):
    """Kurze TTS-Luecke (< SPIEL_NACHLAUF_S) bleibt Barge — kein Fehlstart."""
    anruf.wiedergabe.posten = [{
        "url": "/api/audio-stream/x.wav", "buf": bytearray(), "done": False,
        "sent": 0, "armed": True, "stream": True,
    }]
    anruf.wiedergabe.zuletzt_ton = anruf._uhr() - 0.05  # frisch gespielt
    assert anruf.wiedergabe.spielt() is True
    # 6 Frames reichen fuer START, nicht fuer BARGE (14) — kein Zug.
    _fuettern(anruf, [_frame(2400)] * 6)
    _fuettern(anruf, [_frame(0)] * 40)
    assert anruf.zuege.qsize() == 0
