"""Besuchsgrund-Katalog, frisch vom Standort und BEHANDLERSPEZIFISCH gefiltert.

Zwei Schichten — nie eine clientId, nie ein festes Fach im Kernel:

1. FACHWELT = der Motivkatalog dieser Praxis. Maschinenfragen (PZR,
   Bleaching, Dental-Konzepte, Beispiel-Behandlungen) nur via `fuehrt` /
   `ist_zahn` / `sprech_beispiele`. Ein Hautarzt bekommt keine
   Zahnreinigung, ein Gynaekologe keine Kniespiegelung — nicht weil wir
   den Fachnamen kennen, sondern weil das Motiv bei ihm nicht steht.
   Neue Fach-Maschine: erst `fuehrt(muster)`, sonst nicht bauen.
2. PRAXIS = Begruessung, Kalender, dbPrompt, wissen, Preise. Kommt aus
   der Pickadoc-DB (W-MANDANT). Zwei Hautaerzte koennen verschiedene
   Fragen und Preise haben.

Chef 30.08.2026: Das Besuchsgrund-Mapping muss in JEDEM Telefonat neu
passieren — der Agent sucht aktiv im Katalog des Standorts nach dem passenden
Besuchsgrund fuer den Ziel-Behandler. In Pickadoc sind die Besuchsgruende
kalendergebunden (visitMotive.calendarIds = "nur in diesen Kalendern
sichtbar"; leere Liste = ueberall). Die Motivliste in der Mandanten-Datei
kennt diese Bindung nicht und veraltet — sie ist nur noch Rueckfallebene,
wenn die Cloud Function nicht erreichbar ist.

Ablauf: `anstossen(sit)` holt den Katalog EINMAL pro Anruf im Hintergrund
(masVisitMotives, rein lesend); `katalog(sit)` liefert ihn (oder den
Mandanten-Fallback); `fuer_kalender(...)` filtert auf den Ziel-Behandler.
"""

from __future__ import annotations

import re
import threading
from typing import Any

import httpx

from kern.config import CF_BASE

# Starke Zahn-Marker — nichts Generisches (Kontrolle, Schmerz, OP, Reinigung,
# nacktes „Prophylaxe“: eine Hautarztpraxis kann Hautkrebs-Prophylaxe fuehren).
_ZAHN_KAT_RE = re.compile(
    r"zahnreinigung|\bpzr\b|zahnstein|zahnaufhell|zahnersatz|"
    r"wurzelbehand|kieferorthop|invisalign|narval|"
    r"\bkch\b|\bkfo\b|implantat|zahnarzt|zahnaerzt|zahnärzt",
    re.I,
)
_PZR_KAT_RE = re.compile(
    r"zahnreinigung|\bpzr\b|zahnstein|professionelle\s+(?:zahn)?prophylaxe",
    re.I,
)


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def holen(tenant: dict) -> list[dict]:
    """Katalog live von der Plattform (masVisitMotives) — [] bei Fehler."""
    try:
        r = httpx.post(
            f"{CF_BASE}/masVisitMotives",
            json={
                "clientId": _s(tenant.get("clientId")),
                "locationId": _s(tenant.get("locationId")),
            },
            timeout=10.0,
        )
        data = r.json() if r.status_code == 200 else {}
    except (httpx.HTTPError, ValueError):
        return []
    if not isinstance(data, dict) or data.get("status") != "success":
        return []
    motive = data.get("motives")
    return [m for m in motive if isinstance(m, dict) and _s(m.get("id"))] if isinstance(motive, list) else []


def anstossen(sit: dict) -> None:
    """Katalog-Abruf EINMAL pro Sitzung im Hintergrund anwerfen."""
    if sit.get("motivKatalogLauf") or isinstance(sit.get("motivKatalog"), list):
        return
    sit["motivKatalogLauf"] = True
    tenant = sit.get("tenant") or {}

    def _lauf() -> None:
        kat = holen(tenant)
        if kat:
            sit["motivKatalog"] = kat
            print(f"motive: Katalog frisch geladen ({len(kat)} Besuchsgruende)", flush=True)
        else:
            print("motive: Katalog-Abruf leer/fehlgeschlagen — Mandanten-Liste bleibt", flush=True)
        sit["motivKatalogLauf"] = False

    threading.Thread(target=_lauf, daemon=True).start()


def katalog(sit: dict) -> list[dict]:
    """Frisch geholter Katalog der Sitzung — sonst die Mandanten-Liste."""
    kat = sit.get("motivKatalog")
    if isinstance(kat, list) and kat:
        return kat
    tenant = sit.get("tenant") or {}
    vms = tenant.get("visitMotives")
    return vms if isinstance(vms, list) else []


def erlaubt(vm: dict, calendar_id: str) -> bool:
    """Gilt dieses Motiv fuer den Kalender? Leere calendarIds = ueberall."""
    ids = vm.get("calendarIds")
    if not isinstance(ids, list) or not ids:
        return True
    cid = _s(calendar_id)
    return bool(cid) and cid in [_s(x) for x in ids]


def fuer_kalender(kat: list[dict], calendar_id: str) -> list[dict]:
    """Katalog auf den Ziel-Behandler gefiltert; ohne Kalender: alles."""
    cid = _s(calendar_id)
    if not cid:
        return list(kat)
    return [vm for vm in kat if erlaubt(vm, cid)]


def _motiv_text(vm: dict) -> str:
    if not isinstance(vm, dict):
        return ""
    return " ".join(
        _s(vm.get(k))
        for k in (
            "name", "nameForPatient", "patientInfo",
            "landingPageHeadline", "landingPageDescription",
        )
    )


def _kat_von(sit_oder_kat: Any) -> list[dict]:
    if isinstance(sit_oder_kat, list):
        return [v for v in sit_oder_kat if isinstance(v, dict)]
    if isinstance(sit_oder_kat, dict):
        return katalog(sit_oder_kat)
    return []


def fuehrt(sit_oder_kat: Any, muster: re.Pattern[str]) -> bool:
    """Steht das Muster in irgendeinem Motivnamen/-text? Leerer Katalog = False."""
    return any(muster.search(_motiv_text(v)) for v in _kat_von(sit_oder_kat))


def fuehrt_pzr(sit_oder_kat: Any) -> bool:
    """Fuehrt die Praxis eine professionelle Zahnreinigung im Katalog?"""
    return fuehrt(sit_oder_kat, _PZR_KAT_RE)


def ist_zahn(sit_oder_kat: Any) -> bool:
    """Zahnmedizinische Praxis — am Katalog, nie an einer clientId."""
    return fuehrt(sit_oder_kat, _ZAHN_KAT_RE)


# Gleicher Schnitt wie gehirn._MOTIV_KUERZEL_RE — KCH/PRO/IMP nicht vorlesen.
_KUERZEL_RE = re.compile(r"^[A-ZÄÖÜ]{2,4}\s*\d?\s+")


def sprechname_kurz(vm_oder_name: Any) -> str:
    """Motivname ohne Kuerzel, erste Slash-Haelfte — fuer gesprochene Beispiele."""
    if isinstance(vm_oder_name, dict):
        name = _s(vm_oder_name.get("nameForPatient") or vm_oder_name.get("name"))
    else:
        name = _s(vm_oder_name)
    if not name:
        return ""
    return _s(_KUERZEL_RE.sub("", name).split("/")[0]) or name


def sprech_beispiele(sit_oder_kat: Any, n: int = 2) -> list[str]:
    """Bis zu n Motivnamen DIESER Praxis — Beispiele in Fragen, nie fremdes Fach."""
    out: list[str] = []
    gesehen: set[str] = set()
    for vm in _kat_von(sit_oder_kat):
        name = sprechname_kurz(vm)
        if "krebs" in name.lower():
            name = "Kontrolle"
        if not name or len(name) > 32:
            continue
        key = name.casefold()
        if key in gesehen:
            continue
        gesehen.add(key)
        out.append(name)
        if len(out) >= n:
            break
    return out
