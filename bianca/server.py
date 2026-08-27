"""Eigenständiger Bianca-Dienst (eingehende Anrufe). Port 8096 — Lisa (8095),
Clara (8091/8092/8093) und DemoClara (8094) bleiben unberührt."""

from __future__ import annotations

import threading

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from bianca import agent, session
from bianca.greeting import begruessung
from kern import llm, stt, tenants, tts
from kern.config import (
    BIANCA_PORT,
    BIANCA_VOICE_ID,
    BIANCA_WEB_DIR,
    DEFAULT_TENANT,
    ELEVENLABS_TTS_MODEL,
    LLM_BASE,
    LLM_MODEL,
    WRITE_LIVE,
)
from kern.dienst import Dienst, ndjson

# Biancas Stimme gilt fuer diesen PROZESS — Lisa laeuft als eigener Dienst
# mit ihrer eigenen Stimme weiter.
tts.set_voice(BIANCA_VOICE_ID)

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
)


class StartIn(BaseModel):
    tenant: str = ""


class TurnIn(BaseModel):
    sessionId: str = ""
    text: str = ""


class HangupIn(BaseModel):
    sessionId: str = ""


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
        "ttsModel": ELEVENLABS_TTS_MODEL if tts.bereit() else "",
        "voice": BIANCA_VOICE_ID,
        "filler": len(DIENST.filler_urls),
        "stt": "live+elevenlabs" if stt.bereit() else "live",
        "llmBase": LLM_BASE,
        "llmModel": LLM_MODEL,
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
    return ndjson(DIENST.zug_stream(sit, art="turn", text_in=body.text))


@app.post("/api/listen")
async def api_listen(sessionId: str = Form(""), text: str = Form(""), audio: UploadFile = File(...)):
    sit = session.holen(sessionId)
    if not sit:
        raise HTTPException(404, "sitzung unbekannt")
    blob = await audio.read()
    mime = audio.content_type or "application/octet-stream"
    name = audio.filename or "turn.webm"
    live = " ".join((text or "").split()).strip()
    if live:
        print(f"bianca-listen live session={sessionId} text={live!r}", flush=True)
        return ndjson(DIENST.zug_stream(sit, art="turn", text_in=live))
    return ndjson(DIENST.zug_stream(sit, art="listen", stt_blob=blob, stt_mime=mime, stt_name=name))


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


@app.get("/api/last-call")
def api_last_call():
    return {"ok": True, "writeLive": WRITE_LIVE, "call": session.last_call()}


@app.post("/api/hangup")
def api_hangup(body: HangupIn):
    sit = session.holen(body.sessionId)
    if not sit:
        return {"ok": True, "empty": True}
    note = agent.hangup(sit)
    session.merke_zug(sit, art="hangup", note=(note or {}).get("note") or "", dryRun=bool((note or {}).get("dryRun")))
    session.sichern(sit)
    return {
        "ok": True,
        "writeLive": WRITE_LIVE,
        "note": note or {},
        "call": session.last_call(),
    }


@app.on_event("startup")
def _warm_start():
    def _run():
        # Füller zuerst: ohne sie entsteht genau die Stille, die weg soll.
        DIENST.filler_vorbereiten()
        t = tenants.laden(DEFAULT_TENANT)
        tts.warm(begruessung(t.get("praxisName") or ""))
    threading.Thread(target=_run, daemon=True).start()


@app.get("/api/audio/{name}")
def api_audio(name: str):
    blob = DIENST.audio_holen(name)
    if not blob:
        raise HTTPException(404)
    mime = "audio/wav" if blob[:4] == b"RIFF" else "audio/mpeg"
    return Response(blob, media_type=mime)


if BIANCA_WEB_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(BIANCA_WEB_DIR)), name="static")


@app.get("/")
def index():
    index = BIANCA_WEB_DIR / "index.html"
    if not index.is_file():
        raise HTTPException(404, "bianca_web/index.html fehlt")
    return FileResponse(index, headers={"Cache-Control": "no-store"})


@app.get("/{name}")
def web_file(name: str):
    erlaubt = {"app.js", "styles.css"}
    if name in erlaubt:
        p = BIANCA_WEB_DIR / name
        if p.is_file():
            return FileResponse(p, headers={"Cache-Control": "no-store"})
    raise HTTPException(404)
