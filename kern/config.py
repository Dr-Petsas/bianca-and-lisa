"""Lokale Konfiguration. Liest nur diese .env — startet keine fremden Dienste."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
# override=True: die .env dieses Repos ist die EINE Wahrheit — sonst bleibt
# ein alter Prozess-/setx-Wert (z. B. TTS_BASE=:8210) stehen und der Dienst
# spricht gegen den falschen Container (Vorfall 28.08.2026, kein Audio).
# utf-8-sig: PowerShell schreibt .env gern MIT BOM — dotenv las den ersten
# Schluessel dann als '\ufeffWRITE_LIVE' und das Live-Schreiben war still aus
# (Vorfall 28.08.2026 nachts: Buchungen liefen unbemerkt als Trockenlauf).
load_dotenv(ROOT / ".env", override=True, encoding="utf-8-sig")


def _peek_key(path: Path, name: str) -> str:
    """Eine Zeile aus fremder .env lesen, ohne die ganze Datei zu laden."""
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#") or "=" not in raw:
                continue
            k, _, v = raw.partition("=")
            if k.strip() == name:
                return v.strip().strip('"').strip("'")
    except OSError:
        return ""
    return ""


def _s(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def _b(name: str, default: bool = False) -> bool:
    raw = _s(name)
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


PORT = int(_s("PORT", "8095") or "8095")
# Bianca (eingehende Anrufe) läuft als eigener Prozess neben Lisa.
# Port-Landkarte: Clara 8091, v6 8092, Clara-dev 8093, DemoClara 8094,
# Lisa 8095 — Bianca bekommt 8096.
BIANCA_PORT = int(_s("BIANCA_PORT", "8096") or "8096")
DEFAULT_TENANT = _s("DEFAULT_TENANT", "meddent") or "meddent"
DEV_PHONE = "".join(c for c in _s("DEV_PHONE", "01776004600") if c.isdigit()) or "01776004600"
WRITE_LIVE = _b("WRITE_LIVE", False)

LLM_BASE = _s("LLM_BASE", "http://100.77.30.98:8000/v1").rstrip("/")
LLM_MODEL = _s("LLM_MODEL", "qwen3.6:35b-a3b")
LLM_API_KEY = _s("LLM_API_KEY", "local") or "local"

ELEVENLABS_API_KEY = _s("ELEVENLABS_API_KEY") or _peek_key(
    Path(r"F:\MAS-2\backend\.env"), "ELEVENLABS_API_KEY"
) or _peek_key(Path(r"F:\Clara-Voice\.env"), "ELEVENLABS_API_KEY")

# Lokales TTS auf der 5090 (tts_serve/): GESETZT = NUR der lokale Container
# spricht, OHNE ElevenLabs-Rueckfall (Chef 27.08.2026 — Fehler sollen in der
# Testphase hoerbar sein). Leer = ElevenLabs wie bisher (byte-identisch).
TTS_BASE = _s("TTS_BASE").rstrip("/")
# Lokales STT auf der 5090 (stt_serve/, deutscher Conformer): GESETZT = JEDE
# Transkription geht an den Container, OHNE ElevenLabs-Rueckfall
# (Chef 28.08.2026: "es geht nichts mehr zu elevenlabs"). Leer = Scribe.
STT_BASE = _s("STT_BASE").rstrip("/")
# Stimmname im Container (Referenz-WAV in tts_serve/stimmen/). Leer = "lisa";
# der Bianca-Prozess setzt sich beim Start selbst auf "bianca".
TTS_VOICE = _s("TTS_VOICE")
ELEVENLABS_VOICE_ID = _s("ELEVENLABS_VOICE_ID", "1iF3vHdwHKuVKSPDK23Z")
# Biancas Stimme = die des laufenden ElevenLabs-Agenten "Med Dent Zahnklinik"
# (BIANCA_AGENT_ID, abgefragt 27.08.2026) — dieselbe Stimme wie Clara.
BIANCA_VOICE_ID = _s("BIANCA_VOICE_ID", "cgSgspJ2msm6clMCkdW9")
ELEVENLABS_TTS_MODEL = _s("ELEVENLABS_TTS_MODEL", "eleven_flash_v2_5")

CF_BASE = _s("PICKADOC_CF_BASE", "https://europe-west3-docgenda.cloudfunctions.net").rstrip("/")
MAS_URL = _s("MAS_URL", "http://127.0.0.1:4000").rstrip("/")

TENANTS_DIR = ROOT / "tenants"
DATA_DIR = ROOT / ".data"
WEB_DIR = ROOT / "web"
BIANCA_WEB_DIR = ROOT / "bianca_web"
