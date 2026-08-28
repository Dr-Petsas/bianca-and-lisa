"""Anrufer-Gedächtnis über Anrufgrenzen hinweg — Bianca (28.08.2026).

Beim Auflegen schreibt die Nacharbeit schon eine Kurzfassung. Die lag bisher
nur am Termin. Hier liegt sie zusätzlich lokal, indexiert nach Handynummer
und Patienten-ID. Der nächste Anruf holt die letzte Fassung in den Prompt
und — sobald die Identität klar ist — in den Mund
(„Sie hatten gestern wegen der Krone angerufen, richtig?").

Dieselbe Philosophie wie der Stille-Wächter: Gehirn an, nie bei null
anfangen — nur über Anrufgrenzen hinweg.

Notaus: ANRUF_GEDAECHTNIS=0.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from kern.config import DATA_DIR, DEV_PHONE
from kern import notes

_TZ = ZoneInfo("Europe/Berlin")
_PFAD = DATA_DIR / "bianca_anruf_gedaechtnis.json"
_MAX_JE = 5
_TAGE = 90
_WO = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")


def enabled() -> bool:
    return os.environ.get("ANRUF_GEDAECHTNIS", "1").strip().lower() not in ("0", "false", "no")


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def _jetzt() -> datetime:
    return datetime.now(_TZ)


def _parse(iso: str) -> datetime | None:
    raw = _s(iso)
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_TZ)
    return dt.astimezone(_TZ)


def handy_kern(raw: str) -> str:
    d = "".join(c for c in str(raw or "") if c.isdigit())
    if d.startswith("00"):
        d = d[2:]
    if d.startswith("49") and len(d) > 10:
        d = d[2:]
    return d.lstrip("0")


def _dev_nummer(raw: str) -> bool:
    a = handy_kern(raw)
    b = handy_kern(DEV_PHONE)
    return bool(a and b and (a == b or a.endswith(b) or b.endswith(a)))


def relativ(iso: str, jetzt: datetime | None = None) -> str:
    """gestern / vorgestern / am Mittwoch / letzte Woche / kürzlich."""
    dt = _parse(iso)
    if not dt:
        return "kürzlich"
    tag = (jetzt or _jetzt()).date()
    d = dt.date()
    delta = (tag - d).days
    if delta <= 0:
        return "heute"
    if delta == 1:
        return "gestern"
    if delta == 2:
        return "vorgestern"
    if delta < 7:
        return f"am {_WO[d.weekday()]}"
    if delta < 14:
        return "letzte Woche"
    return "kürzlich"


def satz_aus(rec: dict, jetzt: datetime | None = None) -> str:
    wann = relativ(_s(rec.get("at")), jetzt)
    grund = _s(rec.get("grund"))
    aktion = _s(rec.get("aktion"))
    if grund:
        kern = f"Sie hatten {wann} wegen {grund} angerufen"
    else:
        kern = f"Sie hatten {wann} schon einmal angerufen"
    if aktion == "vereinbart":
        return kern + " — der Termin steht"
    if aktion == "abgesagt":
        return kern + ", der Termin wurde abgesagt"
    if aktion == "verschoben":
        return kern + ", der Termin wurde verschoben"
    return kern


def prompt_aus(rec: dict, jetzt: datetime | None = None) -> str:
    wann = relativ(_s(rec.get("at")), jetzt)
    name = " ".join(x for x in (_s(rec.get("vorname")), _s(rec.get("nachname"))) if x)
    grund = _s(rec.get("grund"))
    aktion = _s(rec.get("aktion")) or "Gespräch"
    teile = [f"{wann.capitalize()}: {aktion}"]
    if name:
        teile.append(name)
    if grund:
        teile.append(f"wegen {grund}")
    return ", ".join(teile) + "."


def _laden(pfad: Path | None = None) -> dict[str, Any]:
    p = pfad or _PFAD
    try:
        roh = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"byPhone": {}, "byPatient": {}}
    if not isinstance(roh, dict):
        return {"byPhone": {}, "byPatient": {}}
    roh.setdefault("byPhone", {})
    roh.setdefault("byPatient", {})
    return roh


def _schreiben(data: dict, pfad: Path | None = None) -> None:
    p = pfad or _PFAD
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def _sauber(liste: list, jetzt: datetime) -> list:
    grenze = jetzt - timedelta(days=_TAGE)
    out = []
    for rec in liste:
        if not isinstance(rec, dict):
            continue
        dt = _parse(_s(rec.get("at")))
        if dt and dt < grenze:
            continue
        out.append(rec)
    return out[-_MAX_JE:]


def _an_liste(data: dict, bucket: str, key: str, rec: dict, jetzt: datetime) -> None:
    if not key:
        return
    kisten = data.setdefault(bucket, {})
    alt = kisten.get(key) or []
    if not isinstance(alt, list):
        alt = []
    kisten[key] = _sauber(alt + [rec], jetzt)


def kurzfassung(sit: dict) -> dict[str, Any]:
    """Deterministische Kurzfassung aus dem Sammler — ohne LLM."""
    s = sit.get("sammler") or {}
    phone = _s(s.get("telefon") or s.get("aktePhone") or sit.get("anruferNummer"))
    pid = _s(s.get("patientId") or (sit.get("patient") or {}).get("id"))
    grund = notes.grund_kurz(sit)
    if grund.lower().startswith("wegen "):
        grund = re.sub(r"^(der|die|das|dem|den)\s+", "", grund[6:].strip(), flags=re.I)
        if grund:
            grund = grund[:1].upper() + grund[1:]
    if (sit.get("lastCancel") or {}).get("ok"):
        aktion = "abgesagt"
    elif (sit.get("lastMove") or {}).get("ok"):
        aktion = "verschoben"
    elif (sit.get("lastBook") or {}).get("booked") or (sit.get("lastBook") or {}).get("dryRun"):
        aktion = "vereinbart"
    elif _s(s.get("phase")) == "gebucht":
        aktion = "vereinbart"
    elif grund or _s(s.get("modus")) in {"buchen", "absagen", "verschieben", "auskunft"}:
        aktion = "offen"
    else:
        aktion = ""
    rec = {
        "at": _s(sit.get("startedAt")) or _jetzt().isoformat(),
        "phoneKern": handy_kern(phone),
        "patientId": pid,
        "vorname": _s(s.get("vorname")),
        "nachname": _s(s.get("nachname")),
        "grund": grund,
        "aktion": aktion,
        "sessionId": _s(sit.get("id")),
    }
    rec["satz"] = satz_aus(rec)
    rec["prompt"] = prompt_aus(rec)
    return rec


def lohnt(rec: dict) -> bool:
    """Leere Hallo-und-weg-Anrufe nicht merken."""
    if not rec:
        return False
    if _s(rec.get("grund")) or _s(rec.get("aktion")) in {"vereinbart", "abgesagt", "verschoben"}:
        return True
    if _s(rec.get("patientId")) and _s(rec.get("nachname")):
        return True
    return False


def merken(sit: dict, *, pfad: Path | None = None) -> dict[str, Any]:
    """Hangup-Nacharbeit: Kurzfassung unter Nummer und Patienten-ID ablegen."""
    if not enabled():
        return {}
    rec = kurzfassung(sit)
    if not lohnt(rec):
        return {}
    jetzt = _jetzt()
    data = _laden(pfad)
    if rec.get("patientId"):
        _an_liste(data, "byPatient", rec["patientId"], rec, jetzt)
    kern = rec.get("phoneKern") or ""
    # Geteilte Dev-/Testnummer nicht als Personen-Schlüssel verwenden.
    if kern and not _dev_nummer(kern):
        _an_liste(data, "byPhone", kern, rec, jetzt)
    _schreiben(data, pfad)
    print(f"bianca-gedaechtnis: gemerkt {rec.get('prompt')!r}", flush=True)
    return rec


def holen(*, phone: str = "", patient_id: str = "", pfad: Path | None = None) -> dict[str, Any]:
    """Letzte Kurzfassung zu dieser Nummer oder diesem Patienten."""
    if not enabled():
        return {}
    data = _laden(pfad)
    jetzt = _jetzt()
    kandidaten: list[dict] = []
    pid = _s(patient_id)
    if pid:
        kandidaten.extend(x for x in (data.get("byPatient") or {}).get(pid) or [] if isinstance(x, dict))
    kern = handy_kern(phone)
    if kern and not _dev_nummer(kern):
        kandidaten.extend(x for x in (data.get("byPhone") or {}).get(kern) or [] if isinstance(x, dict))
    if not kandidaten:
        return {}
    kandidaten = _sauber(kandidaten, jetzt)
    if not kandidaten:
        return {}
    rec = max(kandidaten, key=lambda r: _s(r.get("at")))
    # Relativ-Angaben am Abholtag frisch rechnen.
    rec = dict(rec)
    rec["satz"] = satz_aus(rec, jetzt)
    rec["prompt"] = prompt_aus(rec, jetzt)
    return rec


def anbinden(sit: dict, *, phone: str = "", patient_id: str = "") -> dict[str, Any]:
    """Hängt die letzte Kurzfassung an die Sitzung, falls noch keine da ist
    oder die neue spezieller ist (Patienten-ID schlägt reine Nummer)."""
    rec = holen(phone=phone, patient_id=patient_id)
    if not rec:
        return {}
    alt = sit.get("letzterAnruf") or {}
    if alt.get("patientId") and not rec.get("patientId"):
        return alt
    sit["letzterAnruf"] = rec
    return rec
