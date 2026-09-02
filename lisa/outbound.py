"""Lisa Outbound (W-LISA-OUT 02.09.2026): Cold-Call ueber Asterisk/Zaluma.

CF schickt DB-Bundle (Agent/Patient/Auftrag/Slots) an POST /api/outbound/dial.
Hier: Pending speichern, Asterisk-Call-File originaten, Bridge holt per
outboundUuid die Session aus dem Pending. Bianca-Inbound unberuehrt.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from kern import agentprofil, tenants
from kern.config import DATA_DIR

_PENDING: dict[str, dict[str, Any]] = {}
_PENDING_DIR = DATA_DIR / "outbound-pending"
_PENDING_TTL_S = 300.0

_OUTBOUND_TOKEN = (os.environ.get("LISA_OUTBOUND_API_TOKEN") or "").strip()
_ASTERISK_SSH = (os.environ.get("ASTERISK_SSH") or "root@87.106.34.137").strip()
_ASTERISK_KEY = (os.environ.get("ASTERISK_SSH_KEY")
                 or "/app/secrets/asterisk-cli-key").strip()
_ASTERISK_PROXY = (os.environ.get("ASTERISK_SSH_PROXY") or "").strip()


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _uuid_norm(u: str) -> str:
    return "".join(c for c in (u or "").lower() if c in "0123456789abcdef")


def _uuid_dashed(hex32: str) -> str:
    h = _uuid_norm(hex32)
    if len(h) != 32:
        raise ValueError("uuid muss 32 Hex-Zeichen haben")
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def token_ok(header_val: str) -> bool:
    """Bearer/x-api-key gegen LISA_OUTBOUND_API_TOKEN. Ohne Token: nur lokal."""
    if not _OUTBOUND_TOKEN:
        return True
    roh = _s(header_val)
    if roh.lower().startswith("bearer "):
        roh = roh[7:].strip()
    return bool(roh) and roh == _OUTBOUND_TOKEN


def _ttl_raumen() -> None:
    jetzt = time.monotonic()
    tot = [k for k, v in _PENDING.items()
           if jetzt - float(v.get("_ts") or 0) > _PENDING_TTL_S]
    for k in tot:
        _PENDING.pop(k, None)
        _datei_weg(k)


def _datei_weg(uid: str) -> None:
    try:
        (_PENDING_DIR / f"{_uuid_norm(uid)}.json").unlink(missing_ok=True)
    except OSError:
        pass


def _datei_schreiben(uid: str, meta: dict[str, Any]) -> None:
    try:
        _PENDING_DIR.mkdir(parents=True, exist_ok=True)
        pfad = _PENDING_DIR / f"{_uuid_norm(uid)}.json"
        roh = {k: v for k, v in meta.items() if not str(k).startswith("_")}
        pfad.write_text(json.dumps(roh, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        print(f"lisa-outbound pending-write fail: {e}", flush=True)


def pending_setzen(uid: str, meta: dict[str, Any]) -> None:
    _ttl_raumen()
    ein = dict(meta)
    ein["_ts"] = time.monotonic()
    _PENDING[_uuid_norm(uid)] = ein
    _datei_schreiben(uid, ein)


def pending_holen(uid: str) -> dict[str, Any] | None:
    """Einmal abholbar (Bridge nach AudioSocket-Connect)."""
    _ttl_raumen()
    key = _uuid_norm(uid)
    hit = _PENDING.pop(key, None)
    if hit is None:
        pfad = _PENDING_DIR / f"{key}.json"
        try:
            hit = json.loads(pfad.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return None
    _datei_weg(key)
    if not isinstance(hit, dict):
        return None
    return {k: v for k, v in hit.items() if not str(k).startswith("_")}


def tenant_von_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """CF-DB-Bundle -> Lisa-Tenant (reuse Biancas tenant_von_pre-Form)."""
    agent = bundle.get("agent") if isinstance(bundle.get("agent"), dict) else {}
    pre: dict[str, Any] = {
        "enabled": True,
        "clientId": _s(bundle.get("clientId")) or _s(agent.get("clientId")),
        "locationId": _s(bundle.get("locationId")) or _s(agent.get("locationId")),
        "phoneCallId": _s(bundle.get("phoneCallId")),
        "agent": agent,
        "calendars": bundle.get("calendars") if isinstance(bundle.get("calendars"), list) else [],
        "visitMotives": bundle.get("visitMotives")
        if isinstance(bundle.get("visitMotives"), list) else [],
        "locationName": _s(bundle.get("locationName") or agent.get("locationName")
                           or agent.get("name")),
    }
    docs = bundle.get("doctors")
    if isinstance(docs, list):
        pre["doctors"] = docs
    elif isinstance(bundle.get("doctor"), dict):
        d = bundle["doctor"]
        name = _s(d.get("fullName") or d.get("name")
                  or f"{d.get('firstName') or ''} {d.get('lastName') or ''}")
        if name:
            pre["doctors"] = [name]

    t = agentprofil.tenant_von_pre(pre, did=_s(bundle.get("fromDid")))
    if not t:
        # Reiner CF-Pfad ohne clientId — trotzdem Session aus Agent bauen.
        t = {
            "_id": f"cf-out-{_s(agent.get('id')) or 'x'}",
            "_quelle": "cf",
            "clientId": _s(bundle.get("clientId")),
            "locationId": _s(bundle.get("locationId")),
            "praxisName": _s(pre.get("locationName")) or _s(agent.get("name")) or "Praxis",
            "telefon": _s(agent.get("phoneNumber")),
            "sprache": _s(agent.get("mainLanguage")) or "de",
            "calendars": pre.get("calendars") or [],
            "visitMotives": pre.get("visitMotives") or [],
        }
        gruss = _s(agent.get("firstMessage"))
        if gruss:
            t["begruessungText"] = gruss
        db = agentprofil.db_prompt_von_agent(agent)
        if db:
            t["dbPrompt"] = db

    # Kampagnen-Override schlaegt Agent-firstMessage.
    if _s(bundle.get("firstMessage")):
        t["begruessungText"] = _s(bundle.get("firstMessage"))
    elif _s(agent.get("firstMessagePersonalized")) and not _s(t.get("begruessungText")):
        t["begruessungText"] = _s(agent.get("firstMessagePersonalized"))

    if not _s(t.get("praxisNameVon")) and _s(t.get("praxisName")):
        t["praxisNameVon"] = f"der {_s(t.get('praxisName'))}"

    doctor = bundle.get("doctor") if isinstance(bundle.get("doctor"), dict) else {}
    if doctor and not _s(t.get("behandler")):
        t["behandler"] = _s(
            doctor.get("fullName") or doctor.get("name")
            or f"{doctor.get('firstName') or ''} {doctor.get('lastName') or ''}"
        )
    cal_id = _s(doctor.get("calendarId") or bundle.get("calendarId"))
    if cal_id:
        t["defaultCalendarId"] = cal_id

    t["_quelle"] = str(t.get("_quelle") or "cf")
    if not str(t["_quelle"]).startswith("cf"):
        t["_quelle"] = "cf"
    return t


def patient_von_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    p = bundle.get("patient") if isinstance(bundle.get("patient"), dict) else {}
    vor = _s(p.get("firstName") or p.get("first_name"))
    nach = _s(p.get("lastName") or p.get("last_name"))
    name = _s(p.get("name") or p.get("fullName") or f"{vor} {nach}")
    out: dict[str, Any] = {
        "id": _s(p.get("id") or p.get("patientId")),
        "firstName": vor,
        "lastName": nach,
        "name": name,
        "gender": _s(p.get("gender") or p.get("geschlecht")),
        "phone": _s(p.get("phone") or p.get("mobilePhoneNumber")
                    or p.get("phoneNumber") or bundle.get("toE164")),
    }
    geb = p.get("birthDate") or p.get("birth_date")
    if geb:
        out["birthDate"] = geb if isinstance(geb, str) else str(geb)
    return out


def auftrag_von_bundle(bundle: dict[str, Any]) -> str:
    a = _s(bundle.get("auftrag") or bundle.get("prompt") or bundle.get("task_prompt"))
    if a:
        return a
    agent = bundle.get("agent") if isinstance(bundle.get("agent"), dict) else {}
    teile = [
        _s(agent.get("rolePrompt")),
        _s(agent.get("specialFeaturesPrompt")),
    ]
    text = "\n".join(x for x in teile if x)
    return text or "Rückruf wegen Terminabsprache."


_E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")


def _e164(num: str) -> str:
    n = tenants.nummer_norm(num)
    if not n:
        return ""
    out = "+" + n
    return out if _E164_RE.match(out) else out  # trotzdem versuchen


def _ssh_cmd(fern: str) -> list[str]:
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
           "-o", "ConnectTimeout=15"]
    if _ASTERISK_KEY and Path(_ASTERISK_KEY).is_file():
        cmd += ["-i", _ASTERISK_KEY]
    if _ASTERISK_PROXY:
        cmd += ["-o", f"ProxyJump={_ASTERISK_PROXY}"]
    cmd += [_ASTERISK_SSH, fern]
    return cmd


def _callfile_inhalt(*, to_e164: str, from_did: str, luuid: str) -> str:
    # PJSIP Direct + AudioSocket nach Answer (Application im Call-File).
    # CallerID = Praxis-DID. UUID mit Bindestrichen fuer AudioSocket().
    zeilen = [
        f"Channel: PJSIP/zaluma-trunk/sip:{to_e164}@vc.zaluma.tel",
        f"CallerID: \"Lisa\" <{from_did}>",
        "MaxRetries: 0",
        "RetryTime: 30",
        "WaitTime: 60",
        "Application: AudioSocket",
        f"Data: {luuid},127.0.0.1:40102",
        f"Setvar: __LUUID={luuid}",
        f"Setvar: __FROMDID={from_did}",
        "Archive: no",
    ]
    return "\n".join(zeilen) + "\n"


def originate(*, to_e164: str, from_did: str, luuid: str) -> None:
    """Schreibt ein Asterisk-Call-File per SSH (AMI nur localhost, kein User)."""
    import base64

    to_e164 = _e164(to_e164)
    from_did = _e164(from_did)
    if not to_e164 or not from_did:
        raise ValueError("toE164/fromDid ungueltig")
    dashed = _uuid_dashed(luuid) if "-" not in luuid else luuid
    inhalt = _callfile_inhalt(to_e164=to_e164, from_did=from_did, luuid=dashed)
    name = f"lisa-out-{_uuid_norm(luuid)}.call"
    b64 = base64.b64encode(inhalt.encode("utf-8")).decode("ascii")
    # /tmp schreiben, chown, dann nach outgoing — Asterisk greift sofort zu.
    remote = (
        f"tmp=$(mktemp /tmp/{name}.XXXXXX) && "
        f"printf '%s' '{b64}' | base64 -d > \"$tmp\" && "
        f"chown asterisk:asterisk \"$tmp\" && chmod 666 \"$tmp\" && "
        f"mv \"$tmp\" /var/spool/asterisk/outgoing/{name}"
    )
    r = subprocess.run(
        _ssh_cmd(remote),
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()[:400]
        raise RuntimeError(f"asterisk originate fail: {err or r.returncode}")


def dial(bundle: dict[str, Any]) -> dict[str, Any]:
    """Pending speichern + Originate. Liefert uuid/phoneCallId."""
    to_e164 = _e164(bundle.get("toE164") or bundle.get("to") or "")
    from_did = _e164(
        bundle.get("fromDid")
        or (bundle.get("agent") or {}).get("phoneNumber")
        or ""
    )
    if not to_e164:
        raise ValueError("toE164 fehlt")
    if not from_did:
        raise ValueError("fromDid / agent.phoneNumber fehlt")
    if not _s(bundle.get("clientId")) and not _s((bundle.get("agent") or {}).get("clientId")):
        raise ValueError("clientId fehlt")

    uid = uuid.uuid4().hex
    meta = dict(bundle)
    meta["toE164"] = to_e164
    meta["fromDid"] = from_did
    meta["uuid"] = uid
    pending_setzen(uid, meta)
    try:
        originate(to_e164=to_e164, from_did=from_did, luuid=uid)
    except Exception:
        pending_holen(uid)  # rollback
        raise
    return {
        "ok": True,
        "uuid": uid,
        "phoneCallId": _s(bundle.get("phoneCallId")),
        "toE164": to_e164,
        "fromDid": from_did,
    }
