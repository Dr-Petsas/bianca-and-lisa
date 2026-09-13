"""Additive Diagnose fuer die echte STT-Entscheidung eines Audio-Zugs.

`kern.stt.transcribe` bleibt der alleinige Erkenner. Dieses Modul beobachtet
seine bestehenden Parakeet-/Qwen-Entscheidungspunkte ohne einen zweiten
Decode und ohne die Auswahl oder Latenz zu veraendern.
"""

from __future__ import annotations

import threading
from typing import Any

from kern import stt


_lokal = threading.local()
_ORIGINAL_LOKAL = getattr(stt, "_lokal", None)
_ORIGINAL_QWEN_ENTSCHEID = getattr(stt, "_qwen_darf_uebernehmen", None)


def _parakeet_mit_spur(*args, **kwargs):
    try:
        text = _ORIGINAL_LOKAL(*args, **kwargs)
        _lokal.parakeet_text = str(text or "")
        _lokal.parakeet_fehler = ""
        return text
    except Exception as exc:
        _lokal.parakeet_fehler = f"{type(exc).__name__}: {exc}"
        raise


def _qwen_entscheid_mit_spur(lokal_text: str, kandidat: dict, auffaellig: bool):
    uebernehmen = bool(
        _ORIGINAL_QWEN_ENTSCHEID(lokal_text, kandidat, auffaellig)
    )
    _lokal.qwen_entschieden = True
    _lokal.qwen_uebernommen = uebernehmen
    _lokal.qwen_kandidat = dict(kandidat or {})
    _lokal.parakeet_text = str(lokal_text or "")
    _lokal.parakeet_auffaellig = bool(auffaellig)
    return uebernehmen


def _beobachter_installieren() -> None:
    if (_ORIGINAL_LOKAL is not None
            and not getattr(stt._lokal, "_stt_spur", False)):
        _parakeet_mit_spur._stt_spur = True
        stt._lokal = _parakeet_mit_spur
    if (_ORIGINAL_QWEN_ENTSCHEID is not None
            and not getattr(stt._qwen_darf_uebernehmen, "_stt_spur", False)):
        _qwen_entscheid_mit_spur._stt_spur = True
        stt._qwen_darf_uebernehmen = _qwen_entscheid_mit_spur


_beobachter_installieren()


def _reset() -> None:
    for name in (
        "parakeet_text", "parakeet_fehler", "parakeet_auffaellig",
        "qwen_entschieden", "qwen_uebernommen", "qwen_kandidat",
    ):
        if hasattr(_lokal, name):
            delattr(_lokal, name)


def _qwen_futur() -> Any:
    return getattr(stt, "_qwen_future", None)


def _qwen_konfiguriert() -> bool:
    fn = getattr(stt, "_qwen_konfiguriert", None)
    if callable(fn):
        return bool(fn())
    return bool(getattr(stt, "STT_QWEN_FINAL_BASE", "")
                or getattr(stt, "STT_QWEN_BASE", ""))


def transcribe(
    audio: bytes,
    *,
    mime: str = "audio/webm",
    name: str = "turn.webm",
    keywords: str = "",
) -> tuple[str, dict[str, Any]]:
    """Ein echter Decode plus dessen beobachtete Engine-Entscheidung."""
    _reset()
    vorher = _qwen_futur()
    text = stt.transcribe(audio, mime=mime, name=name, keywords=keywords)
    nachher = _qwen_futur()

    qwen_an = _qwen_konfiguriert()
    parakeet_an = bool(getattr(stt, "STT_BASE", ""))
    kandidat = dict(getattr(_lokal, "qwen_kandidat", {}) or {})
    uebernommen = bool(getattr(_lokal, "qwen_uebernommen", False))
    entschieden = bool(getattr(_lokal, "qwen_entschieden", False))

    if qwen_an and parakeet_an:
        gewinner = "qwen" if uebernommen else "parakeet"
        if entschieden:
            qwen_status = "uebernommen" if uebernommen else "abgelehnt"
        elif nachher is vorher:
            qwen_status = "belegt_oder_pausiert"
        else:
            qwen_status = "parallel_zu_spaet"
    elif qwen_an:
        gewinner, qwen_status = "qwen", "alleinig"
    elif getattr(stt, "STT_WHISPER_BASE", ""):
        gewinner, qwen_status = "whisper_oder_parakeet", "aus"
    elif parakeet_an:
        gewinner, qwen_status = "parakeet", "aus"
    else:
        gewinner, qwen_status = "elevenlabs", "aus"

    parakeet_text = str(getattr(_lokal, "parakeet_text", "") or "")
    if gewinner == "parakeet" and not parakeet_text:
        parakeet_text = str(text or "")
    qwen_text = str(kandidat.get("text") or "")
    if gewinner == "qwen" and not qwen_text:
        qwen_text = str(text or "")

    return str(text or ""), {
        "pipeline": "audio",
        "bytes": len(audio or b""),
        "mime": mime,
        "winner": gewinner,
        "parakeet": {
            "text": parakeet_text,
            "error": str(getattr(_lokal, "parakeet_fehler", "") or ""),
            "suspicious": bool(getattr(_lokal, "parakeet_auffaellig", False)),
        },
        "qwen": {
            "text": qwen_text,
            "status": qwen_status,
            "authoritative": bool(kandidat.get("authoritative")),
            "reason": str(kandidat.get("reason") or ""),
        },
    }
