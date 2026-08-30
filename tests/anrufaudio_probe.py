"""Live-Probe W-CALLAUDIO: echter Upload in den Firebase Storage.

Laedt einen 1-s-Piepton als MP3 nach temp/anrufaudio_probe.mp3 (NICHT in
einen clients/-Pfad — kein PhoneCall wird angefasst), holt die Download-URL
wie das Portal per GET zurueck und loescht das Objekt wieder.

Aufruf:  python -m tests.anrufaudio_probe
"""

from __future__ import annotations

import math
import struct
from urllib.parse import quote

import httpx

import kern.anrufaudio as anrufaudio


def _piep_wav() -> bytes:
    rate, dauer_s, f = 24000, 1.0, 440.0
    n = int(rate * dauer_s)
    pcm = b"".join(
        struct.pack("<h", int(12000 * math.sin(2 * math.pi * f * i / rate)))
        for i in range(n)
    )
    kopf = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + len(pcm), b"WAVE",
        b"fmt ", 16, 1, 1, rate, rate * 2, 2, 16,
        b"data", len(pcm),
    )
    return kopf + pcm


def main() -> None:
    print(f"an() = {anrufaudio.an()}  ({anrufaudio.anzeige()})")
    if not anrufaudio.an():
        print("FEHLT: Service-Account-Key — Probe abgebrochen.")
        return

    wav = _piep_wav()
    mp3 = anrufaudio._mp3(wav)
    blob, ctype = (mp3, "audio/mpeg") if mp3 else (wav, "audio/wav")
    print(f"mp3: {'ok, ' + str(len(mp3)) + ' B' if mp3 else 'ffmpeg fehlt -> wav'}")

    pfad = "temp/anrufaudio_probe.mp3" if mp3 else "temp/anrufaudio_probe.wav"
    url = anrufaudio._upload(pfad, blob, ctype)
    if not url:
        print("UPLOAD FEHLGESCHLAGEN")
        return
    print(f"hochgeladen: {url}")

    r = httpx.get(url, timeout=30)
    print(f"download: http {r.status_code}, {len(r.content)} B, "
          f"content-type={r.headers.get('content-type')}")
    ok = r.status_code == 200 and r.content == blob

    d = httpx.delete(
        f"https://storage.googleapis.com/storage/v1/b/{anrufaudio.FIREBASE_BUCKET}"
        f"/o/{quote(pfad, safe='')}",
        headers={"Authorization": f"Bearer {anrufaudio._access_token()}"},
        timeout=30,
    )
    print(f"aufgeraeumt: http {d.status_code}")
    print("PROBE " + ("GRUEN" if ok else "ROT"))


if __name__ == "__main__":
    main()
