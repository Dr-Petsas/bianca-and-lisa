"""Ausgehende Gespräche — eine Karte, ein Gedächtnis-Eintrag.

Chef 30.08.2026: Aufzeichnung in Campaignr-Monitor UND Lisa-Ausgang zeigen,
ins Praxisgedächtnis aber nur einmal (Event-Id telefonki:lisa_call:{sid}).
"""

from __future__ import annotations

from typing import Any

from kern import gedaechtnis
from lisa import session


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def gedaechtnis_id(sit: dict) -> str:
    return _s(sit.get("gedaechtnisId")) or f"telefonki:lisa_call:{_s(sit.get('id'))}"


def transcript(sit: dict) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for z in sit.get("zuege") or []:
        if not isinstance(z, dict):
            continue
        if _s(z.get("textIn")):
            out.append({"role": "user", "message": _s(z.get("textIn")), "audioUrl": ""})
        if _s(z.get("text")):
            out.append({
                "role": "agent",
                "message": _s(z.get("text")),
                "audioUrl": _s(z.get("audioUrl")),
            })
    return out


def karte(sit: dict) -> dict[str, Any]:
    pat = sit.get("patient") or {}
    km = sit.get("kampagne") or {}
    zuege = sit.get("zuege") or []
    hat_user = any(_s(z.get("textIn")) for z in zuege if isinstance(z, dict))
    gid = gedaechtnis_id(sit)
    return {
        "sessionId": _s(sit.get("id")),
        "startedAt": _s(sit.get("startedAt")),
        "patientName": _s(pat.get("name")) or f"{_s(pat.get('firstName'))} {_s(pat.get('lastName'))}".strip(),
        "patientId": _s(pat.get("id")),
        "phone": _s(pat.get("phone") or pat.get("devPhoneRaw") or pat.get("devPhone")),
        "auftrag": _s(sit.get("auftrag")),
        "probe": bool(sit.get("probe")),
        "campaignId": _s(km.get("campaignId") or km.get("kampagneId")),
        "summary": gedaechtnis.zusammenfassung(sit) if hat_user else "",
        "gedaechtnisId": gid,
        "transcript": transcript(sit),
        "hasAudio": any(_s(z.get("audioUrl")) for z in zuege if isinstance(z, dict)),
        "outcome": "reached" if hat_user else ("" if zuege else "queued"),
    }


def _alle() -> list[dict]:
    gesehen: set[str] = set()
    out: list[dict] = []
    for sit in list(session._STORE.values()):
        sid = _s(sit.get("id"))
        if not sid or sid in gesehen:
            continue
        gesehen.add(sid)
        out.append(sit)
    try:
        for pfad in session._SESS_DIR.glob("*.json"):
            sid = pfad.stem
            if sid in gesehen:
                continue
            sit = session.holen(sid)
            if sit:
                gesehen.add(sid)
                out.append(sit)
    except OSError:
        pass
    out.sort(key=lambda s: _s(s.get("startedAt")), reverse=True)
    return out


def liste(*, patient_id: str = "", phone: str = "", campaign_id: str = "",
          auch_probe: bool = False) -> list[dict[str, Any]]:
    pid = _s(patient_id)
    tel = "".join(c for c in _s(phone) if c.isdigit())
    kid = _s(campaign_id)
    karten = []
    for sit in _alle():
        if sit.get("probe") and not auch_probe:
            continue
        k = karte(sit)
        if pid and k["patientId"] != pid:
            continue
        if tel:
            hat = "".join(c for c in k["phone"] if c.isdigit())
            if hat and not (hat.endswith(tel[-7:]) or tel.endswith(hat[-7:])):
                continue
            if not hat:
                continue
        if kid and k["campaignId"] != kid:
            continue
        karten.append(k)
    return karten


def holen(session_id: str) -> dict[str, Any] | None:
    sit = session.holen(session_id)
    if not sit:
        return None
    return karte(sit)
