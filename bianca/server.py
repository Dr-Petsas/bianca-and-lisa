"""Eigenständiger Bianca-Dienst (eingehende Anrufe). Port 8096 — Lisa (8095),
Clara (8091/8092/8093) und DemoClara (8094) bleiben unberührt."""

from __future__ import annotations

import threading
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from bianca import agent, gehirn, session, weiterleiten
from bianca.greeting import begruessung
from kern import gedaechtnis, halbsatz, llm, sprech, stt, tenants, tts, unterbrechung
from kern.config import (
    BIANCA_PORT,
    BIANCA_VOICE_ID,
    BIANCA_WEB_DIR,
    DEFAULT_TENANT,
    LLM_BASE,
    LLM_MODEL,
    WRITE_LIVE,
)
from kern.dienst import Dienst, ndjson

# Biancas Stimme gilt fuer diesen PROZESS — Lisa laeuft als eigener Dienst
# mit ihrer eigenen Stimme weiter. "bianca" = Referenz-Stimme im lokalen
# TTS-Container (tts_serve/stimmen/bianca.wav), falls TTS_BASE gesetzt ist.
tts.set_voice(BIANCA_VOICE_ID, name="bianca")

app = FastAPI(title="Bianca Telefon-KI", version="0.1")

DIENST = Dienst(
    name="bianca",
    start_fn=agent.start_reply,
    turn_fn=agent.user_turn,
    # Bis zur Buchung antwortet die Zustandsmaschine sofort — geratene
    # Kalender-Füller wären dort falsch. Echte Werkzeug-Füller kommen
    # weiterhin über melde(), sobald wirklich Netz-Zeit anfällt.
    schnell_fn=lambda sit: (sit.get("sammler") or {}).get("phase") != "gebucht",
    merke_zug=session.merke_zug,
    # W-TEMPO: nach Ja/Nein-/Wahlfragen reicht dem Dock weniger Ruhe als
    # Zugende, beim Ziffern-Diktat braucht es mehr (gehirn.stille_ms).
    stille_fn=lambda sit: gehirn.stille_ms(gehirn.sammler(sit)),
)


# Verbinden-Jingle ("Wir verbinden Sie zu Ihrem Arzt") fuer den
# Weiterleitungs-Platzhalter (bianca/weiterleiten.py): als festes Audio
# ablegen — gespielt wird es ueber die bestehende Filler-Kette des Clients.
_JINGLE_PFAD = BIANCA_WEB_DIR / "verbinden.mp3"
if _JINGLE_PFAD.is_file():
    DIENST.audio_fest_legen(weiterleiten.JINGLE_NAME, _JINGLE_PFAD.read_bytes())


class StartIn(BaseModel):
    tenant: str = ""


class TurnIn(BaseModel):
    sessionId: str = ""
    text: str = ""
    # W-BARGE: welches Audio wurde bei wie viel ms unterbrochen?
    bargeUrl: str = ""
    bargeMs: float = 0.0


class WeiterIn(BaseModel):
    sessionId: str = ""
    bargeUrl: str = ""
    bargeMs: float = 0.0


class HangupIn(BaseModel):
    sessionId: str = ""


@app.on_event("startup")
def _testtermin_autoloesch() -> None:
    """Test-Studio-Buchungen bleiben 2 Stunden, dann Autoloesch — nur IDs
    aus der Baukasten-Schlange, nie ein fremder Patiententermin."""
    try:
        from tests.baukasten import aufraeumen
        aufraeumen.waechter_starten()
    except Exception as e:
        print(f"autoloesch-start: {type(e).__name__}: {e}", flush=True)


@app.get("/health")
def health():
    h = llm.health()
    return {
        "ok": True,
        "service": "bianca-telefonki",
        "port": BIANCA_PORT,
        "tenant": DEFAULT_TENANT,
        "writeLive": WRITE_LIVE,
        "llm": h,
        "tts": tts.engine().name if tts.bereit() else "fehlt",
        "ttsModel": tts.modell_info() if tts.bereit() else "",
        "ttsEngine": tts.engine_anzeige() if tts.bereit() else "keine Stimme",
        "voice": BIANCA_VOICE_ID,
        "filler": len(DIENST.filler_urls),
        "stt": stt.engine_anzeige() if stt.bereit() else "live",
        "llmBase": LLM_BASE,
        "llmModel": LLM_MODEL,
        "gedaechtnis": gedaechtnis.anzeige(),
        "lastCall": session.last_call(),
    }


@app.get("/api/tenants")
def api_tenants():
    return {"ok": True, "tenants": tenants.liste(), "default": DEFAULT_TENANT}


@app.post("/api/start")
def api_start(body: StartIn):
    t = tenants.laden(body.tenant or DEFAULT_TENANT)
    sit = session.neu(tenant_id=body.tenant or DEFAULT_TENANT)
    return DIENST.json_antwort(
        sit, art="start",
        extra={"sessionId": sit["id"], "praxis": t.get("praxisName")},
    )


@app.post("/api/turn")
def api_turn(body: TurnIn):
    sit = session.holen(body.sessionId)
    if not sit:
        raise HTTPException(404, "sitzung unbekannt")
    print(f"bianca-turn session={body.sessionId} text={body.text!r}", flush=True)
    return ndjson(DIENST.zug_stream(sit, art="turn", text_in=body.text,
                                    barge_url=body.bargeUrl, barge_ms=body.bargeMs))


@app.post("/api/weiter")
def api_weiter(body: WeiterIn):
    """W-BARGE: Reinsprecher ohne verwertbaren Einwand (Fehlalarm) — die
    Stimme spricht an der Unterbrechungsstelle weiter, ohne LLM."""
    sit = session.holen(body.sessionId)
    if not sit:
        raise HTTPException(404, "sitzung unbekannt")
    if body.bargeUrl:
        unterbrechung.eingang(sit, body.bargeUrl, body.bargeMs)
    out = DIENST.weiter_sprechen(sit, {"sessionId": sit.get("id") or ""})
    if not out:
        return {"ok": True, "empty": True, "text": "", "audioUrl": ""}
    return out


@app.get("/api/quittung")
def api_quittung():
    """W-BARGE: vorgewärmte Sofort-Quittungen ("Hm.", "Okay.") fürs Dock."""
    return {"ok": True, "urls": DIENST.quittung_urls if unterbrechung.enabled() else []}


@app.get("/api/notfall")
def api_notfall():
    """W-STILLE: Warte-Ansagen, die das Dock beim Boot als Blob vorlädt und
    LOKAL spielt, wenn ~1,4 s nach dem Sprechende kein Ton lief."""
    return {"ok": True, "urls": DIENST.notfall_urls}


@app.post("/api/stille")
def api_stille(body: HangupIn):
    """Stille-Wächter (Chef 27.08.2026): das Dock meldet ~4 s Funkstille —
    Bianca stupst deterministisch an (Stand + offene Frage bzw. Talk-Thema),
    ohne LLM und ohne Kalender. Leerer Text = Stups-Budget verbraucht."""
    sit = session.holen(body.sessionId)
    if not sit:
        raise HTTPException(404, "sitzung unbekannt")
    # W-HALBSATZ: haengt ein gehaltenes Satz-Fragment in der Sitzung, hat der
    # Anrufer den Satz nicht fortgesetzt — dann wird ER beantwortet, kein Stups.
    rest = halbsatz.abholen(sit)
    if rest:
        print(f"bianca-stille halbsatz-flush: {rest!r}", flush=True)
        return DIENST.json_antwort(sit, art="turn", text_in=rest,
                                   extra={"sessionId": sit.get("id") or ""})
    reply = agent.stille_zug(sit)
    text = sprech.sanitize(reply.get("text") or "")
    if not text:
        return {"ok": True, "empty": True, "text": "", "audioUrl": ""}
    url, tts_s = DIENST.stimme(text)
    session.merke_zug(sit, art="stille", textIn="", text=text, timings={"tts": tts_s})
    print(f"bianca-stille session={body.sessionId} text={text!r}", flush=True)
    return {"ok": True, "empty": False, "text": text, "audioUrl": url, "writeLive": WRITE_LIVE}


@app.post("/api/listen")
async def api_listen(sessionId: str = Form(""), text: str = Form(""), audio: UploadFile = File(...),
                     bargeUrl: str = Form(""), bargeMs: float = Form(0.0)):
    sit = session.holen(sessionId)
    if not sit:
        raise HTTPException(404, "sitzung unbekannt")
    blob = await audio.read()
    mime = audio.content_type or "application/octet-stream"
    name = audio.filename or "turn.webm"
    live = " ".join((text or "").split()).strip()
    if live:
        print(f"bianca-listen live session={sessionId} text={live!r}", flush=True)
        return ndjson(DIENST.zug_stream(sit, art="turn", text_in=live,
                                        barge_url=bargeUrl, barge_ms=bargeMs))
    return ndjson(DIENST.zug_stream(sit, art="listen", stt_blob=blob, stt_mime=mime, stt_name=name,
                                    barge_url=bargeUrl, barge_ms=bargeMs))


@app.post("/api/transcribe")
async def api_transcribe(audio: UploadFile = File(...)):
    blob = await audio.read()
    mime = audio.content_type or "application/octet-stream"
    name = audio.filename or "turn.webm"
    try:
        gesagt = stt.transcribe(blob, mime=mime, name=name)
    except RuntimeError as e:
        return {"ok": False, "text": "", "error": str(e)}
    return {"ok": True, "text": gesagt}


@app.post("/api/hoeren")
async def api_hoeren(sessionId: str = Form(""), audio: UploadFile = File(...)):
    """W-TEMPO Vorab-STT: Das Dock schickt die Aufnahme schon nach ~200 ms
    Ruhe hierher — die restliche Stille-Wartezeit bis zum Zugende ueberlappt
    mit der Transkription. Reines Ohr: kein Zug, kein Protokoll, kein
    Zustand; dieselben Tenant-Hotwords wie der echte Zug (identisches
    Transkript dank Stille-Trim im Container)."""
    sit = session.holen(sessionId)
    if not sit:
        raise HTTPException(404, "sitzung unbekannt")
    blob = await audio.read()
    try:
        kw = ",".join(tenants.stt_keywords(sit.get("tenant") or {}))
        gesagt = stt.transcribe(blob, mime=audio.content_type or "application/octet-stream",
                                name=audio.filename or "vorab.webm", keywords=kw)
    except RuntimeError as e:
        return {"ok": False, "text": "", "error": str(e)}
    print(f"bianca-vorab-stt bytes={len(blob)} text={gesagt!r}", flush=True)
    return {"ok": True, "text": gesagt}


@app.get("/api/last-call")
def api_last_call():
    return {"ok": True, "writeLive": WRITE_LIVE, "call": session.last_call()}


@app.post("/api/hangup")
def api_hangup(body: HangupIn):
    sit = session.holen(body.sessionId)
    if not sit:
        return {"ok": True, "empty": True}

    # Zweiter Schritt NACH dem Auflegen (Chef 27.08.): Kurzfassung des
    # Gespraechs erzeugen und in den Termin schreiben — der Anruf-Pfad
    # wartet darauf nicht mehr.
    def _nacharbeit() -> None:
        try:
            note = agent.hangup(sit)
            session.merke_zug(sit, art="hangup", note=(note or {}).get("note") or "", dryRun=bool((note or {}).get("dryRun")))
        except Exception as e:
            print(f"bianca-hangup-nacharbeit fail {e}", flush=True)
            session.merke_zug(sit, art="hangup", note="", dryRun=False)
        session.sichern(sit)
        # W-GEDAECHTNIS: Gesprächszusammenfassung ins Praxisgedächtnis (MAS).
        gedaechtnis.report_senden(sit)

    threading.Thread(target=_nacharbeit, daemon=True).start()
    return {"ok": True, "writeLive": WRITE_LIVE, "queued": True}


@app.on_event("startup")
def _warm_start():
    def _run():
        # Füller zuerst: ohne sie entsteht genau die Stille, die weg soll.
        DIENST.filler_vorbereiten()
        DIENST.quittungen_vorbereiten()
        DIENST.notfall_vorbereiten()
        t = tenants.laden(DEFAULT_TENANT)
        tts.warm(begruessung(tenants.praxis_melde(t)))
        # Feste Maschinen-Fragen dauerhaft vorwärmen (kein Patientenbezug):
        # aus dem Platten-Cache fragt die Maschine in ~0,2 s statt ~1,2 s
        # lokaler Synthese. Gewarmt wird die SANITIZE-Form — genau die
        # spricht der Zug später (Cache-Key muss treffen).
        for satz in gehirn.feste_saetze(t):
            tts.warm(sprech.sanitize(satz))
        print("bianca-warm: feste Fragen im Cache", flush=True)
    threading.Thread(target=_run, daemon=True).start()


@app.get("/api/audio/{name}")
def api_audio(name: str):
    blob = DIENST.audio_holen(name)
    if not blob:
        raise HTTPException(404)
    mime = "audio/wav" if blob[:4] == b"RIFF" else "audio/mpeg"
    return Response(blob, media_type=mime)


@app.get("/api/audio-stream/{name}")
def api_audio_stream(name: str):
    """Progressiver WAV-Strom (Phase 2, 29.08.2026): das Dock spielt, waehrend
    der TTS-Container noch rendert. Nach Abschluss liefert dieselbe URL das
    komplette Audio (Chunks bleiben im Slot liegen)."""
    gen = DIENST.audio_stream_iter(name)
    if gen is None:
        raise HTTPException(404)
    return StreamingResponse(gen, media_type="audio/wav",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


if BIANCA_WEB_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(BIANCA_WEB_DIR)), name="static")


# --- Test-Studio (29.08.2026): HTML/CSS/JS kommen AUS DIESEM Prozess, damit
# die Seite auch hinter Lisas /bianca/-Tunnel sofort da ist (kein zweites
# Fenster, kein zweiter Port, kein Redirect auf /studio/ — der wuerde hinter
# Lisa auf 8095/studio landen und weiss bleiben). API und Berichte gehen
# intern an den Editor auf 8097.
_STUDIO_WEB = Path(__file__).resolve().parent.parent / "tests" / "baukasten" / "editor_web"
_STUDIO_BASIS = "http://127.0.0.1:8097"


def _studio_seite(name: str) -> FileResponse:
    p = _STUDIO_WEB / name
    if not p.is_file():
        raise HTTPException(404, "Test-Studio-Datei fehlt")
    return FileResponse(p, headers={"Cache-Control": "no-store"})


@app.get("/studio")
@app.get("/studio/")
def studio_index():
    return _studio_seite("index.html")


@app.get("/studio/ergebnisse")
def studio_ergebnisse():
    return _studio_seite("ergebnisse.html")


@app.get("/studio/web/{name}")
def studio_web(name: str):
    erlaubt = {"app.js", "stil.css", "ergebnisse.js"}
    if name not in erlaubt:
        raise HTTPException(404)
    return _studio_seite(name)


@app.api_route("/studio/api/{pfad:path}", methods=["GET", "POST"])
async def studio_api(request: Request, pfad: str):
    import urllib.error
    import urllib.request

    from starlette.concurrency import run_in_threadpool

    ziel = f"{_STUDIO_BASIS}/api/{pfad}"
    if request.url.query:
        ziel += f"?{request.url.query}"
    body = await request.body() if request.method == "POST" else None
    kopf = {}
    if request.headers.get("content-type"):
        kopf["Content-Type"] = request.headers["content-type"]

    def _holen():
        req = urllib.request.Request(ziel, data=body, headers=kopf, method=request.method)
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read(), r.headers.get("content-type")

    try:
        status, inhalt, mime = await run_in_threadpool(_holen)
    except urllib.error.HTTPError as e:
        return Response(e.read(), status_code=e.code,
                        media_type=e.headers.get("content-type") if e.headers else None,
                        headers={"Cache-Control": "no-store"})
    except (urllib.error.URLError, TimeoutError, OSError):
        raise HTTPException(502, "Test-Studio (8097) antwortet nicht — laeuft der Editor?")
    return Response(inhalt, status_code=status, media_type=mime,
                    headers={"Cache-Control": "no-store"})


# WAVs direkt aus dem Berichte-Ordner — kein urllib-Proxy (Play-Buttons).
_BERICHTE = Path(__file__).resolve().parent.parent / "tests" / "baukasten" / "berichte"
_BERICHTE.mkdir(parents=True, exist_ok=True)
app.mount("/studio/berichte", StaticFiles(directory=str(_BERICHTE)), name="studio-berichte")


@app.get("/")
def index():
    index = BIANCA_WEB_DIR / "index.html"
    if not index.is_file():
        raise HTTPException(404, "bianca_web/index.html fehlt")
    return FileResponse(index, media_type="text/html; charset=utf-8",
                        headers={"Cache-Control": "no-store"})


@app.get("/{name}")
def web_file(name: str):
    erlaubt = {"app.js", "styles.css"}
    if name in erlaubt:
        p = BIANCA_WEB_DIR / name
        if p.is_file():
            return FileResponse(p, headers={"Cache-Control": "no-store"})
    raise HTTPException(404)
