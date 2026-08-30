"""Anruf-Audio in den Firebase Storage (W-CALLAUDIO 30.08.2026).

Das Pickadoc-Portal (docgendaweb, CallR-Seite) spielt je PhoneCall das Feld
``audioRecordingUrl`` ab. Beim alten ElevenLabs-Weg setzte die Cloud Function
diese URL selbst (MP3 unter clients/{clientId}/locations/{locationId}/
phoneCalls/{phoneCallId}.mp3 im Bucket docgenda.appspot.com, Download-URL
mit firebaseStorageDownloadTokens). Seit die Anrufe ueber Bianca laufen,
lud niemand mehr Audio hoch — die Abspiel-Knoepfe blieben stumm.

Dieses Modul baut den kompletten Anruf aus dem Mitschnitt (W-MITSCHNITT,
mitschnitt.anruf_wav), kodiert ihn per ffmpeg zu MP3 und laedt ihn auf
GENAU denselben Storage-Pfad wie die ElevenLabs-CF; die zurueckgegebene
Download-URL geht im post-Payload (agentprofil.call_abschliessen) als
``audioRecordingUrl`` an onPickadocPhoneCall.

Auth: Service-Account-JSON (FIREBASE_CREDENTIALS) -> selbstsigniertes
RS256-JWT -> OAuth2-Token (google-auth waere ein schwerer Zusatz-Stack,
cryptography + httpx reichen). Token wird prozessweit gecacht.

Nie werfend, laeuft nur in der hangup-Nacharbeit (Daemon-Thread) — der
Anruf-Pfad leidet nie. Notaus: CALL_AUDIO_UPLOAD=0.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from kern.config import FIREBASE_BUCKET, FIREBASE_CREDENTIALS

_SCOPE = "https://www.googleapis.com/auth/devstorage.read_write"
_TOKEN_URI_DEFAULT = "https://oauth2.googleapis.com/token"
_UPLOAD_BASE = "https://storage.googleapis.com/upload/storage/v1/b"
_DOWNLOAD_BASE = "https://firebasestorage.googleapis.com/v0/b"

_LOCK = threading.Lock()
_TOKEN: dict[str, Any] = {"wert": "", "bis": 0.0}


def _s(v: Any) -> str:
    return str(v or "").strip()


def an() -> bool:
    """Upload aktiv? Braucht den Service-Account-Key; Notaus per Env."""
    if os.environ.get("CALL_AUDIO_UPLOAD", "").strip().lower() in {"0", "false", "off", "no"}:
        return False
    return bool(FIREBASE_CREDENTIALS) and Path(FIREBASE_CREDENTIALS).is_file()


def anzeige() -> str:
    if an():
        return f"Anruf-Audio -> gs://{FIREBASE_BUCKET} (Portal-Player)"
    return "Anruf-Audio-Upload aus (kein Service-Account-Key)"


def _b64url(blob: bytes) -> str:
    return base64.urlsafe_b64encode(blob).decode("ascii").rstrip("=")


def _access_token() -> str:
    """OAuth2-Token aus dem Service-Account — gecacht bis kurz vor Ablauf."""
    with _LOCK:
        if _TOKEN["wert"] and _TOKEN["bis"] - time.time() > 120:
            return _TOKEN["wert"]

    sa = json.loads(Path(FIREBASE_CREDENTIALS).read_text(encoding="utf-8"))
    token_uri = _s(sa.get("token_uri")) or _TOKEN_URI_DEFAULT

    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    key = serialization.load_pem_private_key(
        sa["private_key"].encode("utf-8"), password=None)
    now = int(time.time())
    kopf = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode("utf-8"))
    claims = _b64url(json.dumps({
        "iss": sa["client_email"],
        "scope": _SCOPE,
        "aud": token_uri,
        "iat": now,
        "exp": now + 3600,
    }).encode("utf-8"))
    unterschrift = key.sign(f"{kopf}.{claims}".encode("ascii"),
                            padding.PKCS1v15(), hashes.SHA256())
    jwt = f"{kopf}.{claims}.{_b64url(unterschrift)}"

    r = httpx.post(token_uri, data={
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": jwt,
    }, timeout=15)
    r.raise_for_status()
    d = r.json()
    with _LOCK:
        _TOKEN["wert"] = _s(d.get("access_token"))
        _TOKEN["bis"] = time.time() + float(d.get("expires_in") or 3600)
        return _TOKEN["wert"]


def _mp3(wav: bytes) -> bytes | None:
    """PCM-WAV -> MP3 (mono, 64 kbit/s — Sprachqualitaet, kleine Dateien).
    ffmpeg liegt im App-Image; fehlt es (nackter Dev-Lauf), None."""
    try:
        p = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
             "-codec:a", "libmp3lame", "-b:a", "64k", "-ac", "1",
             "-f", "mp3", "pipe:1"],
            input=wav, capture_output=True, timeout=120,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    return p.stdout if p.returncode == 0 and p.stdout else None


def _upload(pfad: str, blob: bytes, ctype: str) -> str:
    """Multipart-Upload in den Bucket, Download-Token als Metadatum —
    dieselbe URL-Form, die firebase-admin getDownloadURL() liefert."""
    dl_token = str(uuid.uuid4())
    meta = json.dumps({
        "name": pfad,
        "contentType": ctype,
        "metadata": {"firebaseStorageDownloadTokens": dl_token},
    })
    grenze = "grenze" + uuid.uuid4().hex
    body = (
        f"--{grenze}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{meta}\r\n--{grenze}\r\nContent-Type: {ctype}\r\n\r\n"
    ).encode("utf-8") + blob + f"\r\n--{grenze}--\r\n".encode("ascii")

    r = httpx.post(
        f"{_UPLOAD_BASE}/{FIREBASE_BUCKET}/o",
        params={"uploadType": "multipart"},
        headers={
            "Authorization": f"Bearer {_access_token()}",
            "Content-Type": f"multipart/related; boundary={grenze}",
        },
        content=body, timeout=60,
    )
    if r.status_code < 200 or r.status_code >= 300:
        print(f"anrufaudio upload -> http {r.status_code}: {r.text[:200]}", flush=True)
        return ""
    return (f"{_DOWNLOAD_BASE}/{FIREBASE_BUCKET}/o/{quote(pfad, safe='')}"
            f"?alt=media&token={dl_token}")


def hochladen(sit: dict) -> str:
    """Kompletter Anruf (Mitschnitt-Zusammenschnitt) als MP3 in den Storage.

    Gibt die Download-URL fuer audioRecordingUrl zurueck — oder "" (kein
    Key, kein Mitschnitt, kein PhoneCall-Datensatz, Upload-Fehler). Nie
    werfend; gedacht fuer die hangup-Nacharbeit NACH mitschnitt.ende."""
    try:
        if not an():
            return ""
        pcid = _s(sit.get("phoneCallId"))
        t = sit.get("tenant") or {}
        client_id = _s(t.get("clientId") if isinstance(t, dict) else "")
        location_id = _s(t.get("locationId") if isinstance(t, dict) else "")
        if not (pcid and client_id and location_id):
            return ""

        from kern import mitschnitt
        stimme = _s(sit.get("stimme")).lower() or "bianca"
        wav = mitschnitt.anruf_wav(stimme, _s(sit.get("id")))
        if not wav:
            return ""
        mp3 = _mp3(wav)
        blob, endung, ctype = (
            (mp3, "mp3", "audio/mpeg") if mp3 else (wav, "wav", "audio/wav"))
        pfad = (f"clients/{client_id}/locations/{location_id}"
                f"/phoneCalls/{pcid}.{endung}")
        url = _upload(pfad, blob, ctype)
        if url:
            print(f"anrufaudio hochgeladen {pfad} ({len(blob)} B)", flush=True)
        return url
    except Exception as e:
        print(f"anrufaudio fail: {type(e).__name__}: {e}", flush=True)
        return ""
