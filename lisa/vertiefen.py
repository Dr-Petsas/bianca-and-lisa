"""Auftrag vorbereiten — Sammelphase, kein Analyse-Briefing.

Der alte Knopf hat den Einzeiler mit erfundenen Spiegelstrichen überschrieben.
Jetzt: Fakten holen (Kartei + Mail/Anrufe zum Kontakt), Gesprächsplan falten,
Chef-Auftrag unverändert lassen. Nichts erfinden.
"""

from __future__ import annotations

from typing import Any

from lisa import vorbereitung


def _s(v: Any) -> str:
    return vorbereitung._s(v)


_RECALL_RE = vorbereitung._RECALL_RE


def bleibt_beim_thema(auftrag: str, text: str) -> bool:
    """False, wenn das Modell den Chef-Auftrag durch Recall/PZR ersetzt."""
    kerne = vorbereitung._kerne(auftrag)
    if not kerne:
        return bool(_s(text))
    tl = (text or "").lower()
    if not any(k in tl for k in kerne):
        return False
    if not _RECALL_RE.search(auftrag) and _RECALL_RE.search(text):
        return False
    return True


def notfall_vertiefen(auftrag: str, *, hintergrund: str = "", termine: str = "") -> str:
    """Ohne Netz: Gesprächsplan nur aus dem, was übergeben wurde."""
    unterlage = [z for z in (termine, hintergrund) if _s(z)]
    return vorbereitung._plan(
        auftrag,
        unterlage=unterlage,
        einwaende=vorbereitung._einwaende([], [], [], auftrag),
        luecken=[],
    )


def vertiefen(auftrag: str, *, tenant_id: str = "", patient: dict | None = None) -> dict[str, Any]:
    """Sammelphase. auftrag bleibt der Chef-Text; briefing ist der Plan."""
    return vorbereitung.sammeln(auftrag, tenant_id=tenant_id, patient=patient)
