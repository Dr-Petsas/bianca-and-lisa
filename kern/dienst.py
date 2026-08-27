"""Gemeinsame Dienst-Maschinerie für Lisa (ausgehend) und Bianca (eingehend):
Audio-Ablage, vorgerenderte Füller, NDJSON-Zug-Strom mit Überbrückung.

Hier liegt die komplette Latenz-Mechanik — eine Verbesserung wirkt auf BEIDE
Stimmen, ein Rückbau bricht beide. Zeitwerte sind live gemessen (27.08.2026),
nicht raten, nicht runden.
"""

from __future__ import annotations

import json
import queue
import secrets
import threading
import time
from typing import Any, Callable

from fastapi.responses import StreamingResponse

from kern import filler, sprech, stt, tts
from kern.config import WRITE_LIVE

# Vorab-Füller: so früh raus, dass keine Stille entsteht, aber nicht bei
# blitzschnellen Zügen (Cache-Treffer brauchen keinen Überbrückungssatz).
FILLER_VORAB_S = 0.3
# Not-Füller: nur wenn ein Zug OHNE erkannte Absicht UND ohne Werkzeug wirklich
# hängt. Normale Plauder-Antworten kommen nach 1,4 bis 2,6 s — eine kürzere
# Frist würde den Füller in die Antwort hineinsprechen (gemessen 27.08.2026).
FILLER_SPAET_S = 3.2


def _s(v) -> str:
    return " ".join(str(v or "").split()).strip()


def zeile(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False) + "\n"


def ndjson(gen) -> StreamingResponse:
    return StreamingResponse(
        gen,
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


class Dienst:
    """Bündelt pro Stimme (Lisa/Bianca) Audio-Ablage, Füller und Zug-Strom.

    start_fn(sit)               -> Antwort-Dict des ersten Zugs
    turn_fn(sit, text, melde)   -> Antwort-Dict eines Folgezugs
    schnell_fn(sit)             -> True, solange eine deterministische Phase
                                   sofort antwortet (Vorab-Füller unterdrücken)
    merke_zug(sit, **zug)       -> Sitzungsprotokoll der jeweiligen Stimme
    """

    def __init__(
        self,
        *,
        name: str,
        start_fn: Callable[[dict], dict],
        turn_fn: Callable[..., dict],
        schnell_fn: Callable[[dict], bool] | None = None,
        merke_zug: Callable[..., None] | None = None,
    ) -> None:
        self.name = name
        self.start_fn = start_fn
        self.turn_fn = turn_fn
        self.schnell_fn = schnell_fn or (lambda sit: False)
        self.merke_zug = merke_zug or (lambda sit, **zug: None)
        self.audio: dict[str, bytes] = {}
        self.filler_urls: dict[str, str] = {}
        self.feste_urls: dict[str, str] = {}

    # ---- Audio-Ablage -----------------------------------------------------

    def audio_legen(self, blob: bytes) -> str:
        if not blob:
            return ""
        aid = secrets.token_hex(6)
        self.audio[aid] = blob
        ext = "wav" if blob[:4] == b"RIFF" else "mp3"
        return f"/api/audio/{aid}.{ext}"

    def audio_holen(self, name: str) -> bytes | None:
        return self.audio.get(name.rsplit(".", 1)[0])

    def audio_fest_legen(self, name: str, blob: bytes) -> str:
        """Festes, benanntes Audio (z. B. Verbinden-Jingle) unter stabiler URL
        ablegen — abspielbar ueber melde("audio:<name>") im Zug-Strom."""
        name = _s(name)
        if not name or not blob:
            return ""
        self.audio[name] = blob
        ext = "wav" if blob[:4] == b"RIFF" else "mp3"
        url = f"/api/audio/{name}.{ext}"
        self.feste_urls[name] = url
        return url

    def audio_fest_url(self, name: str) -> str:
        return self.feste_urls.get(_s(name)) or ""

    def stimme(self, text: str) -> tuple[str, float]:
        if not text or not tts.bereit():
            return "", 0.0
        t0 = time.perf_counter()
        try:
            url = self.audio_legen(tts.engine().speak(text))
        except RuntimeError:
            return "", round(time.perf_counter() - t0, 2)
        return url, round(time.perf_counter() - t0, 2)

    # ---- Füller gegen die Totzeit ------------------------------------------
    # Die Audios werden beim Start einmal gerendert und bleiben liegen —
    # abspielen kostet danach null Zeit.

    def filler_vorbereiten(self) -> None:
        if not tts.bereit():
            return
        for text in filler.alle_saetze():
            try:
                url = self.audio_legen(tts.engine().speak(text))
                if url:
                    self.filler_urls[text] = url
            except Exception as e:
                print(f"{self.name}-filler fail {text!r} {e}", flush=True)
        print(f"{self.name}-filler bereit: {len(self.filler_urls)} Saetze", flush=True)

    def _filler_url(self, sit: dict, gruppe: str) -> str:
        nr = int(sit.get("fillerNr") or 0)
        sit["fillerNr"] = nr + 1
        url = self.filler_urls.get(filler.satz(gruppe, nr))
        if url:
            return url
        return self.filler_urls.get(filler.satz("allgemein", nr)) or ""

    # ---- Antwort-Bau -------------------------------------------------------

    def json_antwort(self, sit: dict, *, art: str, text_in: str = "",
                     extra: dict | None = None, melde=None, vorab=None) -> dict[str, Any]:
        extra = extra or {}
        sit.pop("_vorabText", None)
        t0 = time.perf_counter()
        if art == "start":
            reply = self.start_fn(sit)
        else:
            try:
                reply = self.turn_fn(sit, text_in, melde=melde, vorab=vorab)
            except TypeError:
                reply = self.turn_fn(sit, text_in, melde=melde)
        llm_s = round(time.perf_counter() - t0, 2)
        # Sprech-Filter: Uhrzeiten/Daten als Worte, Fachbegriffe und Regie raus.
        text = sprech.sanitize(reply.get("text") or "")
        # Erster Satz schon gesprochen (Stream-Vorab)? Dann nur den Rest vertonen.
        gesprochen = _s(sit.pop("_vorabText", ""))
        if gesprochen and text.startswith(gesprochen):
            rest = text[len(gesprochen):].strip()
            url, tts_s = self.stimme(rest) if rest else ("", 0.0)
        else:
            if gesprochen:
                print(f"{self.name}-vorab verworfen (Text weicht ab)", flush=True)
            url, tts_s = self.stimme(text)
        timings = {"llm": llm_s, "tts": tts_s, "total": round(llm_s + tts_s, 2)}
        self.merke_zug(sit, art=art, textIn=text_in, text=text, book=reply.get("book"), timings=timings)
        return {
            "ok": True,
            "empty": False,
            "sessionId": extra.get("sessionId") or sit.get("id") or "",
            "praxis": extra.get("praxis") or "",
            "textIn": text_in,
            "text": text,
            "audioUrl": url,
            "book": reply.get("book"),
            "writeLive": WRITE_LIVE,
            "error": reply.get("error") or "",
            "timings": timings,
        }

    # ---- NDJSON-Zug-Strom ---------------------------------------------------

    def zug_stream(self, sit: dict, *, art: str, text_in: str = "", extra: dict | None = None,
                   stt_blob: bytes | None = None, stt_mime: str = "", stt_name: str = ""):
        """NDJSON: Überbrückungssatz sofort raus, Antwort folgt — nie Stille."""
        q: queue.Queue = queue.Queue()
        # JETZT ablesen, nicht später: der Arbeitsfaden unten beendet die
        # schnelle Phase, sobald sie geklärt ist — er ist schneller als die
        # Fristberechnung im Hauptfaden und würde sie sonst in die Irre führen.
        schnelle_phase = bool(self.schnell_fn(sit))

        def melde(tool: str) -> None:
            q.put(("tool", tool))

        def vorab(satz: str) -> None:
            # Erster Satz aus dem LLM-Stream: sofort vertonen und rausgeben,
            # während das Modell den Rest schreibt — DAS drückt die gefühlte
            # Antwortzeit unter die reine Modell-Laufzeit.
            san = sprech.sanitize(satz)
            if not san:
                return
            url, _ = self.stimme(san)
            if url:
                sit["_vorabText"] = san
                q.put(("vorab", url))

        def arbeit() -> None:
            try:
                gesagt = text_in
                stt_s = None
                if stt_blob is not None:
                    t0 = time.perf_counter()
                    try:
                        gesagt = stt.transcribe(stt_blob, mime=stt_mime, name=stt_name)
                    except RuntimeError as e:
                        print(f"{self.name}-listen fail bytes={len(stt_blob)} {e}", flush=True)
                        q.put(("leer", str(e)))
                        return
                    stt_s = round(time.perf_counter() - t0, 2)
                    if not gesagt:
                        print(f"{self.name}-listen empty bytes={len(stt_blob)} mime={stt_mime}", flush=True)
                        q.put(("leer", ""))
                        return
                    print(f"{self.name}-listen ok text={gesagt!r}", flush=True)
                    q.put(("gehoert", gesagt))
                out = self.json_antwort(sit, art=art, text_in=gesagt, extra=extra, melde=melde, vorab=vorab)
                if stt_s is not None:
                    tt = {"stt": stt_s, **(out.get("timings") or {})}
                    tt["total"] = round(stt_s + float(tt.get("llm") or 0) + float(tt.get("tts") or 0), 2)
                    out["timings"] = tt
                q.put(("fertig", out))
            except Exception as e:
                q.put(("fehler", str(e)))

        threading.Thread(target=arbeit, daemon=True).start()
        filler_raus = False

        def frist_setzen(gehoert: str) -> tuple[float, str]:
            """Aus dem Gehörten raten, ob ein Kalender-Zugriff kommt."""
            # In einer schnellen (deterministischen) Phase antwortet die
            # Zustandsmaschine sofort — ein Kalender-Füller ("ich schaue kurz
            # nach") wäre dort schlicht falsch. Werkzeug-Füller kommen dann
            # nur noch über melde(), wenn wirklich Netz-Zeit anfällt.
            if schnelle_phase:
                return time.monotonic() + FILLER_SPAET_S, "allgemein"
            gruppe = filler.vermutet(gehoert, angebot_offen=bool(sit.get("offered")))
            if gruppe:
                return time.monotonic() + FILLER_VORAB_S, gruppe
            return time.monotonic() + FILLER_SPAET_S, "allgemein"

        frist, vorab_gruppe = frist_setzen(text_in)
        while True:
            try:
                wartezeit = None if filler_raus else max(0.02, frist - time.monotonic())
                typ, wert = q.get(timeout=wartezeit)
            except queue.Empty:
                url = self._filler_url(sit, vorab_gruppe)
                if url:
                    yield zeile({"type": "filler", "audioUrl": url})
                filler_raus = True
                continue
            if typ == "gehoert":
                frist, vorab_gruppe = frist_setzen(wert)
                yield zeile({"type": "transcript", "textIn": wert})
            elif typ == "vorab":
                # Erster Antwortsatz — läuft über den Füller-Kanal des Clients
                # (sofort abspielen), der Rest folgt im reply-Audio.
                yield zeile({"type": "filler", "audioUrl": wert})
                filler_raus = True
            elif typ == "tool":
                if isinstance(wert, str) and wert.startswith("audio:"):
                    # Festes Audio (z. B. Verbinden-Jingle): das ist Inhalt,
                    # kein geratener Ueberbrueckungssatz — IMMER ausspielen.
                    url = self.audio_fest_url(wert.split(":", 1)[1])
                    if url:
                        yield zeile({"type": "filler", "audioUrl": url})
                    filler_raus = True
                elif not filler_raus:
                    url = self._filler_url(sit, filler.fuer_tool(wert))
                    if url:
                        yield zeile({"type": "filler", "audioUrl": url})
                    filler_raus = True
            elif typ == "leer":
                yield zeile({"type": "empty", "error": wert})
                return
            elif typ == "fehler":
                yield zeile({"type": "empty", "error": wert})
                return
            else:  # fertig
                yield zeile({"type": "reply", **wert})
                return
