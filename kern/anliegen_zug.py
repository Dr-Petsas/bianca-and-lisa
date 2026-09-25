"""V4-Mund: Anliegen-Strategie der Praxis anwenden.

Ohne Eintrag bleibt das V4-Default (Dokumente nur persoenlich, kein Rueckruf).
Eine veroeffentlichte Regel ersetzt genau diesen Default — Terminverwaltung
wird nie umgebogen.
"""

from __future__ import annotations

from typing import Any

from kern import anliegen_ablage, anliegen_katalog as ak
from kern.anliegen_katalog import Folge

_ART_NACH_KATALOG = {
    "rezept": "rezept",
    "ueberweisung": "ueberweisung",
    "krankmeldung": "au",
    "rechnung": "rechnung",
    "plan": "unterlagen",
    "akte": "unterlagen",
    "befund": "befund",
    "unterlagen": "unterlagen",
    "dokument": "unterlagen",
}


def _s(v: Any) -> str:
    return " ".join(str(v or "").split()).strip()


def policy_von(tenant: dict | None) -> dict[str, Any]:
    tenant = tenant if isinstance(tenant, dict) else {}
    if isinstance(tenant.get("anliegenPolicy"), dict) and tenant["anliegenPolicy"]:
        return tenant["anliegenPolicy"]
    return anliegen_ablage.anreichern(dict(tenant)).get("anliegenPolicy") or {}


def regel_fuer(tenant: dict | None, anliegen_id: str) -> ak.Regel | None:
    if not ak.an():
        return None
    tenant = tenant if isinstance(tenant, dict) else {}
    if not tenant.get("anliegenPolicy"):
        tenant = anliegen_ablage.anreichern(dict(tenant))
    return ak.regel(tenant, anliegen_id)


def id_fuer_dokument(art: str) -> str:
    return _ART_NACH_KATALOG.get(_s(art).lower(), "")


def dokument_regel(tenant: dict | None, text: str) -> ak.Regel | None:
    from kern import praxisregeln

    if not praxisregeln.dokument_anforderung(text):
        return None
    art = praxisregeln.dokument_art(text)
    kid = id_fuer_dokument(art)
    return regel_fuer(tenant, kid) if kid else None


def satz(r: ak.Regel | None, tenant: dict | None = None) -> str:
    return ak.antwort(r, tenant)


def folge(r: ak.Regel | None) -> str:
    return r.folge.value if r is not None else ""


__all__ = [
    "dokument_regel", "folge", "id_fuer_dokument", "policy_von",
    "regel_fuer", "satz", "Folge",
]
