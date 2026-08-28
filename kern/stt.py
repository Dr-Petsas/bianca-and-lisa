"""Spracheingabe. STT_BASE gesetzt = lokaler Parakeet-Container (5090,
Claras bewaehrte Telefon-Engine + Fuzzy-Namens-Nachkorrektur), OHNE
ElevenLabs-Rueckfall (Chef 28.08.2026: "es geht nichts mehr zu elevenlabs").
Leer = ElevenLabs Scribe wie frueher. ``keywords`` (Komma-Liste, z. B.
Behandler-Nachnamen aus dem Tenant) gehen als Hotwords an die Nachkorrektur
im Container — der Scribe-Pfad ignoriert sie."""

from __future__ import annotations

import re

import httpx

from kern.config import ELEVENLABS_API_KEY, STT_BASE

# Clara-V7-Halluzinationsfilter (worker_mic_utils._is_stt_hallucination),
# angepasst ans Patiententelefon: "Tschuess"/"Vielen Dank"/"Okay" bleiben
# echte Antworten. Nur Atem-/Untertitel-Phantome und Token-Loops fallen.
_HALLU_RE = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"^\s*thank you[!\.\s]*$",
    r"^\s*thanks(?: for watching)?[!\.\s]*$",
    r"^\s*you[!\.\?\s]*$",
    r"^\s*bye[\s\-]*bye?[!\.\s]*$",
    r"^\s*hello[!\.\?\s]*$",
    r"^\s*subscribe[!\.\s]*$",
    r"^\s*see you (?:next time|later)[!\.\s]*$",
    r"^\s*ahem[!\.\s]*$",
    r"^\s*music[!\.\s]*$",
    r"^\s*\[?music\]?[!\.\s]*$",
    r"^\s*\.{1,6}\s*$",
    r"^\s*thank you[,!\.\s]*(?:dr|doctor|sir)?[,!\.\s]*$",
    r"^\s*thank you very much[!\.\s]*$",
    r"^\s*excuse me[,!\.\s]*$",
    r"^\s*tchau[,!\.\s]*$",
    r"^\s*ciao[,!\.\s]*$",
    r"^\s*bye[,!\.\s]*$",
    r".*untertitel.*(zdf|ard|amara|community|funk)",
    r".*\bamara\.org\b",
    r"^\s*konec[!\.,\s]*$",
    r"^\s*obrigad[ao][!\.\s]*$",
    r"^\s*c'est",
    r"^\s*voil[àa]",
))
_KURZ_OK = frozenset({
    "ja", "nein", "doch", "klar", "okay", "ok", "gut", "genau", "mhm",
    "hm", "hmm", "aha", "stop", "halt", "weiter", "nö", "noe", "jo",
    "joa", "jep", "nee", "näh", "naeh", "nix",
})

_CLIENT: httpx.Client | None = None


def _client() -> httpx.Client:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = httpx.Client(timeout=httpx.Timeout(15.0, connect=3.0))
    return _CLIENT


def _ist_halluzination(text: str) -> bool:
    """Clara-V7-Atem-/Untertitel-Waechter. True = Transkript verwerfen."""
    t = (text or "").strip()
    if not t:
        return True
    if any(0x0400 <= ord(c) < 0x0500 for c in t):
        return True
    stripped = re.sub(r"[\.!\?,;\s]+$", "", t.lower())
    if stripped in _KURZ_OK:
        return False
    if len(t) < 4:
        return True
    if any(p.match(t) for p in _HALLU_RE):
        return True
    toks = re.findall(r"[A-Za-zÄÖÜäöüß]+", t.lower())
    if len(toks) >= 3 and len(set(toks)) == 1:
        return True
    if len(toks) >= 5 and len(set(toks)) <= 2:
        return True
    if len(t) < 30 and re.search(r"[éèêàâóòôãáñç]", t):
        return True
    return False


def _sauber(text) -> str:
    text = " ".join(str(text or "").split()).strip()
    if _ist_halluzination(text):
        return ""
    return text


def _lokal(audio: bytes, *, mime: str, name: str, keywords: str = "") -> str:
    r = _client().post(
        f"{STT_BASE}/transcribe",
        files={"file": (name, audio, mime or "application/octet-stream")},
        data={"keywords": keywords} if keywords else None,
    )
    if r.status_code != 200:
        raise RuntimeError(f"stt_lokal_http_{r.status_code}")
    return _sauber(r.json().get("text"))


def transcribe(audio: bytes, *, mime: str = "audio/webm", name: str = "turn.webm",
               keywords: str = "") -> str:
    if not audio or len(audio) < 800:
        return ""
    if STT_BASE:
        return _lokal(audio, mime=mime, name=name, keywords=keywords)
    if not ELEVENLABS_API_KEY:
        return ""
    r = httpx.post(
        "https://api.elevenlabs.io/v1/speech-to-text",
        headers={"xi-api-key": ELEVENLABS_API_KEY},
        data={
            "model_id": "scribe_v2",
            "language_code": "de",
            "tag_audio_events": "false",
        },
        files={"file": (name, audio, mime or "application/octet-stream")},
        timeout=8.0,
    )
    if r.status_code != 200:
        raise RuntimeError(f"stt_http_{r.status_code}")
    return _sauber(r.json().get("text"))


def bereit() -> bool:
    return bool(STT_BASE or ELEVENLABS_API_KEY)


def engine_anzeige() -> str:
    """Fuer die Dock-/Health-Anzeige: wer hoert gerade zu?"""
    if STT_BASE:
        return "Parakeet (lokal)"
    return "ElevenLabs Scribe" if ELEVENLABS_API_KEY else "keine"
