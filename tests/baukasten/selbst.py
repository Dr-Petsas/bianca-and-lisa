"""Selbst-Anruf im Teststudio: du bist der Anrufer, kein Caller-TTS.

Spricht denselben Test-Bianca-Dienst an wie der Story-Lauf (8098).
Audio-URLs werden auf 8097 umgeschrieben, damit der Browser hinter
/studio/ auf 8096 nicht versehentlich die Live-Bianca trifft.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

BIANCA_BASIS = "http://127.0.0.1:8098"


class LiveAnruf:
    """Minimaler Anruf-Stand, denselben Vertrag wie runner.Anruf fuer /api/live."""

    def __init__(self, story_id: str = "selbst-anruf"):
        self.story = {"id": story_id, "anliegen": "selbst"}
        self.zuege: list[dict[str, Any]] = []
        self.session_id = ""
        self.client = httpx.Client(timeout=httpx.Timeout(180.0, connect=10.0))

    def schliessen(self) -> None:
        try:
            self.client.close()
        except Exception:
            pass


def ton_studio(url: str) -> str:
    """Bianca-Audio-Pfad -> Studio-Proxy (nicht Live-8096)."""
    u = str(url or "").strip()
    if not u:
        return ""
    if u.startswith("http://") or u.startswith("https://"):
        from urllib.parse import urlparse
        u = urlparse(u).path
    u = u.split("?", 1)[0]
    if u.startswith("/api/audio-stream/"):
        return "api/selbst/ton/audio-stream/" + u.rsplit("/", 1)[-1]
    if u.startswith("/api/audio/"):
        return "api/selbst/ton/audio/" + u.rsplit("/", 1)[-1]
    if u.startswith("api/"):
        return u
    name = u.rsplit("/", 1)[-1]
    return f"api/selbst/ton/audio/{name}" if name else ""


def _zeile(roh: str) -> dict[str, Any] | None:
    s = (roh or "").strip()
    if not s:
        return None
    try:
        ev = json.loads(s)
    except json.JSONDecodeError:
        return None
    return ev if isinstance(ev, dict) else None


def ndjson_lesen(client: httpx.Client, method: str, url: str, **kw) -> dict[str, Any]:
    t0 = time.perf_counter()
    filler: list[str] = []
    final: dict[str, Any] = {}
    with client.stream(method, url, **kw) as r:
        r.raise_for_status()
        for roh in r.iter_lines():
            ev = _zeile(roh)
            if not ev:
                continue
            typ = str(ev.get("type") or "")
            if typ == "filler" and ev.get("audioUrl"):
                filler.append(ton_studio(str(ev.get("audioUrl"))))
            if typ in ("reply", "warte", "empty"):
                final = ev
                break
    if not final:
        final = {"type": "empty", "empty": True, "text": "", "audioUrl": ""}
    final["fillerUrls"] = filler
    final["latenzS"] = round(time.perf_counter() - t0, 2)
    if final.get("audioUrl"):
        final["audioUrl"] = ton_studio(str(final["audioUrl"]))
    return final


def merke_bianca(anruf: LiveAnruf, antwort: dict[str, Any], *, warte: bool = False) -> None:
    anruf.zuege.append({
        "wer": "bianca",
        "text": str(antwort.get("text") or ""),
        "audioUrl": str(antwort.get("audioUrl") or ""),
        "warte": bool(warte or antwort.get("type") == "warte"),
        "frage": str(antwort.get("frage") or ""),
        "modus": str(antwort.get("modus") or ""),
        "book": antwort.get("book"),
        "waechter": antwort.get("waechter") or [],
        "timings": antwort.get("timings") or {},
        "latenzS": antwort.get("latenzS") or (antwort.get("timings") or {}).get("total"),
        "ersterTonS": (antwort.get("timings") or {}).get("tts"),
    })


def merke_anrufer(anruf: LiveAnruf, text: str, gehoert: str = "") -> None:
    anruf.zuege.append({
        "wer": "anrufer",
        "text": text,
        "gehoert": gehoert or text,
        "baustein": "selbst",
    })


def start(anruf: LiveAnruf, *, basis: str = BIANCA_BASIS) -> dict[str, Any]:
    r = anruf.client.post(f"{basis}/api/start", json={"tenant": ""})
    r.raise_for_status()
    antwort = r.json()
    anruf.session_id = str(antwort.get("sessionId") or "")
    if not anruf.session_id:
        raise RuntimeError("kein sessionId vom Test-Bianca")
    if antwort.get("audioUrl"):
        antwort["audioUrl"] = ton_studio(str(antwort["audioUrl"]))
    merke_bianca(anruf, antwort)
    return antwort


def zug_text(anruf: LiveAnruf, text: str, *, basis: str = BIANCA_BASIS) -> dict[str, Any]:
    gesagt = " ".join((text or "").split())
    merke_anrufer(anruf, gesagt)
    final = ndjson_lesen(
        anruf.client, "POST", f"{basis}/api/turn",
        json={"sessionId": anruf.session_id, "text": gesagt,
              "bargeUrl": "", "bargeMs": 0},
    )
    if final.get("type") == "warte":
        merke_bianca(anruf, final, warte=True)
        return final
    if final.get("textIn") and final.get("textIn") != gesagt:
        anruf.zuege[-1]["gehoert"] = str(final["textIn"])
    merke_bianca(anruf, final)
    return final


def zug_audio(anruf: LiveAnruf, blob: bytes, mime: str, name: str,
              *, basis: str = BIANCA_BASIS) -> dict[str, Any]:
    final = ndjson_lesen(
        anruf.client, "POST", f"{basis}/api/listen",
        data={"sessionId": anruf.session_id, "text": "", "bargeUrl": "", "bargeMs": "0"},
        files={"audio": (name or "turn.webm", blob, mime or "application/octet-stream")},
    )
    gehoert = str(final.get("textIn") or "")
    merke_anrufer(anruf, gehoert or "(gesprochen)", gehoert)
    if final.get("type") == "warte":
        merke_bianca(anruf, final, warte=True)
        return final
    merke_bianca(anruf, final)
    return final


def auflegen(anruf: LiveAnruf, *, basis: str = BIANCA_BASIS) -> None:
    if anruf.session_id:
        try:
            anruf.client.post(f"{basis}/api/hangup",
                              json={"sessionId": anruf.session_id})
        except httpx.HTTPError as e:
            print(f"selbst-hangup: {e}", flush=True)
    anruf.schliessen()


def bericht_bauen(anruf: LiveAnruf) -> dict[str, Any]:
    return {
        "id": "selbst-anruf",
        "story": dict(anruf.story),
        "fehler": "",
        "zuege": list(anruf.zuege),
        "ergebnis": {
            "ok": True,
            "checks": [],
            "latenzMaxS": 0,
            "ersterTonMaxS": 0,
            "waechter": [],
            "zuege": len(anruf.zuege),
        },
    }
