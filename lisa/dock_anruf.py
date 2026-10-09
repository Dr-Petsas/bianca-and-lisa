"""Echter Lisa-Anruf aus dem Dock (W-LISA-DOCK-ECHT 09.10.2026).

Chef: "ich suche den Patienten, gebe den Prompt ein und Lisa ruft an" — oder
eine frei eingetragene Nummer samt Namen. Gewählt wird über denselben Weg wie
bei der Cloud Function (Call-File auf dem Asterisk, AudioSocket an
sipbridge-lisa). Die Sitzung entsteht erst beim Abheben, mit derselben
Vorbereitung wie das Testgespräch im Browser.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from typing import Any, Callable

from lisa import outbound, tenants

ABBRUCH_SATZ = ("Entschuldigen Sie, ich muss das Gespräch an dieser Stelle leider "
                "beenden. Auf Wiederhören.")

_LAENDER = ("+49", "+43", "+41")
# Die Dock-Adresse ist offen erreichbar: Mehrwert- und Sondernummern kosten pro
# Minute und werden nie gewählt.
_GESPERRT = (
    "+49900", "+49137", "+49138", "+49118", "+49180", "+4919", "+49700",
    "+43900", "+43930", "+43939", "+41900", "+41901", "+41906",
)
_ZIEL_RE = re.compile(r"^\+[1-9]\d{7,14}$")

_LAEUFT = ("waehlt", "klingelt", "verbunden", "beendet_wird")
# Call-File wartet 60 s auf das Abheben — danach gilt der Anruf als verpasst.
_KLINGEL_MAX_S = 90.0
_LAUF_MAX_S = 20 * 60.0

_LOCK = threading.Lock()
_ANRUFE: dict[str, dict[str, Any]] = {}


class Besetzt(Exception):
    """Lisa telefoniert schon — ein Dock-Anruf zur Zeit."""


def _s(v: Any) -> str:
    return str(v or "").strip()


def _key(uid: str) -> str:
    return outbound._uuid_norm(uid)


def ziel(nummer: str) -> str:
    n = tenants.nummer_norm(_s(nummer))
    e = f"+{n}" if n else ""
    if not _ZIEL_RE.match(e):
        raise ValueError("Die Telefonnummer ist nicht vollständig.")
    if not e.startswith(_LAENDER):
        raise ValueError("Lisa ruft nur Nummern in Deutschland, Österreich und der Schweiz an.")
    if e.startswith(_GESPERRT):
        raise ValueError("Sonder- und Mehrwertnummern wählt Lisa nicht.")
    return e


def absender(tenant_id: str) -> str:
    """Erste Praxis-DID — der Angerufene sieht die Praxis und landet beim
    Rückruf bei Bianca."""
    t = tenants.laden(_s(tenant_id)) or {}
    dids = t.get("dids") if isinstance(t.get("dids"), list) else [t.get("did")]
    for did in dids:
        n = tenants.nummer_norm(_s(did))
        if n:
            return f"+{n}"
    return ""


def _frisch(e: dict[str, Any]) -> dict[str, Any]:
    if e.get("status") == "klingelt" and time.time() - float(e.get("ts") or 0) > _KLINGEL_MAX_S:
        e["status"] = "nicht_erreicht"
    return e


def _laeuft() -> bool:
    jetzt = time.time()
    for e in _ANRUFE.values():
        _frisch(e)
        if e.get("status") in _LAEUFT and jetzt - float(e.get("ts") or 0) < _LAUF_MAX_S:
            return True
    return False


def waehlen(*, tenant_id: str, auftrag: str, patient: dict[str, Any], nummer: str,
            dial: Callable[[dict[str, Any]], dict[str, Any]] | None = None) -> dict[str, Any]:
    to = ziel(nummer)
    von = absender(tenant_id)
    if not von:
        raise ValueError("Für diese Praxis ist keine Absendernummer eingetragen.")
    t = tenants.laden(_s(tenant_id)) or {}
    pat = dict(patient or {})
    pat["phone"] = to
    meta = {
        "dock": True,
        "tenant": _s(tenant_id),
        "auftrag": auftrag,
        "patient": pat,
        "toE164": to,
        "fromDid": von,
        "clientId": _s(t.get("clientId")),
        "locationId": _s(t.get("locationId")),
    }
    platz = f"w{uuid.uuid4().hex}"
    with _LOCK:
        if _laeuft():
            raise Besetzt("Lisa telefoniert gerade — erst auflegen, dann neu anrufen.")
        _ANRUFE[platz] = {"status": "waehlt", "ts": time.time(), "to": to,
                          "name": _s(pat.get("name")), "sessionId": ""}
    try:
        out = (dial or outbound.dial)(meta)
    except Exception:
        with _LOCK:
            _ANRUFE.pop(platz, None)
        raise
    uid = _key(out.get("uuid") or "")
    with _LOCK:
        e = _ANRUFE.pop(platz, {})
        vorhanden = _ANRUFE.get(uid)
        if vorhanden:
            # Schnell abgehoben: verbunden() war vor uns da.
            e = {**e, **vorhanden}
        else:
            e["status"] = "klingelt"
        e["ts"] = e.get("ts") or time.time()
        _ANRUFE[uid] = e
    return {"ok": True, "uuid": uid, "toE164": to, "fromDid": von}


def verbunden(uid: str, session_id: str) -> None:
    with _LOCK:
        e = _ANRUFE.setdefault(_key(uid), {"ts": time.time()})
        e["status"] = "verbunden"
        e["sessionId"] = session_id
        e["verbundenTs"] = time.time()


def beendet(sit: dict[str, Any]) -> None:
    uid = _s((sit or {}).get("echtUuid"))
    if not uid:
        return
    with _LOCK:
        e = _ANRUFE.get(_key(uid))
        if e:
            e["status"] = "beendet"


def auflegen(uid: str) -> str:
    """Klingelt es noch, wird die Vormerkung verworfen (beim Abheben legt die
    Brücke sofort auf). Läuft das Gespräch, verabschiedet Lisa sich beim
    nächsten Zug."""
    k = _key(uid)
    with _LOCK:
        e = _ANRUFE.get(k)
        if not e:
            return "unbekannt"
        _frisch(e)
        if e.get("status") in ("waehlt", "klingelt"):
            outbound.pending_holen(k)
            e["status"] = "abgebrochen"
        elif e.get("status") == "verbunden":
            e["status"] = "beendet_wird"
        return str(e.get("status") or "")


def abbruch_offen(sit: dict[str, Any]) -> bool:
    uid = _s((sit or {}).get("echtUuid"))
    if not uid:
        return False
    with _LOCK:
        e = _ANRUFE.get(_key(uid))
        return bool(e and e.get("status") == "beendet_wird")


def status(uid: str) -> dict[str, Any] | None:
    with _LOCK:
        e = _ANRUFE.get(_key(uid))
        return dict(_frisch(e)) if e else None


def zuruecksetzen() -> None:
    with _LOCK:
        _ANRUFE.clear()
