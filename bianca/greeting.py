"""Biancas Meldung beim Abheben — kurz, warm, vorgerendert (Null-Latenz)."""

from __future__ import annotations


def begruessung(praxis: str) -> str:
    wo = " ".join(str(praxis or "").split()).strip() or "unserer Praxis"
    return f"{wo}, guten Tag! Mein Name ist Bianca. Was kann ich für Sie tun?"
