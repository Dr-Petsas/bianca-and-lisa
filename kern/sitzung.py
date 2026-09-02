"""Sitzungs-Protokoll, für Lisa und Bianca gleich: Züge und Werkzeug-Spuren.

Reine Dict-Operationen auf der Sitzung — kein Netz, keine Pfade. Die
Ablage (Store, last_call-Datei) bleibt pro Stimme in lisa/session.py bzw.
bianca/session.py, damit sich die beiden Dienste nie in die Quere kommen.
"""

from __future__ import annotations

from typing import Any


def merke_zug(sit: dict[str, Any], **zug: Any) -> None:
    sit.setdefault("zuege", []).append(zug)
    sit["zuege"] = sit["zuege"][-24:]


def _tools_des_zugs(sit: dict[str, Any]) -> list[dict[str, Any]]:
    """Werkzeuge des laufenden Zugs abholen (fuer Antwort + Mitschnitt)."""
    aus = sit.pop("_toolsZug", None) or []
    return [t for t in aus if isinstance(t, dict)]


def merke_tool(sit: dict[str, Any], name: str, result: dict[str, Any],
               *, args: dict[str, Any] | None = None) -> None:
    """Werkzeug-Spur merken — inkl. CF-Dispatch (URL/Body/Response/ms)
    fuer die Unterhaltungs-Anzeige (W-TOOL-UI 02.09.2026)."""
    dispatch = result.get("dispatch") if isinstance(result.get("dispatch"), dict) else None
    ein: dict[str, Any] = {
        "name": name,
        "ok": bool(result.get("ok")),
        "booked": bool(result.get("booked")),
        "dryRun": bool(result.get("dryRun")),
        "slotIso": result.get("slotIso") or "",
        "appointmentId": result.get("appointmentId") or "",
        "patientId": result.get("patientId") or (
            (result.get("patient") or {}).get("id") if isinstance(result.get("patient"), dict) else ""
        ) or "",
        "createdPatient": bool(result.get("createdPatient") or result.get("created")),
        "spoken": result.get("spoken") or "",
        "note": result.get("note") or "",
    }
    if args:
        ein["args"] = args
    if dispatch:
        ein["dispatch"] = {
            "route": dispatch.get("route") or "",
            "url": dispatch.get("url") or "",
            "method": dispatch.get("method") or "POST",
            "request": dispatch.get("request"),
            "httpStatus": dispatch.get("httpStatus"),
            "ms": dispatch.get("ms"),
            "response": dispatch.get("response"),
            "updates": dispatch.get("updates") or [],
        }
        if dispatch.get("route"):
            ein["cf"] = dispatch["route"]
        if dispatch.get("ms") is not None:
            ein["ms"] = dispatch["ms"]
    sit.setdefault("tools", []).append(ein)
    sit["tools"] = sit["tools"][-24:]
    # Pro Zug bundeln — landet in Antwort, Sitzungs-Protokoll und Mitschnitt.
    sit.setdefault("_toolsZug", []).append(ein)
    if name == "create_patient":
        sit["lastCreate"] = {**ein, "created": bool(result.get("created"))}
        if result.get("patient") and isinstance(result.get("patient"), dict):
            sit["patient"] = {**(sit.get("patient") or {}), **result["patient"]}
    if name == "book_slot":
        sit["lastBook"] = ein
        if result.get("appointmentId"):
            sit.setdefault("booking", {})["appointmentId"] = result["appointmentId"]
        if ein.get("createdPatient") and ein.get("patientId"):
            sit["lastCreate"] = {**ein, "created": True}
    elif name == "cancel_appointment":
        sit["lastCancel"] = ein
    elif name == "move_appointment":
        sit["lastMove"] = ein
        if result.get("appointmentId"):
            sit.setdefault("booking", {})["appointmentId"] = result["appointmentId"]
        if result.get("slots"):
            sit["offered"] = result["slots"]
    elif name == "note_appointment":
        sit["lastNote"] = ein
        sit["noteWritten"] = True


def oeffentlich(sit: dict[str, Any]) -> dict[str, Any]:
    pat = sit.get("patient") or {}
    return {
        "sessionId": sit.get("id"),
        "startedAt": sit.get("startedAt"),
        "patientName": pat.get("name") or "",
        "patientId": pat.get("id") or "",
        "auftrag": sit.get("auftrag") or "",
        "tools": sit.get("tools") or [],
        "zuege": sit.get("zuege") or [],
        "lastBook": sit.get("lastBook"),
        "lastCancel": sit.get("lastCancel"),
        "lastMove": sit.get("lastMove"),
        "lastNote": sit.get("lastNote"),
        "lastCreate": sit.get("lastCreate"),
    }
