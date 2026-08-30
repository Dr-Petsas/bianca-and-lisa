from __future__ import annotations

import json
from typing import Any

from kern.config import DEFAULT_TENANT, TENANTS_DIR


def _sauber(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def liste() -> list[dict[str, str]]:
    out = []
    if not TENANTS_DIR.is_dir():
        return out
    for p in sorted(TENANTS_DIR.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        out.append({
            "id": p.stem,
            "clientId": _sauber(d.get("clientId")) or p.stem,
            "praxisName": _sauber(d.get("praxisName")) or p.stem,
        })
    return out


def laden(tenant_id: str = "") -> dict[str, Any]:
    name = _sauber(tenant_id) or DEFAULT_TENANT
    pfad = TENANTS_DIR / f"{name}.json"
    if not pfad.is_file():
        pfad = TENANTS_DIR / f"{DEFAULT_TENANT}.json"
    raw = json.loads(pfad.read_text(encoding="utf-8"))
    raw["_id"] = pfad.stem
    return raw


def von_did(nummer: str) -> dict[str, Any] | None:
    """Mandant zur ANGERUFENEN Nummer (DID) — Vorbereitung fuer das
    SIP-Routing Nummer->Mandant (W-MANDANT-4, 30.08.2026).

    Jeder Tenant kann unter "dids" seine Rufnummern tragen. Verglichen wird
    auf Ziffern (ohne +, Leerzeichen, Klammern) und mit gefalteter deutscher
    Vorwahl: "+49 211 555" und "0211 555" meinen dieselbe Leitung. Kein
    Treffer => None, der Aufrufer faellt auf DEFAULT_TENANT zurueck."""

    def _ziffern(v: Any) -> str:
        return "".join(c for c in str(v or "") if c.isdigit())

    def _kern(z: str) -> str:
        # 00-Prefix (internationale Waehlform) und Landeskennung 49 falten;
        # das len-Guard schuetzt Ortsnetze wie 0491 (Leer) vor Fehlfaltung.
        if z.startswith("00"):
            z = z[2:]
        if z.startswith("49") and len(z) > 9:
            z = z[2:]
        return z.lstrip("0")

    ziffern = _ziffern(nummer)
    if not ziffern:
        return None
    kern = _kern(ziffern)
    for info in liste():
        d = laden(info["id"])
        dids = d.get("dids") if isinstance(d.get("dids"), list) else []
        for did in dids:
            dz = _ziffern(did)
            if not dz:
                continue
            if dz == ziffern or (kern and _kern(dz) == kern):
                return d
    return None


def praxis_melde(tenant: dict[str, Any]) -> str:
    """Name, mit dem sich Bianca beim Abheben meldet (Nominativ, gern kurz).

    Feld ``praxisNameMelde`` — fehlt es, gilt ``praxisName`` wie bisher.
    """
    return _sauber(tenant.get("praxisNameMelde")) or _sauber(tenant.get("praxisName"))


def praxis_von(tenant: dict[str, Any]) -> str:
    """Gebeugte Form fuer "hier ist Lisa von ..." (Chef 29.08.2026).

    Plural-Namen ("Zahnärzte im Medical Center Düsseldorf") brauchen
    "von DEN ZahnärztEN ..." — das kann kein Code raten, darum traegt der
    Mandant die Sprechform selbst (``praxisNameVon``, inkl. Artikel).
    Ohne Feld gilt der alte Weg: "der {praxisName}".
    """
    von = _sauber(tenant.get("praxisNameVon"))
    if von:
        return von
    p = _sauber(tenant.get("praxisName"))
    return f"der {p}" if p else ""


def stt_keywords(tenant: dict[str, Any]) -> list[str]:
    """Einwort-Namen fuer die STT-Nachkorrektur (Behandler des Mandanten).

    Claras Fuzzy-Nachkorrektur (stt_serve/postcorrect.py) arbeitet mit
    Einwort-Keywords ab 4 Zeichen — wir liefern die Behandler-Nachnamen
    ("Petsas", "Nikolaou", "Patrikis"), damit Hoerfehler wie "Betsas" oder
    "Batrikis" schon VOR dem LLM korrigiert werden (Claras Anlaut-Gruppen
    P/B, T/D/Z ...). Bewusst KEINE Marker-Keywords (Heads-up, Teleskopkrone,
    Kons): das Patiententelefon bleibt wie Claras Bianca ohne Phrasen-Fixes.
    """
    kandidaten: list[str] = []
    quellen: list[Any] = [tenant.get("behandler")]
    cals = tenant.get("calendars") if isinstance(tenant.get("calendars"), list) else []
    quellen += [c.get("name") for c in cals if isinstance(c, dict)]
    # Mandanten-Hotwords (z. B. Ueberweiser "Grüger"/"Lange", "Narval"):
    # gleiche Fuzzy-Nachkorrektur wie die Behandler-Namen, rein additiv.
    extra = tenant.get("sttHotwords") if isinstance(tenant.get("sttHotwords"), list) else []
    quellen += [w for w in extra if _sauber(w)]
    for q in quellen:
        for tok in _sauber(q).replace(".", " ").split():
            t = tok.strip("-()")
            if len(t) >= 4 and t.lower() not in {"doktor", "prof", "med", "dent"}:
                kandidaten.append(t[0].upper() + t[1:])
    out: list[str] = []
    for k in kandidaten:
        if k not in out:
            out.append(k)
    return out


def kalender_von(tenant: dict[str, Any], name: str = "") -> dict[str, Any] | None:
    cals = tenant.get("calendars") if isinstance(tenant.get("calendars"), list) else []
    q = _sauber(name).lower()
    if q:
        for c in cals:
            if _sauber(c.get("name")).lower() == q:
                return c
        tokens = [t for t in q.replace(".", " ").split() if t not in {"dr", "doktor", "med"}]
        best, score = None, 0
        for c in cals:
            n = _sauber(c.get("name")).lower()
            s = sum(1 for t in tokens if t and t in n)
            if s > score:
                best, score = c, s
        if best:
            return best
    cid = _sauber(tenant.get("defaultCalendarId"))
    if cid:
        return next((c for c in cals if _sauber(c.get("id")) == cid), {"id": cid, "name": ""})
    return cals[0] if cals else None


def motiv_von(tenant: dict[str, Any], name: str = "") -> dict[str, Any] | None:
    vms = tenant.get("visitMotives") if isinstance(tenant.get("visitMotives"), list) else []
    q = _sauber(name).lower()
    if q:
        for v in vms:
            if _sauber(v.get("name")).lower() == q:
                return v
        hit = next((v for v in vms if q in _sauber(v.get("name")).lower() or _sauber(v.get("name")).lower() in q), None)
        if hit:
            return hit
    return next((v for v in vms if "kontroll" in _sauber(v.get("name")).lower()), vms[0] if vms else None)
