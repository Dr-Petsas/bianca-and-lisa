"""Gemeinsame Dienst-Maschinerie für Lisa (ausgehend) und Bianca (eingehend):
Audio-Ablage, vorgerenderte Füller, NDJSON-Zug-Strom mit Überbrückung.

Hier liegt die komplette Latenz-Mechanik — eine Verbesserung wirkt auf BEIDE
Stimmen, ein Rückbau bricht beide. Zeitwerte sind live gemessen (27.08.2026),
nicht raten, nicht runden.
"""

from __future__ import annotations

import json
import queue
import re
import secrets
import threading
import time
from typing import Any, Callable

from fastapi.responses import StreamingResponse

from kern import filler, sprech, stt, tenants, tts, unterbrechung
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
        stille_fn: Callable[[dict], int] | None = None,
    ) -> None:
        self.name = name
        self.start_fn = start_fn
        self.turn_fn = turn_fn
        self.schnell_fn = schnell_fn or (lambda sit: False)
        self.merke_zug = merke_zug or (lambda sit, **zug: None)
        # W-TEMPO: liefert die Stille-Schwelle (ms) fuer die NAECHSTE
        # Dock-Aufnahme (offene Frage bekannt -> kurze Antwort = 350 ms).
        # None = Feld fehlt in den Antworten, Dock bleibt bei seinem Default.
        self.stille_fn = stille_fn
        self.audio: dict[str, bytes] = {}
        self.filler_urls: dict[str, str] = {}
        self.feste_urls: dict[str, str] = {}
        # Barge-Quittungen (W-BARGE): vorgewärmte "Hm."/"Okay."-URLs, die das
        # Dock SOFORT beim Reinsprech-Stopp spielt (GET /api/quittung).
        self.quittung_urls: list[str] = []
        # Laufende Audio-Streams (Phase 2, 29.08.2026): aid -> Slot mit
        # Chunk-Liste + done-Marke; der Feeder-Faden fuellt, /api/audio-stream
        # liest mit. Chunks bleiben liegen — ein Re-Fetch nach Abschluss
        # (Dock-Fehlerpfad) bekommt das komplette Audio.
        self.audio_streams: dict[str, dict] = {}
        self._stream_ord: list[str] = []

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

    def audio_stream_anlegen(self) -> tuple[str, Callable[[bytes], None], Callable[[], None]]:
        """Slot fuer einen laufenden Audio-Strom: (aid, push, fertig).
        push() haengt PCM-Stuecke an, fertig() schliesst den Strom."""
        aid = secrets.token_hex(6)
        slot: dict[str, Any] = {"chunks": [], "done": False, "cond": threading.Condition()}
        self.audio_streams[aid] = slot
        self._stream_ord.append(aid)
        while len(self._stream_ord) > 24:
            self.audio_streams.pop(self._stream_ord.pop(0), None)

        def push(b: bytes) -> None:
            if not b:
                return
            with slot["cond"]:
                slot["chunks"].append(b)
                slot["cond"].notify_all()

        def fertig() -> None:
            with slot["cond"]:
                slot["done"] = True
                slot["cond"].notify_all()

        return aid, push, fertig

    def audio_stream_iter(self, name: str):
        """Generator fuer /api/audio-stream/<aid>.wav: offener WAV-Header,
        dann PCM-Stuecke, sobald der Feeder sie liefert. None = unbekannt."""
        slot = self.audio_streams.get(name.rsplit(".", 1)[0])
        if slot is None:
            return None

        def gen():
            yield tts.wav_header_offen()
            i = 0
            while True:
                with slot["cond"]:
                    if i >= len(slot["chunks"]) and not slot["done"]:
                        # Feeder-Absturz ohne fertig(): nach 30 s ohne neues
                        # Stueck den Strom schliessen statt ewig haengen.
                        if not slot["cond"].wait(timeout=30.0) and i >= len(slot["chunks"]):
                            return
                    stuecke = slot["chunks"][i:]
                    i = len(slot["chunks"])
                    zu_ende = slot["done"] and i >= len(slot["chunks"])
                for s in stuecke:
                    yield s
                if zu_ende and i >= len(slot["chunks"]):
                    return

        return gen()

    def stimme(self, text: str, karte: dict | None = None) -> tuple[str, float]:
        if not text or not tts.bereit():
            return "", 0.0
        t0 = time.perf_counter()
        try:
            url = self.audio_legen(self._sprech_blob(text, karte))
        except RuntimeError:
            return "", round(time.perf_counter() - t0, 2)
        return url, round(time.perf_counter() - t0, 2)

    def stimme_stream(self, text: str, karte: dict | None = None) -> tuple[str, float]:
        """Wie stimme(), aber mit SOFORTIGER Stream-URL, wenn der lokale
        Container Audio-Chunk-Streaming kann (Phase 2, 29.08.2026): der Zug
        geht raus, bevor die Synthese fertig ist — das Dock spielt progressiv,
        der erste Ton kommt nach der Container-TTFA statt nach dem Voll-Render.

        Blocking bleiben: ElevenLabs-Pfad, komplett gecachte Texte (eh sofort)
        und Ziffern-Saetze (Nachhoer-Waechter braucht das ganze Audio) —
        Ziffern-SAETZE innerhalb eines Mehr-Satz-Textes rendert der Feeder
        blocking und schiebt sie verifiziert in den Strom.

        ``karte`` (W-BARGE): der Feeder schreibt je Satz den End-Zeitpunkt im
        Audio mit (endenMs, kumulierte PCM-Bytes -> ms) — daraus rechnet
        unterbrechung.eingang() beim Reinsprechen den ungesprochenen Rest."""
        if not text or not tts.bereit():
            return "", 0.0
        if not tts.stream_bereit() or tts.im_cache(text):
            return self.stimme(text, karte)
        saetze = [s.strip() for s in re.split(r"(?<=[.!?]) +(?=[A-ZÄÖÜ])", text.strip()) if s.strip()] or [text.strip()]
        frisch = [s for s in saetze if not tts.im_cache(s) and not tts.ziffern_satz(s)]
        if not frisch:
            return self.stimme(text, karte)
        if karte is not None:
            karte["saetze"] = list(saetze)
            karte["endenMs"] = []
        t0 = time.perf_counter()
        aid, push, fertig = self.audio_stream_anlegen()

        def feeder() -> None:
            t1 = time.perf_counter()
            erster: float | None = None
            gesamt = 0
            try:
                for satz in saetze:
                    stand = gesamt
                    try:
                        if tts.im_cache(satz) or tts.ziffern_satz(satz):
                            blob = tts.engine().speak(satz)
                            if blob and blob[:4] == b"RIFF" and len(blob) > 44:
                                push(blob[44:])
                                gesamt += len(blob) - 44
                                if erster is None:
                                    erster = time.perf_counter() - t1
                        else:
                            for stueck in tts.engine().speak_stream(satz):
                                push(stueck)
                                gesamt += len(stueck)
                                if erster is None:
                                    erster = time.perf_counter() - t1
                        if karte is not None:
                            # Kein Ton fuer diesen Satz (None) = gilt beim
                            # Barge als ungesprochen — nie Inhalt verlieren.
                            karte["endenMs"].append(
                                gesamt * 1000 // (tts.PCM_RATE * 2) if gesamt > stand else None)
                    except Exception as e:
                        # Testphase: Fehler hoerbar lassen (Satz fehlt im
                        # Audio), aber die restlichen Saetze noch sprechen.
                        if karte is not None:
                            karte["endenMs"].append(None)
                        print(f"{self.name}-stream satz-fail {satz[:40]!r} {e}", flush=True)
            finally:
                fertig()
                print(f"{self.name}-stream ttfa={erster if erster is not None else -1:.2f}s "
                      f"gesamt={time.perf_counter() - t1:.2f}s saetze={len(saetze)}", flush=True)

        threading.Thread(target=feeder, daemon=True).start()
        return f"/api/audio-stream/{aid}.wav", round(time.perf_counter() - t0, 2)

    @staticmethod
    def _karte_ganz(karte: dict | None, text: str, blob: bytes) -> None:
        """Satz-Karte fuer einen Ein-Block-Render (W-BARGE): der ganze Text
        gilt als EIN Satz; ohne WAV (MP3-Pfad) bleibt endenMs leer — beim
        Barge zaehlt dann alles als ungesprochen (nie Inhalt verlieren)."""
        if karte is None:
            return
        karte["saetze"] = [_s(text)]
        if blob and blob[:4] == b"RIFF" and len(blob) > 44:
            karte["endenMs"] = [(len(blob) - 44) * 1000 // (tts.PCM_RATE * 2)]
        else:
            karte["endenMs"] = []

    def _sprech_blob(self, text: str, karte: dict | None = None) -> bytes:
        """Satzweise sprechen, zu EINEM WAV fuegen (kein Streaming, keine
        Naht im Wort): gewarmte Maschinen-Fragen kommen aus dem Pin-Cache
        (~0 s), nur neue Saetze kosten Synthese — und jeder Satz landet
        einzeln im LRU, Quittungen wiederholen sich im Gespraech gratis.
        Gewarmte Gesamttexte (Begruessung, Fueller) bleiben EIN Block,
        sonst verfehlte der Split ihren Cache-Key."""
        if tts.im_cache(text):
            blob = tts.engine().speak(text)
            self._karte_ganz(karte, text, blob)
            return blob
        saetze = [s.strip() for s in re.split(r"(?<=[.!?]) +(?=[A-ZÄÖÜ])", text.strip()) if s.strip()]
        if len(saetze) <= 1:
            blob = tts.engine().speak(text)
            self._karte_ganz(karte, text, blob)
            return blob
        teile = [tts.engine().speak(s) for s in saetze]
        blob = tts.wav_fuegen(teile)
        if blob:
            if karte is not None:
                karte["saetze"] = list(saetze)
                enden: list[int] = []
                gesamt = 0
                for teil in teile:
                    gesamt += max(0, len(teil) - 44)
                    enden.append(gesamt * 1000 // (tts.PCM_RATE * 2))
                karte["endenMs"] = enden
            return blob
        # Teile nicht fuegbar (z. B. MP3 vom ElevenLabs-Pfad): ein Render.
        blob = tts.engine().speak(text)
        self._karte_ganz(karte, text, blob)
        return blob

    # ---- Füller gegen die Totzeit ------------------------------------------
    # Die Audios kommen aus dem Platten-Cache (.data/tts-cache) — nur beim
    # allerersten Start (oder nach Stimmen-/Engine-Wechsel) wird synthetisiert.

    def filler_vorbereiten(self) -> None:
        if not tts.bereit():
            return
        for text in filler.alle_saetze():
            try:
                url = self.audio_legen(tts.speak_dauerhaft(text))
                if url:
                    self.filler_urls[text] = url
            except Exception as e:
                print(f"{self.name}-filler fail {text!r} {e}", flush=True)
        print(f"{self.name}-filler bereit: {len(self.filler_urls)} Saetze", flush=True)

    def quittungen_vorbereiten(self) -> None:
        """Barge-Quittungen ("Hm.", "Okay.") vorwaermen (W-BARGE): die Docks
        holen die URLs einmal ueber GET /api/quittung und spielen sie SOFORT
        beim Reinsprech-Stopp — noch vor Aufnahme und Einwand-Zug."""
        if not tts.bereit():
            return
        urls: list[str] = []
        for text in unterbrechung.QUITTUNGEN:
            try:
                url = self.audio_legen(tts.speak_dauerhaft(text))
                if url:
                    urls.append(url)
            except Exception as e:
                print(f"{self.name}-quittung fail {text!r} {e}", flush=True)
        self.quittung_urls = urls
        print(f"{self.name}-quittung bereit: {len(urls)} Saetze", flush=True)

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
        sit.pop("_vorabUrl", None)
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
        # W-BARGE: war der vorige Zug unterbrochen und dieser Einwand hat den
        # Zustand nicht bewegt, kommt der ungesprochene Rest mit Bruecke dran.
        # Ein Abbruch-Befehl ("Stopp.") verwirft den Rest (29.08.2026).
        text = unterbrechung.fortsetzen(sit, text, reply, gesagt=text_in)
        # Erster Satz schon gesprochen (Stream-Vorab)? Dann nur den Rest vertonen.
        gesprochen = _s(sit.pop("_vorabText", ""))
        vorab_url = _s(sit.pop("_vorabUrl", ""))
        karte: dict[str, Any] = {"saetze": [], "endenMs": []}
        if gesprochen and text.startswith(gesprochen):
            rest = text[len(gesprochen):].strip()
            url, tts_s = self.stimme_stream(rest, karte) if rest else ("", 0.0)
            unterbrechung.merken(sit, url=url, karte=karte, text=text,
                                 vorab_text=gesprochen, vorab_url=vorab_url)
        else:
            if gesprochen:
                print(f"{self.name}-vorab verworfen (Text weicht ab)", flush=True)
            url, tts_s = self.stimme_stream(text, karte)
            unterbrechung.merken(sit, url=url, karte=karte, text=text)
        # STT-Zeit (Cloud-Transkription) gehört mit ins Protokoll — sie ist
        # ein voller Latenz-Posten des Zugs (Messlücke bis 28.08.2026).
        stt_s = sit.pop("_sttS", None)
        timings = {"llm": llm_s, "tts": tts_s, "total": round(llm_s + tts_s, 2)}
        if stt_s is not None:
            timings = {"stt": stt_s, **timings}
            timings["total"] = round(stt_s + llm_s + tts_s, 2)
        self.merke_zug(sit, art=art, textIn=text_in, text=text, book=reply.get("book"), timings=timings)
        antwort = {
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
        antwort.update(self._stille_feld(sit))
        return antwort

    # ---- Barge-Fortsetzung (W-BARGE) ---------------------------------------

    def weiter_sprechen(self, sit: dict, extra: dict | None = None) -> dict[str, Any] | None:
        """Fehlalarm oder leerer Einwurf nach einem Barge: an der
        Unterbrechungsstelle weitersprechen — deterministisch, ohne LLM.
        None = keine Unterbrechung offen (Aufrufer faellt auf sein
        normales Leer-Verhalten zurueck)."""
        text = unterbrechung.wiederaufnahme(sit)
        if not text:
            return None
        karte: dict[str, Any] = {"saetze": [], "endenMs": []}
        url, tts_s = self.stimme_stream(text, karte)
        unterbrechung.merken(sit, url=url, karte=karte, text=text)
        timings = {"llm": 0.0, "tts": tts_s, "total": tts_s}
        self.merke_zug(sit, art="weiter", textIn="", text=text, timings=timings)
        print(f"{self.name}-weiter (Barge-Fortsetzung): {text[:60]!r}", flush=True)
        extra = extra or {}
        antwort = {
            "ok": True,
            "empty": False,
            "sessionId": extra.get("sessionId") or sit.get("id") or "",
            "praxis": extra.get("praxis") or "",
            "textIn": "",
            "text": text,
            "audioUrl": url,
            "book": None,
            "writeLive": WRITE_LIVE,
            "error": "",
            "timings": timings,
        }
        antwort.update(self._stille_feld(sit))
        return antwort

    def _stille_feld(self, sit: dict) -> dict[str, int]:
        """W-TEMPO: Stille-Schwelle fuer die naechste Dock-Aufnahme (ms)."""
        if not self.stille_fn:
            return {}
        try:
            return {"stilleMs": int(self.stille_fn(sit))}
        except Exception:
            return {}

    # ---- NDJSON-Zug-Strom ---------------------------------------------------

    def zug_stream(self, sit: dict, *, art: str, text_in: str = "", extra: dict | None = None,
                   stt_blob: bytes | None = None, stt_mime: str = "", stt_name: str = "",
                   barge_url: str = "", barge_ms: float = 0.0):
        """NDJSON: Überbrückungssatz sofort raus, Antwort folgt — nie Stille."""
        # W-BARGE: das Dock meldet, WO es der Stimme ins Wort gefallen ist —
        # daraus entstehen Rest + gestutztes Protokoll, BEVOR der Zug laeuft.
        if _s(barge_url):
            unterbrechung.eingang(sit, barge_url, barge_ms)
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
                sit["_vorabUrl"] = url
                q.put(("vorab", url))

        def arbeit() -> None:
            try:
                gesagt = text_in
                stt_s = None
                # W-TEMPO: Das Dock schickt Vorab-Transkripte als TEXT-Zug —
                # der Echo-Waechter muss dort genauso greifen wie im
                # Audio-Pfad, sonst schluckt ein Lautsprecher-Echo der
                # eigenen Stimme den Barge nicht mehr. Nur bei gemeldetem
                # Barge pruefen: ohne Unterbrechung sprach niemand, ein
                # normaler Text-Zug (Lisa-Diktat, Tests) bleibt unberuehrt.
                if stt_blob is None and gesagt and _s(barge_url) and unterbrechung.ist_echo(sit, gesagt):
                    print(f"{self.name}-barge echo verworfen (vorab): {gesagt!r}", flush=True)
                    q.put(("leer", "echo"))
                    return
                if stt_blob is not None:
                    t0 = time.perf_counter()
                    try:
                        # Behandler-Namen des Mandanten als Hotwords fuer die
                        # Parakeet-Nachkorrektur ("Betsas" -> "Petsas").
                        kw = ",".join(tenants.stt_keywords(sit.get("tenant") or {}))
                        gesagt = stt.transcribe(stt_blob, mime=stt_mime, name=stt_name,
                                                keywords=kw)
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
                    if unterbrechung.ist_echo(sit, gesagt):
                        # Lautsprecher-Echo der eigenen Stimme hat den Barge
                        # ausgeloest — kein Einwand: leise weitersprechen.
                        print(f"{self.name}-barge echo verworfen: {gesagt!r}", flush=True)
                        q.put(("leer", "echo"))
                        return
                    q.put(("gehoert", gesagt))
                if stt_s is not None:
                    sit["_sttS"] = stt_s
                out = self.json_antwort(sit, art=art, text_in=gesagt, extra=extra, melde=melde, vorab=vorab)
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
                if isinstance(wert, str) and wert.startswith("sag:"):
                    # Feste gesprochene Zwischen-Ansage (z. B. "Einen Moment,
                    # ich stelle die Verbindung her") — Inhalt, kein geratener
                    # Fueller: IMMER vertonen und VOR spaeteren Audios ausspielen.
                    san = sprech.sanitize(wert.split(":", 1)[1])
                    url = self.stimme(san)[0] if san else ""
                    if url:
                        yield zeile({"type": "filler", "audioUrl": url})
                    filler_raus = True
                elif isinstance(wert, str) and wert.startswith("audio:"):
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
                # W-BARGE: Barge ohne verwertbaren Einwand (nichts gehoert
                # oder eigenes Echo) => an der Unterbrechungsstelle weiter.
                weiter = self.weiter_sprechen(sit, extra)
                if weiter:
                    yield zeile({"type": "reply", **weiter})
                else:
                    yield zeile({"type": "empty", "error": wert})
                return
            elif typ == "fehler":
                yield zeile({"type": "empty", "error": wert})
                return
            else:  # fertig
                yield zeile({"type": "reply", **wert})
                return
