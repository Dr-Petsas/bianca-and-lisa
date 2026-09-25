"""Reservierung für Neupatienten — nur dieser Block, Gesprächsführung bleibt V5.

Neupatienten und unbekannte Dritte bekommen eine Reservierungs-SMS.
Der Kalender trägt bis zur Bestätigung den Vorlagennamen Reservierung SMS.
Der gehörte Name steht als Hinweis in der SMS. Die Leitungshandynummer
wird still übernommen und nicht noch einmal abgefragt.
"""

from __future__ import annotations

from typing import Any

from kern.calendar import _cf_call
from kern.patients import handy_e164, ist_handy_de

PLATZHALTER_VORNAME = "Reservierung"
PLATZHALTER_NACHNAME = "SMS"

_SATZ_SELBST = (
    "Da Sie zum ersten Mal zu uns kommen, schicke ich Ihnen gleich eine SMS "
    "zur Reservierung Ihres Termins. Bitte öffnen Sie die SMS und folgen Sie "
    "dem Link, um Ihre Reservierung zu bestätigen. Die Bestätigung dieses "
    "Termins ist neunzig Minuten lang möglich."
)
_SATZ_DRITTE_REST = (
    "schicke ich Ihnen gleich eine SMS zur Reservierung des Termins. "
    "Bitte öffnen Sie die SMS und folgen Sie dem Link, um die Reservierung "
    "zu bestätigen. Die Bestätigung dieses Termins ist neunzig Minuten "
    "lang möglich."
)


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _sammler(sit: dict) -> dict:
    s = sit.get("sammler")
    return s if isinstance(s, dict) else {}


def anrufer_handy(sit: dict) -> str:
    """Deutsche Mobilnummer, die mit dem Anruf mitkam. Festnetz zählt nicht."""
    anrufer = sit.get("anrufer") if isinstance(sit.get("anrufer"), dict) else {}
    raw = anrufer.get("telefon") or sit.get("callerPhone") or ""
    nr = handy_e164(raw)
    return nr if ist_handy_de(nr) else ""


def bestaetigtes_handy(sit: dict) -> bool | str:
    s = _sammler(sit)
    nr = handy_e164(s.get("telefon") or "")
    if s.get("telefonOk") and ist_handy_de(nr):
        return nr
    return ""


def nummer_still(sit: dict) -> bool:
    """Mitgekommene Handynummer festschreiben. Nichts mehr dazu fragen."""
    nr = anrufer_handy(sit)
    if not nr:
        return False
    s = sit.setdefault("sammler", {})
    if not isinstance(s, dict):
        return False
    # needs_phone an einer BESTANDSAKTE: die Leitung steht noch nicht in
    # der Akte. Still erneut bestätigen bucht denselben Fehlschlag in einer
    # Schleife (Anruf 9057eb03). Neupatient ohne Akte: die erkannte
    # Handynummer IST das SMS-Ziel und wird nicht noch einmal abgefragt.
    if (sit.get("needsPhoneOffen") and not s.get("telefonOk")
            and _s(s.get("patientId"))):
        return False
    schon = handy_e164(s.get("telefon") or "")
    if s.get("telefonOk") and schon and schon != nr and ist_handy_de(schon):
        return True
    s["telefon"] = nr
    s["telefonOk"] = True
    s["telefonBekannt"] = nr
    s["telefonOffen"] = ""
    s["telefonTeil"] = ""
    if s.get("fuerWen"):
        s["smsEmpfaenger"] = "anrufer"
        s["kontaktTelefon"] = nr
    return True


def _neu_oder_unbekannter_dritter(sit: dict) -> bool:
    s = _sammler(sit)
    if s.get("warSchonMal") is False and not s.get("fuerWen"):
        return True
    if s.get("fuerWen") and not _s(s.get("patientId")):
        return True
    return False


def gilt(sit: dict) -> bool:
    """Neupatient oder unbekannter Dritter, und eine SMS-fähige Nummer."""
    if not _neu_oder_unbekannter_dritter(sit):
        return False
    return bool(anrufer_handy(sit) or bestaetigtes_handy(sit))


def kurzfrage(sit: dict) -> tuple[str, str] | None:
    """Neupatient mit erkannter Handynummer: nur kurz den Namen, kein Verhör.

    None = dieser Weg gilt nicht, die normale Kette fragt weiter.
    ("", "") = Name reicht, Buchstabieren, Versicherung und Nummer entfallen.
    """
    if not gilt(sit):
        return None
    nummer_still(sit)
    s = _sammler(sit)
    if not _s(s.get("nachname")):
        return "nachname", "Wie heißen Sie?"
    if not _s(s.get("vorname")):
        return "vorname", "Und der Vorname?"
    s["buchstabiert"] = True
    if not _s(s.get("versicherung")):
        s["versicherung"] = "gesetzlich"
        s["versicherungOk"] = True
    return "", ""


def _dritte_anrede(sit: dict) -> str:
    """Gehörter Name, sonst 'Ihr Sohn' / 'Ihre Tochter'. Nie 'diese Person'."""
    s = _sammler(sit)
    name = " ".join(x for x in (_s(s.get("vorname")), _s(s.get("nachname"))) if x)
    if name:
        return name
    from bianca import gehirn
    return gehirn.fuer_wen_phrase(s)


def erklaerung(sit: dict) -> str:
    if not _sammler(sit).get("fuerWen"):
        return _SATZ_SELBST
    wer = _dritte_anrede(sit)
    kopf = f"Da {wer} zum ersten Mal zu uns kommt, " if wer else "Da es das erste Mal bei uns ist, "
    return kopf + _SATZ_DRITTE_REST


def _zielnummer(sit: dict) -> str:
    return anrufer_handy(sit) or str(bestaetigtes_handy(sit) or "")


def vormerken(sit: dict, ctx: dict) -> bool:
    """SMS-Token anlegen und den Termin als Vorlage buchen.

    Schlägt das Anlegen fehl, bleibt der normale Bestätigungsweg — der
    Anrufer soll nicht mit einem stillen Termin dastehen.
    """
    if not isinstance(ctx, dict):
        return False
    stand = sit.get("reservierung") if isinstance(sit.get("reservierung"), dict) else {}
    if stand.get("token"):
        _platzhalter(ctx)
        ctx["skipConfirmation"] = True
        return True
    if not gilt(sit):
        return False
    phone = _zielnummer(sit)
    s = _sammler(sit)
    first = _s(s.get("vorname"))
    last = _s(s.get("nachname"))
    if sit.get("nameReservierung"):
        first, last = "", ""
    tenant = sit.get("tenant") if isinstance(sit.get("tenant"), dict) else {}
    status, data, _dispatch = _cf_call("agentNameConfirm", {
        "action": "create",
        "clientId": _s(tenant.get("clientId")),
        "locationId": _s(tenant.get("locationId")),
        "sessionId": _s(sit.get("id") or sit.get("sessionId")),
        "phone": phone,
        "firstName": first,
        "lastName": last,
        "dryRun": bool(tenant.get("_testNoWrite")),
    })
    if status != 200 or not isinstance(data, dict) or not data.get("token"):
        return False
    sit["reservierung"] = {
        "token": _s(data.get("token")),
        "url": _s(data.get("url")),
        "phone": phone,
        "firstName": first,
        "lastName": last,
    }
    _platzhalter(ctx)
    ctx["skipConfirmation"] = True
    return True


def _platzhalter(ctx: dict) -> None:
    ctx["firstName"] = PLATZHALTER_VORNAME
    ctx["lastName"] = PLATZHALTER_NACHNAME
    ctx["patientName"] = f"{PLATZHALTER_VORNAME} {PLATZHALTER_NACHNAME}"
    ctx.pop("gender", None)
    ctx.pop("patientId", None)
    for key in ("patientIdBound", "patientIdFirstName", "patientIdLastName"):
        ctx.pop(key, None)


def binden(sit: dict, appointment_id: str, patient_id: str = "") -> None:
    stand = sit.get("reservierung") if isinstance(sit.get("reservierung"), dict) else {}
    token = _s(stand.get("token"))
    aid = _s(appointment_id)
    if not token or not aid:
        return
    _cf_call("agentNameConfirm", {
        "action": "bind",
        "token": token,
        "appointmentId": aid,
        "patientId": _s(patient_id),
        "start": _s(_sammler(sit).get("slotIso")),
    })
    stand["appointmentId"] = aid
    sit["reservierung"] = stand
