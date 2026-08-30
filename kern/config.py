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
# Whisper-GPU-STT auf dem Dev-Rechner (W-STT-WHISPER 30.08.2026): GESETZT =
# Transkription laeuft ZUERST ueber den Whisper-Stream-Container (WebSocket,
# pickadoc-stt, large-v3 auf der Dev-GPU, via Tailscale). Ist er nicht
# erreichbar, faellt der Zug automatisch auf STT_BASE (Parakeet) zurueck —
# Chef 30.08.2026. NIE auf ElevenLabs. Leer = Verhalten wie vorher.
#   vom pickadoc1-App-Container: STT_WHISPER_BASE=ws://100.81.214.94:8092
STT_WHISPER_BASE = _s("STT_WHISPER_BASE").rstrip("/")
STT_WHISPER_KEY = _s("STT_WHISPER_KEY", "pickadoc-stt-dev-key")
# Stimmname im Container (Referenz-WAV in tts_serve/stimmen/). Leer = "lisa";
# der Bianca-Prozess setzt sich beim Start selbst auf "bianca".
TTS_VOICE = _s("TTS_VOICE")
ELEVENLABS_VOICE_ID = _s("ELEVENLABS_VOICE_ID", "1iF3vHdwHKuVKSPDK23Z")
# Biancas Stimme = die des laufenden ElevenLabs-Agenten "Med Dent Zahnklinik"
# (BIANCA_AGENT_ID, abgefragt 27.08.2026) — dieselbe Stimme wie Clara.
BIANCA_VOICE_ID = _s("BIANCA_VOICE_ID", "cgSgspJ2msm6clMCkdW9")
ELEVENLABS_TTS_MODEL = _s("ELEVENLABS_TTS_MODEL", "eleven_flash_v2_5")

CF_BASE = _s("PICKADOC_CF_BASE", "https://europe-west3-docgenda.cloudfunctions.net").rstrip("/")
# W-MANDANT (30.08.2026): Mandant anhand der ANGERUFENEN Nummer aus der
# Pickadoc-DB laden — dieselbe Cloud Function wie der alte phone_agent
# (onPickadocPhoneCall, phase=pre; Auth: Shared Secret als Bearer + x-api-key).
# Token-Fallback: peek auf die phone_agent-.env, wie beim ElevenLabs-Key.
PHONE_CALL_URL = _s("PICKADOC_PHONE_CALL_URL").rstrip("/") or f"{CF_BASE}/onPickadocPhoneCall"
PHONE_CALL_TOKEN = _s("PICKADOC_PHONE_CALL_API_TOKEN") or _peek_key(
    Path(r"D:\dev\Dr-Petsas\phone_agent\.env"), "PICKADOC_PHONE_CALL_API_TOKEN")
# Achtung: das echte Secret BEGINNT mit '#' (geprueft 30.08.2026 gegen den
# Firebase Secret Manager) — in einer env_file fuer Docker Compose muss der
# Wert deshalb in Anfuehrungszeichen stehen, sonst schneidet Compose ihn
# als Kommentar ab und die CF antwortet 401 "missing API token".
PHONE_CALL_TOKEN = PHONE_CALL_TOKEN.strip('"').strip("'")
# Anruf-Audio ins Portal (W-CALLAUDIO 30.08.2026): das Gespraechs-MP3 geht
# auf denselben Storage-Pfad wie beim alten ElevenLabs-Weg, die Download-URL
# als audioRecordingUrl in den PhoneCall (Abspiel-Knopf der CallR-Seite).
# Key-Suche: 1. FIREBASE_CREDENTIALS (Pfad), 2. secrets/ in diesem Repo
# (Container-Mount), 3. peek auf die phone_agent-.env (nur Dev-Rechner).
_fb = _s("FIREBASE_CREDENTIALS")
if not _fb:
    _kandidat = ROOT / "secrets" / "docgenda-service-account.json"
    _fb = str(_kandidat) if _kandidat.is_file() else _peek_key(
        Path(r"D:\dev\Dr-Petsas\phone_agent\.env"), "PICKADOC_FIREBASE_CREDENTIALS")
FIREBASE_CREDENTIALS = _fb
FIREBASE_BUCKET = _s("FIREBASE_STORAGE_BUCKET", "docgenda.appspot.com")
MAS_URL = _s("MAS_URL", "http://127.0.0.1:4000").rstrip("/")
# Praxisgedächtnis (W-GEDAECHTNIS 29.08.2026): Gesprächs-Reports an
# POST {MAS_URL}/brain/events, Anrufer-Kontext von /brain/caller-context.
# Der Service-Token wird nur gebraucht, wenn das MAS Auth erzwingt — dann
# (wie beim ElevenLabs-Key) direkt aus der MAS-.env gelesen. Die Client-Id
# ist der Firebase-Mandant der Praxis (MAS-Default, siehe MAS /health).
MAS_TOKEN = _s("MAS_TOKEN") or _peek_key(Path(r"F:\MAS-2\backend\.env"), "MAS_SERVICE_TOKEN")
MAS_CLIENT_ID = _s("MAS_CLIENT_ID", "MEe4ZQHEzOPzLcexyhdT")

TENANTS_DIR = ROOT / "tenants"
DATA_DIR = ROOT / ".data"
WEB_DIR = ROOT / "web"
BIANCA_WEB_DIR = ROOT / "bianca_web"
