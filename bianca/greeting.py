"""Biancas Meldung beim Abheben — kurz, warm, vorgerendert (Null-Latenz)."""

from __future__ import annotations


def begruessung(praxis: str) -> str:
    """``praxis`` = Melde-Name im Nominativ (Mandanten-Feld ``praxisNameMelde``
    bzw. tenants.praxis_melde), z. B. "Zahnärzte im Medical Center"."""
    wo = " ".join(str(praxis or "").split()).strip() or "unserer Praxis"
    return f"{wo}, guten Tag! Mein Name ist Bianca. Was kann ich für Sie tun?"


def gruss_saeubern(text: str) -> str:
    """W-MEDDENT: Live-Bug „Wem kann ich…“ aus DB/TTS abfangen."""
    t = " ".join(str(text or "").split()).strip()
    return t.replace("Wem kann ich", "Was kann ich")
