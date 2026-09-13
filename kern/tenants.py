from __future__ import annotations

import json
import re
from typing import Any

from kern.config import DEFAULT_TENANT, TENANTS_DIR

# Stilles Default-Motiv: nie Akut/Notfall, nur wenn der Anrufer das gesagt hat.
_AKUT_NAME_RE = re.compile(r"akut|notfall|schmerz|notsprech|akutsprech", re.I)
_SAFE_NAME_RE = re.compile(
    r"kontroll|vorsorge|screening|check.?up|nachsorge|"
    r"besprechung|beratung|untersuchung|recall",
    re.I,
)

# Kalender, die KEINE Person sind: Zimmer/Prophylaxe, nicht Behandler.
# Thaler 08.09.2026: "Prophylaxe" stand als Behandler in der Arztwahl.
# Chef 08.09.2026: Zimmer 1 Notfall, 2/3 PZR, 4 Behandlung bei Thaler.
_FUNKTION_KAL_RE = re.compile(
    r"^(?:die\s+|der\s+|das\s+)?"
    r"(?:"
    r"prophylaxe|hygiene|\bpzr\b|zahnreinigung|prophy|"
    r"professionelle\s+zahnreinigung|"
    r".*(?:zimmer|zi\.?|raum)\s*[1-4].*"
    r")\s*$",
    re.I,
)
_ZIMMER_NR_RE = re.compile(
    r"(?:zimmer|zi\.?|raum)\s*[:\-]?\s*([1-4])\b"
    r"|[(\[]\s*zi\.?\s*([1-4])\s*[)\]]",
    re.I,
)
_PZR_MOTIV_RE = re.compile(
    r"zahnreinigung|\bpzr\b|zahnstein|professionelle\s+(?:zahn)?prophylaxe",
    re.I,
)
_BESPRECH_MUSTER = [
    r"besprechung", r"beratung", r"recall", r"check.?up",
    r"kontrolluntersuchung", r"kontroll",
]


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
            "locationId": _sauber(d.get("locationId")),
            "aliases": [
                _sauber(x) for x in (d.get("tenantAliases") or [])
                if _sauber(x)
            ],
            "praxisName": _sauber(d.get("praxisName")) or p.stem,
        })
    return out


def laden(tenant_id: str = "") -> dict[str, Any]:
    angefragt = _sauber(tenant_id)
    name = angefragt or DEFAULT_TENANT
    pfad = TENANTS_DIR / f"{name}.json"
    if not pfad.is_file():
        # Ein unbekannter Mandant darf niemals still auf den Kunden aus
        # DEFAULT_TENANT (produktiv: MedDent) umgebogen werden. Nur ein leerer
        # Dock-Start wählt den ausdrücklich konfigurierten Dev-Default.
        if angefragt:
            return fach_fallback("allgemein")
        pfad = TENANTS_DIR / f"{DEFAULT_TENANT}.json"
        if not pfad.is_file():
            return fach_fallback("allgemein")
    raw = json.loads(pfad.read_text(encoding="utf-8"))
    raw["_id"] = pfad.stem
    return raw


def nummer_norm(roh: Any) -> str:
    """Rufnummer auf eine vergleichbare Ziffernform bringen.

    "+49 211 54244101", "004921154244101" und "0211 54244101" meinen
    dieselbe Leitung — alle drei werden zu "4921154244101" (W-MANDANT)."""
    ziffern = "".join(c for c in str(roh or "") if c.isdigit())
    if ziffern.startswith("00"):
        return ziffern[2:]
    if ziffern.startswith("0"):
        return "49" + ziffern[1:]
    return ziffern


def von_did(did: Any) -> dict[str, Any] | None:
    """Lokalen Mandanten anhand der ANGERUFENEN Nummer finden (W-MANDANT).

    Ein Tenant-JSON darf ``dids`` (Liste) oder ``did`` (String) tragen —
    kuratierte Mandanten (meddent) werden so OHNE Netz aufgeloest; erst
    unbekannte Nummern gehen an die Pickadoc-DB (kern/agentprofil.py)."""
    ziel = nummer_norm(did)
    if not ziel or not TENANTS_DIR.is_dir():
        return None
    for p in sorted(TENANTS_DIR.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        roh = d.get("dids") if isinstance(d.get("dids"), list) else [d.get("did")]
        if any(nummer_norm(x) == ziel for x in roh if x):
            d["_id"] = p.stem
            return d
    return None


def fach_fallback(fachgebiet: str = "allgemein", *, did: str = "") -> dict[str, Any]:
    """Fail-closed statt Kundenwechsel: neutrales, nicht buchendes Profil."""
    from kern import fachprofil
    return fachprofil.fallback_tenant(fachgebiet, did=did)


def fallback_fuer_did(did: Any) -> dict[str, Any]:
    """Bekannte DID aus ihrer Datei, unbekannte DID aus neutralem Template."""
    lokal = von_did(did)
    if lokal is not None:
        return lokal
    return fach_fallback("allgemein", did=str(did or ""))


def von_client_id(client_id: Any) -> dict[str, Any] | None:
    """Lokalen Mandanten ueber die Firebase-clientId finden (W-MANDANT):
    liefert die kuratierte Basis (Sprechformen, Wissen) fuer CF-Treffer."""
    ziel = _sauber(client_id)
    if not ziel or not TENANTS_DIR.is_dir():
        return None
    for p in sorted(TENANTS_DIR.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if _sauber(d.get("clientId")) == ziel:
            d["_id"] = p.stem
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
    """Einwort-Namen fuer die STT-Nachkorrektur (Praxis + Behandler).

    Claras Fuzzy-Nachkorrektur (stt_serve/postcorrect.py) arbeitet mit
    Einwort-Keywords ab 4 Zeichen — wir liefern die Behandler-Nachnamen
    ("Petsas", "Nikolaou", "Patrikis"), damit Hoerfehler wie "Betsas" oder
    "Batrikis" sowie den individuellen Praxisnamen ("Ttola" -> "Thaler")
    schon VOR dem LLM korrigiert werden (Claras Anlaut-Gruppen P/B, T/D/Z
    ...). Bewusst KEINE Marker-Keywords (Heads-up, Teleskopkrone, Kons):
    das Patiententelefon bleibt wie Claras Bianca ohne Phrasen-Fixes.
    """
    kandidaten: list[str] = []
    quellen: list[Any] = [
        tenant.get("behandler"),
        tenant.get("praxisName"),
        tenant.get("praxisNameMelde"),
        tenant.get("praxisNameVon"),
    ]
    cals = tenant.get("calendars") if isinstance(tenant.get("calendars"), list) else []
    quellen += [c.get("name") for c in cals if isinstance(c, dict)]
    # Mandanten-Hotwords (z. B. Ueberweiser "Grüger"/"Lange", "Narval"):
    # gleiche Fuzzy-Nachkorrektur wie die Behandler-Namen, rein additiv.
    extra = tenant.get("sttHotwords") if isinstance(tenant.get("sttHotwords"), list) else []
    quellen += [w for w in extra if _sauber(w)]
    generisch = {
        "doktor", "prof", "med", "dent", "herr", "herrn", "frau",
        "praxis", "praxen", "zahnarzt",
        "zahnärzte", "zahnaerzte", "zahnmedizin", "klinik", "zentrum",
        "zahnarztpraxis", "hautarztpraxis", "gemeinschaftspraxis",
        "center", "medical", "telefonassistentin",
    }
    for q in quellen:
        for tok in _sauber(q).replace(".", " ").split():
            t = tok.strip("-()")
            if len(t) >= 4 and t.lower() not in generisch:
                kandidaten.append(t[0].upper() + t[1:])
    out: list[str] = []
    for k in kandidaten:
        if k not in out:
            out.append(k)
    return out


def zimmer_nr(cal_oder_name: Any) -> int | None:
    """Zimmer 1-4 aus dem Kalendernamen, sonst None.

    Trifft 'Zimmer 3', 'Zi 4', 'Leonita (Zi2)', 'Irem (Zi 4)'.
    """
    if isinstance(cal_oder_name, dict):
        name = _sauber(cal_oder_name.get("name"))
    else:
        name = _sauber(cal_oder_name)
    m = _ZIMMER_NR_RE.search(name)
    if not m:
        return None
    z = m.group(1) or m.group(2)
    try:
        n = int(z)
    except (TypeError, ValueError):
        return None
    return n if 1 <= n <= 4 else None


def ist_funktionskalender(cal_oder_name: Any) -> bool:
    """True bei Prophylaxe / Hygiene / Zimmer — kein Behandler-Name."""
    if zimmer_nr(cal_oder_name):
        return True
    if isinstance(cal_oder_name, dict):
        name = _sauber(cal_oder_name.get("name"))
    else:
        name = _sauber(cal_oder_name)
    kern = re.sub(r"^(?:dr\.?|doktor|prof\.?)\s+", "", name, flags=re.I).strip()
    return bool(kern and _FUNKTION_KAL_RE.match(kern))


def behandler_kalender(tenant: dict[str, Any]) -> list[dict[str, Any]]:
    """Nur Personen-Kalender — Funktionskalender (Prophylaxe) fliegen raus."""
    return [
        c for c in (tenant.get("calendars") or [])
        if isinstance(c, dict) and _sauber(c.get("name")) and not ist_funktionskalender(c)
    ]


def _raum_rang(cal: dict[str, Any]) -> tuple[int, str]:
    """Zimmer 2 vor Zimmer 3, dann der Name."""
    name = _sauber(cal.get("name"))
    m = _ZIMMER_NR_RE.search(name)
    nr = int(m.group(1)) if m else 9
    return (nr, name.lower())


def funktionskalender_alle(tenant: dict[str, Any]) -> list[dict[str, Any]]:
    """Alle Prophylaxe-/Zimmer-Kalender, Zimmer 2 vor Zimmer 3."""
    out = [
        c for c in (tenant.get("calendars") or [])
        if isinstance(c, dict) and ist_funktionskalender(c) and _sauber(c.get("id"))
    ]
    out.sort(key=_raum_rang)
    return out


def funktionskalender(tenant: dict[str, Any]) -> dict[str, Any] | None:
    """Der erste Prophylaxe-/Zimmer-Kalender (Zimmer 2 vor 3)."""
    alle = funktionskalender_alle(tenant)
    return alle[0] if alle else None


def hat_funktionskalender(tenant: dict[str, Any]) -> bool:
    return funktionskalender(tenant) is not None and bool(behandler_kalender(tenant))


def ist_pzr_motiv(vm: dict[str, Any] | None) -> bool:
    if not isinstance(vm, dict):
        return False
    return bool(_PZR_MOTIV_RE.search(
        f"{_sauber(vm.get('name'))} {_sauber(vm.get('nameForPatient'))}"))


def ist_besprechung_motiv(vm: dict[str, Any] | None) -> bool:
    """Kontrolle/Beratung/Recall — keine Füllung, keine OP, kein Notfall."""
    if not isinstance(vm, dict) or ist_akut_motiv(vm) or ist_pzr_motiv(vm):
        return False
    text = f"{_sauber(vm.get('name'))} {_sauber(vm.get('nameForPatient'))}"
    return bool(_SAFE_NAME_RE.search(text))


def kalender_beim(name: str) -> str:
    """'bei …' — Funktionskalender als Ort, nicht als Arzt."""
    n = _sauber(name)
    if not n:
        return ""
    if not ist_funktionskalender(n):
        return ""
    nr = zimmer_nr(n)
    # Nur PZR-Zimmer (2/3) oder ein Kalender namens Prophylaxe — nie
    # "bei der Prophylaxe" fuer Notfall-Zimmer 1 oder Behandlungs-Zimmer 4.
    if nr in {2, 3} or re.search(r"prophylaxe|hygiene|\bpzr\b", n, re.I):
        return "der Prophylaxe"
    return ""


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
    d = default_kalender(tenant)
    if d:
        return d
    return None


def default_kalender(tenant: dict[str, Any]) -> dict[str, Any] | None:
    """Der Standard-Behandler des Mandanten (defaultCalendarId, sonst der
    erste Personen-Kalender). Funktionskalender (Prophylaxe) zaehlen nicht
    — das ist kein Arzt. Chef 03.09.2026: "wenn jemand nicht weiss zu
    welchem arzt er soll dann immer bei dr. Petsas buchen"."""
    personen = behandler_kalender(tenant)
    cid = _sauber(tenant.get("defaultCalendarId"))
    if cid:
        hit = next((c for c in personen if _sauber((c or {}).get("id")) == cid), None)
        if hit:
            return hit
    return personen[0] if personen else None


def behandler_reihe(tenant: dict[str, Any]) -> list[dict[str, Any]]:
    """Kalender in SPRECH-Reihenfolge fuer Aufzaehlungen (Chef 03.09.2026):
    "erwähne nicht die Namen in dieser RehenFolge: Dr. Nikolaou, Dr.Patrikis
    und Dr. Petsas. sondern umgekehert." — der Standard-Behandler zuerst,
    die uebrigen in umgekehrter Kalender-Reihenfolge. Ergibt bei Meddent
    exakt: Dr. Petsas, Dr. Patrikis, Dr. Nikolaou. Funktionskalender
    (Prophylaxe) stehen nie in der Liste."""
    cals = behandler_kalender(tenant)
    d = default_kalender(tenant)
    did = _sauber((d or {}).get("id"))
    rest = [c for c in cals if _sauber((c or {}).get("id")) != did]
    kopf = [d] if d and _sauber(d.get("name")) else []
    return kopf + rest[::-1]


def _kalender_fuehrt(vm: dict[str, Any], calendar_id: str) -> bool:
    ids = vm.get("calendarIds") if isinstance(vm.get("calendarIds"), list) else []
    if not calendar_id or not ids:
        return True
    return any(_sauber(x) == _sauber(calendar_id) for x in ids)


def besprechung_motiv(katalog: list[dict[str, Any]] | None,
                      calendar_id: str = "") -> dict[str, Any] | None:
    """Erstes Besprechungs-/Kontroll-Motiv — nie Füllung, nie Notfall, nie PZR."""
    kandidaten = [
        v for v in (katalog or [])
        if isinstance(v, dict) and ist_besprechung_motiv(v)
        and _kalender_fuehrt(v, calendar_id)
    ]
    if not kandidaten:
        return None
    for muster in _BESPRECH_MUSTER:
        rx = re.compile(muster, re.I)
        for v in kandidaten:
            text = f"{_sauber(v.get('name'))} {_sauber(v.get('nameForPatient'))}"
            if rx.search(text):
                return v
    return kandidaten[0]


def ist_akut_motiv(vm: dict[str, Any] | None) -> bool:
    """True bei Akut/Notfall/Schmerz — darf nie stiller Default sein."""
    if not isinstance(vm, dict):
        return False
    text = f"{_sauber(vm.get('name'))} {_sauber(vm.get('nameForPatient'))} {_sauber(vm.get('id'))}"
    return bool(_AKUT_NAME_RE.search(text))


def _sicheres_default(vms: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Kontrolle/Besprechung/Vorsorge — nie das erste Motiv, wenn das Notfall ist.

    Live 08.09.2026 Blessing + Thaler: visitMotives[0] war Akut/Notfall,
    niemand hatte Schmerzen gesagt, die KI suchte und las trotzdem Notfall vor.
    """
    sicher = [v for v in vms if not ist_akut_motiv(v)]
    if not sicher:
        return None
    for v in sicher:
        n = _sauber(v.get("name")).lower()
        if "kontroll" in n:
            return v
    for v in sicher:
        if _SAFE_NAME_RE.search(_sauber(v.get("name")) or _sauber(v.get("nameForPatient"))):
            return v
    return sicher[0]


def motiv_von(tenant: dict[str, Any], name: str = "") -> dict[str, Any] | None:
    vms = tenant.get("visitMotives") if isinstance(tenant.get("visitMotives"), list) else []
    q = _sauber(name).lower()
    suche_default = (not q) or q in {
        "kontrolluntersuchung", "kontrolle", "vorsorge", "untersuchung",
    }
    if q:
        for v in vms:
            n = _sauber(v.get("name")).lower()
            if n == q:
                if suche_default and ist_akut_motiv(v):
                    break
                return v
        treffer = [
            v for v in vms
            if q in _sauber(v.get("name")).lower() or _sauber(v.get("name")).lower() in q
        ]
        if suche_default:
            treffer = [v for v in treffer if not ist_akut_motiv(v)]
        if treffer:
            return treffer[0]
    return _sicheres_default(vms)
