"""Online-Buchungslink als Fallback (W-ONLINE-FALLBACK 26.09.2026).

Chef 26.09.2026 (woertlich): "wenn der name mehr als 3 mal hin und her
korrigiert wird sollt bianca anbieten das ganze online abzuschliessen, weil
zu viele nebengeraeusche in der leitung hier hinderlich sind. die rufnummer
an die die sms gehen soll, soll dabei NICHT erfragt sondern erkannt werden.
es ist eigentlich nur der online buchungslink zu senden.... der bei jedem
Kunden hinterlegt ist. aber erklaeren muss sie das freundlich."

Greift NUR waehrend einer BUCHUNG, wenn das Namensfeld sein Frage-Budget
(kern/frage_budget) erschoepft hat UND eine echte Mobilnummer ERKANNT ist
(Anrufer-ID/Akte ueber ``namenslink.handy`` — nie erfragt). Dann schickt
Bianca per Cloud Function ``agentNameConfirm`` (action ``booking-link``) den
bei jedem Kunden hinterlegten Online-Buchungslink per SMS und schliesst das
Gespraech freundlich ab. KEINE Rueckrufe (Chef: "Rueckrufe nur wenn der job
nicht erledigt werden konnte, totale Ausnahme").

Bianca-frei: keine Importe aus ``bianca/``. Notaus: ``ONLINE_FALLBACK=0``.
"""

from __future__ import annotations

import os
from typing import Any

from kern import namenslink, patients, sitzung
from kern.calendar import _cf_call


# Namensfelder, deren Budget-Erschoepfung den Online-Fallback ausloest.
NAME_FELDER = {"name", "nachname", "nachname_korr", "vorname", "buchstabieren"}


def _s(v: Any) -> str:
    return str(v or "").strip()


def aktiv() -> bool:
    return (os.getenv("ONLINE_FALLBACK", "1") or "1").strip().lower() not in {
        "0", "false", "off", "no",
    }


def erkannte_handy(sit: dict) -> str:
    """Erkannte Mobilnummer (Anrufer-ID/Akte) — nie erfragt."""
    return namenslink.handy(sit)


def bereits_gesendet(sit: dict) -> bool:
    beleg = sit.get("onlineBuchungslink")
    if isinstance(beleg, dict):
        return bool(beleg.get("ok") or beleg.get("gesendet"))
    return bool(beleg)


def greift(sit: dict, frage_id: str) -> bool:
    """True, wenn nach Namens-Budget-Erschoepfung der Online-Link greifen soll."""
    if not aktiv():
        return False
    if _s(frage_id) not in NAME_FELDER:
        return False
    s = sit.get("sammler") if isinstance(sit.get("sammler"), dict) else {}
    if _s(s.get("modus")) not in {"", "buchen"}:
        return False
    if bereits_gesendet(sit):
        return False
    return bool(erkannte_handy(sit))


TEXT_OK = (
    "Die Verbindung rauscht gerade ziemlich, da verstehe ich Ihren Namen "
    "nicht sicher — und ich moechte nichts Falsches eintragen. Ich schicke "
    "Ihnen deshalb einfach den Link zur Online-Buchung per SMS. Dort koennen "
    "Sie Ihren Termin in Ruhe selbst auswaehlen. Vielen Dank fuer Ihren "
    "Anruf und einen schoenen Tag!"
)

TEXT_FEHLER = (
    "Die Verbindung ist gerade leider sehr schlecht, da bekomme ich Ihren "
    "Namen nicht sicher zusammen. Bitte buchen Sie Ihren Termin in Ruhe "
    "online ueber unsere Webseite oder rufen Sie uns bei besserer "
    "Verbindung noch einmal an. Vielen Dank und einen schoenen Tag!"
)


def senden(sit: dict) -> dict:
    """Online-Buchungslink per SMS an die erkannte Nummer schicken.

    Setzt ``sit['onlineBuchungslink']`` (Abschlussbeleg fuer die
    Fail-Klassifikation) und liefert die Antwort fuer den Zug zurueck:
    ``{"text": ..., "hangup": True, "onlineFallback": True, "ok": bool}``.
    """
    phone = erkannte_handy(sit)
    tenant = sit.get("tenant") if isinstance(sit.get("tenant"), dict) else {}
    dry = bool(tenant.get("_testNoWrite"))
    client_id = _s(tenant.get("clientId"))
    location_id = _s(tenant.get("locationId"))
    if not phone or not client_id or not location_id:
        # Ohne erkannte Nummer/Mandant nie behaupten, etwas geschickt zu haben.
        return {"text": TEXT_FEHLER, "hangup": True,
                "onlineFallback": True, "ok": False}

    status, data, dispatch = _cf_call("agentNameConfirm", {
        "action": "booking-link",
        "clientId": client_id,
        "locationId": location_id,
        "sessionId": _s(sit.get("id") or sit.get("sessionId")),
        "phone": phone,
        "dryRun": dry,
    })
    data = data if isinstance(data, dict) else {}
    url = _s(data.get("url"))
    gesendet = bool(data.get("sent"))
    ok = status == 200 and (gesendet or bool(data.get("dryRun")))

    sit["onlineBuchungslink"] = {
        "ok": ok,
        "gesendet": gesendet,
        "an": phone,
        "url": url,
        "dryRun": bool(data.get("dryRun")),
        "httpStatus": status,
    }
    sitzung.merke_tool(
        sit,
        "online_buchungslink",
        {
            "ok": ok,
            "dispatch": dispatch,
            "note": f"Online-Buchungslink per SMS an {phone}" if ok else "",
        },
        args={"phone": phone, "url": url},
    )
    if not ok:
        return {"text": TEXT_FEHLER, "hangup": True,
                "onlineFallback": True, "ok": False}
    return {"text": TEXT_OK, "hangup": True, "onlineFallback": True,
            "ok": True, "url": url}
