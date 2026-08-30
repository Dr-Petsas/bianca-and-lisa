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
    return t


def _cf_pre(did: str, caller: str = "") -> dict[str, Any] | None:
    e164 = "+" + tenants.nummer_norm(did)
    call_id = f"bianca-{tenants.nummer_norm(did)}-{int(time.time())}"
    body = {
        "phase": "pre",
        # Die CF verlangt callerPhone zwingend (Patienten-Zuordnung). Die
        # AudioSocket-Bruecke kennt die Anrufernummer nicht — "anonymous"
        # wie bei unterdrueckter Rufnummer: kein Patient matcht, Agent kommt.
        "callerPhone": _s(caller) or "anonymous",
        "calledNumber": e164,
        "callId": call_id,
        "conversationId": call_id,
        "roomName": call_id,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {PHONE_CALL_TOKEN}",
        "x-api-key": PHONE_CALL_TOKEN,
    }
    r = httpx.post(PHONE_CALL_URL, json=body, headers=headers, timeout=WARTE_S)
    if r.status_code < 200 or r.status_code >= 300:
        print(f"agentprofil cf {e164} -> http {r.status_code}: {r.text[:200]}", flush=True)
        return None
    d = r.json()
    return d if isinstance(d, dict) else None


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
                _CACHE[norm] = (time.monotonic(), dict(t) if t else None)
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
