"""Eigenständiger Lisa-Dienst. Port 8095 — rührt Clara/Demo/MAS nicht an."""

from __future__ import annotations

import os
import threading

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.background import BackgroundTask

from kern import agentprofil, gedaechtnis, halbsatz, mitschnitt, sprech, unterbrechung, webpfad
from kern.dienst import Dienst, ndjson
from lisa import agent, anliegen, bewerbung, calendar, filler, kampagnen_store, llm, patients, remote, session, stt, tenants, tts, vorbereitung
from lisa import outbound
from lisa.config import BIANCA_WEB_DIR, DEFAULT_TENANT, DEV_PHONE, LLM_BASE, LLM_MODEL, PORT, WEB_DIR, WRITE_LIVE
from lisa.greeting import begruessung

app = FastAPI(title="Lisa Telefon-KI", version="0.1")
remote.token()


def _ist_bewerbung(sit: dict) -> bool:
    return (sit or {}).get("lisaArt") == bewerbung.ART


def _start_fn(sit: dict):
    return bewerbung.start_reply(sit) if _ist_bewerbung(sit) else agent.start_reply(sit)


def _turn_fn(sit: dict, spoken: str, **kw):
    return bewerbung.user_turn(sit, spoken, **kw) if _ist_bewerbung(sit) else agent.user_turn(sit, spoken, **kw)


def _stille_fn(sit: dict):
    return bewerbung.stille_zug(sit) if _ist_bewerbung(sit) else agent.stille_zug(sit)


def _hangup_fn(sit: dict):
    return bewerbung.hangup(sit) if _ist_bewerbung(sit) else agent.hangup(sit)


# Die komplette Latenz-Maschinerie (Audio-Ablage, Füller, NDJSON-Strom) liegt
# in kern.dienst und wird mit Bianca geteilt. Lisas Eigenheiten stecken nur in
# den vier Funktionszeigern.
DIENST = Dienst(
    name="lisa",
    start_fn=_start_fn,
    turn_fn=_turn_fn,
    # Solange die Identitätsprüfung läuft, antwortet die Zustandsmaschine
    # sofort — Vorab-Füller wären dort falsch. Bewerbung hat keinen Kalender.
    schnell_fn=lambda sit: _ist_bewerbung(sit) or sit.get("idCheck") not in (None, "", "fertig"),
    merke_zug=session.merke_zug,
)


def bianca_ziel() -> str:
    """Tunnel-Lisa läuft im Container: 127.0.0.1:8096 ist dort leer.
    Compose setzt LISA_BIANCA_URL=http://bianca:8096."""
    return (os.environ.get("LISA_BIANCA_URL") or "http://127.0.0.1:8096").rstrip("/")


class SucheIn(BaseModel):
    q: str = ""
    tenant: str = ""


class StartIn(BaseModel):
    tenant: str = ""
    auftrag: str = ""
    patient: dict | None = None
    # Lisa-Outbound (Bridge mode=outbound): Pending-UUID, kein Dock-Body.
    outboundUuid: str = ""


class OutboundDialIn(BaseModel):
    phoneCallId: str = ""
    clientId: str = ""
    locationId: str = ""
    fromDid: str = ""
    toE164: str = ""
    agent: dict | None = None
    auftrag: str = ""
    prompt: str = ""
    firstMessage: str = ""
    patient: dict | None = None
    doctor: dict | None = None
    freeTimeSlots: list | None = None
    calendars: list | None = None
    visitMotives: list | None = None
    locationName: str = ""
    campaignId: str = ""
    doctors: list | None = None
    calendarId: str = ""


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


class AuftragIn(BaseModel):
    sessionId: str = ""
    auftrag: str = ""


class VertiefenIn(BaseModel):
    tenant: str = ""
    auftrag: str = ""
    patient: dict | None = None


class HangupIn(BaseModel):
    sessionId: str = ""


class KampagneNeu(BaseModel):
    name: str = ""
    auftrag: str = ""
    tenant: str = ""
    liste: str = ""


class KampagnePatch(BaseModel):
    name: str | None = None
    auftrag: str | None = None
    tenant: str | None = None


class KampagneEmpfaenger(BaseModel):
    liste: str = ""
    empfaenger: list | None = None


class KampagneMark(BaseModel):
    empfaengerId: str = ""
    status: str = ""
    sessionId: str = ""


class KampagneStart(BaseModel):
    tenant: str = ""
    auftrag: str = ""
    probe: bool = True
    kampagne: dict | None = None


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


def _ndjson(gen):
    return ndjson(gen)


def _json_antwort(sit, *, art: str, text_in: str = "", extra: dict | None = None, melde=None):
    return DIENST.json_antwort(sit, art=art, text_in=text_in, extra=extra, melde=melde)


def _zug_stream(sit, **kw):
    return DIENST.zug_stream(sit, **kw)


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
        "ttsModel": tts.modell_info() if tts.bereit() else "",
        "ttsEngine": tts.engine_anzeige() if tts.bereit() else "keine Stimme",
        "filler": f"{len(DIENST.filler_urls)}/{len(filler.alle_saetze())}",
        "stt": stt.engine_anzeige() if stt.bereit() else "live",
        "llmBase": LLM_BASE,
        "llmModel": LLM_MODEL,
        "gedaechtnis": gedaechtnis.anzeige(),
        "outbound": True,
        "lastCall": session.last_call(),
    }


@app.get("/api/tenants")
def api_tenants():
    return {"ok": True, "tenants": tenants.liste(), "default": DEFAULT_TENANT}


@app.post("/api/patients")
def api_patients(body: SucheIn):
    t = agentprofil.fuer_tenant(body.tenant or DEFAULT_TENANT)
    found = patients.search_patients(t, body.q)
    karten = []
    for p in found.get("patients") or []:
        karte = patients.karten_patient(p)
        hist = patients.termine_fuer(t, p)
        karte["past"] = hist["past"]
        karte["upcoming"] = hist["upcoming"]
        karten.append(karte)
    return {"ok": True, "patients": karten, "error": found.get("error") or ""}


def _auth_outbound(request: Request) -> None:
    tok = (
        (request.headers.get("authorization") or "").strip()
        or (request.headers.get("x-api-key") or "").strip()
    )
    if not outbound.token_ok(tok):
        raise HTTPException(401, "token")


def _start_outbound(uid: str):
    """Bridge-Outbound: Pending-Meta -> Session aus CF-DB-Profil."""
    meta = outbound.pending_holen(uid)
    if not meta:
        raise HTTPException(404, "outbound pending unbekannt oder verbraucht")
    tenant = outbound.tenant_von_bundle(meta)
    patient = outbound.patient_von_bundle(meta)
    auftrag = outbound.auftrag_von_bundle(meta)
    if not patient.get("name") and not patient.get("id"):
        raise HTTPException(400, "patient fehlt im outbound-bundle")
    slots = meta.get("freeTimeSlots") if isinstance(meta.get("freeTimeSlots"), list) else []
    sit = session.neu(
        tenant=tenant,
        auftrag=auftrag,
        patient=patient,
        past=[],
        upcoming=[],
        offered=slots,
        phone_call_id=str(meta.get("phoneCallId") or ""),
    )
    # Slots schon gesetzt — Hintergrund-Anreicherung trotzdem fuer Historie.
    threading.Thread(target=_anreichern, args=(sit,), daemon=True).start()
    threading.Thread(target=anliegen.vorbereiten, args=(sit,), daemon=True).start()
    return _json_antwort(
        sit, art="start",
        extra={"sessionId": sit["id"], "praxis": tenant.get("praxisName"),
               "outbound": True},
    )


@app.post("/api/outbound/dial")
def api_outbound_dial(body: OutboundDialIn, request: Request):
    """CF startOutboundCall -> Originate auf Asterisk/Zaluma."""
    _auth_outbound(request)
    bundle = body.model_dump()
    try:
        out = outbound.dial(bundle)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except RuntimeError as e:
        print(f"lisa-outbound dial fail: {e}", flush=True)
        raise HTTPException(502, str(e)) from e
    print(f"lisa-outbound dial ok uuid={out.get('uuid')} "
          f"to={out.get('toE164')} phoneCallId={out.get('phoneCallId')}", flush=True)
    return out


@app.post("/api/start")
def api_start(body: StartIn):
    if (body.outboundUuid or "").strip():
        return _start_outbound(body.outboundUuid.strip())
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
    t = agentprofil.fuer_tenant(body.tenant or DEFAULT_TENANT)
    sit = session.neu(
        tenant=t,
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
    return _ndjson(_zug_stream(sit, art="turn", text_in=body.text,
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
    Lisa stupst deterministisch an (Auftrag + zuletzt offene Frage), ohne
    LLM und ohne Kalender. Leerer Text = Stups-Budget verbraucht."""
    sit = session.holen(body.sessionId)
    if not sit:
        raise HTTPException(404, "sitzung unbekannt")
    # W-HALBSATZ: haengt ein gehaltenes Satz-Fragment in der Sitzung, hat der
    # Anrufer den Satz nicht fortgesetzt — dann wird ER beantwortet, kein Stups.
    rest = halbsatz.abholen(sit)
    if rest:
        print(f"lisa-stille halbsatz-flush: {rest!r}", flush=True)
        return DIENST.json_antwort(sit, art="turn", text_in=rest,
                                   extra={"sessionId": sit.get("id") or ""})
    reply = _stille_fn(sit)
    text = sprech.sanitize(reply.get("text") or "")
    if not text:
        return {"ok": True, "empty": True, "text": "", "audioUrl": ""}
    url, tts_s, cached = DIENST.stimme(text)
    timings: dict = {"tts": tts_s}
    if cached:
        timings["ttsCache"] = True
    session.merke_zug(sit, art="stille", textIn="", text=text, timings=timings)
    mitschnitt.zug(sit, DIENST, art="stille", text=text, timings=timings, audio_url=url)
    print(f"lisa-stille session={body.sessionId} text={text!r}", flush=True)
    return {"ok": True, "empty": False, "text": text, "audioUrl": url, "writeLive": WRITE_LIVE}


@app.on_event("startup")
def _warm_start():
    def _run():
        # Füller zuerst: ohne sie entsteht genau die Stille, die weg soll.
        DIENST.filler_vorbereiten()
        DIENST.quittungen_vorbereiten()
        DIENST.notfall_vorbereiten()
        t = tenants.laden(DEFAULT_TENANT)
        tts.warm(begruessung(
            tenants.praxis_von(t),
            "Kontrolltermin vorverlegen",
            behandler=t.get("behandler") or "",
        ))
    threading.Thread(target=_run, daemon=True).start()


@app.post("/api/listen")
async def api_listen(sessionId: str = Form(""), text: str = Form(""), audio: UploadFile = File(...),
                     bargeUrl: str = Form(""), bargeMs: float = Form(0.0),
                     ohrMit: str = Form("0")):
    sit = session.holen(sessionId)
    if not sit:
        raise HTTPException(404, "sitzung unbekannt")
    blob = await audio.read()
    mime = audio.content_type or "application/octet-stream"
    name = audio.filename or "turn.webm"
    live = " ".join((text or "").split()).strip()
    ohr = (ohrMit or "").strip() in {"1", "true", "yes", "on"}
    if live:
        print(f"lisa-listen live session={sessionId} text={live!r}", flush=True)
        # W-MITSCHNITT: beim Vorab-TEXT-Zug (W-TEMPO) kommt das Audio nur
        # zum Archivieren mit — transkribiert wird nicht mehr.
        mitschnitt.eingang(sit, blob, mime)
        return _ndjson(_zug_stream(sit, art="turn", text_in=live,
                                   barge_url=bargeUrl, barge_ms=bargeMs, ohr=ohr))
    return _ndjson(_zug_stream(sit, art="listen", stt_blob=blob, stt_mime=mime, stt_name=name,
                               barge_url=bargeUrl, barge_ms=bargeMs, ohr=ohr))


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
    """W-TEMPO Vorab-STT (wie Bianca): Aufnahme kommt schon nach ~200 ms Ruhe
    an — die restliche Stille-Wartezeit ueberlappt mit der Transkription.
    Reines Ohr, kein Zug, kein Zustand; Tenant-Hotwords wie der echte Zug."""
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
    print(f"lisa-vorab-stt bytes={len(blob)} text={gesagt!r}", flush=True)
    return {"ok": True, "text": gesagt}


@app.post("/api/auftrag/vertiefen")
@app.post("/api/auftrag/vorbereiten")
def api_auftrag_vertiefen(body: VertiefenIn):
    auftrag = (body.auftrag or "").strip()
    if not auftrag:
        raise HTTPException(400, "auftrag fehlt")
    return vorbereitung.sammeln(
        auftrag,
        tenant_id=body.tenant or DEFAULT_TENANT,
        patient=body.patient or {},
    )


@app.post("/api/auftrag")
def api_auftrag(body: AuftragIn):
    sit = session.holen(body.sessionId)
    if not sit:
        raise HTTPException(404, "sitzung unbekannt")
    neu = (body.auftrag or "").strip()
    if not neu:
        raise HTTPException(400, "auftrag fehlt")
    sit["auftrag"] = neu
    # W-HIRN (03.09.2026): der Nachschub-Auftrag wird ein eigenes Anliegen —
    # das alte parkt, das Session-Hirn fuehrt den Stand im Prompt mit.
    from kern import hirn as kern_hirn
    kern_hirn.anliegen_hinzufuegen(sit, kern_hirn.seed_von_auftrag(neu))
    return _json_antwort(sit, art="auftrag", text_in=f"(Neuer Auftrag vom Chef, jetzt ausführen: {neu})")


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
            note = _hangup_fn(sit)
            session.merke_zug(sit, art="hangup", note=(note or {}).get("note") or "", dryRun=bool((note or {}).get("dryRun")))
        except Exception as e:
            print(f"lisa-hangup-nacharbeit fail {e}", flush=True)
            session.merke_zug(sit, art="hangup", note="", dryRun=False)
        session.sichern(sit)
        # W-MITSCHNITT: offene Stream-Audios einlösen, Ende-Zeit stempeln.
        mitschnitt.ende(sit, DIENST)
        # W-GEDAECHTNIS: Gesprächszusammenfassung ins Praxisgedächtnis (MAS).
        gedaechtnis.report_senden(sit)

    threading.Thread(target=_nacharbeit, daemon=True).start()
    return {"ok": True, "writeLive": WRITE_LIVE, "queued": True}


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


# --- Bianca-Durchreiche -----------------------------------------------------
# Der Cloudflare-Tunnel zeigt nur auf DIESEN Dienst (8095). Biancas Dienst
# (8096) ist von aussen nicht erreichbar — darum reicht Lisa alles unter
# /bianca/... an ihn durch. Im Container darf das NICHT 127.0.0.1 sein
# (Connection refused -> Tab "Bianca antwortet nicht"). Lokal bleibt der Default.
_BIANCA_ZIEL = bianca_ziel()
# read=None: die NDJSON-Stroeme (Fueller waehrend Werkzeug-Laeufen) duerfen
# beliebig lange offen bleiben.
_BIANCA_KANAL = httpx.AsyncClient(base_url=_BIANCA_ZIEL, timeout=httpx.Timeout(10.0, read=None))


@app.get("/bianca")
def bianca_umleiten():
    # Ohne Schraegstrich am Ende wuerden Biancas relative Pfade ("api/...")
    # auf Lisas Wurzel zeigen.
    return RedirectResponse("/bianca/")


@app.api_route("/bianca/{pfad:path}", methods=["GET", "HEAD", "POST"])
async def bianca_durchreichen(pfad: str, request: Request):
    kopf = {"x-forwarded-prefix": "/bianca"}
    ct = request.headers.get("content-type")
    if ct:
        kopf["content-type"] = ct
    try:
        weiter = _BIANCA_KANAL.build_request(
            request.method,
            httpx.URL(path="/" + pfad, query=request.url.query.encode()),
            headers=kopf,
            content=request.stream() if request.method not in {"GET", "HEAD"} else None,
        )
        antwort = await _BIANCA_KANAL.send(weiter, stream=True)
    except httpx.HTTPError:
        raise HTTPException(502, "Bianca-Dienst (Port 8096) antwortet nicht")
    raus = {k: v for k, v in antwort.headers.items() if k.lower() in {
        "content-type", "cache-control", "content-disposition",
        "content-length", "accept-ranges", "content-range", "location",
    }}
    # Absolute Redirects (/studio/) sonst raus aus /bianca/ → platte Tabs.
    loc = raus.get("location") or raus.get("Location")
    if loc:
        raus["location"] = webpfad.location_hinter_prefix(loc, "/bianca")
    # Cloudflare darf alte 404 auf neu hinzugekommenen Viewer-Dateien
    # nicht festhalten (Vorfall 09.09.2026: anrufe.js).
    raus.setdefault("cache-control", "no-store")
    mime = (raus.get("content-type") or raus.get("Content-Type") or "").lower()
    if "text/html" in mime:
        roh = await antwort.aread()
        await antwort.aclose()
        html = webpfad.html_studio_pfade(roh.decode("utf-8", errors="replace"), "/bianca")
        raus.pop("content-length", None)
        raus.pop("Content-Length", None)
        return Response(html, status_code=antwort.status_code, headers=raus,
                        media_type="text/html; charset=utf-8")
    return StreamingResponse(
        antwort.aiter_raw(),
        status_code=antwort.status_code,
        headers=raus,
        background=BackgroundTask(antwort.aclose),
    )


@app.get("/api/kampagnen")
def api_kampagnen_liste():
    return {"ok": True, "kampagnen": kampagnen_store.liste()}


@app.post("/api/kampagnen")
def api_kampagnen_neu(body: KampagneNeu):
    return kampagnen_store.anlegen(
        name=body.name,
        auftrag=body.auftrag,
        tenant=body.tenant or DEFAULT_TENANT,
        empfaenger_roh=body.liste,
    )


@app.get("/api/kampagnen/{kid}")
def api_kampagnen_eine(kid: str):
    doc = kampagnen_store.holen(kid)
    if not doc:
        raise HTTPException(404, "kampagne unbekannt")
    return doc


@app.patch("/api/kampagnen/{kid}")
def api_kampagnen_patch(kid: str, body: KampagnePatch):
    doc = kampagnen_store.speichern(
        kid, name=body.name, auftrag=body.auftrag, tenant=body.tenant,
    )
    if not doc:
        raise HTTPException(404, "kampagne unbekannt")
    return doc


@app.post("/api/kampagnen/{kid}/empfaenger")
def api_kampagnen_dazu(kid: str, body: KampagneEmpfaenger):
    doc = kampagnen_store.empfaenger_dazu(
        kid, roh=body.liste, zeilen=body.empfaenger,
    )
    if not doc:
        raise HTTPException(404, "kampagne unbekannt")
    return doc


@app.delete("/api/kampagnen/{kid}/empfaenger/{eid}")
def api_kampagnen_weg(kid: str, eid: str):
    doc = kampagnen_store.empfaenger_weg(kid, eid)
    if not doc:
        raise HTTPException(404, "kampagne unbekannt")
    return doc


@app.post("/api/kampagnen/{kid}/markieren")
def api_kampagnen_mark(kid: str, body: KampagneMark):
    doc = kampagnen_store.markieren(
        kid, body.empfaengerId, status=body.status, session_id=body.sessionId,
    )
    if not doc:
        raise HTTPException(404, "kampagne oder status unbekannt")
    return doc


@app.post("/api/kampagne/start")
def api_kampagne_start(body: KampagneStart):
    """Bewerbungs-Anruf: Lisa schweigt bis zur Meldung, kein Patient nötig."""
    auftrag = (body.auftrag or "").strip() or bewerbung.DEFAULT_AUFTRAG
    km = body.kampagne if isinstance(body.kampagne, dict) else {}
    t = agentprofil.fuer_tenant(body.tenant or DEFAULT_TENANT)
    sit = session.neu(
        tenant=t,
        auftrag=auftrag,
        patient={},
        past=[],
        upcoming=[],
    )
    sit["lisaArt"] = bewerbung.ART
    sit["kampagne"] = km
    sit["probe"] = bool(body.probe)
    bewerbung.start_reply(sit)
    session.sichern(sit)
    return _json_antwort(
        sit, art="start",
        extra={"sessionId": sit["id"], "praxis": t.get("praxisName"),
               "bewerbung": True},
    )


if WEB_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


_MITSCHNITT_LISA = "lisa"


@app.get("/api/anrufe")
def api_lisa_anrufe():
    return {"ok": True, "anrufe": mitschnitt.liste(_MITSCHNITT_LISA)}


@app.get("/api/anrufe/{sid}")
def api_lisa_anruf(sid: str):
    m = mitschnitt.laden(_MITSCHNITT_LISA, sid)
    if not m:
        raise HTTPException(404, "anruf unbekannt")
    return {"ok": True, "anruf": m}


@app.get("/api/anrufe/{sid}/audio/{datei}")
def api_lisa_anruf_audio(sid: str, datei: str):
    p = mitschnitt.audio_pfad(_MITSCHNITT_LISA, sid, datei)
    if p is None:
        raise HTTPException(404)
    mime = {"wav": "audio/wav", "mp3": "audio/mpeg", "m4a": "audio/mp4",
            "ogg": "audio/ogg"}.get(p.suffix.lstrip("."), "audio/webm")
    return FileResponse(p, media_type=mime)


@app.get("/api/anrufe/{sid}/download")
def api_lisa_anruf_download(sid: str):
    m = mitschnitt.laden(_MITSCHNITT_LISA, sid)
    if not m:
        raise HTTPException(404, "anruf unbekannt")
    blob = mitschnitt.anruf_wav(_MITSCHNITT_LISA, sid)
    if not blob:
        raise HTTPException(404, "kein Audio in diesem Mitschnitt")
    stempel = str(m.get("startedAt") or "")[:16].replace(":", "-").replace("T", "_")
    name = f"lisa-anruf-{stempel or sid[:8]}.wav"
    return Response(blob, media_type="audio/wav",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.post("/api/anrufe/{sid}/loeschen")
def api_lisa_anruf_loeschen(sid: str):
    return {"ok": mitschnitt.loeschen(_MITSCHNITT_LISA, sid)}


@app.get("/anrufe")
def anrufe_umleiten():
    # Eingehende Live-Anrufe (Bianca) — das ist die Liste auf dieser Seite.
    return RedirectResponse("/bianca/anrufe", status_code=307)


@app.get("/lisa-anrufe")
def lisa_anrufe_seite():
    p = BIANCA_WEB_DIR / "anrufe.html"
    if not p.is_file():
        raise HTTPException(404, "anrufe.html fehlt")
    html = p.read_text(encoding="utf-8")
    html = html.replace("Bianca — Anrufe", "Lisa — Anrufe")
    html = html.replace("Bianca — Unterhaltungen mit Audio, Transkript, Tools und Zeiten",
                        "Lisa — ausgehende Anrufe mit Audio, Transkript und Zeiten")
    html = html.replace('href="."', 'href="/#lisa"')
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@app.get("/anrufe.js")
def lisa_anrufe_js():
    p = BIANCA_WEB_DIR / "anrufe.js"
    if not p.is_file():
        raise HTTPException(404)
    return FileResponse(p, media_type="application/javascript; charset=utf-8",
                        headers={"Cache-Control": "no-store"})


@app.get("/praxis.js")
def lisa_praxis_js():
    p = BIANCA_WEB_DIR / "praxis.js"
    if not p.is_file():
        raise HTTPException(404)
    return FileResponse(p, media_type="application/javascript; charset=utf-8",
                        headers={"Cache-Control": "no-store"})


@app.get("/")
def index():
    index = WEB_DIR / "index.html"
    if not index.is_file():
        raise HTTPException(404, "web/index.html fehlt")
    return FileResponse(index, media_type="text/html; charset=utf-8",
                        headers={"Cache-Control": "no-store"})


@app.get("/kampagne")
def kampagne_seite():
    seite = WEB_DIR / "kampagne.html"
    if not seite.is_file():
        raise HTTPException(404, "web/kampagne.html fehlt")
    return FileResponse(seite, media_type="text/html; charset=utf-8",
                        headers={"Cache-Control": "no-store"})


@app.api_route("/{name}", methods=["GET", "HEAD"])
def web_file(name: str):
    # HEAD muss gehen — sonst wirkt /replay.html „gelöscht“ (405 auf Probe).
    erlaubt = {"app.js", "shell.js", "styles.css", "fernsteuerung.html", "replay.html",
               "kampagne.html", "kampagne.js"}
    if name in erlaubt:
        p = WEB_DIR / name
        if p.is_file():
            return FileResponse(p, headers={"Cache-Control": "no-store"})
    raise HTTPException(404)
