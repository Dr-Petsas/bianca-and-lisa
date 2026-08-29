"""Besuchsgrund-Katalog, frisch vom Standort und BEHANDLERSPEZIFISCH gefiltert.

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

import threading
from typing import Any

import httpx

from kern.config import CF_BASE


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
