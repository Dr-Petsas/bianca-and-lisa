"""Eigenständiger Lisa-Dienst. Port 8095 — rührt Clara/Demo/MAS nicht an."""

from __future__ import annotations

import queue
import secrets
import threading
import time
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import json

from lisa import agent, anliegen, calendar, filler, llm, patients, remote, session, sprech, stt, tenants, tts
from lisa.config import DEFAULT_TENANT, DEV_PHONE, ELEVENLABS_TTS_MODEL, LLM_BASE, LLM_MODEL, PORT, WEB_DIR, WRITE_LIVE
from lisa.greeting import begruessung

app = FastAPI(title="Lisa Telefon-KI", version="0.1")
_AUDIO: dict[str, bytes] = {}
remote.token()


class SucheIn(BaseModel):
    q: str = ""
    tenant: str = ""


class StartIn(BaseModel):
    tenant: str = ""
    auftrag: str = ""
    patient: dict | None = None


class TurnIn(BaseModel):
    sessionId: str = ""
    text: str = ""


class AuftragIn(BaseModel):
    sessionId: str = ""
    auftrag: str = ""


class HangupIn(BaseModel):
    sessionId: str = ""


class RemoteMsg(BaseModel):
    token: str = ""
    role: str = "user"
    text: str = ""
    speaker: str = ""


class RemoteAck(BaseModel):
    token: str = ""
    ids: list[str] = []
    status: str = "fertig"


class RemoteBoard(BaseModel):
    token: str = ""
    text: str = ""


class RemoteUpload(BaseModel):
    token: str = ""
    name: str = ""
    data: str = ""
    note: str = ""


def _von_hier(request) -> bool:
    ip = (request.client.host if request.client else "") or ""
    return ip in {"127.0.0.1", "::1", "::ffff:127.0.0.1"}


def _tok(request: Request, extra: str = "") -> str:
    return (
        (extra or "").strip()
        or (request.query_params.get("token") or "").strip()
        or (request.headers.get("x-remote-token") or "").strip()
    )


def _remote_guard(request: Request, token: str = "") -> None:
    if not remote.token_ok(_tok(request, token), _von_hier(request)):
        raise HTTPException(401, "token")


def _audio_legen(blob: bytes) -> str:
    if not blob:
        return ""
    aid = secrets.token_hex(6)
    _AUDIO[aid] = blob
    ext = "wav" if blob[:4] == b"RIFF" else "mp3"
    return f"/api/audio/{aid}.{ext}"


def _anreichern(sit: dict) -> None:
    """Kartei, Termine, Slots — nie auf dem Mund-Pfad."""
    try:
        t = sit["tenant"]
        pat = patients.patient_aufloesen(t, sit.get("patient") or {})
        hist = patients.termine_fuer(t, pat)
        sit["patient"] = pat
        sit["past"] = pat.get("past") or hist["past"]
        sit["upcoming"] = pat.get("upcoming") or hist["upcoming"]
        ctx = sit.setdefault("booking", {})
        if pat.get("id"):
            ctx["patientId"] = pat.get("id") or ""
            ctx["firstName"] = pat.get("firstName") or ctx.get("firstName") or ""
            ctx["lastName"] = pat.get("lastName") or ctx.get("lastName") or ""
            ctx["patientName"] = pat.get("name") or ctx.get("patientName") or ""
            ctx["phone"] = pat.get("phone") or ctx.get("phone") or ""
        nxt = (sit["upcoming"] or [None])[0] if sit["upcoming"] else None
        if nxt and isinstance(nxt, dict):
            ctx["appointmentId"] = nxt.get("id") or ctx.get("appointmentId") or ""
            ctx["appointmentDate"] = nxt.get("date") or (nxt.get("iso") or "")[:10]
            ctx["slotIso"] = nxt.get("iso") or ctx.get("slotIso") or ""
        calendar.vorrat_fuellen(sit)
        msgs = sit.get("messages") or []
        if msgs and msgs[0].get("role") == "system":
            msgs[0]["content"] = agent.system_prompt_aktuell(sit)
    except Exception as e:
        print(f"lisa-enrich fail {e}", flush=True)


def _stimme(text: str) -> tuple[str, float]:
    if not text or not tts.bereit():
        return "", 0.0
    t0 = time.perf_counter()
    try:
        url = _audio_legen(tts.engine().speak(text))
    except RuntimeError:
        return "", round(time.perf_counter() - t0, 2)
    return url, round(time.perf_counter() - t0, 2)


def _zeile(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False) + "\n"


# Füller gegen die Totzeit. Die Audios werden beim Start einmal gerendert und
# bleiben liegen — abspielen kostet danach null Zeit.
_FILLER_URLS: dict[str, str] = {}
# Vorab-Füller: so früh raus, dass keine Stille entsteht, aber nicht bei
# blitzschnellen Zügen (Cache-Treffer brauchen keinen Überbrückungssatz).
_FILLER_VORAB_S = 0.3
# Not-Füller: nur wenn ein Zug OHNE erkannte Absicht UND ohne Werkzeug wirklich
# haengt. Normale Plauder-Antworten kommen nach 1,4 bis 2,6 s — eine kuerzere
# Frist wuerde den Fueller in die Antwort hineinsprechen (gemessen 27.08.2026).
_FILLER_SPAET_S = 3.2


def _filler_vorbereiten() -> None:
    if not tts.bereit():
        return
    for text in filler.alle_saetze():
        try:
            url = _audio_legen(tts.engine().speak(text))
            if url:
                _FILLER_URLS[text] = url
        except Exception as e:
            print(f"lisa-filler fail {text!r} {e}", flush=True)
    print(f"lisa-filler bereit: {len(_FILLER_URLS)} Saetze", flush=True)


def _filler_url(sit, gruppe: str) -> str:
    nr = int(sit.get("fillerNr") or 0)
    sit["fillerNr"] = nr + 1
    url = _FILLER_URLS.get(filler.satz(gruppe, nr))
    if url:
        return url
    return _FILLER_URLS.get(filler.satz("allgemein", nr)) or ""


def _angebot_offen(sit) -> bool:
    return bool(sit.get("offered"))


def _zug_stream(sit, *, art: str, text_in: str = "", extra: dict | None = None,
                stt_blob: bytes | None = None, stt_mime: str = "", stt_name: str = ""):
    """NDJSON: Überbrückungssatz sofort raus, Antwort folgt — nie Stille."""
    q: queue.Queue = queue.Queue()
    # JETZT ablesen, nicht spaeter: der Arbeitsfaden unten setzt idCheck auf
    # "fertig", sobald die Identitaet geklaert ist — er ist schneller als die
    # Fristberechnung im Hauptfaden und wuerde sie sonst in die Irre fuehren.
    id_phase = sit.get("idCheck") not in (None, "", "fertig")

    def melde(tool: str) -> None:
        q.put(("tool", tool))

    def arbeit() -> None:
        try:
            gesagt = text_in
            stt_s = None
            if stt_blob is not None:
                t0 = time.perf_counter()
                try:
                    gesagt = stt.transcribe(stt_blob, mime=stt_mime, name=stt_name)
                except RuntimeError as e:
                    print(f"lisa-listen fail bytes={len(stt_blob)} {e}", flush=True)
                    q.put(("leer", str(e)))
                    return
                stt_s = round(time.perf_counter() - t0, 2)
                if not gesagt:
                    print(f"lisa-listen empty bytes={len(stt_blob)} mime={stt_mime}", flush=True)
                    q.put(("leer", ""))
                    return
                print(f"lisa-listen ok text={gesagt!r}", flush=True)
                q.put(("gehoert", gesagt))
            out = _json_antwort(sit, art=art, text_in=gesagt, extra=extra, melde=melde)
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
        # In der Identitaetsphase antwortet die Zustandsmaschine sofort — ein
        # Kalender-Füller ("ich schaue kurz nach") waere dort schlicht falsch.
        if id_phase:
            return time.monotonic() + _FILLER_SPAET_S, "allgemein"
        gruppe = filler.vermutet(gehoert, angebot_offen=_angebot_offen(sit))
        if gruppe:
            return time.monotonic() + _FILLER_VORAB_S, gruppe
        return time.monotonic() + _FILLER_SPAET_S, "allgemein"

    frist, vorab_gruppe = frist_setzen(text_in)
    while True:
        try:
            wartezeit = None if filler_raus else max(0.02, frist - time.monotonic())
            typ, wert = q.get(timeout=wartezeit)
        except queue.Empty:
            url = _filler_url(sit, vorab_gruppe)
            if url:
                yield _zeile({"type": "filler", "audioUrl": url})
            filler_raus = True
            continue
        if typ == "gehoert":
            frist, vorab_gruppe = frist_setzen(wert)
            yield _zeile({"type": "transcript", "textIn": wert})
        elif typ == "tool":
            if not filler_raus:
                url = _filler_url(sit, filler.fuer_tool(wert))
                if url:
                    yield _zeile({"type": "filler", "audioUrl": url})
                filler_raus = True
        elif typ == "leer":
            yield _zeile({"type": "empty", "error": wert})
            return
        elif typ == "fehler":
            yield _zeile({"type": "empty", "error": wert})
            return
        else:  # fertig
            yield _zeile({"type": "reply", **wert})
            return


def _ndjson(gen):
    return StreamingResponse(
        gen,
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


def _json_antwort(sit, *, art: str, text_in: str = "", extra: dict | None = None, melde=None):
    extra = extra or {}
    t0 = time.perf_counter()
    if art == "start":
        reply = agent.start_reply(sit)
    else:
        reply = agent.user_turn(sit, text_in, melde=melde)
    llm_s = round(time.perf_counter() - t0, 2)
    # Sprech-Filter: Uhrzeiten/Daten als Worte, Fachbegriffe und Regie raus.
    text = sprech.sanitize(reply.get("text") or "")
    url, tts_s = _stimme(text)
    timings = {"llm": llm_s, "tts": tts_s, "total": round(llm_s + tts_s, 2)}
    session.merke_zug(sit, art=art, textIn=text_in, text=text, book=reply.get("book"), timings=timings)
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


@app.get("/health")
def health():
    h = llm.health()
    return {
        "ok": True,
        "service": "lisa-telefonki",
        "port": PORT,
        "tenant": DEFAULT_TENANT,
        "writeLive": WRITE_LIVE,
        "devPhone": DEV_PHONE,
        "llm": h,
        "tts": tts.engine().name if tts.bereit() else "fehlt",
        "ttsModel": ELEVENLABS_TTS_MODEL if tts.bereit() else "",
        "filler": f"{len(_FILLER_URLS)}/{len(filler.alle_saetze())}",
        "stt": "live+elevenlabs" if stt.bereit() else "live",
        "llmBase": LLM_BASE,
        "llmModel": LLM_MODEL,
        "lastCall": session.last_call(),
    }


@app.get("/api/tenants")
def api_tenants():
    return {"ok": True, "tenants": tenants.liste(), "default": DEFAULT_TENANT}


@app.post("/api/patients")
def api_patients(body: SucheIn):
    t = tenants.laden(body.tenant or DEFAULT_TENANT)
    found = patients.search_patients(t, body.q)
    karten = []
    for p in found.get("patients") or []:
        karte = patients.karten_patient(p)
        hist = patients.termine_fuer(t, p)
        karte["past"] = hist["past"]
        karte["upcoming"] = hist["upcoming"]
        karten.append(karte)
    return {"ok": True, "patients": karten, "error": found.get("error") or ""}


@app.post("/api/start")
def api_start(body: StartIn):
    auftrag = (body.auftrag or "").strip()
    if not auftrag:
        raise HTTPException(400, "auftrag fehlt")
    pat = body.patient or {}
    if not (pat.get("name") or pat.get("id") or pat.get("firstName")):
        raise HTTPException(400, "patient fehlt")
    if not pat.get("name"):
        pat["name"] = f"{pat.get('firstName') or ''} {pat.get('lastName') or ''}".strip()
    if not pat.get("devPhone"):
        from lisa.patients import format_de_phone
        pat["devPhone"] = format_de_phone(DEV_PHONE)
        pat["devPhoneRaw"] = DEV_PHONE
    t = tenants.laden(body.tenant or DEFAULT_TENANT)
    sit = session.neu(
        tenant_id=body.tenant or DEFAULT_TENANT,
        auftrag=auftrag,
        patient=pat,
        past=[],
        upcoming=[],
    )
    threading.Thread(target=_anreichern, args=(sit,), daemon=True).start()
    # Eigener Faden: der Anliegen-Satz soll fertig sein, wenn der Angerufene
    # die Identitaetsfrage bestaetigt — nicht hinter den Kalender-Umlaeufen warten.
    threading.Thread(target=anliegen.vorbereiten, args=(sit,), daemon=True).start()
    return _json_antwort(sit, art="start", extra={"sessionId": sit["id"], "praxis": t.get("praxisName")})


@app.post("/api/turn")
def api_turn(body: TurnIn):
    sit = session.holen(body.sessionId)
    if not sit:
        raise HTTPException(404, "sitzung unbekannt")
    print(f"lisa-turn session={body.sessionId} text={body.text!r}", flush=True)
    return _ndjson(_zug_stream(sit, art="turn", text_in=body.text))


@app.on_event("startup")
def _warm_start():
    def _run():
        # Füller zuerst: ohne sie entsteht genau die Stille, die weg soll.
        _filler_vorbereiten()
        t = tenants.laden(DEFAULT_TENANT)
        tts.warm(begruessung(
            t.get("praxisName") or "",
            "Kontrolltermin vorverlegen",
            behandler=t.get("behandler") or "",
        ))
    threading.Thread(target=_run, daemon=True).start()


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
        print(f"lisa-listen live session={sessionId} text={live!r}", flush=True)
        return _ndjson(_zug_stream(sit, art="turn", text_in=live))
    return _ndjson(_zug_stream(sit, art="listen", stt_blob=blob, stt_mime=mime, stt_name=name))


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


@app.post("/api/auftrag")
def api_auftrag(body: AuftragIn):
    sit = session.holen(body.sessionId)
    if not sit:
        raise HTTPException(404, "sitzung unbekannt")
    neu = (body.auftrag or "").strip()
    if not neu:
        raise HTTPException(400, "auftrag fehlt")
    sit["auftrag"] = neu
    return _json_antwort(sit, art="auftrag", text_in=f"(Neuer Auftrag vom Chef, jetzt ausführen: {neu})")


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


@app.get("/remote/state")
def remote_state(request: Request, token: str = "", limit: int = 120):
    _remote_guard(request, token)
    out = remote.state(limit)
    if _von_hier(request):
        t = remote.token()
        out["token"] = t
        out["fernPath"] = f"/fernsteuerung.html#t={t}"
    return out


@app.post("/remote/message")
def remote_message(request: Request, body: RemoteMsg):
    _remote_guard(request, body.token)
    return remote.add_message(role=body.role, text=body.text, speaker=body.speaker)


@app.get("/remote/pending")
def remote_pending(request: Request, token: str = ""):
    _remote_guard(request, token)
    return {"ok": True, "messages": remote.pending()}


@app.post("/remote/ack")
def remote_ack(request: Request, body: RemoteAck):
    _remote_guard(request, body.token)
    remote.ack(body.ids, body.status or "fertig")
    return {"ok": True}


@app.post("/remote/board")
def remote_board(request: Request, body: RemoteBoard):
    _remote_guard(request, body.token)
    remote.set_board(body.text)
    return {"ok": True}


@app.post("/remote/upload")
def remote_upload(request: Request, body: RemoteUpload):
    _remote_guard(request, body.token)
    return remote.save_file(name=body.name, data_b64=body.data, note=body.note)


@app.get("/api/audio/{name}")
def api_audio(name: str):
    aid = name.rsplit(".", 1)[0]
    blob = _AUDIO.get(aid)
    if not blob:
        raise HTTPException(404)
    mime = "audio/wav" if blob[:4] == b"RIFF" else "audio/mpeg"
    return Response(blob, media_type=mime)


if WEB_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.get("/")
def index():
    index = WEB_DIR / "index.html"
    if not index.is_file():
        raise HTTPException(404, "web/index.html fehlt")
    return FileResponse(index, headers={"Cache-Control": "no-store"})


@app.get("/{name}")
def web_file(name: str):
    erlaubt = {"app.js", "styles.css", "fernsteuerung.html"}
    if name in erlaubt:
        p = WEB_DIR / name
        if p.is_file():
            return FileResponse(p, headers={"Cache-Control": "no-store"})
    raise HTTPException(404)
