"""Anruf-Probe fuer die SIP-Bruecke (W-SIP): simuliert Asterisk-AudioSocket.

Spielt einen kompletten Mini-Anruf gegen eine LAUFENDE Bruecke (Default
127.0.0.1:40101), die ihrerseits gegen eine laufende Bianca spricht:

1. UUID-Rahmen senden, Begruessung EMPFANGEN (Rahmen zaehlen).
2. Einen Anrufer-Satz sprechen — das Audio kommt aus Biancas eigenem TTS
   (echte deutsche Sprache, das STT muss ihn verstehen), auf 8 kHz gedrueckt,
   in 20-ms-Rahmen getaktet gesendet, danach Stille.
3. Antwort-Audio EMPFANGEN und mitzaehlen.

Aufruf:  python tests/sip_bridge_probe.py [satz ...]
Env:     BRUECKE (host:port), BIANCA (http-Basis fuer die TTS-Leihe)

Schreibt nie in den Kalender-Pfad hinein, solange der gesprochene Satz
keine Buchung ausloest — Default ist eine harmlose Frage.
"""

from __future__ import annotations

import audioop
import os
import socket
import struct
import sys
import time
import uuid

import httpx

BRUECKE = os.environ.get("BRUECKE", "127.0.0.1:40101")
BIANCA = (os.environ.get("BIANCA") or "http://127.0.0.1:8096").rstrip("/")
SAETZE = sys.argv[1:] or ["Wie sind denn Ihre Öffnungszeiten?"]

K_UUID, K_AUDIO, K_ENDE = 0x01, 0x10, 0x00
FRAME_B = 320  # 20 ms bei 8 kHz PCM16


def sprich(text: str) -> bytes:
    """Anrufer-Audio besorgen: Biancas /api/transcribe-Gegenstueck gibt es
    nicht als TTS-Endpunkt — wir nehmen den TTS-Container direkt, wenn
    TTS_BASE gesetzt ist, sonst die /api/audio-URL eines Stups... einfacher:
    wir lassen Bianca einen Start machen und nutzen deren Audio NICHT —
    stattdessen rendert der TTS-Container den Satz mit der lisa-Stimme."""
    tts_base = (os.environ.get("TTS_BASE") or "").rstrip("/")
    if not tts_base:
        raise SystemExit("TTS_BASE setzen (z. B. http://100.82.122.62:8213) — "
                         "die Probe braucht echtes deutsches Sprach-Audio.")
    r = httpx.post(f"{tts_base}/speak", json={"text": text, "voice": "thomas"},
                   timeout=60.0)
    if r.status_code != 200:
        # Anrufer-Klon "thomas" fehlt? Mit "lisa" klingt es nach Echo,
        # funktioniert aber fuers Protokoll genauso.
        r = httpx.post(f"{tts_base}/speak", json={"text": text, "voice": "lisa"},
                       timeout=60.0)
        r.raise_for_status()
    pcm24 = r.content  # rohes PCM16 mono 24 kHz laut tts_serve/api.md
    pcm8, _ = audioop.ratecv(pcm24, 2, 1, 24000, 8000, None)
    return pcm8


def rahmen_senden(s: socket.socket, pcm: bytes) -> None:
    takt = time.monotonic()
    for i in range(0, len(pcm), FRAME_B):
        stueck = pcm[i:i + FRAME_B].ljust(FRAME_B, b"\x00")
        s.sendall(struct.pack(">BH", K_AUDIO, FRAME_B) + stueck)
        takt += 0.02
        rest = takt - time.monotonic()
        if rest > 0:
            time.sleep(rest)


def stille_senden(s: socket.socket, ms: int) -> None:
    rahmen_senden(s, b"\x00" * (ms * 16))


def empfangen(s: socket.socket, mindestens_ms: int, deckel_s: float) -> int:
    """Audio-Rahmen zaehlen, bis ~mindestens_ms Ton da war und dann Ruhe
    einkehrt (0,8 s ohne Rahmen) oder der Deckel reisst. Nebenbei Stille
    senden, damit die Bruecke einen lebenden Anrufer sieht."""
    s.settimeout(0.25)
    ton_ms = 0
    ende = time.monotonic() + deckel_s
    zuletzt = time.monotonic()
    puffer = b""
    while time.monotonic() < ende:
        try:
            blob = s.recv(4096)
            if not blob:
                break
            puffer += blob
            while len(puffer) >= 3:
                typ, ln = puffer[0], struct.unpack(">H", puffer[1:3])[0]
                if len(puffer) < 3 + ln:
                    break
                if typ == K_AUDIO:
                    ton_ms += ln // 16
                puffer = puffer[3 + ln:]
            zuletzt = time.monotonic()
        except socket.timeout:
            if ton_ms >= mindestens_ms and time.monotonic() - zuletzt > 0.8:
                break
        # lebender Anrufer: 100 ms Stille nachschieben
        s.sendall(struct.pack(">BH", K_AUDIO, FRAME_B) + b"\x00" * FRAME_B)
    return ton_ms


def main() -> None:
    host, port = BRUECKE.rsplit(":", 1)
    audios = [sprich(satz) for satz in SAETZE]  # vorab rendern (Takt sauber)
    s = socket.create_connection((host, int(port)), timeout=10)
    s.sendall(struct.pack(">BH", K_UUID, 16) + uuid.uuid4().bytes)
    print("verbunden — warte auf Begruessung...", flush=True)
    ms = empfangen(s, 1500, 30.0)
    print(f"begruessung: {ms} ms Audio", flush=True)
    assert ms > 500, "keine Begruessung gehoert"
    for satz, pcm in zip(SAETZE, audios):
        print(f"anrufer sagt: {satz!r} ({len(pcm)//16} ms)", flush=True)
        rahmen_senden(s, pcm)
        stille_senden(s, 700)
        ms = empfangen(s, 800, 45.0)
        print(f"antwort: {ms} ms Audio", flush=True)
        assert ms > 300, "keine Antwort gehoert"
    s.sendall(struct.pack(">BH", K_ENDE, 0))
    s.close()
    print("PROBE OK", flush=True)


if __name__ == "__main__":
    main()
