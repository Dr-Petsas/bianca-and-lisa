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

from kern import filler, sprech, stt, tenants, tts
from kern.config import STT_VORAB, WRITE_LIVE

# Vorab-Füller: so früh raus, dass keine Stille entsteht, aber nicht bei
# blitzschnellen Zügen (Cache-Treffer brauchen keinen Überbrückungssatz).
FILLER_VORAB_S = 0.3
# Not-Füller: nur wenn ein Zug OHNE erkannte Absicht UND ohne Werkzeug wirklich
# hängt. Normale Plauder-Antworten kommen nach 1,4 bis 2,6 s — eine kürzere
# Frist würde den Füller in die Antwort hineinsprechen (gemessen 27.08.2026).
FILLER_SPAET_S = 3.2

# Satz-Häppchen (28.08.2026): lange Antworten werden satzweise vertont und
# jedes fertige Stück SOFORT ausgespielt (die Docks spielen filler-Audios als
# Kette), statt den ganzen Rest als EINEN Block zu synthetisieren — beim
# lokalen TTS (~1,5 s je Satz) stand sonst nach dem Vorab-Satz nochmal
# sekundenlang Stille, besonders bei Lisas langen Antworten. Kein Split nach
# Ziffern-Punkt ("am 28. August"), nur vor großgeschriebenem Satzanfang.
_HAEPPCHEN_RE = re.compile(r"(?<=[.!?…])(?<!\d[.!?…])\s+(?=[A-ZÄÖÜ„»(])")
HAEPPCHEN_MIN = 25


def haeppchen_teile(text: str) -> list[str]:
    """Sätze fürs häppchenweise Vertonen — Winzlinge kleben am Nachbarn."""
    roh = [t.strip() for t in _HAEPPCHEN_RE.split(_s(text)) if t.strip()]
    teile: list[str] = []
    for t in roh:
        if teile and (len(teile[-1]) < HAEPPCHEN_MIN or len(t) < HAEPPCHEN_MIN):
            teile[-1] = f"{teile[-1]} {t}"
        else:
            teile.append(t)
    return teile


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

    def _vertonen(self, text: str, haeppchen=None) -> tuple[str, float]:
        """Wie stimme(), aber im Zug-Strom häppchenweise: fertige Stücke gehen
        sofort über haeppchen(url) raus. Gecachte Texte (gewarmte Begrüßungen)
        bleiben EIN Block — ihr Cache-Key trägt den Gesamttext.

        Kann der Container Chunk-Streaming (CosyVoice-Turbo), läuft die GANZE
        Äußerung als EIN Stream-Aufruf (beste Prosodie, erster Ton nach
        wenigen hundert Millisekunden); sonst satzweises Blocking."""
        if not text:
            return "", 0.0
        if haeppchen is None or tts.im_cache(text):
            return self.stimme(text)
        t0 = time.perf_counter()
        gestreamt = self._stream_haeppchen(text, haeppchen)
        if gestreamt:
            return "", round(time.perf_counter() - t0, 2)
        teile = haeppchen_teile(text)
        if len(teile) < 2:
            return self.stimme(text)
        gesamt = 0.0
        for teil in teile[:-1]:
            url, dauer = self.stimme(teil)
            gesamt += dauer
            if url:
                haeppchen(url)
        url, dauer = self.stimme(teile[-1])
        return url, round(gesamt + dauer, 2)

    def _stream_haeppchen(self, text: str, haeppchen) -> bool:
        """Äußerung über den Chunk-Stream des Containers ausspielen.

        True = alles (oder ein angefangener Teil) ist über haeppchen raus.
        False = NICHTS gesendet — der Aufrufer darf blocking nachlegen.
        Bricht der Stream MITTEN in der Äußerung ab, gilt sie als gesendet:
        nochmal von vorn sprechen wäre schlimmer als ein fehlendes Ende."""
        if not tts.bereit() or len(text) > 1200:
            return False
        eng = tts.engine()
        if eng.name != "lokal" or not getattr(eng, "kann_stream", lambda: False)():
            return False
        gesendet = 0
        try:
            for wav in eng.speak_stream(text):
                url = self.audio_legen(wav)
                if url:
                    haeppchen(url)
                    gesendet += 1
        except Exception as e:
            print(f"{self.name}-stream fail nach {gesendet} Häppchen: {e}", flush=True)
            return gesendet > 0
        return gesendet > 0

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

    def _filler_url(self, sit: dict, gruppe: str) -> str:
        nr = int(sit.get("fillerNr") or 0)
        sit["fillerNr"] = nr + 1
        url = self.filler_urls.get(filler.satz(gruppe, nr))
        if url:
            return url
        return self.filler_urls.get(filler.satz("allgemein", nr)) or ""

    # ---- Antwort-Bau -------------------------------------------------------

    def json_antwort(self, sit: dict, *, art: str, text_in: str = "",
                     extra: dict | None = None, melde=None, vorab=None,
                     haeppchen=None) -> dict[str, Any]:
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
            url, tts_s = self._vertonen(rest, haeppchen) if rest else ("", 0.0)
        else:
            if gesprochen:
                print(f"{self.name}-vorab verworfen (Text weicht ab)", flush=True)
            url, tts_s = self._vertonen(text, haeppchen)
        # STT-Zeit (Cloud-Transkription) gehört mit ins Protokoll — sie ist
        # ein voller Latenz-Posten des Zugs (Messlücke bis 28.08.2026).
        stt_s = sit.pop("_sttS", None)
        timings = {"llm": llm_s, "tts": tts_s, "total": round(llm_s + tts_s, 2)}
        if stt_s is not None:
            timings = {"stt": stt_s, **timings}
            timings["total"] = round(stt_s + llm_s + tts_s, 2)
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

    # ---- Vorab-Transkript im Stille-Fenster (28.08.2026) ---------------------

    def hoervorab(self, sit: dict, *, blob: bytes, mime: str, name: str) -> str:
        """Startet die Transkription, WAEHREND das Dock die Stille noch bestaetigt.

        Das Dock schickt den Mitschnitt schon bei ~150 ms Pegel-Stille (der
        fehlende Rest ist Stille); die 350 ms bis zur Stille-Bestaetigung
        plus Final-Upload reichen Parakeet (0,25-0,45 s) fast immer — beim
        /api/listen-Eintreffen liegt das Transkript bereit und das LLM
        startet sofort. Redet der Anrufer doch weiter, verwirft das Dock die
        Kennung und der Lauf hier verfaellt ungenutzt (nur ein umsonst
        gerechneter CPU-Decode im Container). Notaus: STT_VORAB=0.
        """
        if not STT_VORAB:
            return ""
        vid = secrets.token_hex(8)
        eintrag: dict[str, Any] = {"id": vid, "event": threading.Event(),
                                   "text": None, "fehler": "", "t0": time.perf_counter()}
        sit["_vorabStt"] = eintrag  # neuer Lauf verdraengt den alten der Sitzung

        def lauf() -> None:
            try:
                kw = ",".join(tenants.stt_keywords(sit.get("tenant") or {}))
                eintrag["text"] = stt.transcribe(blob, mime=mime, name=name, keywords=kw)
            except Exception as e:  # noqa: BLE001 — Fehler => Normalpfad im Zug
                eintrag["fehler"] = str(e)
            finally:
                eintrag["event"].set()

        threading.Thread(target=lauf, daemon=True).start()
        return vid

    def _vorab_ergebnis(self, sit: dict, vorab_id: str) -> str | None:
        """Vorab-Transkript abholen (None = kein brauchbares Vorab)."""
        eintrag = sit.get("_vorabStt")
        if not vorab_id or not eintrag or eintrag.get("id") != vorab_id:
            return None
        sit.pop("_vorabStt", None)
        # Der Lauf hat ~0,35 s Vorsprung — laenger als 1,5 s Restwartezeit
        # heisst Container-Problem: dann lieber Normalpfad mit dem Final-Blob.
        if not eintrag["event"].wait(timeout=1.5):
            print(f"{self.name}-vorab timeout — normalpfad", flush=True)
            return None
        if eintrag["fehler"] is not None and eintrag["fehler"] != "":
            print(f"{self.name}-vorab fehler {eintrag['fehler']} — normalpfad", flush=True)
            return None
        return str(eintrag.get("text") or "")

    # ---- NDJSON-Zug-Strom ---------------------------------------------------

    def zug_stream(self, sit: dict, *, art: str, text_in: str = "", extra: dict | None = None,
                   stt_blob: bytes | None = None, stt_mime: str = "", stt_name: str = "",
                   vorab_id: str = ""):
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
            # Antwortzeit unter die reine Modell-Laufzeit. Kann der Container
            # streamen, geht schon das ERSTE Teilstück des Satzes raus
            # (~0,3-0,8 s statt komplette Satz-Synthese, 28.08.2026);
            # gecachte Sätze bleiben der noch schnellere RAM-Treffer.
            san = sprech.sanitize(satz)
            if not san:
                return
            if not tts.im_cache(san) and self._stream_haeppchen(
                san, lambda url: q.put(("vorab", url))
            ):
                sit["_vorabText"] = san
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
                        # Vorab-Transkript aus dem Stille-Fenster? Dann ist die
                        # STT-Arbeit schon (fast) erledigt — stt_s misst ehrlich
                        # nur die Restwartezeit auf dem kritischen Pfad.
                        gesagt = self._vorab_ergebnis(sit, vorab_id)
                        if gesagt is None:
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
                    q.put(("gehoert", gesagt))
                if stt_s is not None:
                    sit["_sttS"] = stt_s
                out = self.json_antwort(
                    sit, art=art, text_in=gesagt, extra=extra, melde=melde, vorab=vorab,
                    haeppchen=lambda url: q.put(("vorab", url)),
                )
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
                yield zeile({"type": "empty", "error": wert})
                return
            elif typ == "fehler":
                yield zeile({"type": "empty", "error": wert})
                return
            else:  # fertig
                yield zeile({"type": "reply", **wert})
                return
