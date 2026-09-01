"""SIP-Bruecke (W-SIP 29.08.2026): Asterisk AudioSocket <-> Bianca-Sitzung.

Anrufweg: Zaluma -> Asterisk (87.106.34.137) -> Answer() +
Dial(AudioSocket/127.0.0.1:40101/<uuid>) -> SSH-Ruecktunnel -> dieser Dienst
(pickadoc1) -> Bianca (8096) ueber ihre bestehende Dock-API. Die Bruecke ist
ein reiner UEBERSETZER: sie haelt keinerlei Gespraechslogik — Fluss, Waechter,
Fueller und Buchung bleiben komplett in bianca/* und kern/*.

AudioSocket (Asterisk 18, res/chan/app_audiosocket): TCP, Rahmen =
1 Byte Typ + 2 Byte Laenge (big endian) + Nutzlast. Typen: 0x00 Ende,
0x01 UUID (16 Byte), 0x03 DTMF, 0x10 Audio (PCM16 LE mono 8 kHz, 20 ms =
320 Byte), 0xff Fehler. Beide Richtungen dasselbe Audioformat.

Uebersetzung je Zug:
- Anrufer-Audio: 8-kHz-Rahmen sammeln, Zugende per RMS-Stille (Schwelle
  ``stilleMs`` sagt Bianca je Frage an, W-TEMPO), auf 16 kHz heben, als WAV
  an POST /api/listen — Biancas NDJSON-Strom (filler/transcript/warte/reply)
  steuert, was der Anrufer hoert.
- Bianca-Audio: WAV 24 kHz (auch progressive /api/audio-stream-URLs) auf
  8 kHz druecken und in 20-ms-Rahmen getaktet zurueckschreiben; MP3
  (Verbinden-Jingle) dekodiert ffmpeg.
- Barge-in: spricht der Anrufer waehrend Bianca spricht, stoppt die Wiedergabe
  SOFORT, eine vorgewaermte Quittung ("Hm.") spielt, und der naechste Zug
  traegt bargeUrl+bargeMs — Biancas W-BARGE-Logik (Rest + Fortsetzung)
  arbeitet unveraendert.
- Stille: ~4 s Funkstille nach Biancas Sprechende -> POST /api/stille
  (deterministischer Stups, Budget verwaltet der Server).
- hangup=true in der Antwort (Weiterleitung/Abschied) -> Audio zu Ende
  spielen, AudioSocket-Ende-Rahmen, POST /api/hangup. Legt der ANRUFER auf
  (TCP-Ende), ebenso /api/hangup — die Nacharbeit (Terminnotiz, Gedaechtnis)
  laeuft serverseitig wie beim Dock.

Kein Rueckbau der Dock-Wege: die Browser-Docks (8095/8096) laufen unveraendert
parallel; die Bruecke ist ein ZUSAETZLICHER Klient derselben API.
"""

from __future__ import annotations

import asyncio
import audioop
import contextlib
import json
import os
import re
import struct
import time
from collections import deque

import httpx

BIANCA_BASE = (os.environ.get("BIANCA_BASE") or "http://127.0.0.1:8096").rstrip("/")
BRIDGE_PORT = int(os.environ.get("BRIDGE_PORT") or "40101")
BRIDGE_TENANT = (os.environ.get("BRIDGE_TENANT") or "").strip()

# W-MANDANT (30.08.2026): Der Dialplan (extensions_bianca.conf) traegt je
# DID eine FESTE AudioSocket-UUID, deren Hex-Ende die Leitung verraet
# (…4101 / …4110). Die Brücke uebersetzt das UUID-Ende in die angerufene
# Nummer und meldet sie Bianca beim /api/start — dort laedt
# kern/agentprofil.py den passenden Mandanten (lokal bzw. Pickadoc-DB).
# Format: "hexende=+E164,hexende=+E164". Neue DID = neuer Dialplan-Eintrag
# mit eigener UUID + Eintrag hier (oder in BRIDGE_DID_MAP).
_DID_MAP_ROH = (os.environ.get("BRIDGE_DID_MAP")
                or "4101=+4921154244101,4110=+4921154244110,"
                   "4120=+4921154244120,4105=+4921154244105").strip()
DID_MAP: dict[str, str] = {}
for _paar in _DID_MAP_ROH.split(","):
    _k, _, _v = _paar.partition("=")
    if _k.strip() and _v.strip():
        DID_MAP[_k.strip().lower()] = _v.strip()


def did_von_uuid(uuid_bytes: bytes) -> str:
    """Angerufene Nummer aus der Dialplan-UUID — leer, wenn unbekannt."""
    hexs = (uuid_bytes or b"").hex().lower()
    treffer = ""
    for ende, did in DID_MAP.items():
        # Der laengste passende Schluessel gewinnt (…244101 schlaegt …4101).
        if hexs.endswith(ende) and len(ende) > len(treffer):
            treffer = ende
    return DID_MAP.get(treffer, "")


def caller_von_uuid(uuid_bytes: bytes) -> str:
    """Anrufernummer aus dem UUID-Kopf (W-ANRUFER 30.08.2026).

    AudioSocket uebergibt nur die UUID — deshalb packt der Dialplan die
    CALLERID-Ziffern (FILTER 0-9, Ziffern sind gueltige Hex-Zeichen)
    rechtsbuendig in die ERSTEN 20 Hex-Zeichen, links mit 'f' gepolstert;
    das UUID-Ende bleibt die DID-Kennung (did_von_uuid unveraendert).
    Nur-Ziffern nach dem Polster = Nummer (roh, wie geliefert — z. B.
    "004915253904756"; normalisiert wird serverseitig). Alles andere
    (alte feste UUIDs "b1a2ca00…", Zufalls-UUIDs der Proben, reines
    f-Polster bei unterdrueckter Nummer) -> ""."""
    hexs = (uuid_bytes or b"").hex().lower()
    kopf = hexs[:20].lstrip("f")
    if len(kopf) >= 5 and kopf.isdigit():
        return kopf
    return ""

# W-SIP-PEGEL (30.08.2026): Biancas Renders fahren mit Sprach-RMS -14 dBFS
# und Peaks am 0,95-Deckel — im Dock richtig (Chef-Abnahme 28.08.), auf der
# G.711-Strecke klang das "sehr uebersteuert" (Kollege 30.08.). Darum wird
# NUR Richtung Asterisk gedaempft, an der einen Sende-Stelle in
# Wiedergabe.lauf() VOR der Echo-Referenz (Halbduplex-Wache bleibt
# konsistent, das echte Leitungsecho ist ja ebenso leiser). 0.5 = -6 dB.
# 1.0 = Alt-Verhalten. Docks und TTS-Pegel-Schicht unangetastet.
try:
    BRIDGE_GAIN = float(os.environ.get("BRIDGE_GAIN") or "0.5")
except ValueError:
    BRIDGE_GAIN = 0.5
if BRIDGE_GAIN <= 0:
    BRIDGE_GAIN = 1.0

# W-SIP-ECHO-RAUS (30.08.2026, Chef: "schmeiss das echo gedöhns raus fürs
# stt"): die Halbduplex-Echo-Sperre (Eingang zaehlt nur als Sprache, wenn
# er 30 % ueber dem juengst Gesendeten liegt) hielt echte Antworten vom
# STT fern — Kollegen-Test 17:0x: Sprache mit rms 8000-9000 bei echoRef
# 12000-15000 wurde komplett verschluckt. Die Sperre ist DEFAULT AUS;
# das echte Leitungsecho ist seit W-SIP-PEGEL 6 dB leiser, und faellt
# doch ein Echo-Transkript durch, faengt es die Text-Echo-Wache im Dienst
# (unterbrechung.ist_echo: verwerfen + weitersprechen). Rueckweg fuer den
# Notfall: BRIDGE_ECHO=1 = Alt-Verhalten (W-SIP-RAUSCH-Halbduplex).
BRIDGE_ECHO = (os.environ.get("BRIDGE_ECHO") or "0").strip() == "1"

# W-START-RUHE (31.08.2026, Chef: "manchmal hackt es am anfang oder der
# agent spricht schon aber die leitung steht noch gar nicht ... und es
# klingt eh natuerlicher, wenn der nicht sofort abnimmt"): zwischen dem
# Abheben (UUID-Rahmen der Leitung) und der Begruessung liegt MINDESTENS
# diese Ruhe. Die Laufzeit von /api/start wird angerechnet — dauert der
# Mandanten-Lookup ohnehin so lange, kommt nichts obendrauf. 0 = aus.
try:
    START_RUHE_S = float(os.environ.get("BRIDGE_START_RUHE_S") or "1.0")
except ValueError:
    START_RUHE_S = 1.0

# AudioSocket-Rahmentypen
K_ENDE = 0x00
K_UUID = 0x01
K_DTMF = 0x03
K_AUDIO = 0x10
K_FEHLER = 0xFF

RATE_IN = 8000          # Asterisk-Seite (slin)
RATE_STT = 16000        # Parakeet-freundlich
RATE_TTS = 24000        # Biancas WAVs
FRAME_MS = 20
FRAME_B = RATE_IN * 2 * FRAME_MS // 1000  # 320

# Zugende-Erkennung (Werte an die Dock-Mechanik angelehnt). Echte
# Telefonleitungen tragen DAUER-Grundrauschen (Live-Befund 29.08.2026:
# starre Schwelle 400 loeste nach 400 ms einen falschen Barge aus und die
# Aufnahme fand nie ein Ende) — darum adaptiver Rauschteppich (_floor):
# faellt schnell auf leise Rahmen, steigt langsam (~+50 %/s) auf laute,
# Sprech-Schwelle = max(Grundwert, 3x Teppich), Barge braucht mehr.
SPRECH_RMS = 400        # Untergrenze der Sprech-Schwelle (int16-RMS)
SPRECH_DECKEL = 2200    # Obergrenze: normale Telefonstimme (~1500-4000)
                        # kommt IMMER durch, egal wie hoch der Teppich steht
BARGE_RMS = 1100        # Untergrenze der Barge-Schwelle (Echo/Knacken < echt)
BARGE_DECKEL = 6000     # Obergrenze der Barge-Schwelle (lautes Reinsprechen)
# Leitungsecho-Sperre (Live-Befund 29.08.2026 spaet): die Zaluma/PSTN-Strecke
# wirft Biancas eigene Stimme fast ungedaempft zurueck (Barge bei rms=17518,
# floor=238 — das war die Begruessung selbst). Deshalb Halbduplex-Wache:
# solange juengst eigener Ton gesendet wurde, zaehlt Eingang nur als
# Sprache, wenn er DEUTLICH lauter ist als das lauteste eben Gesendete.
# Der Rauschteppich friert waehrenddessen ein (Echo darf die Schwelle
# nicht hochziehen). Zweiter Live-Befund: das Echo kommt bis ~1 s
# VERZOEGERT (Mobilfunk) und traf in die Satzpause der Begruessung — darum
# langes Fenster waehrend der Wiedergabe, kurzer Nachlauf danach (sonst
# sperrt der Begruessungs-Schwanz die echte Antwort des Anrufers aus).
# SEIT W-SIP-ECHO-RAUS (30.08.2026) DEFAULT AUS — nur mit BRIDGE_ECHO=1:
ECHO_FAKTOR = 1.3       # Anrufer muss 30 % ueber dem Sende-Pegel liegen
ECHO_FENSTER = 100      # 2 s Sende-Historie, solange Bianca spricht
ECHO_NACHLAUF = 40      # 800 ms Sperr-Schwanz nach dem Sprechende
FLOOR_START = 200.0
FLOOR_MIN = 60.0
FLOOR_MAX = 4000.0
START_FRAMES = 3        # 60 ms Sprache = Zugbeginn
BARGE_FRAMES = 14       # 280 ms Sprache waehrend Bianca spricht = Barge
# W-STT-SCHWANZ (30.08.2026): 500 ms Vorlauf wie der phone_agent
# (VAD_PREROLL_MS=500, dort gegen abgeschnittene Wortanfaenge wie
# "gesetzlich" -> "ersetzlich") statt vorher 300 ms.
VORLAUF_FRAMES = 25     # 500 ms Ringpuffer vor dem Zugbeginn
MIN_SPRACHE_FRAMES = 12 # unter 240 ms Sprachanteil: verwerfen (Knacser)
# W-SIP-KURZJA (30.08.2026): ein gesprochenes "Ja" hat nur ~100-200 ms
# Stimmanteil — der 240-ms-Deckel verwarf echte Antworten ("zug verworfen
# (5 Sprach-Frames)", Anrufer sagte mehrfach Ja, kein Zug erreichte Bianca).
# Kurz-aber-laut-Ausnahme: ab KURZ_FRAMES Sprach-Frames reicht ein
# Spitzenpegel auf Sprachniveau; Leitungs-Knackser (1-2 Frames) bleiben
# draussen, den Rest faengt der Stille-Trim im STT-Container (W-STT-TRIM).
KURZ_FRAMES = 4         # 80 ms Sprachanteil ...
KURZ_PEAK = 1200        # ... wenn der Spitzenpegel klar Sprache ist
# W-SIP-KURZJA Teil 2: der 800-ms-Echo-Sperr-Schwanz nach Biancas
# Sprechende blockte schnelle Antworten auf Ja/Nein-Fragen (genau die,
# fuer die W-TEMPO die 350-ms-Schwelle ansagt) — der Wortanfang galt als
# Echo, der Rest schaffte die 3 Start-Frames nicht. Jetzt klingt die
# Echo-Referenz nach dem Sprechende ab: volle Sperre ECHO_VOLL_S, dann
# linear auf 0 bis zum Ende des Nachlauf-Fensters (800 ms wie bisher).
ECHO_VOLL_S = 0.3       # so lange gilt die volle Echo-Referenz
# W-STT-SCHWANZ (30.08.2026): Hysterese fuers Zugende. Am Satzende senkt
# sich die Stimme um 10-20 dB — leise Schluss-Ziffern lagen unter der
# Ein-Schwelle, still_seit lief mitten im Wort los und der Zug endete,
# waehrend der Anrufer noch aussprach ("letzte Ziffern verschluckt",
# Kollegen-Befund 30.08.). Vorbild phone_agent (VAD_ON 600 / VAD_OFF 320):
# Sprache bleibt "an", solange der Pegel ueber der niedrigeren
# Aus-Schwelle liegt. Der leise Auslauf haelt das Zugende hoechstens
# HALTE_MAX_S ueber den letzten klar lauten Rahmen hinaus offen —
# Dauerrauschen zwischen den Schwellen kann die Aufnahme nie endlos
# aufhalten (Deckel MAX_ZUG_S bleibt daneben bestehen).
HALTE_FAKTOR = 0.45     # Aus-Schwelle = 45 % der Ein-Schwelle
HALTE_MAX_S = 1.0       # leiser Auslauf verlaengert hoechstens so lange
STILLE_MS_DEFAULT = 500 # wie das Dock; Bianca sagt je Frage ihre Schwelle an
MAX_ZUG_S = 20.0        # Deckel je Aeusserung
STUPS_NACH_S = 4.0      # Funkstille bis /api/stille (wie Dock)
MAX_ANRUF_S = 1800.0


# W-VERBINDEN-ECHT (31.08.2026): meldet Bianca im reply ein transfer-Ziel
# ({nummer, name} — der Client hat eine Weiterleitung eingerichtet), merkt
# sich die Bruecke die Nummer je Anruf-UUID. Der Asterisk-Dialplan fragt sie
# NACH dem AudioSocket-Ende per CURL auf DEMSELBEN Port ab (HTTP-Peek:
# erste Bytes "GET") und waehlt selbst zu Zaluma raus — kein zweiter
# Tunnel-Port, keine neue Firewall-Regel. Eintraege sind EINMAL abholbar
# (der Dialplan fragt nach jedem Anruf) und verfallen nach TRANSFER_TTL_S.
TRANSFER_TTL_S = 300.0
_TRANSFERS: dict[str, tuple[float, str]] = {}
_HTTP_UUID_RE = re.compile(r"uuid=([0-9a-fA-F\-]+)")


def _uuid_norm(u: str) -> str:
    return "".join(c for c in (u or "").lower() if c in "0123456789abcdef")


def transfer_merken(uuid_hex: str, nummer: str) -> None:
    u, n = _uuid_norm(uuid_hex), " ".join(str(nummer or "").split())
    if u and n:
        _TRANSFERS[u] = (time.monotonic(), n)


def transfer_holen(uuid_roh: str) -> str:
    """Weiterleitungs-Nummer zum Anruf — einmal abholbar, TTL raeumt Reste."""
    jetzt = time.monotonic()
    for k in [k for k, (t, _) in _TRANSFERS.items() if jetzt - t > TRANSFER_TTL_S]:
        _TRANSFERS.pop(k, None)
    hit = _TRANSFERS.pop(_uuid_norm(uuid_roh), None)
    return hit[1] if hit else ""


async def _http_transfer(reader: asyncio.StreamReader,
                         writer: asyncio.StreamWriter) -> None:
    """CURL des Dialplans: ``GET /transfer?uuid=<uuid>`` -> Nummer (text/plain).

    Das fuehrende "GET" hat _klient schon konsumiert — hier kommt der Rest
    der Request-Zeile. Unbekannte/verbrauchte UUID => leerer Body, der
    Dialplan legt dann normal auf."""
    try:
        roh = await asyncio.wait_for(reader.read(1024), timeout=2.0)
    except Exception:
        roh = b""
    zeile = roh.split(b"\r\n", 1)[0].decode("ascii", "replace")
    m = _HTTP_UUID_RE.search(zeile)
    nummer = transfer_holen(m.group(1)) if m else ""
    body = nummer.encode("ascii", "ignore")
    with contextlib.suppress(Exception):
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n"
                     b"Content-Length: " + str(len(body)).encode("ascii") +
                     b"\r\nConnection: close\r\n\r\n" + body)
        await writer.drain()
        writer.close()
    if m:
        print(f"bruecke-transfer-abfrage uuid={m.group(1)} -> "
              f"{nummer or 'leer'}", flush=True)


def _wav(pcm: bytes, rate: int) -> bytes:
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + len(pcm), b"WAVE", b"fmt ", 16, 1, 1,
        rate, rate * 2, 2, 16, b"data", len(pcm),
    ) + pcm


class Wiedergabe:
    """Getaktete Ausgabe Richtung Asterisk: 20-ms-Rahmen, progressiv
    befuellbare Posten (Stream-URLs spielen, waehrend sie noch laden)."""

    def __init__(self, schreib) -> None:
        self._schreib = schreib          # async fn(bytes 320)
        self.posten: list[dict] = []     # {url, buf, done, sent}
        self.lock = asyncio.Lock()
        self.zuletzt_ton = 0.0           # monotonic des letzten Rahmens
        self.fertig_seit = time.monotonic()
        self._sende_rms: deque = deque(maxlen=ECHO_FENSTER)

    def echo_pegel(self) -> int:
        """Lautester juengst gesendeter Rahmen (0 = lange still).

        Waehrend der Wiedergabe zaehlt das volle 2-s-Fenster (verzoegertes
        Echo faellt sonst in Satzpausen), danach nur der kurze Nachlauf —
        und der klingt AB (W-SIP-KURZJA): jeder Rahmen zaehlt voll, solange
        er juenger als ECHO_VOLL_S ist, danach linear fallend bis zum Ende
        des Nachlauf-Fensters. So sperrt der Begruessungs-Schwanz nicht
        mehr die schnelle kurze Antwort ("Ja") des Anrufers aus.
        """
        if self.aktiv:
            return max(self._sende_rms, default=0)
        werte = list(self._sende_rms)[-ECHO_NACHLAUF:]
        # Stille-Rahmen fuellen die Deque weiter (lauf() sendet Dauer-Stille),
        # darum ist die Position vom Ende zugleich das Alter des Rahmens.
        nachlauf_s = ECHO_NACHLAUF * FRAME_MS / 1000.0
        ref = 0.0
        n = len(werte)
        for i, w in enumerate(werte):
            if w <= 0:
                continue
            alter = (n - 1 - i) * FRAME_MS / 1000.0
            if alter <= ECHO_VOLL_S:
                f = 1.0
            else:
                f = max(0.0, 1.0 - (alter - ECHO_VOLL_S) / (nachlauf_s - ECHO_VOLL_S))
            ref = max(ref, w * f)
        return int(ref)

    def neu(self, url: str) -> dict:
        p = {"url": url, "buf": bytearray(), "done": False, "sent": 0}
        self.posten.append(p)
        return p

    @property
    def aktiv(self) -> bool:
        return any(len(p["buf"]) > p["sent"] or not p["done"] for p in self.posten)

    def stoppen(self) -> tuple[str, float]:
        """Barge: alles verwerfen; (url, gespielte ms) des laufenden Postens."""
        url, ms = "", 0.0
        for p in self.posten:
            if p["sent"] > 0 and (len(p["buf"]) > p["sent"] or not p["done"]):
                url, ms = p["url"], p["sent"] / (RATE_IN * 2 / 1000.0)
                break
        # Auch ein eben FERTIG gespielter Posten zaehlt als Unterbrechungsort,
        # wenn danach noch ungespielte Posten warten.
        if not url:
            wartend = [p for p in self.posten if p["sent"] == 0]
            gespielt = [p for p in self.posten if p["sent"] > 0]
            if wartend and gespielt:
                letzte = gespielt[-1]
                url, ms = letzte["url"], letzte["sent"] / (RATE_IN * 2 / 1000.0)
        self.posten.clear()
        return url, ms

    async def lauf(self) -> None:
        naechster = time.monotonic()
        sprach = False
        while True:
            jetzt = time.monotonic()
            if jetzt < naechster:
                await asyncio.sleep(naechster - jetzt)
            naechster = max(naechster + FRAME_MS / 1000.0, time.monotonic() - 0.1)
            rahmen = b""
            async with self.lock:
                while self.posten:
                    p = self.posten[0]
                    rest = len(p["buf"]) - p["sent"]
                    if rest >= FRAME_B:
                        rahmen = bytes(p["buf"][p["sent"]:p["sent"] + FRAME_B])
                        p["sent"] += FRAME_B
                        break
                    if p["done"]:
                        if rest > 0:
                            rahmen = bytes(p["buf"][p["sent"]:]) + b"\x00" * (FRAME_B - rest)
                            p["sent"] = len(p["buf"])
                            self.posten.pop(0)
                            break
                        self.posten.pop(0)
                        continue
                    break  # Posten laedt noch — auf Daten warten
            if rahmen:
                if BRIDGE_GAIN != 1.0:
                    rahmen = audioop.mul(rahmen, 2, BRIDGE_GAIN)
                self._sende_rms.append(audioop.rms(rahmen, 2))
                await self._schreib(rahmen)
                self.zuletzt_ton = time.monotonic()
                sprach = True
            else:
                self._sende_rms.append(0)
                # fertig_seit nur beim UEBERGANG spielen->leer setzen — sonst
                # zaehlt der Stups-Timer nie (Live-Befund 29.08.2026).
                if sprach:
                    self.fertig_seit = time.monotonic()
                    sprach = False
                # Dauer-Stille senden: der Medienstrom Richtung Asterisk/
                # Zaluma darf NIE abreissen (RTP-Timeout beendet sonst den
                # Anruf, sobald Bianca schweigt und zuhoert).
                await self._schreib(b"\x00" * FRAME_B)


class Anruf:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                 vorab: bytes = b"") -> None:
        self.reader = reader
        self.writer = writer
        self._vorab = vorab       # von _klient schon gelesene Kopf-Bytes
        self.uuid_hex = ""        # Anruf-UUID (Schluessel fuer W-VERBINDEN-ECHT)
        self.http = httpx.AsyncClient(base_url=BIANCA_BASE,
                                      timeout=httpx.Timeout(60.0, connect=5.0))
        self.session_id = ""
        self.did = ""  # W-MANDANT: angerufene Nummer aus der Dialplan-UUID
        self.caller = ""  # W-ANRUFER: Anrufernummer aus dem UUID-Kopf
        self.stille_ms = STILLE_MS_DEFAULT
        self.wiedergabe = Wiedergabe(self._audio_raus)
        self.zuege: asyncio.Queue = asyncio.Queue()
        self.schreib_lock = asyncio.Lock()
        self.lebt = True
        self.barge_url = ""
        self.barge_ms = 0.0
        self.quittungen: list[bytes] = []
        self.quittung_nr = 0
        self.stups_zahl = 0
        # VAD-Zustand
        self._ring: list[bytes] = []
        self._rec = bytearray()
        self._rec_an = False
        self._rec_start = 0.0
        self._sprech_run = 0
        self._sprech_frames = 0
        self._peak_run = 0         # Spitzenpegel des laufenden Sprach-Laufs
        self._rec_peak = 0         # Spitzenpegel der laufenden Aufnahme
        self._letzte_sprache = time.monotonic()
        self._letzte_laut = time.monotonic()  # letzter Rahmen UEBER der Ein-Schwelle
        self._rest = bytearray()
        self._floor = FLOOR_START  # Rauschteppich der Leitung (adaptiv)
        self._audio_format = ""    # "", "slin" oder "alaw" (Erst-Erkennung)
        self._diag_n = 0           # Pegel-Diagnose: Rahmen seit letzter Zeile
        self._diag_max = 0

    # ---- AudioSocket-Rohschicht ------------------------------------------

    async def _audio_raus(self, pcm: bytes) -> None:
        async with self.schreib_lock:
            self.writer.write(struct.pack(">BH", K_AUDIO, len(pcm)) + pcm)
            await self.writer.drain()

    async def _ende_raus(self) -> None:
        with contextlib.suppress(Exception):
            async with self.schreib_lock:
                self.writer.write(struct.pack(">BH", K_ENDE, 0))
                await self.writer.drain()

    async def _rahmen_lesen(self) -> tuple[int, bytes] | None:
        try:
            if self._vorab:
                kopf, self._vorab = self._vorab, b""
            else:
                kopf = await self.reader.readexactly(3)
        except (asyncio.IncompleteReadError, ConnectionError):
            return None
        typ, laenge = kopf[0], struct.unpack(">H", kopf[1:3])[0]
        nutz = b""
        if laenge:
            try:
                nutz = await self.reader.readexactly(laenge)
            except (asyncio.IncompleteReadError, ConnectionError):
                return None
        return typ, nutz

    # ---- Audio von Bianca holen -------------------------------------------

    async def _laden(self, url: str) -> None:
        """URL fetchen, nach 8 kHz wandeln, progressiv in die Wiedergabe."""
        posten = self.wiedergabe.neu(url)
        try:
            if "/api/audio-stream/" in url:
                zustand = None
                kopf_rest = 44
                uebertrag = b""
                async with self.http.stream("GET", url) as r:
                    async for stueck in r.aiter_bytes():
                        if kopf_rest:
                            schnitt = min(kopf_rest, len(stueck))
                            stueck = stueck[schnitt:]
                            kopf_rest -= schnitt
                        if not stueck:
                            continue
                        stueck = uebertrag + stueck
                        if len(stueck) % 2:  # PCM16-Ausrichtung halten
                            uebertrag = stueck[-1:]
                            stueck = stueck[:-1]
                        else:
                            uebertrag = b""
                        pcm8, zustand = audioop.ratecv(stueck, 2, 1, RATE_TTS, RATE_IN, zustand)
                        async with self.wiedergabe.lock:
                            posten["buf"].extend(pcm8)
            else:
                r = await self.http.get(url)
                blob = r.content
                if blob[:4] == b"RIFF":
                    pcm8, _ = audioop.ratecv(blob[44:], 2, 1, RATE_TTS, RATE_IN, None)
                else:  # MP3 (Jingle) — ffmpeg dekodiert
                    pcm8 = await self._mp3_zu_pcm8(blob)
                async with self.wiedergabe.lock:
                    posten["buf"].extend(pcm8)
        except Exception as e:
            print(f"bruecke-laden fail {url} {type(e).__name__}: {e}", flush=True)
        finally:
            posten["done"] = True

    @staticmethod
    async def _mp3_zu_pcm8(blob: bytes) -> bytes:
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
                "-f", "s16le", "-ar", str(RATE_IN), "-ac", "1", "pipe:1",
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL)
            out, _ = await proc.communicate(blob)
            return out or b""
        except FileNotFoundError:
            print("bruecke-mp3 uebersprungen (kein ffmpeg)", flush=True)
            return b""

    def _spielen(self, url: str) -> None:
        if url:
            asyncio.create_task(self._laden(url))

    def _quittung(self) -> None:
        if not self.quittungen:
            return
        pcm = self.quittungen[self.quittung_nr % len(self.quittungen)]
        self.quittung_nr += 1
        p = self.wiedergabe.neu("")  # eigene URL: nie als Barge-Rest deutbar
        p["buf"].extend(pcm)
        p["done"] = True

    # ---- Anrufer-Audio: Zugende-Erkennung ----------------------------------

    def _eingang(self, nutz: bytes) -> bytes:
        """Anrufer-Frame nach PCM16 wandeln.

        Live-Befund 30.08.2026: Asterisk reicht auf der Zaluma-Strecke das
        Anrufer-Audio UNKONVERTIERT als G.711 A-law durch (160-Byte-Frames
        statt 320; A-law-Stille 0xD5 als PCM16 gelesen = konstant -10795 —
        exakt der "Dauerton" im Mitschnitt, an dem das STT verhungerte).
        Richtung Anrufer wandelt Asterisk unser slin sauber — nur der
        Rueckweg braucht die Dekodierung. Erkennung einmal pro Anruf ueber
        die Frame-Laenge (20 ms: alaw=160, slin=320); Local-Channel-Tests
        und die Docker-Probe senden weiterhin echtes slin.

        W-SIP-SLIN 30.08.2026: die Laengen-Heuristik konnte alaw nicht von
        ULAW unterscheiden (beide 160 B) — ulaw-Anrufer (je nach Zubringer)
        klangen mit der A-law-Kennlinie uebel verzerrt (Signatur: ulaw-Stille
        0xFF als alaw gelesen = konstant +848, im Log floor~880). Seitdem
        nutzt der Asterisk-Dialplan die AudioSocket()-APPLIKATION statt
        Dial(AudioSocket/...): sie zwingt den Kanal auf slin, Asterisk
        transkodiert selbst — hier kommt IMMER slin (320 B) an. Der
        alaw-Zweig bleibt nur als Rueckfall fuer einen alten Dialplan.
        """
        if not self._audio_format:
            self._audio_format = "alaw" if len(nutz) == 160 else "slin"
            print(f"bruecke-format {self._audio_format} "
                  f"(frame={len(nutz)}B)", flush=True)
        if self._audio_format == "alaw":
            return audioop.alaw2lin(nutz, 2)
        return nutz

    def _vad(self, pcm: bytes) -> None:
        self._rest.extend(pcm)
        while len(self._rest) >= FRAME_B:
            rahmen = bytes(self._rest[:FRAME_B])
            del self._rest[:FRAME_B]
            self._vad_rahmen(rahmen)

    def _vad_rahmen(self, rahmen: bytes) -> None:
        rms = audioop.rms(rahmen, 2)
        # Leitungsecho-Sperre (nur mit BRIDGE_ECHO=1, s. W-SIP-ECHO-RAUS):
        # kam juengst eigener Ton raus, gilt Eingang nur als Sprache, wenn
        # er DEUTLICH lauter ist als das Gesendete. echo_ref laeuft fuer
        # die Pegel-Diagnose immer mit.
        echo_ref = self.wiedergabe.echo_pegel()
        echo = BRIDGE_ECHO and echo_ref >= SPRECH_RMS and rms < echo_ref * ECHO_FAKTOR
        if not echo:
            # Rauschteppich: schnell runter auf leise Rahmen, langsam
            # (~+50 %/s) hoch — Dauerrauschen waechst in die Schwelle hinein,
            # echte Sprache bleibt darueber, danach faellt der Teppich zurueck.
            # Echo-Rahmen lassen ihn EINGEFROREN (sonst zieht die eigene
            # Stimme die Schwelle hoch).
            if rms < self._floor:
                self._floor = max(FLOOR_MIN, 0.7 * self._floor + 0.3 * rms)
            else:
                self._floor = min(FLOOR_MAX, self._floor * 1.008 + 1.0)
        if self.wiedergabe.aktiv and not self._rec_an:
            schwelle = min(max(BARGE_RMS, self._floor * 5.0), BARGE_DECKEL)
        else:
            schwelle = min(max(SPRECH_RMS, self._floor * 2.2), SPRECH_DECKEL)
        laut = (not echo) and rms >= schwelle
        # Pegel-Diagnose: alle 2 s eine Zeile — Feldbefunde ohne Blindflug.
        self._diag_n += 1
        self._diag_max = max(self._diag_max, rms)
        if self._diag_n >= 100:
            print(f"bruecke-pegel max={self._diag_max} floor={self._floor:.0f} "
                  f"schwelle={schwelle:.0f} echoRef={echo_ref} "
                  f"aktiv={self.wiedergabe.aktiv} rec={self._rec_an}", flush=True)
            self._diag_n = 0
            self._diag_max = 0
        jetzt = time.monotonic()
        if laut:
            self._sprech_run += 1
            self._peak_run = max(self._peak_run, rms)
            self._letzte_laut = jetzt
            self._letzte_sprache = jetzt
        else:
            self._sprech_run = 0
            self._peak_run = 0
            # W-STT-SCHWANZ: leiser Sprach-Auslauf (Hysterese) haelt das
            # Zugende offen — aber nur waehrend einer laufenden Aufnahme
            # und hoechstens HALTE_MAX_S nach dem letzten lauten Rahmen.
            if (self._rec_an and not echo and rms >= schwelle * HALTE_FAKTOR
                    and jetzt - self._letzte_laut <= HALTE_MAX_S):
                self._letzte_sprache = jetzt

        if not self._rec_an:
            self._ring.append(rahmen)
            if len(self._ring) > VORLAUF_FRAMES:
                self._ring.pop(0)
            noetig = BARGE_FRAMES if self.wiedergabe.aktiv else START_FRAMES
            if self._sprech_run >= noetig:
                if self.wiedergabe.aktiv:
                    url, ms = self.wiedergabe.stoppen()
                    self.barge_url, self.barge_ms = url, ms
                    self._quittung()
                    print(f"bruecke-barge url={url} ms={ms:.0f} "
                          f"rms={rms} floor={self._floor:.0f} "
                          f"echoRef={echo_ref}", flush=True)
                self._rec_an = True
                self._rec_start = jetzt
                self._rec = bytearray(b"".join(self._ring))
                self._ring.clear()
                self._sprech_frames = self._sprech_run
                self._rec_peak = self._peak_run
            return

        self._rec.extend(rahmen)
        if laut:
            self._sprech_frames += 1
            self._rec_peak = max(self._rec_peak, rms)
        still_seit = (jetzt - self._letzte_sprache) * 1000.0
        if still_seit >= max(self.stille_ms, 200) or (jetzt - self._rec_start) >= MAX_ZUG_S:
            self._rec_an = False
            pcm, frames, peak = bytes(self._rec), self._sprech_frames, self._rec_peak
            self._rec = bytearray()
            self._sprech_frames = 0
            self._rec_peak = 0
            # W-SIP-KURZJA: kurze, aber klar sprach-laute Zuege ("Ja",
            # "Nein", "Okay") zaehlen — nur Knackser (1-3 Frames oder
            # ohne Sprachpegel) werden weiter verworfen.
            gilt = frames >= MIN_SPRACHE_FRAMES or (
                frames >= KURZ_FRAMES and peak >= KURZ_PEAK)
            if gilt:
                self.stups_zahl = 0
                print(f"bruecke-zug {len(pcm) // 16} ms "
                      f"({frames} Sprach-Frames, peak={peak}, "
                      f"floor={self._floor:.0f})", flush=True)
                self.zuege.put_nowait(pcm)
            else:
                print(f"bruecke-zug verworfen ({frames} Sprach-Frames, "
                      f"peak={peak}, floor={self._floor:.0f})", flush=True)

    # ---- Bianca-Dialog ------------------------------------------------------

    async def _start(self) -> bool:
        t0 = time.monotonic()
        r = await self.http.post("/api/start",
                                 json={"tenant": BRIDGE_TENANT, "did": self.did,
                                       "caller": self.caller})
        if r.status_code != 200:
            print(f"bruecke-start http {r.status_code}", flush=True)
            return False
        d = r.json()
        self.session_id = d.get("sessionId") or ""
        self.stille_ms = int(d.get("stilleMs") or STILLE_MS_DEFAULT)
        print(f"bruecke-start session={self.session_id} did={self.did or '-'} "
              f"tenant={d.get('tenantId', '')} text={d.get('text', '')[:60]!r}", flush=True)
        # W-START-RUHE: erst nach einer kurzen Ruhe seit Abheben begruessen —
        # die /api/start-Zeit zaehlt mit, gewartet wird nur der Rest.
        rest = START_RUHE_S - (time.monotonic() - t0)
        if rest > 0:
            await asyncio.sleep(rest)
        self._spielen(d.get("audioUrl") or "")
        with contextlib.suppress(Exception):
            q = await self.http.get("/api/quittung")
            for url in (q.json().get("urls") or [])[:4]:
                blob = (await self.http.get(url)).content
                if blob[:4] == b"RIFF":
                    pcm8, _ = audioop.ratecv(blob[44:], 2, 1, RATE_TTS, RATE_IN, None)
                    self.quittungen.append(pcm8)
        return bool(self.session_id)

    async def _zug(self, pcm8: bytes) -> bool:
        """Einen Anrufer-Zug an Bianca geben. False = auflegen."""
        pcm16, _ = audioop.ratecv(pcm8, 2, 1, RATE_IN, RATE_STT, None)
        wav = _wav(pcm16, RATE_STT)
        if os.environ.get("BRIDGE_DUMP") == "1":
            pfad = f"/tmp/zug-{int(time.time())}.wav"
            with open(pfad, "wb") as f:
                f.write(wav)
            print(f"bruecke-dump {pfad}", flush=True)
        daten = {"sessionId": self.session_id, "text": "",
                 "bargeUrl": self.barge_url, "bargeMs": str(self.barge_ms)}
        self.barge_url, self.barge_ms = "", 0.0
        auflegen = False
        try:
            async with self.http.stream(
                "POST", "/api/listen", data=daten,
                files={"audio": ("zug.wav", wav, "audio/wav")},
            ) as r:
                async for zeile in r.aiter_lines():
                    zeile = zeile.strip()
                    if not zeile:
                        continue
                    try:
                        ev = json.loads(zeile)
                    except ValueError:
                        continue
                    typ = ev.get("type") or ""
                    if typ == "filler":
                        self._spielen(ev.get("audioUrl") or "")
                    elif typ == "transcript":
                        print(f"bruecke-gehoert {ev.get('textIn', '')!r}", flush=True)
                    elif typ == "warte":
                        self.stille_ms = int(ev.get("stilleMs") or 900)
                    elif typ == "reply":
                        self._spielen(ev.get("audioUrl") or "")
                        if ev.get("stilleMs"):
                            self.stille_ms = int(ev["stilleMs"])
                        if ev.get("hangup"):
                            auflegen = True
                        # W-VERBINDEN-ECHT: Weiterleitungs-Ziel VOR dem
                        # Ende-Rahmen vormerken — der Dialplan fragt sofort
                        # nach dem AudioSocket-Ende per CURL nach.
                        tr = ev.get("transfer") if isinstance(ev.get("transfer"), dict) else {}
                        if tr.get("nummer"):
                            transfer_merken(self.uuid_hex, str(tr["nummer"]))
                            print(f"bruecke-transfer vorgemerkt "
                                  f"{tr.get('name', '')!r} {tr['nummer']}", flush=True)
                        print(f"bruecke-antwort {ev.get('text', '')[:80]!r}"
                              f"{' [hangup]' if auflegen else ''}", flush=True)
        except Exception as e:
            print(f"bruecke-zug fail {type(e).__name__}: {e}", flush=True)
        return not auflegen

    async def _stups(self) -> None:
        self.stups_zahl += 1
        try:
            r = await self.http.post("/api/stille", json={"sessionId": self.session_id})
            d = r.json() if r.status_code == 200 else {}
        except Exception:
            d = {}
        if d.get("audioUrl"):
            print(f"bruecke-stups {d.get('text', '')[:60]!r}", flush=True)
            self._spielen(d["audioUrl"])

    async def _dialog(self) -> None:
        ende = time.monotonic() + MAX_ANRUF_S
        while self.lebt and time.monotonic() < ende:
            try:
                pcm = await asyncio.wait_for(self.zuege.get(), timeout=1.0)
            except asyncio.TimeoutError:
                ruhig = (not self.wiedergabe.aktiv and not self._rec_an
                         and time.monotonic() - self.wiedergabe.fertig_seit > STUPS_NACH_S
                         and time.monotonic() - self._letzte_sprache > STUPS_NACH_S)
                if ruhig and self.stups_zahl < 2:
                    await self._stups()
                    self.wiedergabe.fertig_seit = time.monotonic()
                continue
            if not await self._zug(pcm):
                # Abschied/Weiterleitung: fertig spielen, dann auflegen.
                for _ in range(600):
                    if not self.wiedergabe.aktiv:
                        break
                    await asyncio.sleep(0.1)
                await asyncio.sleep(0.4)
                await self._ende_raus()
                self.lebt = False
                return

    # ---- Lebenszyklus -------------------------------------------------------

    async def lauf(self) -> None:
        peer = self.writer.get_extra_info("peername")
        rahmen = await self._rahmen_lesen()
        if not rahmen or rahmen[0] != K_UUID:
            # Healthcheck/Port-Scan: kommentarlos schliessen, keine Sitzung.
            self.writer.close()
            await self.http.aclose()
            return
        self.did = did_von_uuid(rahmen[1])
        self.caller = caller_von_uuid(rahmen[1])
        self.uuid_hex = rahmen[1].hex()
        print(f"bruecke-anruf von {peer} uuid={rahmen[1].hex()} "
              f"did={self.did or '?'} caller={self.caller or 'unterdrueckt'}", flush=True)
        if not await self._start():
            await self._ende_raus()
            self.writer.close()
            await self.http.aclose()
            return
        spieler = asyncio.create_task(self.wiedergabe.lauf())
        dialog = asyncio.create_task(self._dialog())
        try:
            while self.lebt:
                r = await self._rahmen_lesen()
                if r is None or r[0] == K_ENDE:
                    break
                if r[0] == K_AUDIO:
                    self._vad(self._eingang(r[1]))
                elif r[0] == K_FEHLER:
                    print(f"bruecke-asterisk-fehler {r[1].hex()}", flush=True)
        finally:
            self.lebt = False
            spieler.cancel()
            dialog.cancel()
            with contextlib.suppress(Exception):
                await self.http.post("/api/hangup", json={"sessionId": self.session_id})
            with contextlib.suppress(Exception):
                self.writer.close()
            await self.http.aclose()
            print(f"bruecke-ende session={self.session_id}", flush=True)


async def _klient(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    # W-VERBINDEN-ECHT: HTTP-Peek — der Dialplan-CURL (GET /transfer?uuid=…)
    # teilt sich den Port mit AudioSocket. Erste 3 Bytes entscheiden:
    # "GET" = Transfer-Abfrage, alles andere = AudioSocket-Rahmenkopf
    # (wandert als vorab-Bytes in den Anruf).
    try:
        kopf = await reader.readexactly(3)
    except (asyncio.IncompleteReadError, ConnectionError, OSError):
        with contextlib.suppress(Exception):
            writer.close()
        return
    if kopf == b"GET":
        await _http_transfer(reader, writer)
        return
    try:
        await Anruf(reader, writer, vorab=kopf).lauf()
    except Exception as e:
        print(f"bruecke-anruf crash {type(e).__name__}: {e}", flush=True)
        with contextlib.suppress(Exception):
            writer.close()


async def main() -> None:
    server = await asyncio.start_server(_klient, "0.0.0.0", BRIDGE_PORT)
    print(f"bruecke bereit auf :{BRIDGE_PORT} -> {BIANCA_BASE}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
