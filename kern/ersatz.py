"""Praxis hat storniert: nicht Absage-Fluss, sondern Ersatztermin.

Live Blessing 21.09.2026 (9e10c435): Eine Mitarbeiterin sagte den Termin
ab. Die Anruferin wollte einen neuen — Bianca hoerte jedes „abgesagt“
als Patienten-Storno und suchte nie.

Regel:
- Passive/Praxis-Absage ist nie „ich will stornieren“.
- Nach bestaetigter Identitaet den stornierten Termin vorlesen und
  denselben Rahmen (Arzt, Motiv, Dauer) als Ersatz anbieten.
- Die lebende Terminliste bleibt unangetastet. Vorlage kommt aus
  ``recentCancellations`` der Find-Function.
"""

from __future__ import annotations

import re
from typing import Any

from kern.slots import spoken_slot

_PRAXIS_ABSAGE_RE = re.compile(
    r"(?:wurde|worden)\s+[^.!?]{0,48}abgesagt|"
    r"abgesagt\s+worden|"
    r"(?:die\s+)?(?:praxis|mitarbeiterin|anmeldung|rezeption)\s+"
    r"[^.!?]{0,40}abgesagt|"
    r"(?:von\s+(?:der\s+)?praxis|von\s+ihnen|von\s+einer\s+mitarbeiterin)"
    r"[^.!?]{0,32}abgesagt|"
    r"\bsie\s+haben\s+[^.!?]{0,28}abgesagt|"
    r"\bhaben\s+sie\s+[^.!?]{0,28}abgesagt",
    re.I,
)
_ICH_WILL_ABSAGEN_RE = re.compile(
    r"\bich\s+(?:m(?:ö|oe)chte|will|w(?:ü|ue)rde|bitte)\s+"
    r"(?!nicht\b)[^.!?]{0,28}(?:absag|stornier)|"
    r"\bbitte\s+[^.!?]{0,16}(?:absag|stornier)|"
    r"(?:absag|stornier)\w*\s+(?:sie\s+)?(?:mir\s+)?(?:bitte\s+)?"
    r"(?:den|meinen|ihn)\b",
    re.I,
)
_ERSATZ_WUNSCH_RE = re.compile(
    r"neuen?\s+termin|"
    r"ersatztermin|ersatz\s+termin|"
    r"nicht\s+(?:absag|stornier)|"
    r"(?:will|m(?:ö|oe)chte|brauch\w*)\s+(?:einen?\s+)?termin|"
    r"keinen\s+termin\s+absag",
    re.I,
)

GRUND_LABEL = {
    "absentExcused": "von der Praxis storniert",
    "isDeleted": "im Papierkorb",
    "past": "bereits vorbei",
    "virtual": "virtuell / unbestätigt",
    "none": "kein Termin in der Akte",
    "mixed": "kein kommender Termin",
    "not_found": "Patient nicht gefunden",
}

NICHT_GESEHEN = (
    "Den abgesagten Termin sehe ich hier nicht sicher. "
    "Worum ging es und bei wem — dann suche ich Ihnen einen neuen."
)


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def praxis_hat_abgesagt(text: str) -> bool:
    t = _s(text)
    if not t:
        return False
    if _ICH_WILL_ABSAGEN_RE.search(t) and not _PRAXIS_ABSAGE_RE.search(t):
        return False
    return bool(_PRAXIS_ABSAGE_RE.search(t))


def ersatz_wunsch(text: str) -> bool:
    return bool(_ERSATZ_WUNSCH_RE.search(_s(text)))


def ich_will_absagen(text: str) -> bool:
    return bool(_ICH_WILL_ABSAGEN_RE.search(_s(text)))


def blockiert_absage(text: str) -> bool:
    """Dieser Satz darf den Absage-Fluss nicht oeffnen."""
    t = _s(text)
    if not t:
        return False
    if praxis_hat_abgesagt(t):
        return True
    if ersatz_wunsch(t) and not ich_will_absagen(t):
        if re.search(r"nicht\s+(?:absag|stornier)", t, re.I):
            return True
    return False


def erkannt(text: str) -> bool:
    return praxis_hat_abgesagt(text) or blockiert_absage(text)


def merken(sit: dict, text: str = "") -> bool:
    if erkannt(text) or sit.get("praxisAbsage"):
        sit["praxisAbsage"] = True
        if ersatz_wunsch(text) or praxis_hat_abgesagt(text):
            sit["ersatzSuche"] = True
        return True
    return False


def aktiv(sit: dict | None) -> bool:
    return bool(sit and (sit.get("ersatzSuche") or sit.get("praxisAbsage")))


def _identitaet_steht(sit: dict) -> bool:
    s = sit.get("sammler") if isinstance(sit.get("sammler"), dict) else {}
    if _s(s.get("anruferCheck")) == "ja":
        return True
    if _s(s.get("patientId")) and _s(s.get("nachname")):
        return True
    return False


def suche_faellig(sit: dict) -> bool:
    if not aktiv(sit) or sit.get("ersatzGesucht"):
        return False
    if sit.get("ersatzPin") or sit.get("ersatzLeer"):
        return False
    s = sit.get("sammler") if isinstance(sit.get("sammler"), dict) else {}
    if _s(s.get("modus")) not in {"", "buchen", "absagen"}:
        return False
    if _s(s.get("frage")) in {"anrufer_check", "fuer_wen_check"}:
        return False
    return _identitaet_steht(sit)


def grund_text(code: str) -> str:
    return GRUND_LABEL.get(_s(code), "kein kommender Termin")


def _liste(res: dict | None) -> list[dict[str, Any]]:
    if not isinstance(res, dict):
        return []
    raw = res.get("recentCancellations")
    if not isinstance(raw, list):
        d = res.get("dispatch") if isinstance(res.get("dispatch"), dict) else {}
        resp = d.get("response") if isinstance(d.get("response"), dict) else {}
        raw = resp.get("recentCancellations")
    aus: list[dict[str, Any]] = []
    for a in raw or []:
        if isinstance(a, dict) and _s(a.get("appointmentId") or a.get("id")):
            aus.append(a)
    return aus


def grund_von(res: dict | None) -> str:
    if not isinstance(res, dict):
        return ""
    code = _s(res.get("noUpcomingReason"))
    if code:
        return code
    d = res.get("dispatch") if isinstance(res.get("dispatch"), dict) else {}
    resp = d.get("response") if isinstance(d.get("response"), dict) else {}
    return _s(resp.get("noUpcomingReason") or resp.get("status"))


def aufnehmen(sit: dict, res: dict | None) -> list[dict[str, Any]]:
    sit["ersatzGesucht"] = True
    sit["noUpcomingReason"] = grund_von(res)
    cancels = _liste(res)
    sit["recentCancellations"] = cancels
    if not cancels:
        sit["ersatzLeer"] = True
    return cancels


def bestaetigen_frage(termin: dict) -> str:
    iso = _s(termin.get("start") or termin.get("iso"))
    wann = spoken_slot(iso) if iso else _s(termin.get("appointmentDate"))
    arzt = _s(termin.get("doctorName"))
    grund = _s((termin.get("visitMotive") or {}).get("name") or termin.get("motivName"))
    teile = ["Ich sehe:"]
    if grund:
        teile.append(f"Ihre {grund}")
    else:
        teile.append("Ihr Termin")
    if wann:
        teile.append(wann)
    if arzt:
        teile.append(f"bei {arzt}")
    teile.append("wurde abgesagt. Soll ich Ihnen dafür einen Ersatz suchen?")
    return " ".join(teile)


def annehmen(sit: dict, termin: dict | None = None) -> dict[str, Any]:
    pin = dict(termin or {})
    if not pin:
        raw = sit.get("recentCancellations") or []
        pin = dict(raw[0]) if raw and isinstance(raw[0], dict) else {}
    sit["ersatzPin"] = pin
    sit["ersatzLeer"] = False
    s = sit.setdefault("sammler", {})
    if not isinstance(s, dict):
        return pin
    s["modus"] = "buchen"
    s["frage"] = ""
    s["phase"] = ""
    vm = pin.get("visitMotive") if isinstance(pin.get("visitMotive"), dict) else {}
    mid = _s(vm.get("id") or pin.get("motivId"))
    mname = _s(vm.get("name") or pin.get("motivName"))
    if mid:
        s["motivId"] = mid
    if mname:
        s["motivName"] = mname
        if not _s(s.get("grund")):
            s["grund"] = mname
    cal = _s(pin.get("calendarId"))
    arzt = _s(pin.get("doctorName"))
    if cal:
        alt = s.get("arzt") if isinstance(s.get("arzt"), dict) else {}
        s["arzt"] = {
            **alt,
            "calendarId": cal,
            "calendarName": arzt or _s(alt.get("calendarName")),
            "typ": "ersatz",
        }
    return pin


def ablehnen(sit: dict) -> None:
    sit.pop("ersatzPin", None)
    sit["ersatzSuche"] = False
    s = sit.get("sammler") if isinstance(sit.get("sammler"), dict) else {}
    if isinstance(s, dict) and _s(s.get("frage")) == "ersatz_check":
        s["frage"] = ""


def modus_buchen(sit: dict) -> None:
    s = sit.setdefault("sammler", {})
    if not isinstance(s, dict):
        return
    if _s(s.get("modus")) in {"", "absagen"}:
        s["modus"] = "buchen"
        s["phase"] = ""
        if _s(s.get("frage")) in {"nachname", "vorname", "buchstabieren"}:
            s["frage"] = ""
