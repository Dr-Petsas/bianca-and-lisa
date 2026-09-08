"""Thaler: Besuchsgrund -> Zimmer (Chef 08.09.2026).

Die Cloud Function liefert nur einen Arztkalender (Eva). Thaler bucht
raeumlich:

- Prophylaxe / PZR     -> Kalender Prophylaxe, Zimmer 3, wenn voll Zimmer 2
- Notfall / Schmerzen  -> bei Thaler, Zimmer 1
- restliche Behandlung -> bei Thaler selbst in Zimmer 4

Live stehen Zimmer in der rooms-Sammlung, nicht als Kalender. Gibt es
Kalender namens Zimmer 1-4 (Tests), suchen wir dort. Sonst: PZR auf
Prophylaxe, alles andere auf Eva.

Nur dieser Mandant. MedDent bleibt unveraendert.
"""

from __future__ import annotations

import re
from typing import Any

from kern import tenants as kern_tenants

THALER_CLIENT = "7tTnJZfJkb801r2rmYed"

# Reihenfolge = Suchreihenfolge (erster Treffer mit Slots gewinnt).
DEFAULT_MAP = {
    "pzr": [3, 2],
    "akut": [1],
    "behandlung": [4],
}

# Spur-Frage: Frau Thaler oder Prophylaxe — kein Behandler-Roster.
_PZR_SPUR_RE = re.compile(
    r"prophylaxe|hygiene|\bpzr\b|zahnreinigung|zahnstein",
    re.I,
)
_PZR_NEIN_RE = re.compile(
    r"\bnicht\s+(?:zur\s+|die\s+|eine\s+)?(?:prophylaxe|zahnreinigung|\bpzr\b)|"
    r"\bkeine\s+(?:prophylaxe|zahnreinigung)",
    re.I,
)
_THALER_SPUR_RE = re.compile(
    r"\bthaler\b|\bkahler\b|\bparler\b|\btahler\b|\btaler\b|"
    r"bei\s+(?:ihr|frau|der\s+zahnaerztin|der\s+zahnärztin|"
    r"der\s+aerztin|der\s+ärztin)|"
    r"zur\s+(?:zahnaerztin|zahnärztin)|"
    r"\bzahn(?:arzt|aerztin|ärztin)\b",
    re.I,
)


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def aktiv(tenant: dict[str, Any] | None) -> bool:
    """Nur mit ausdruecklicher Karte oder Thaler-clientId."""
    if not isinstance(tenant, dict):
        return False
    if isinstance(tenant.get("zimmerMap"), dict) and tenant["zimmerMap"]:
        return True
    return _s(tenant.get("clientId")) == THALER_CLIENT


def karte(tenant: dict[str, Any] | None) -> dict[str, list[int]]:
    roh = (tenant or {}).get("zimmerMap") if isinstance(tenant, dict) else None
    if not isinstance(roh, dict) or not roh:
        return dict(DEFAULT_MAP)
    out = dict(DEFAULT_MAP)
    for key in ("pzr", "akut", "behandlung"):
        nums = roh.get(key)
        if isinstance(nums, list) and nums:
            sauber = []
            for n in nums:
                try:
                    i = int(n)
                except (TypeError, ValueError):
                    continue
                if 1 <= i <= 4 and i not in sauber:
                    sauber.append(i)
            if sauber:
                out[key] = sauber
    return out


def gruppe(s: dict | None, sit: dict | None = None) -> str:
    """pzr | akut | behandlung — aus Motiv/Grund, nie geraten als Notfall."""
    from bianca import gehirn
    stand = s if isinstance(s, dict) else {}
    if sit is not None and not stand.get("motivId") and not stand.get("grund"):
        stand = gehirn.sammler(sit)
    if gehirn.ist_pzr_grund(stand):
        return "pzr"
    vm = None
    mid = _s(stand.get("motivId"))
    name = _s(stand.get("motivName"))
    if mid or name:
        vm = {"id": mid, "name": name}
    if gehirn._ist_akut(stand) or kern_tenants.ist_akut_motiv(vm):
        return "akut"
    return "behandlung"


def zimmer_von(tenant: dict[str, Any], nr: int) -> dict[str, Any] | None:
    """Kalender, dessen Name Zimmer/Zi ``nr`` traegt."""
    for c in (tenant or {}).get("calendars") or []:
        if not isinstance(c, dict) or not _s(c.get("id")):
            continue
        if kern_tenants.zimmer_nr(c.get("name")) == nr:
            return c
    return None


def prophylaxe_kalender(tenant: dict[str, Any] | None) -> dict[str, Any] | None:
    """Kalender namens Prophylaxe/Hygiene, sonst Zimmer 3."""
    t = tenant if isinstance(tenant, dict) else {}
    for c in t.get("calendars") or []:
        if not isinstance(c, dict) or not _s(c.get("id")):
            continue
        name = _s(c.get("name"))
        if re.search(r"prophylaxe|hygiene|\bpzr\b", name, re.I):
            return c
    return zimmer_von(t, 3)


def spur_deute(text: str) -> str:
    """pzr | thaler | '' — Antwort auf die Thaler-Spur-Frage."""
    t = _s(text)
    if not t:
        return ""
    if _PZR_SPUR_RE.search(t) and not _PZR_NEIN_RE.search(t):
        return "pzr"
    if _THALER_SPUR_RE.search(t):
        return "thaler"
    return ""


def raeume(tenant: dict[str, Any] | None, grp: str) -> list[dict[str, Any]]:
    """Kalender in Suchreihenfolge: Zimmer 1-4, sonst Prophylaxe/Eva."""
    t = tenant if isinstance(tenant, dict) else {}
    nums = karte(t).get(grp) or []
    out: list[dict[str, Any]] = []
    gesehen: set[str] = set()
    for n in nums:
        cal = zimmer_von(t, int(n))
        cid = _s((cal or {}).get("id"))
        if cal and cid and cid not in gesehen:
            out.append(cal)
            gesehen.add(cid)
    if out:
        return out
    if not aktiv(t):
        return []
    if grp == "pzr":
        p = prophylaxe_kalender(t)
        if p and _s(p.get("id")):
            return [p]
    d = kern_tenants.default_kalender(t)
    if d and _s(d.get("id")):
        return [d]
    return []


def sprechname(tenant: dict[str, Any] | None, grp: str) -> str:
    """Was Bianca sagt — Prophylaxe oder Thaler, nie 'Zimmer 4'."""
    if grp == "pzr":
        return "Prophylaxe"
    d = kern_tenants.default_kalender(tenant or {})
    return _s((d or {}).get("name")) or "Frau Thaler"


def an_arzt(sit: dict) -> None:
    """Sammler-Arzt auf die Zimmer der aktuellen Gruppe setzen."""
    from bianca import gehirn
    tenant = sit.get("tenant") if isinstance(sit.get("tenant"), dict) else {}
    if not aktiv(tenant):
        return
    s = gehirn.sammler(sit)
    if not (s.get("grund") or s.get("motivId")):
        return
    grp = gruppe(s)
    zimmer = raeume(tenant, grp)
    if not zimmer:
        return
    first = zimmer[0]
    ids = [_s(z.get("id")) for z in zimmer if _s(z.get("id"))]
    name = sprechname(tenant, grp)
    alt = dict(s.get("arzt") or {})
    gleich = (
        alt.get("calendarId") == first.get("id")
        and list(alt.get("raeume") or []) == ids
    )
    if gleich:
        alt["calendarName"] = name
        alt["typ"] = alt.get("typ") or "zimmer"
        s["arzt"] = alt
        return
    s["arzt"] = {
        "typ": "zimmer",
        "calendarId": first["id"],
        "calendarName": name,
        "raeume": ids,
    }
    gehirn._vorrat_leeren(sit)


def raeume_am(sit: dict) -> list[dict[str, Any]]:
    """Zimmer-Objekte aus dem schon gesetzten Arzt (Reihenfolge halten)."""
    from bianca import gehirn
    tenant = sit.get("tenant") if isinstance(sit.get("tenant"), dict) else {}
    a = gehirn.sammler(sit).get("arzt") or {}
    ids = [str(x) for x in (a.get("raeume") or []) if str(x).strip()]
    if not ids:
        return []
    by_id = {
        _s(c.get("id")): c
        for c in (tenant.get("calendars") or [])
        if isinstance(c, dict) and _s(c.get("id"))
    }
    return [by_id[i] for i in ids if i in by_id]


def spur_anwenden(sit: dict, welche: str) -> bool:
    """Spur-Antwort binden. pzr setzt Grund + Zimmer, thaler nur Eva."""
    from bianca import gehirn
    s = gehirn.sammler(sit)
    tenant = sit.get("tenant") if isinstance(sit.get("tenant"), dict) else {}
    if welche == "pzr":
        if not s.get("grund"):
            s["grund"] = "Zahnreinigung"
            s["grundWortlaut"] = s.get("grundWortlaut") or "Prophylaxe"
        an_arzt(sit)
        return bool((s.get("arzt") or {}).get("calendarId"))
    if welche == "thaler":
        d = gehirn.arzt_default(tenant)
        if not d:
            return False
        alt = dict(s.get("arzt") or {})
        if alt.get("calendarId") == d.get("calendarId") and alt.get("typ") != "funktion":
            return True
        s["arzt"] = {
            "typ": "genannt",
            "calendarId": d["calendarId"],
            "calendarName": d.get("calendarName") or "Frau Thaler",
        }
        gehirn._vorrat_leeren(sit)
        return True
    return False
