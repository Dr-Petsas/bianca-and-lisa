"""DID -> Mandant aus der Pickadoc-DB (W-MANDANT 30.08.2026).

Chef: "anhand der angerufenen nummer müssen wir in der db den passenden
agent laden und somit alle nötigen informationen erhalten." Der Weg ist
derselbe wie im alten phone_agent: die ANGERUFENE Nummer geht als
``calledNumber`` an die Cloud Function ``onPickadocPhoneCall`` (phase=pre),
zurück kommt der komplette Agent (clientId, locationId, Kalender, Motive,
Begrüßung, STT-Keywords).

Aufloesungs-Reihenfolge (fuer_did) — Chef 30.08.2026: "die Konfig und somit
die begruessung MUSS aus der DB kommen":

1. **Cloud Function** (Token gesetzt): die DB ist die Wahrheit. Die Antwort
   wird auf Biancas Tenant-Schema gemappt; passt die clientId zu einem
   lokalen Mandanten, dient dessen Datei nur als BASIS fuer Felder, die die
   DB nicht kennt (Sprechformen, wissen) — Begruessung (firstMessage),
   Kalender, Motive, Keywords und der Agent-Prompt (dbPrompt) kommen aus
   der DB und GEWINNEN.
2. **Lokaler Mandant mit passender DID** (Feld ``dids`` in tenants/*.json):
   nur noch Rueckfall — CF aus, CF down oder kein Agent zur Nummer.
3. Nichts gefunden -> None; der Aufrufer faellt auf DEFAULT_TENANT zurueck
   (nie stumm scheitern — der Anruf wird immer angenommen).

TTL-Cache je Nummer (AGENT_PROFIL_TTL_S, Default 300 s): der Anrufstart
zahlt die CF-Latenz nur beim ersten Anruf; Fehlschlaege werden kurz
negativ gecached, damit nicht jeder Anruf den Timeout bezahlt.

Notaus: DID_AGENT=0 => kein CF-Lookup (lokale DID-Zuordnung bleibt).
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime
from typing import Any

import httpx

from kern import tenants
from kern.config import PHONE_CALL_TOKEN, PHONE_CALL_URL

WARTE_S = float(os.environ.get("PICKADOC_PHONE_CALL_TIMEOUT_S") or "8")
_TTL_S = float(os.environ.get("AGENT_PROFIL_TTL_S") or "300")
_FEHL_TTL_S = 60.0

_CACHE: dict[str, tuple[float, dict[str, Any] | None]] = {}
_LOCK = threading.Lock()


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def enabled() -> bool:
    if os.environ.get("DID_AGENT", "").strip().lower() in {"0", "false", "no", "off"}:
        return False
    return bool(PHONE_CALL_TOKEN)


def anzeige() -> str:
    if enabled():
        return "DID -> Pickadoc-DB (onPickadocPhoneCall), tenants/*.json nur Rueckfall"
    return "DID -> nur lokale tenants/*.json (kein CF-Token)"


def _keywords(roh: Any) -> list[str]:
    """Agent-Keywords ("Petsas, Nikolaou; Narval") -> Liste wie sttHotwords."""
    if isinstance(roh, list):
        return [_s(x) for x in roh if _s(x)]
    text = _s(roh)
    if not text:
        return []
    return [p.strip() for p in text.replace(";", ",").split(",") if p.strip()]


def _kalender(pre: dict[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    roh = pre.get("calendars") if isinstance(pre.get("calendars"), list) else []
    for row in roh:
        if not isinstance(row, dict):
            continue
        cid, name = _s(row.get("id")), _s(row.get("name"))
        if cid and name:
            out.append({"id": cid, "name": name})
    if not out:
        # Nur Namen ohne Kalender-Ids (alte Agents): Arztwahl bleibt moeglich,
        # die Slot-Suche laeuft dann global (typ=egal-Verhalten).
        for d in (pre.get("doctors") if isinstance(pre.get("doctors"), list) else []):
            if _s(d):
                out.append({"id": "", "name": _s(d)})
    return out


def _motive(pre: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    roh = pre.get("visitMotives") if isinstance(pre.get("visitMotives"), list) else []
    for row in roh:
        if not isinstance(row, dict):
            continue
        mid, name = _s(row.get("id")), _s(row.get("name") or row.get("nameForPatient"))
        if not mid or not name:
            continue
        eintrag: dict[str, Any] = {"id": mid, "name": name}
        try:
            if row.get("duration") is not None:
                eintrag["duration"] = int(row["duration"])
        except (TypeError, ValueError):
            pass
        out.append(eintrag)
    return out


# Prompt-Fragmente des DB-Agents — dieselben Felder/Ueberschriften wie
# phone_agent assemble_persona_instructions (Agent.getFullSystemPrompt),
# aber OHNE dessen Verhaltens-Vorspann und Tool-Ausfall-Schwanz: das
# VERHALTEN (Buchungsweg, Gespraechsregeln) ist bei Bianca hart im festen
# System-Prompt, die DB liefert die Praxis-FAKTEN (Chef 30.08.2026).
_PROMPT_FRAGMENTE = (
    ("rolePrompt", "Rolle"),
    ("tasksPrompt", "Aufgaben"),
    ("specialFeaturesPrompt", "Besondere Features"),
    ("locationPrompt", "Standort"),
    ("patientsPrompt", "Patienten"),
    ("appointmentPrompt", "Termine"),
    ("referrerPrompt", "Überweiser"),
    ("mandatoryPrompt", "Pflichten"),
    ("miscellaneousPrompt", "Sonstiges"),
)

_PLATZHALTER_RE = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")
_TAGE = ("Montag", "Dienstag", "Mittwoch", "Donnerstag",
         "Freitag", "Samstag", "Sonntag")


def _platzhalter_fuellen(text: str) -> str:
    """{{current_time}} & Co. aus den alten ElevenLabs-Prompts einloesen —
    unbekannte Platzhalter bleiben stehen (kein stilles Wegschneiden)."""
    if "{{" not in text:
        return text
    now = datetime.now()
    werte = {
        "current_time": now.strftime("%Y-%m-%dT%H:%M"),
        "current_week_day": f"{_TAGE[now.weekday()]} {now.strftime('%Y-%m-%d')}",
        "patient_time_zone": "Europe/Berlin",
    }
    flach = dict(werte)
    for k, v in werte.items():
        flach[k.replace("_", "")] = v

    def _ersetzen(m: re.Match[str]) -> str:
        k = re.sub(r"[\s\-]+", "_", _s(m.group(1))).lower()
        return flach.get(k) or flach.get(k.replace("_", "")) or m.group(0)

    return _PLATZHALTER_RE.sub(_ersetzen, text)


def db_prompt_von_agent(agent: dict[str, Any]) -> str:
    """Agent-Prompt aus der DB: Fragment-Felder mit Ueberschriften; sind alle
    leer, gilt der systemPrompt-Blob (manche Betreiber pflegen alles dort)."""
    if not isinstance(agent, dict):
        return ""
    teile: list[str] = []
    for key, titel in _PROMPT_FRAGMENTE:
        body = str(agent.get(key) or "").strip()
        if body:
            teile.append(f"# {titel}:\n{body}")
    text = "\n\n".join(teile) or str(agent.get("systemPrompt") or "").strip()
    return _platzhalter_fuellen(text)


def tenant_von_pre(pre: dict[str, Any], did: str = "") -> dict[str, Any] | None:
    """CF-Antwort (phase=pre) -> Biancas Tenant-Schema.

    Die DB gewinnt (Chef 30.08.2026): Begruessung (firstMessage), Kalender,
    Motive, Keywords und der Agent-Prompt (dbPrompt) kommen IMMER aus der
    CF-Antwort. Passt die clientId zu einer lokalen tenants/*.json, dient
    die Datei nur als Basis fuer Felder, die die DB nicht kennt
    (praxisName*-Sprechformen, wissen)."""
    if not isinstance(pre, dict):
        return None
    agent = pre.get("agent") if isinstance(pre.get("agent"), dict) else {}
    client_id = _s(agent.get("clientId")) or _s(pre.get("clientId"))
    if not client_id or pre.get("enabled") is False:
        return None

    basis = tenants.von_client_id(client_id)
    t: dict[str, Any] = dict(basis) if basis else {}
    t["clientId"] = client_id
    loc = _s(agent.get("locationId")) or _s(pre.get("locationId"))
    if loc:
        t["locationId"] = loc
    t["_quelle"] = "cf+datei" if basis else "cf"
    if not t.get("_id"):
        t["_id"] = f"cf-{_s(agent.get('id')) or tenants.nummer_norm(did) or client_id}"

    cals = _kalender(pre)
    if cals:
        t["calendars"] = cals
        if not _s(t.get("defaultCalendarId")) and cals[0].get("id"):
            t["defaultCalendarId"] = cals[0]["id"]
    motive = _motive(pre)
    if motive:
        t["visitMotives"] = motive

    if not _s(t.get("behandler")):
        docs = pre.get("doctors") if isinstance(pre.get("doctors"), list) else []
        t["behandler"] = _s(docs[0]) if docs else _s((cals[0].get("name") if cals else ""))
    if not _s(t.get("telefon")):
        t["telefon"] = _s(agent.get("phoneNumber"))
    if not _s(t.get("sprache")):
        t["sprache"] = _s(agent.get("mainLanguage")) or "de"

    hot = list(t.get("sttHotwords") or []) if isinstance(t.get("sttHotwords"), list) else []
    for kw in _keywords(agent.get("keywords")):
        if kw not in hot:
            hot.append(kw)
    if hot:
        t["sttHotwords"] = hot

    # Die Begruessung kommt IMMER aus der DB (agent.firstMessage) — auch wenn
    # eine kuratierte Datei als Basis dient. Chef 30.08.2026: "die Konfig und
    # somit die begruessung MUSS aus der DB kommen" (validiert er absichtlich
    # ueber einen Marker-Text im DB-Agent).
    gruss = _s(agent.get("firstMessage"))
    if gruss:
        t["begruessungText"] = gruss
    if not _s(t.get("praxisName")):
        t["praxisName"] = _s(pre.get("locationName")) or _s(agent.get("locationName"))

    # Agent-Prompt aus der DB: Praxis-Fakten (Standort, Patienten, Ueberweiser,
    # Preise ...) fuer den Merge in Biancas festen Verhaltens-Prompt.
    db = db_prompt_von_agent(agent)
    if db:
        t["dbPrompt"] = db

    # W-CALLSTATUS: die pre-Phase hat einen PhoneCall-Datensatz angelegt —
    # seine Id gehoert zur SITZUNG (call_erfassen), nie in den Cache.
    pcid = _s(pre.get("phoneCallId"))
    if pcid:
        t["_phoneCallId"] = pcid
    return t


def _cf_senden(body: dict[str, Any]) -> dict[str, Any] | None:
    """Ein Wurf an onPickadocPhoneCall (pre/post/analysis) — None bei Fehler."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {PHONE_CALL_TOKEN}",
        "x-api-key": PHONE_CALL_TOKEN,
    }
    r = httpx.post(PHONE_CALL_URL, json=body, headers=headers, timeout=WARTE_S)
    if r.status_code < 200 or r.status_code >= 300:
        print(f"agentprofil cf phase={body.get('phase')} -> http {r.status_code}: "
              f"{r.text[:200]}", flush=True)
        return None
    d = r.json()
    return d if isinstance(d, dict) else None


def _cf_pre(did: str, caller: str = "") -> dict[str, Any] | None:
    e164 = "+" + tenants.nummer_norm(did)
    call_id = f"bianca-{tenants.nummer_norm(did)}-{int(time.time())}"
    # W-ANRUFER (30.08.2026): die Bruecke liest die Anrufernummer aus dem
    # UUID-Kopf des Dialplans (roh, z. B. "004915253904756") — die CF will
    # +E164 (trimPhoneNumber matcht Patienten ueber "+49…"). Unterdrueckte
    # Nummer -> "anonymous" wie bisher: kein Patient matcht, der Agent
    # kommt trotzdem, das Portal zeigt "Unterdrueckte Nummer".
    caller_norm = tenants.nummer_norm(caller)
    return _cf_senden({
        "phase": "pre",
        "callerPhone": ("+" + caller_norm) if caller_norm else "anonymous",
        "calledNumber": e164,
        "callId": call_id,
        "conversationId": call_id,
        "roomName": call_id,
    })


def fuer_did(did: Any, caller: str = "") -> dict[str, Any] | None:
    """Mandant zur angerufenen Nummer — die DB ist die Wahrheit (Chef
    30.08.2026), die lokale Datei nur Rueckfall (CF aus/down/kein Agent)."""
    norm = tenants.nummer_norm(did)
    if not norm:
        return None

    t: dict[str, Any] | None = None
    if enabled():
        with _LOCK:
            hit = _CACHE.get(norm)
            frisch = bool(hit) and time.monotonic() - hit[0] < (_TTL_S if hit[1] else _FEHL_TTL_S)
        if frisch:
            t = dict(hit[1]) if hit[1] else None
        else:
            try:
                pre = _cf_pre(norm, caller)
                t = tenant_von_pre(pre, did=norm) if pre else None
            except Exception as e:
                print(f"agentprofil cf fail did={norm}: {type(e).__name__}: {e}", flush=True)
                t = None
            with _LOCK:
                # phoneCallId gilt nur fuer DIESEN Anruf — nie mitcachen,
                # sonst haengen spaetere Anrufe am fremden Datensatz.
                ablage = dict(t) if t else None
                if ablage:
                    ablage.pop("_phoneCallId", None)
                _CACHE[norm] = (time.monotonic(), ablage)
            if t:
                print(f"agentprofil did={norm} -> {t.get('_quelle')} {t.get('_id')} "
                      f"clientId={t.get('clientId')}", flush=True)
            else:
                print(f"agentprofil did={norm} -> kein Agent in der DB", flush=True)
    if t:
        return t

    lokal = tenants.von_did(norm)
    if lokal:
        print(f"agentprofil did={norm} -> lokale Datei {lokal.get('_id')} (Rueckfall)", flush=True)
        return lokal
    return None


def cache_leeren() -> None:
    with _LOCK:
        _CACHE.clear()


# ---------------------------------------------------------------------------
# W-CALLSTATUS (Chef 30.08.2026): "wenn der call beendet ist muss die
# entsprechende cloud function aufgerufen werden, dann wird der status auf
# aufgelegt oder so aehnlich gesetzt und eine zusammenfassung erstellt."
# pre legt den PhoneCall-Datensatz an (inProgress), post schliesst ihn
# (status=callCompleted, Transkript, Dauer), analysis traegt die
# Zusammenfassung nach — gleiche CF, gleiche Auth wie fuer_did.
# ---------------------------------------------------------------------------

def call_erfassen(sit: dict, did: Any = "", caller: str = "") -> None:
    """Beim Anrufstart: die phoneCallId dieses Anrufs in die Sitzung holen.

    Kam der Mandant frisch aus der CF, liegt sie schon am Tenant
    (_phoneCallId). Kam er aus dem TTL-Cache, hat DIESER Anruf noch keinen
    Datensatz — dann registriert ein Daemon-Thread den Anruf nach (die
    Begruessung wartet nie auf die CF)."""
    sit["did"] = _s(did)
    t = sit.get("tenant") or {}
    if not isinstance(t, dict):
        return
    pcid = _s(t.pop("_phoneCallId", ""))
    if pcid:
        sit["phoneCallId"] = pcid
        return
    if not enabled() or not str(t.get("_quelle") or "").startswith("cf"):
        return  # kein DB-Agent zu dieser Nummer -> kein PhoneCall-Datensatz
    norm = tenants.nummer_norm(did)
    if not norm:
        return

    def _lauf() -> None:
        try:
            pre = _cf_pre(norm, caller)
            neu = _s((pre or {}).get("phoneCallId"))
            if neu:
                sit["phoneCallId"] = neu
                print(f"agentprofil call registriert phoneCallId={neu}", flush=True)
        except Exception as e:
            print(f"agentprofil call-registrierung fail: {type(e).__name__}: {e}", flush=True)

    threading.Thread(target=_lauf, daemon=True).start()


# DocGenda PhoneCallCategory-Namen (String-Form, von der CF akzeptiert).
_KATEGORIEN_ERLAUBT = {
    "appointment", "cancellation", "callbackRequest", "prescription",
    "medicalReferral", "medicalReport", "message", "question",
}
_UNZUFRIEDEN_ERLAUBT = {"practice", "agent", "both", "none", "unknown"}

_JSON_ZAUN_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.I)


def _json_objekt(text: str) -> dict[str, Any] | None:
    """JSON-Objekt aus einer LLM-Antwort fischen (mit/ohne Code-Zaun)."""
    roh = _s(text)
    zaun = _JSON_ZAUN_RE.search(roh)
    if zaun:
        roh = zaun.group(1).strip()
    treffer = re.search(r"\{[\s\S]*\}", roh)
    if not treffer:
        return None
    try:
        obj = json.loads(treffer.group(0))
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def _analyse_llm(transcript: list[dict[str, Any]]) -> dict[str, Any]:
    """Qualitaets-Analyse wie phone_agent call_analysis (gleiches Schema,
    gleiche Regeln, unser lokales vLLM): summary, weiche Kategorien,
    Zufriedenheit, Agent-Fehler, Unzufriedenheits-Zuordnung.

    Leeres Dict bei LLM-Fehler oder ohne Anrufer-Zeile — der Abschluss
    faellt dann auf die deterministischen Werte zurueck."""
    if not any(z.get("role") == "user" for z in transcript):
        return {}
    zeilen = []
    for z in transcript:
        wer = "Assistentin" if z.get("role") == "agent" else "Anrufer"
        zeilen.append(f"{wer}: {z.get('message')}")
    text = "\n".join(zeilen)[:12000]
    system = (
        "Du bist Qualitätsprüfer einer deutschen Arztpraxis-Telefon-KI. "
        "Analysiere das Transkript und antworte NUR mit einem JSON-Objekt "
        "(kein Markdown).\n"
        "Schema:\n"
        "{\n"
        '  "summary": "2-4 Sätze Deutsch: Anliegen, Ergebnis, offene Punkte",\n'
        '  "categories": ["appointment"|"cancellation"|"callbackRequest"|"prescription"'
        '|"medicalReferral"|"medicalReport"|"message"|"question"],\n'
        '  "patientSatisfaction": 1|2|3|4|5,\n'
        '  "patientSatisfactionReason": "kurz Deutsch: woran man die Stimmung erkennt",\n'
        '  "agentError": true|false,\n'
        '  "agentErrorDetails": ["kurz Deutsch, z.B. gleiche Frage 3× wiederholt"],\n'
        '  "dissatisfactionCause": "practice"|"agent"|"both"|"none"|"unknown",\n'
        '  "dissatisfactionCauseReason": "kurz Deutsch: warum diese Zuordnung"\n'
        "}\n"
        "Regeln:\n"
        "- summary immer Deutsch.\n"
        "- agentError=true bei schlechtem Agent-Verhalten: Wiederholungen, "
        "ignoriertes Anliegen, unsinnige Nachfragen — NICHT bei korrekter "
        "Nachfrage nach Name/Telefon beim ersten Mal.\n"
        "- dissatisfactionCause: practice = Unmut wegen Praxis/Terminlage, "
        "agent = Unmut wegen Agent-Verhalten, both = beides, "
        "none = Patient wirkt zufrieden, unknown = unklar.\n"
        "- Satisfaction 5=gelöst/freundlich, 1=eskaliert/sehr verärgert."
    )
    try:
        from kern import llm
        r = llm.chat(
            [{"role": "system", "content": system},
             {"role": "user", "content": f"Transkript:\n{text}"}],
            temperature=0.1, max_tokens=500,
        )
        if not r.get("ok"):
            return {}
        return _json_objekt(r.get("text") or "") or {}
    except Exception as e:
        print(f"agentprofil analyse-llm fail: {type(e).__name__}: {e}", flush=True)
        return {}


def _cf_evaluation(sit: dict, analyse: dict[str, Any]) -> dict[str, Any]:
    """Komplettes evaluation-Objekt — JEDES Feld belegt. Die CF baut daraus
    ungeprueft ihr Firestore-Update; fehlende Felder wuerden dort zu
    undefined-Werten, der Write wirft und wird still verschluckt
    (updatePhoneCall faengt und loggt nur) — live erlebt 30.08.2026:
    analysis meldete success, der Datensatz blieb ohne Summary."""
    tool_details = [
        _s(t.get("name")) or "tool"
        for t in (sit.get("tools") or [])
        if isinstance(t, dict) and t.get("ok") is False
    ][:10]
    try:
        sat = int(analyse.get("patientSatisfaction"))
        sat = max(1, min(5, sat))
        sat_grund = _s(analyse.get("patientSatisfactionReason"))
    except (TypeError, ValueError):
        sat, sat_grund = 3, ""
    grund = str(analyse.get("dissatisfactionCause") or "").strip().lower()
    if grund not in _UNZUFRIEDEN_ERLAUBT:
        grund = "unknown"
    agent_details = [
        _s(x) for x in (analyse.get("agentErrorDetails") or []) if _s(x)
    ][:10] if isinstance(analyse.get("agentErrorDetails"), list) else []
    return {
        "patientSatisfaction": sat,
        "patientSatisfactionReason": sat_grund or "keine automatische Bewertung",
        "toolError": bool(tool_details),
        "toolErrorDetails": tool_details,
        "agentError": bool(analyse.get("agentError")),
        "agentErrorDetails": agent_details,
        "dissatisfactionCause": grund,
        "dissatisfactionCauseReason": _s(analyse.get("dissatisfactionCauseReason")),
    }


def _cf_kategorien(sit: dict) -> list[str]:
    """Harte Kategorien aus der Sitzung (DocGenda PhoneCallCategory-Namen) —
    deterministisch wie phone_agent hard_categories_from_session."""
    def _ok(e: Any) -> bool:
        return isinstance(e, dict) and bool(e.get("ok") or e.get("booked"))

    cats: list[str] = []
    if _ok(sit.get("lastBook")) or _ok(sit.get("lastMove")):
        cats.append("appointment")
    if _ok(sit.get("lastCancel")):
        cats.append("cancellation")
    if sit.get("praxisNotiz"):
        cats.append("callbackRequest")
    return cats


def _cf_transkript(sit: dict) -> tuple[list[dict[str, Any]], int]:
    """Transkript im DocGenda-TranscriptItem-Format + Dauer in Sekunden.

    Quelle ist der Mitschnitt (traegt offsetMs je Zug und dauerMs);
    ohne Mitschnitt hilfsweise das LLM-Protokoll (Zeiten dann 0)."""
    zuege: list[dict[str, Any]] = []
    dauer = 0
    try:
        from kern import mitschnitt
        m = mitschnitt.laden(_s(sit.get("stimme")).lower() or "bianca",
                             _s(sit.get("id"))) or {}
        zuege = m.get("zuege") or []
        dauer = int(round(float(m.get("dauerMs") or 0) / 1000.0))
    except Exception:
        zuege, dauer = [], 0

    out: list[dict[str, Any]] = []
    for z in zuege:
        if not isinstance(z, dict):
            continue
        secs = int(round(float(z.get("offsetMs") or 0) / 1000.0))
        if _s(z.get("textIn")):
            out.append({"role": "user", "message": _s(z.get("textIn")),
                        "timeInCallSecs": secs})
        if _s(z.get("text")):
            out.append({"role": "agent", "message": _s(z.get("text")),
                        "timeInCallSecs": secs})
    if not out:
        for msg in sit.get("messages") or []:
            rolle = msg.get("role") if isinstance(msg, dict) else ""
            text = _s(msg.get("content")) if isinstance(msg, dict) else ""
            # Regie-Zeilen wie "(Ein Anrufer ist in der Leitung. ...)" sind
            # kein Gespraech.
            if rolle not in ("user", "assistant") or not text or text.startswith("("):
                continue
            out.append({"role": "agent" if rolle == "assistant" else "user",
                        "message": text, "timeInCallSecs": 0})
    if not dauer:
        try:
            start = datetime.fromisoformat(_s(sit.get("startedAt")))
            dauer = max(0, int((datetime.now(start.tzinfo) - start).total_seconds()))
        except (ValueError, TypeError):
            dauer = 0
    return out, dauer


def call_abschliessen(sit: dict) -> None:
    """Nach dem Auflegen (hangup-Nacharbeit, laeuft schon im Daemon-Thread):
    phase=post (Status -> callCompleted, Transkript, Dauer) und
    phase=analysis (Zusammenfassung im Terminpopup-Stil). Nie werfend —
    der Anruf-Pfad und die uebrige Nacharbeit leiden nie."""
    try:
        pcid = _s(sit.get("phoneCallId"))
        t = sit.get("tenant") or {}
        client_id = _s(t.get("clientId"))
        location_id = _s(t.get("locationId"))
        if not (enabled() and pcid and client_id and location_id):
            return
        transcript, dauer_s = _cf_transkript(sit)
        kategorien = _cf_kategorien(sit)
        basis = {"phoneCallId": pcid, "clientId": client_id,
                 "locationId": location_id}
        # W-CALLAUDIO: der komplette Anruf als MP3 in den Firebase Storage —
        # die Download-URL laesst den Abspiel-Knopf der Portal-CallR-Seite
        # wieder spielen (frueher setzte die ElevenLabs-CF diese URL).
        from kern import anrufaudio
        audio_url = anrufaudio.hochladen(sit)
        post_body = {**basis, "phase": "post", "transcript": transcript,
                     "callDurationSecs": dauer_s, "endReason": "hangup",
                     "categories": kategorien}
        if audio_url:
            post_body["audioRecordingUrl"] = audio_url
        post = _cf_senden(post_body)
        # Zusammenfassung + Bewertung wie beim alten phone_agent: LLM-Analyse
        # (lokales vLLM), harte + weiche Kategorien gemergt (eigene Kopie —
        # der post-Payload behaelt die harten), deterministischer Rueckfall.
        analyse = _analyse_llm(transcript)
        gemergt = list(kategorien)
        weich = analyse.get("categories")
        for k in (weich if isinstance(weich, list) else []):
            if k in _KATEGORIEN_ERLAUBT and k not in gemergt:
                gemergt.append(k)
        from kern import gedaechtnis
        summary = _s(analyse.get("summary")) or gedaechtnis.zusammenfassung(sit)
        analysis = _cf_senden({**basis, "phase": "analysis",
                               "summary": summary,
                               "categories": gemergt,
                               "evaluation": _cf_evaluation(sit, analyse)})
        print(f"agentprofil call abgeschlossen phoneCallId={pcid} "
              f"post={'ok' if post else 'FEHLER'} "
              f"analysis={'ok' if analysis else 'FEHLER'} "
              f"dauer={dauer_s}s kategorien={gemergt}", flush=True)
    except Exception as e:
        print(f"agentprofil call-abschluss fail: {type(e).__name__}: {e}", flush=True)
