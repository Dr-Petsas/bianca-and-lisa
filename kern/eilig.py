"""Dringender Termin und Melanom: heute buchen, sonst sofort kommen.

Live Blessing 21.09.2026 (eb85f827): Der Patient wollte einen neuen,
dringenden Termin nach ausgefallenem Juli-Termin. Bianca hoerte Absage,
buchte Kontrolle im Dezember und ignorierte den Melanom-Verdacht.

Regel:
- Lebensgefahr bleibt 112 (praxisregeln).
- Melanom / Hautkrebsverdacht ist immer eilig.
- „Ich brauche dringend einen Termin“ ist eilig, wenn die Praxis den
  Sofort-Komme-Weg fuehrt (Blessing-Marker oder Anliegen-Wahl sofort).
- Zuerst heutige Slots anbieten. Ist keiner frei: kommen, Wartezeit
  mitbringen — kein Dezember, kein Rueckruf.
- „den ich absagen musste … jetzt einen neuen Termin“ ist Neubuchung,
  keine Absage.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Berlin")

_MELANOM_RE = re.compile(
    r"\bmelanom\w*|\bmelanoma\w*|"
    r"verdacht\s+auf\s+(?:ein(?:en)?\s+)?(?:haut)?krebs|"
    r"(?:haut)?krebsverdacht|"
    r"schwarzer?\s+hautkrebs",
    re.I,
)
_DRINGEND_TERMIN_RE = re.compile(
    r"(?:ziemlich\s+|sehr\s+|jetzt\s+|ganz\s+)?"
    r"(?:dringend\w*|eilig)"
    r"[^.!?]{0,48}\btermin\w*"
    r"|\btermin\w*[^.!?]{0,48}"
    r"(?:dringend\w*|eilig|heute\s+noch|so\s+schnell)"
    r"|heute\s+unbedingt[^.!?]{0,24}\btermin",
    re.I,
)
_ABSAGE_JETZT_RE = re.compile(
    r"(?:termin\w*|ihn|den)\s+[^.!?]{0,40}?\b(?:jetzt|bitte|doch|gleich)\s+"
    r"(?:absag|stornier)|"
    r"\b(?:absag|stornier)\w*[^.!?]{0,24}\bjetzt\b",
    re.I,
)
_NEU_TERMIN_RE = re.compile(
    r"neuen?\s+termin|"
    r"jetzt\s+(?:bitte\s+ich\s+um|brauch\w*|m(?:ö|oe)chte)\s+"
    r"(?:einen?\s+)?(?:neuen?\s+)?termin|"
    r"keinen\s+termin\s+absag|"
    r"nicht\s+(?:absag|stornier)",
    re.I,
)
_ABSAGE_VERGANGEN_RE = re.compile(
    r"absagen\s+musste|absagen\s+mussten|"
    r"abgesagt\s+(?:wegen|hatte|worden|werden)|"
    r"abgesagt\s+werden\s+musste|"
    r"(?:termin\w*|er|sie)\s+[^.!?]{0,24}ausgefallen|"
    r"ausgefallen\s+ist",
    re.I,
)
KOMMEN_SATZ = (
    "Das klingt akut. Kommen Sie bitte jetzt direkt in die Praxis. "
    "Eine feste Uhrzeit gibt es dafür nicht — bringen Sie bitte "
    "Wartezeit mit. Sie werden so schnell wie möglich gesehen."
)


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def heute_iso() -> str:
    return datetime.now(TZ).date().isoformat()


def melanom(text: str) -> bool:
    return bool(_MELANOM_RE.search(_s(text)))


def dringender_termin(text: str) -> bool:
    t = _s(text)
    if not t:
        return False
    if _ABSAGE_JETZT_RE.search(t) and not _NEU_TERMIN_RE.search(t):
        return False
    return bool(_DRINGEND_TERMIN_RE.search(t) or melanom(t))


def vergangene_absage_plus_neubuchung(text: str) -> bool:
    """Alte Absage + Wunsch nach neuem Termin — nie als Storno deuten."""
    t = _s(text)
    if not t:
        return False
    if _ABSAGE_JETZT_RE.search(t) and not _NEU_TERMIN_RE.search(t):
        return False
    return bool(_ABSAGE_VERGANGEN_RE.search(t) and _NEU_TERMIN_RE.search(t))



_NICHT_KOMMEN_RE = re.compile(r"\bnicht\s+kommen\b", re.I)
_TERMIN_MACHEN_RE = re.compile(
    r"\btermin\w*\b[^.!?]{0,48}\b(?:ausmachen|vereinbaren|buchen|machen)\b|"
    r"\b(?:ausmachen|vereinbaren|buchen)\b[^.!?]{0,32}\btermin\w*\b",
    re.I,
)
_ECHTE_ABSAGE_RE = re.compile(
    r"\b(?:absag|stornier|abbestell|cancel)\w*",
    re.I,
)
_NAECHSTER_SLOT_RE = re.compile(
    r"so\s+bald|baldm(?:ö|oe)glichst|"
    r"n(?:ä|ae)chstm(?:ö|oe)glich|"
    r"sehr\s+sp(?:ä|ae)t|\bkeines\b|\bkeins\b|\bkeiner\b",
    re.I,
)


def nicht_kommen_will_termin(text: str) -> bool:
    """„Kann jetzt nicht kommen, einen Termin ausmachen“ ist eine Neubuchung."""
    t = _s(text)
    if not t or _ECHTE_ABSAGE_RE.search(t):
        return False
    return bool(_NICHT_KOMMEN_RE.search(t) and _TERMIN_MACHEN_RE.search(t))


def will_naechsten_slot(text: str) -> bool:
    """Angebot zu spät oder ausdrücklich der nächste freie Termin."""
    return bool(_NAECHSTER_SLOT_RE.search(_s(text)))


def _sofort_praxis(tenant: dict | None) -> bool:
    from kern import praxisregeln
    if praxisregeln.notfall_sofort_aktiv(tenant):
        return True
    try:
        from kern import anliegen_zug
        r = anliegen_zug.regel_fuer(tenant, "notfall")
    except Exception:
        r = None
    return bool(r is not None and r.wahl == "sofort")


def erkannt(text: str, tenant: dict | None = None) -> bool:
    t = _s(text)
    if not t:
        return False
    if melanom(t):
        return True
    if not dringender_termin(t):
        return False
    return _sofort_praxis(tenant)


def aktiv(sit: dict | None) -> bool:
    return bool(sit and sit.get("eiligHeute"))


def merken(sit: dict, text: str = "") -> bool:
    """Eilig-Flag setzen, sobald Melanom oder dringender Termin faellt."""
    tenant = sit.get("tenant") if isinstance(sit.get("tenant"), dict) else {}
    if erkannt(text, tenant) or aktiv(sit):
        sit["eiligHeute"] = True
        return True
    s = sit.get("sammler") if isinstance(sit.get("sammler"), dict) else {}
    gebuendelt = " ".join(
        _s(s.get(k)) for k in ("grund", "grundWortlaut", "motivName")
    )
    if erkannt(gebuendelt, tenant):
        sit["eiligHeute"] = True
        return True
    return False


def wunsch_heute(sit: dict) -> dict[str, Any]:
    return {"date": heute_iso(), "minDaysAhead": 0}


def slots_heute(vorrat: list) -> list:
    tag = heute_iso()
    jetzt = datetime.now(TZ)
    out = []
    for v in vorrat or []:
        if isinstance(v, dict):
            iso = str(v.get("iso") or v.get("start") or "")
        else:
            iso = str(v)
        if not iso.startswith(tag):
            continue
        try:
            dt = datetime.fromisoformat(iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=TZ)
            if dt <= jetzt:
                continue
        except ValueError:
            pass
        out.append(v)
    return out


def kommen_satz(tenant: dict | None = None) -> str:
    try:
        from kern import anliegen_zug
        r = anliegen_zug.regel_fuer(tenant, "notfall")
        if r is not None and r.wahl == "sofort":
            satz = anliegen_zug.satz(r, tenant)
            if satz:
                return satz
    except Exception:
        pass
    return KOMMEN_SATZ


def kommen_reply(sit: dict) -> dict[str, Any]:
    s = sit.setdefault("sammler", {})
    if isinstance(s, dict):
        s["phase"] = "fertig"
        s["frage"] = ""
        s["buchIntent"] = False
        s["slotIso"] = ""
    sit["offered"] = []
    sit["slotVorrat"] = []
    sit["eiligKomme"] = True
    return {"text": kommen_satz(sit.get("tenant")), "hangup": True}
