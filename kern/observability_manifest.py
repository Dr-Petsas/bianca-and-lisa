"""PII-freie Funnel-Ereignisse für Reservierung und Terminverwaltung.

Diese Spur ist absichtlich vollständig von ``sit["tools"]`` getrennt.
Erlaubt sind nur feste Kategorien, relative Zeiten, Statuscodes, Laufzeiten
und Zähler. Namen, Rufnummern, IDs, URLs, Tokens, Slot-Zeiten, SMS-Links und
Transkripte können über diese API nicht ins Manifest gelangen.

Notaus: ``OBSERVABILITY_MANIFEST=0``.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

SCHEMA = "pickadoc.observability/v1"
_MAX_EVENTS = 64

_FUNNELS = {"reservation", "verwaltung"}
_PHASES = {
    "reservation": {"create", "bind", "status", "done", "expired", "cleanup"},
    "verwaltung": {
        "identity", "found", "confirmed", "read", "announced", "write",
    },
}
_ROUTES = {
    "none",
    "name_confirm",
    "calendar_day_read",
    "patient_appointments_read",
    "appointment_announcement",
    "cancel_write",
    "move_write",
    "note_write",
}
_OUTCOMES = {
    "started",
    "open",
    "ok",
    "done",
    "expired",
    "found",
    "empty",
    "not_found",
    "ambiguous",
    "confirmed",
    "announced",
    "rejected",
    "write_ok",
    "write_error",
    "error",
    "cleanup_ok",
    "unknown",
}
_ERRORS = {
    "none",
    "network",
    "timeout",
    "not_found",
    "conflict",
    "upstream",
    "invalid_response",
    "rejected",
    "unknown",
}
_SOURCES = {
    "none",
    "patientId",
    "telefon",
    "name60",
    "nameExact",
    "name_unter60",
    "identitaet_widerspruch",
    "no_detail",
    "name_required",
    "unknown",
}
_EVENT_KEYS = {
    "phase",
    "offsetMs",
    "httpStatus",
    "durationMs",
    "routeClass",
    "outcome",
    "errorClass",
    "source",
    "candidateCount",
}


def an() -> bool:
    return (os.getenv("OBSERVABILITY_MANIFEST", "1") or "1").strip().lower() not in {
        "0", "false", "off", "no",
    }


def _offset_ms(sit: dict) -> int:
    try:
        start = datetime.fromisoformat(str(sit.get("startedAt") or ""))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        return max(
            0,
            int((datetime.now(timezone.utc) - start.astimezone(timezone.utc)).total_seconds() * 1000),
        )
    except (TypeError, ValueError):
        return 0


def _int(v: Any, *, minimum: int = 0, maximum: int = 2_147_483_647) -> int | None:
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return None
    return max(minimum, min(maximum, n))


def _enum(v: Any, erlaubt: set[str], fallback: str) -> str:
    text = str(v or "").strip()
    return text if text in erlaubt else fallback


def _status_fehler(status: int | None) -> str:
    if status is None or status == 0:
        return "network"
    if status == 404:
        return "not_found"
    if status == 409:
        return "conflict"
    if status >= 500:
        return "upstream"
    if status >= 400:
        return "rejected"
    return "none"


def emit(
    sit: dict,
    funnel: str,
    phase: str,
    *,
    dispatch: dict | None = None,
    route_class: str = "none",
    outcome: str = "unknown",
    error_class: str = "",
    source: str = "none",
    candidate_count: int | None = None,
    http_status: int | None = None,
    duration_ms: int | float | None = None,
) -> dict:
    """Ein Ereignis über eine harte Allowlist an die Sitzung hängen."""
    if not an() or funnel not in _FUNNELS or phase not in _PHASES[funnel]:
        return {}
    d = dispatch if isinstance(dispatch, dict) else {}
    status = _int(http_status if http_status is not None else d.get("httpStatus"), maximum=599)
    dauer = _int(duration_ms if duration_ms is not None else d.get("ms"), maximum=3_600_000)
    fehler = error_class or (_status_fehler(status) if outcome in {"error", "write_error"} else "none")
    event: dict[str, Any] = {
        "phase": phase,
        "offsetMs": _offset_ms(sit),
        "routeClass": _enum(route_class, _ROUTES, "none"),
        "outcome": _enum(outcome, _OUTCOMES, "unknown"),
        "errorClass": _enum(fehler, _ERRORS, "unknown"),
    }
    if status is not None:
        event["httpStatus"] = status
    if dauer is not None:
        event["durationMs"] = dauer
    safe_source = _enum(source, _SOURCES, "unknown")
    if safe_source != "none":
        event["source"] = safe_source
    count = _int(candidate_count, maximum=10_000)
    if count is not None:
        event["candidateCount"] = count

    root = sit.setdefault("observability", {"schema": SCHEMA})
    if not isinstance(root, dict):
        root = {"schema": SCHEMA}
        sit["observability"] = root
    root["schema"] = SCHEMA
    events = root.setdefault(funnel, [])
    if not isinstance(events, list):
        events = []
        root[funnel] = events
    # Doppelte terminale Beobachtungen desselben Zugs bringen keinen Wert.
    if events and all(
        events[-1].get(k) == event.get(k)
        for k in ("phase", "outcome", "routeClass", "source", "candidateCount")
    ):
        return event
    events.append(event)
    root[funnel] = events[-_MAX_EVENTS:]
    return event


def export(sit: dict) -> dict:
    """Sitzungsspur erneut allowlisten; sicher für ``anruf.json``."""
    raw = sit.get("observability")
    if not an() or not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {"schema": SCHEMA}
    for funnel in sorted(_FUNNELS):
        sauber: list[dict[str, Any]] = []
        for item in raw.get(funnel) or []:
            if not isinstance(item, dict):
                continue
            phase = _enum(item.get("phase"), _PHASES[funnel], "")
            if not phase:
                continue
            event = {k: item[k] for k in _EVENT_KEYS if k in item}
            event["phase"] = phase
            event["offsetMs"] = _int(event.get("offsetMs")) or 0
            event["routeClass"] = _enum(event.get("routeClass"), _ROUTES, "none")
            event["outcome"] = _enum(event.get("outcome"), _OUTCOMES, "unknown")
            event["errorClass"] = _enum(event.get("errorClass"), _ERRORS, "unknown")
            if "source" in event:
                event["source"] = _enum(event["source"], _SOURCES, "unknown")
            for key, maximum in (
                ("httpStatus", 599),
                ("durationMs", 3_600_000),
                ("candidateCount", 10_000),
            ):
                if key in event:
                    value = _int(event[key], maximum=maximum)
                    if value is None:
                        event.pop(key, None)
                    else:
                        event[key] = value
            sauber.append(event)
        if sauber:
            out[funnel] = sauber[-_MAX_EVENTS:]
    return out if len(out) > 1 else {}
