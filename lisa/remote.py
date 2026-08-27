"""Lokaler Fernsteuerungs-Draht NUR fuer dieses Repo. Kein MAS, kein Clara."""

from __future__ import annotations

import json
import secrets
import time
from pathlib import Path
from typing import Any

from lisa.config import DATA_DIR, ROOT

STORE = DATA_DIR / "remote.json"
TOKEN_FILE = DATA_DIR / "remote_token.txt"
INBOX = ROOT / "_posteingang"
MAX_BYTES = 24 * 1024 * 1024


def _leer() -> dict[str, Any]:
    return {"messages": [], "board": {"text": "", "updatedAt": 0}}


def _laden() -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not STORE.is_file():
        return _leer()
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _leer()


def _speichern(doc: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def token() -> str:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if TOKEN_FILE.is_file():
        t = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if t:
            return t
    t = secrets.token_urlsafe(18)
    TOKEN_FILE.write_text(t, encoding="utf-8")
    return t


def token_ok(got: str, von_hier: bool) -> bool:
    if von_hier:
        return True
    want = token().encode("utf-8")
    have = (got or "").encode("utf-8")
    if not have or len(have) != len(want):
        return False
    return secrets.compare_digest(have, want)


def state(limit: int = 120) -> dict[str, Any]:
    doc = _laden()
    msgs = list(doc.get("messages") or [])[-max(1, min(limit, 200)):]
    return {
        "ok": True,
        "messages": msgs,
        "board": doc.get("board") or {"text": "", "updatedAt": 0},
        "hint": "Lisa · nur Grok · nur dieses Projekt",
    }


def add_message(*, role: str, text: str, speaker: str = "") -> dict[str, Any]:
    raw = str(text or "").strip()
    clean = raw[:8000] if role == "agent" else " ".join(raw.split()).strip()[:8000]
    if not clean:
        return {"ok": False, "reason": "text_required"}
    doc = _laden()
    msg = {
        "id": secrets.token_hex(8),
        "role": "agent" if role == "agent" else "user",
        "text": clean[:8000],
        "status": "fertig" if role == "agent" else "neu",
        "createdAt": int(time.time() * 1000),
    }
    if msg["role"] == "agent":
        msg["speaker"] = speaker or "grok"
    doc.setdefault("messages", []).append(msg)
    _speichern(doc)
    return {"ok": True, "id": msg["id"]}


def pending() -> list[dict[str, Any]]:
    return [m for m in (_laden().get("messages") or []) if m.get("role") == "user" and m.get("status") == "neu"]


def ack(ids: list[str], status: str) -> None:
    want = {str(i) for i in ids}
    doc = _laden()
    for m in doc.get("messages") or []:
        if m.get("id") in want:
            m["status"] = status
    _speichern(doc)


def set_board(text: str) -> None:
    doc = _laden()
    doc["board"] = {"text": str(text or "").strip()[:4000], "updatedAt": int(time.time() * 1000)}
    _speichern(doc)


def save_file(*, name: str, data_b64: str, note: str = "") -> dict[str, Any]:
    roh = str(data_b64 or "")
    b64 = roh.split(",", 1)[1] if "," in roh else roh
    if not b64.strip():
        return {"ok": False, "reason": "file_required"}
    import base64
    try:
        buf = base64.b64decode(b64)
    except Exception:
        return {"ok": False, "reason": "file_broken"}
    if not buf:
        return {"ok": False, "reason": "file_empty"}
    if len(buf) > MAX_BYTES:
        return {"ok": False, "reason": "file_too_big"}
    INBOX.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in Path(name or "datei").name)[:80] or "datei"
    stempel = time.strftime("%Y%m%d_%H%M%S")
    ziel = INBOX / f"{stempel}_{safe}"
    ziel.write_bytes(buf)
    text = f"[DATEI] {ziel.name} ({max(1, len(buf)//1024)} KB) liegt unter: {ziel}"
    if note.strip():
        text += f"\nDazu: {note.strip()}"
    text += "\nLies die Datei von diesem Pfad. Nur Projekt F:\\Bianca&Lisa TelefonKI."
    msg = add_message(role="user", text=text)
    return {"ok": True, "path": str(ziel), "messageId": msg.get("id") or ""}
