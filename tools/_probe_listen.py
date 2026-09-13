#!/usr/bin/env python3
"""Reproduce Bianca listen hang after STT (run on pickadoc1)."""
from __future__ import annotations

import io
import json
import time
import uuid
import wave
import urllib.request


DID = "+4921154244110"
CALLER = "00491776004600"
BASE = "http://127.0.0.1:8096"


def post_json(path: str, payload: dict, timeout: float = 30):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def listen_with_text(sid: str, text: str, timeout: float = 90) -> str:
    # minimal wav required by endpoint
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 8000)
    wav = buf.getvalue()
    b = "----B" + uuid.uuid4().hex[:8]
    chunks = []
    def field(n, v):
        chunks.append(
            f"--{b}\r\nContent-Disposition: form-data; name=\"{n}\"\r\n\r\n{v}\r\n".encode()
        )
    def file(n, fn, data, ct):
        chunks.append(
            f"--{b}\r\nContent-Disposition: form-data; name=\"{n}\"; filename=\"{fn}\"\r\n"
            f"Content-Type: {ct}\r\n\r\n".encode()
            + data
            + b"\r\n"
        )
    field("sessionId", sid)
    field("text", text)
    field("ohrMit", "0")
    file("audio", "zug.wav", wav, "audio/wav")
    body = b"".join(chunks) + f"--{b}--\r\n".encode()
    req = urllib.request.Request(
        BASE + "/api/listen",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={b}"},
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", "replace")
    print(f"listen took {time.time()-t0:.2f}s")
    return raw


def main() -> None:
    start = post_json("/api/start", {"did": DID, "caller": CALLER, "mode": "inbound"})
    sid = start["sessionId"]
    print("session", sid, "greet", (start.get("text") or "")[:60])
    print("audioUrl", bool(start.get("audioUrl")), "len", len(start.get("audioUrl") or ""))

    # 1) first turn like the caller
    raw = listen_with_text(sid, "Ich möchte gerne einen Termin haben.")
    for line in raw.splitlines()[:12]:
        print(line[:240])

    post_json("/api/hangup", {"sessionId": sid}, timeout=20)
    print("done")


if __name__ == "__main__":
    main()
