"""Meldung beim Abheben — kurz, warm, vorgerendert (Null-Latenz)."""

from __future__ import annotations

from typing import Any

from kern import assistent


def begruessung(praxis: str, tenant: dict[str, Any] | None = None) -> str:
    """``praxis`` = Melde-Name im Nominativ (Mandanten-Feld ``praxisNameMelde``
    bzw. tenants.praxis_melde), z. B. "Zahnärzte im Medical Center".

    Nur der RUECKFALL: normalerweise kommt die Begruessung als
    ``begruessungText`` aus der Praxis-Datenbank (Chef 30.08.2026). ``tenant``
    liefert den Namen der Assistenz — ohne Mandant bleibt es Bianca."""
    wo = " ".join(str(praxis or "").split()).strip() or "unserer Praxis"
    wer = assistent.name(tenant)
    return f"{wo}, guten Tag! Mein Name ist {wer}. Was kann ich für Sie tun?"


def gruss_saeubern(text: str) -> str:
    """W-MEDDENT: Live-Bug „Wem kann ich…“ aus DB/TTS abfangen."""
    t = " ".join(str(text or "").split()).strip()
    return t.replace("Wem kann ich", "Was kann ich")
