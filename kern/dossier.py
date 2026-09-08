"""Sitzungs-Dossier + Talk-Takte in echten Lücken (W-DOSSIER 08.09.2026).

Job bleibt die einzige Stimme für Termine, Namen und Nummern. Talk ist
keine zweite Unterhaltung, sondern eine Schlange kurzer Takte, die Job
zieht, wenn eine Lücke da ist (Hintergrund, Werkzeug, zwischen Pflichtfragen).

Das Dossier sammelt im Hintergrund, was schon da ist — letzter Besuch,
Behandler, MAS-Kontext — und blockiert den Mund nie. Feste Takte, kein
erfundenes Plaudern. Spurwechsel (Kontrolle → Implantat-Besprechung)
schreibt zurück auf den Job, bucht aber nie.

Notaus: TALK_SCHICHT=0 blendet nur die LLM-Talk-Schicht aus; Dossier und
Lücken-Sätze bleiben (sonst fällt der Kartei-Füller wieder auf „Einen Moment.“).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from kern import empfehlungen, fachprofil, motive

LEER: dict[str, Any] = {
    "bereit": False,
    "letzterBesuch": "",
    "letzterGrund": "",
    "letzterArzt": "",
    "calendarId": "",
    "masText": "",
    "masOffen": [],
    "fachtemplate": "allgemein",
    "layers": {},
    "empfehlungen": [],
    "takte": [],
    "gesagt": [],
    "offen": "",
    "spur": "",
}

_KEIN_SATZ = {
    "telefon", "telefon_check", "buchstabieren", "slotwahl",
    "bestaetigung", "arzt_notiz", "arzt_notiz_diktat", "anrufer_check",
}
_KEIN_FRAGE = _KEIN_SATZ | {"arzt_check"}
_PHASE_DICHT = {"angebot", "bestaetigen", "gebucht", "fertig"}
_PZR_RE = re.compile(r"zahnreinigung|prophylaxe|\bpzr\b", re.I)
_AKUT_RE = re.compile(r"schmerz|notfall|\bweh\b|akut", re.I)
_OFFEN_RE = re.compile(r"noch offen|rückruf|rueckruf", re.I)

# Neues Anliegen, nicht der Rückblick auf ein altes Implantat.
_IMPLANT = r"implantat\w*"
_NEU = r"(?:noch\s+(?:ein|eins|eines|mal|einmal)|weiteres|nochmal|erneut|wieder|zweites)"
_WUNSCH = r"(?:brauch\w*|br(?:ä|ae)ucht\w*|m(?:ö|oe)cht\w*|will\b|h(?:ä|ae)tt\w*\s+gern)"
_IMPLANT_NEU_RE = re.compile(
    rf"(?:{_IMPLANT}).{{0,80}}(?:{_NEU}|{_WUNSCH})|"
    rf"(?:{_NEU}|{_WUNSCH}).{{0,40}}(?:{_IMPLANT})",
    re.I,
)


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def von(sit: dict | None) -> dict[str, Any]:
    sit = sit or {}
    d = sit.get("dossier")
    if not isinstance(d, dict):
        d = {
            k: (
                list(v) if isinstance(v, list)
                else dict(v) if isinstance(v, dict)
                else v
            )
            for k, v in LEER.items()
        }
        sit["dossier"] = d
        return d
    for k, v in LEER.items():
        if k not in d:
            d[k] = (
                list(v) if isinstance(v, list)
                else dict(v) if isinstance(v, dict)
                else v
            )
    return d


def _tage(iso: str) -> int:
    tag = _s(iso)[:10]
    if not tag:
        return -1
    try:
        d = datetime.strptime(tag, "%Y-%m-%d").date()
    except ValueError:
        return -1
    return (datetime.now().date() - d).days


def _offen_zeilen(text: str) -> list[str]:
    out: list[str] = []
    for roh in str(text or "").splitlines():
        zeile = _s(roh).lstrip("-").strip()
        if zeile and _OFFEN_RE.search(zeile):
            out.append(zeile[:160])
        if len(out) >= 3:
            break
    return out


def _sammler(sit: dict) -> dict:
    s = sit.get("sammler")
    return s if isinstance(s, dict) else {}


def fuellen(sit: dict | None) -> dict[str, Any]:
    """Fakten aus Kartei + Sammler + MAS zusammenziehen — nie werfend."""
    sit = sit or {}
    d = von(sit)
    s = _sammler(sit)
    k = sit.get("anruferKartei") if isinstance(sit.get("anruferKartei"), dict) else {}
    arzt = s.get("arzt") if isinstance(s.get("arzt"), dict) else {}
    d["letzterBesuch"] = _s(s.get("letzterBesuch")) or _s(k.get("letzterBesuch"))
    d["letzterGrund"] = _s(s.get("letzterGrund")) or _s(k.get("letzterGrund"))
    d["letzterArzt"] = (
        _s(arzt.get("calendarName"))
        or _s(k.get("doctorName") or k.get("calendarName"))
    )
    d["calendarId"] = _s(arzt.get("calendarId")) or _s(k.get("calendarId"))
    d["masText"] = str(sit.get("gedaechtnis") or "").strip()
    d["masOffen"] = _offen_zeilen(d["masText"])
    layers = fachprofil.aktualisieren(sit)
    d["fachtemplate"] = str((layers.get("fach") or {}).get("id") or "allgemein")
    d["layers"] = layers
    d["bereit"] = bool(d["letzterGrund"] or d["letzterArzt"] or d["masText"])
    takte_bauen(sit)
    return d


def verwerfen_anrufer(sit: dict | None) -> None:
    """Identität verneint — Besuch aus der Rufnummer-Kartei darf nicht bleiben."""
    sit = sit or {}
    d = sit.get("dossier")
    if not isinstance(d, dict):
        return
    d["letzterBesuch"] = ""
    d["letzterGrund"] = ""
    d["letzterArzt"] = ""
    d["calendarId"] = ""
    d["masOffen"] = []
    d["takte"] = [t for t in (d.get("takte") or []) if t != "verlauf"]
    d["bereit"] = bool(_s(d.get("masText")))


def takte_bauen(sit: dict | None) -> list[str]:
    """Welche Talk-Takte liegen bereit — ohne sie zu ziehen."""
    sit = sit or {}
    d = von(sit)
    s = _sammler(sit)
    gesagt = [str(x) for x in (d.get("gesagt") or [])]
    if s.get("anruferCheck") or sit.get("anruferHalloGesagt"):
        if "hallo" not in gesagt:
            gesagt.append("hallo")
    if s.get("rueckblick") in {"gefragt", "fertig"} and "verlauf" not in gesagt:
        gesagt.append("verlauf")
    if s.get("pzr") and "pzr" not in gesagt:
        gesagt.append("pzr")
    d["gesagt"] = gesagt
    d["empfehlungen"] = empfehlungen.kandidaten(sit, d)
    d["takte"] = [
        t for t in empfehlungen.legacy_takte(sit, d)
        if t not in gesagt
    ]
    return list(d["takte"])


def ist_luecke(sit: dict | None, *, art: str = "satz") -> bool:
    """Darf Talk / Kartei-Satz jetzt den Mund? Pflicht-Rückfragen nie."""
    sit = sit or {}
    s = _sammler(sit)
    if _s(s.get("phase")) in _PHASE_DICHT:
        return False
    frage = _s(s.get("frage"))
    if art == "frage":
        if frage in _KEIN_FRAGE:
            return False
    elif frage in _KEIN_SATZ:
        return False
    if art == "satz":
        hg = sit.get("hgLaeuft") if isinstance(sit.get("hgLaeuft"), dict) else {}
        if any(hg.get(k) for k in ("kartei", "vorrat", "anruferKartei")):
            return _s(s.get("modus")) == "buchen" or bool(s.get("bekannt"))
        return _s(s.get("modus")) == "buchen"
    return _s(s.get("modus")) == "buchen"


def satz(sit: dict | None) -> str:
    """Feststellung für die Warte-Lücke — nie eine Frage."""
    sit = sit or {}
    if not ist_luecke(sit, art="satz"):
        return ""
    if sit.get("karteiFillerGesagt"):
        return ""
    d = fuellen(sit)
    if "verlauf" in (d.get("gesagt") or []):
        return ""
    s = _sammler(sit)
    if not (s.get("bekannt") or s.get("anruferCheck") == "ja"):
        return ""
    if _AKUT_RE.search(_s(s.get("grund"))):
        return ""
    grund = _s(d.get("letzterGrund"))
    if not grund or _tage(d.get("letzterBesuch") or "") <= 7:
        return ""
    from kern import sprech as _sprech
    grund = _sprech.ohne_krebs(grund)
    n = grund.lower()
    if "kontroll" in n or "krebs" in n:
        kurz = "die Kontrolle"
    elif _PZR_RE.search(n) and motive.fuehrt_pzr(sit):
        kurz = "die Zahnreinigung"
    elif len(grund) > 22:
        kurz = grund[:20].rstrip() + "…"
    else:
        kurz = grund
    text = f"Letztes Mal {kurz} — einen Moment."
    return text if "?" not in text else ""


def naechster_takt(sit: dict | None) -> str:
    takte_bauen(sit)
    d = von(sit or {})
    if not ist_luecke(sit, art="frage"):
        return ""
    takte = d.get("takte") or []
    return str(takte[0]) if takte else ""


def markiere(sit: dict | None, takt: str) -> None:
    if not takt:
        return
    d = von(sit)
    gesagt = [str(x) for x in (d.get("gesagt") or [])]
    if takt not in gesagt:
        gesagt.append(takt)
    d["gesagt"] = gesagt
    d["offen"] = takt
    d["takte"] = [t for t in (d.get("takte") or []) if t != takt]


def spur_signal(text: str) -> str:
    """Neues Job-Anliegen aus einem Talk-Satz — sonst leer."""
    t = _s(text)
    if not t:
        return ""
    if _IMPLANT_NEU_RE.search(t):
        return "implantat"
    if re.search(
        r"(?:zahn)?schien\w*.{0,48}abhol|abhol\w*.{0,48}(?:zahn)?schien|"
        r"narval.{0,32}abhol",
        t, re.I,
    ):
        return "schiene-abhol"
    return ""
