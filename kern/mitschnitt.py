"""Anruf-Mitschnitt (W-MITSCHNITT 30.08.2026): jedes Gespräch landet als
Ordner unter .data/anrufe/<stimme>/<sessionId>/ — Manifest (anruf.json) plus
Audio je Zug (Anrufer-Aufnahme UND gesprochene Antwort). Das Dock zeigt die
Liste unter /anrufe mit Transkript, Abspiel-Knöpfen und allen Zeiten.

Grundsätze:
- Jeder Zug wird SOFORT auf Platte geschrieben (Absturz mitten im Anruf
  verliert höchstens den laufenden Zug) — nicht erst beim Auflegen wie die
  Sitzungs-Ablage. Kein 24er-Deckel: das Manifest trägt ALLE Züge.
- Stream-Audio (Phase 2) ist beim Zug-Ende oft noch nicht fertig gerendert:
  der Eintrag merkt sich die URL als "offen", jeder spätere Flush und das
  Gesprächs-Ende (ende()) lösen sie gegen die fertigen Bytes ein.
- Fehler werden geloggt und verschluckt — der Anruf-Pfad leidet nie.
- Notaus: MITSCHNITT=0 => kein Ordner, kein Byte, Verhalten wie vorher.
"""

from __future__ import annotations

import json
import os
import re
import struct
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kern.config import DATA_DIR

_LOCK = threading.Lock()
_DATEI_RE = re.compile(r"^[a-z0-9_]+\.(wav|mp3|webm|m4a|ogg)$")


def an() -> bool:
    return str(os.environ.get("MITSCHNITT", "1")).strip().lower() not in {"0", "false", "off", "no"}


def _wurzel() -> Path:
    return DATA_DIR / "anrufe"


def _stimme(sit: dict) -> str:
    return str(sit.get("stimme") or "stimme").strip().lower() or "stimme"


def ordner(sit: dict) -> Path | None:
    sid = str(sit.get("id") or "").strip()
    if not sid:
        return None
    return _wurzel() / _stimme(sit) / sid


def _jetzt() -> str:
    return datetime.now(timezone.utc).isoformat()


def _offset_ms(sit: dict) -> int:
    try:
        t0 = datetime.fromisoformat(str(sit.get("startedAt")))
        return max(0, int((datetime.now(timezone.utc) - t0).total_seconds() * 1000))
    except (TypeError, ValueError):
        return 0


def _wav_ms(blob: bytes) -> int | None:
    """Spieldauer eines eigenen PCM16-WAVs (Header 44 Byte) in ms."""
    if not blob or blob[:4] != b"RIFF" or len(blob) <= 44:
        return None
    try:
        rate = struct.unpack_from("<I", blob, 24)[0]
        kanaele = struct.unpack_from("<H", blob, 22)[0]
        breite = struct.unpack_from("<H", blob, 34)[0] // 8
        je_s = rate * kanaele * max(1, breite)
        return int((len(blob) - 44) * 1000 // je_s) if je_s else None
    except struct.error:
        return None


def _endung(blob: bytes, mime: str) -> str:
    if blob[:4] == b"RIFF":
        return "wav"
    if blob[:3] == b"ID3" or (len(blob) > 1 and blob[0] == 0xFF and (blob[1] & 0xE0) == 0xE0):
        return "mp3"
    m = (mime or "").lower()
    if "mp4" in m or "m4a" in m or "aac" in m:
        return "m4a"
    if "ogg" in m or "opus" in m:
        return "ogg"
    return "webm"


def _laden(pfad: Path) -> dict[str, Any] | None:
    try:
        return json.loads((pfad / "anruf.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _schreiben(pfad: Path, manifest: dict[str, Any]) -> None:
    (pfad / "anruf.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")


def _manifest(sit: dict, pfad: Path) -> dict[str, Any]:
    alt = _laden(pfad)
    if alt is not None:
        return alt
    return {
        "id": sit.get("id") or "",
        "stimme": sit.get("stimme") or "",
        "tenantId": sit.get("tenantId") or "",
        "startedAt": sit.get("startedAt") or _jetzt(),
        "endedAt": None,
        "dauerMs": None,
        "zuege": [],
    }


def _zusammenfassung(manifest: dict, sit: dict) -> None:
    """Kopfdaten bei jedem Flush aus der Sitzung auffrischen — die Liste
    zeigt Name/Ergebnis, ohne jede Manifest-Datei ganz zu verstehen."""
    pat = sit.get("patient") or {}
    s = sit.get("sammler") or {}
    name = pat.get("name") or " ".join(x for x in (s.get("vorname"), s.get("nachname")) if x).strip()
    manifest["patientName"] = name or ""
    manifest["auftrag"] = sit.get("auftrag") or ""
    for k in ("lastBook", "lastCancel", "lastMove", "lastNote", "lastCreate"):
        if sit.get(k) is not None:
            manifest[k] = sit.get(k)
    if sit.get("praxisNotiz"):
        manifest["praxisNotiz"] = sit["praxisNotiz"]
    if sit.get("tools"):
        manifest["tools"] = sit.get("tools")


def _audio_einloesen(manifest: dict, pfad: Path, dienst) -> None:
    """Offene Stream-URLs gegen fertige Bytes tauschen (jeder Flush probiert
    es erneut — spätestens ende() wartet aufs Render-Ende)."""
    holen = getattr(dienst, "audio_bytes_fertig", None)
    if not callable(holen):
        return
    for zug in manifest.get("zuege") or []:
        for ein in zug.get("audioOut") or []:
            url = ein.get("url")
            if not url or ein.get("datei"):
                continue
            try:
                blob = holen(url)
            except Exception:
                blob = None
            if not blob:
                continue
            datei = str(ein.get("ziel") or f"z{zug.get('nr', 0):03d}_stimme.wav")
            try:
                (pfad / datei).write_bytes(blob)
            except OSError:
                continue
            ein["datei"] = datei
            ein["ms"] = _wav_ms(blob)
            ein.pop("url", None)
            ein.pop("ziel", None)


def eingang(sit: dict, blob: bytes, mime: str = "") -> None:
    """Anrufer-Audio des laufenden Zugs sichern (VOR der Antwort): die Datei
    wird gemerkt und vom nächsten zug()-Eintrag übernommen."""
    if not an() or not blob:
        return
    pfad = ordner(sit)
    if pfad is None:
        return
    try:
        with _LOCK:
            pfad.mkdir(parents=True, exist_ok=True)
            manifest = _manifest(sit, pfad)
            nr = len(manifest.get("zuege") or []) + 1
            teil = len(sit.get("_mitEin") or [])
            stamm = f"z{nr:03d}_anrufer_{teil + 1}" if teil else f"z{nr:03d}_anrufer"
            datei = f"{stamm}.{_endung(blob, mime)}"
            (pfad / datei).write_bytes(blob)
        # Liste, nicht Einzelwert: bei W-HALBSATZ (gehaltener Satz) liefern
        # zwei Aufnahmen EINEN Zug — beide gehören ins Manifest.
        sit.setdefault("_mitEin", []).append({"datei": datei, "ms": _wav_ms(blob), "zeit": _jetzt()})
    except Exception as e:
        print(f"mitschnitt-eingang fail {e}", flush=True)


def zug(sit: dict, dienst, *, art: str, text_in: str = "", text: str = "",
        timings: dict | None = None, waechter: list | None = None,
        audio_url: str = "", vorab_urls: list[str] | None = None,
        book: Any = None, frage: str = "") -> None:
    """Einen gesprochenen Zug ins Manifest schreiben — sofort, nicht erst
    beim Auflegen. Audio kommt aus der Dienst-Ablage (RAM) auf die Platte;
    noch laufende Streams bleiben als "offen" markiert."""
    if not an():
        return
    pfad = ordner(sit)
    if pfad is None:
        return
    try:
        with _LOCK:
            pfad.mkdir(parents=True, exist_ok=True)
            manifest = _manifest(sit, pfad)
            nr = len(manifest.get("zuege") or []) + 1
            urls = [u for u in (vorab_urls or []) if u]
            if audio_url and audio_url not in urls:
                urls.append(audio_url)
            raus: list[dict[str, Any]] = []
            for i, url in enumerate(urls):
                ziel = f"z{nr:03d}_stimme_{i + 1}.wav" if len(urls) > 1 else f"z{nr:03d}_stimme.wav"
                raus.append({"url": url, "ziel": ziel})
            ein = sit.pop("_mitEin", None)
            eintrag: dict[str, Any] = {
                "nr": nr,
                "art": art,
                "zeit": _jetzt(),
                "offsetMs": _offset_ms(sit),
                "textIn": text_in,
                "text": text,
                "timings": timings or {},
            }
            if waechter:
                eintrag["waechter"] = waechter
            if ein:
                eintrag["audioIn"] = ein
            if raus:
                eintrag["audioOut"] = raus
            if book:
                eintrag["book"] = book
            if frage:
                eintrag["frage"] = frage
            manifest.setdefault("zuege", []).append(eintrag)
            _audio_einloesen(manifest, pfad, dienst)
            _zusammenfassung(manifest, sit)
            _schreiben(pfad, manifest)
    except Exception as e:
        print(f"mitschnitt-zug fail {e}", flush=True)


def ende(sit: dict, dienst, *, warte_s: float = 10.0) -> None:
    """Beim Auflegen (in der Hangup-Nacharbeit, nie auf dem Anruf-Pfad):
    auf offene Streams warten, Rest-Audio einlösen, Ende-Zeit stempeln."""
    if not an():
        return
    pfad = ordner(sit)
    if pfad is None or not (pfad / "anruf.json").is_file():
        return
    try:
        frist = time.monotonic() + max(0.0, warte_s)
        while True:
            with _LOCK:
                manifest = _manifest(sit, pfad)
                _audio_einloesen(manifest, pfad, dienst)
                offen = any(
                    ein.get("url") and not ein.get("datei")
                    for z in manifest.get("zuege") or []
                    for ein in z.get("audioOut") or []
                )
                if not offen or time.monotonic() >= frist:
                    manifest["endedAt"] = _jetzt()
                    try:
                        t0 = datetime.fromisoformat(str(manifest.get("startedAt")))
                        t1 = datetime.fromisoformat(str(manifest["endedAt"]))
                        manifest["dauerMs"] = max(0, int((t1 - t0).total_seconds() * 1000))
                    except (TypeError, ValueError):
                        pass
                    for z in manifest.get("zuege") or []:
                        if z.get("art") == "hangup":
                            break
                    else:
                        hz = next((z for z in reversed(sit.get("zuege") or []) if z.get("art") == "hangup"), None)
                        if hz:
                            manifest.setdefault("zuege", []).append({
                                "nr": len(manifest.get("zuege") or []) + 1,
                                "art": "hangup",
                                "zeit": manifest["endedAt"],
                                "offsetMs": manifest.get("dauerMs") or 0,
                                "textIn": "",
                                "text": "",
                                "note": hz.get("note") or "",
                                "timings": {},
                            })
                    _zusammenfassung(manifest, sit)
                    _schreiben(pfad, manifest)
                    return
            time.sleep(0.25)
    except Exception as e:
        print(f"mitschnitt-ende fail {e}", flush=True)


# ---- Lesen (API-Routen) -----------------------------------------------------

def liste(stimme: str, limit: int = 200) -> list[dict[str, Any]]:
    """Kopfzeilen aller Mitschnitte, neueste zuerst — fürs Dock."""
    basis = _wurzel() / (stimme or "").strip().lower()
    if not basis.is_dir():
        return []
    aus: list[dict[str, Any]] = []
    for d in basis.iterdir():
        if not d.is_dir():
            continue
        m = _laden(d)
        if not m:
            continue
        zuege = m.get("zuege") or []
        aus.append({
            "id": m.get("id") or d.name,
            "startedAt": m.get("startedAt") or "",
            "endedAt": m.get("endedAt"),
            "dauerMs": m.get("dauerMs"),
            "patientName": m.get("patientName") or "",
            "zuege": len(zuege),
            "lastBook": m.get("lastBook"),
            "lastCancel": m.get("lastCancel"),
            "lastMove": m.get("lastMove"),
            "praxisNotiz": m.get("praxisNotiz") or "",
            "offen": m.get("endedAt") is None,
        })
    aus.sort(key=lambda e: e.get("startedAt") or "", reverse=True)
    return aus[:max(1, limit)]


def laden(stimme: str, sid: str) -> dict[str, Any] | None:
    sid = (sid or "").strip()
    if not re.fullmatch(r"[0-9a-f]{8,32}", sid):
        return None
    return _laden(_wurzel() / (stimme or "").strip().lower() / sid)


def audio_pfad(stimme: str, sid: str, datei: str) -> Path | None:
    sid = (sid or "").strip()
    if not re.fullmatch(r"[0-9a-f]{8,32}", sid) or not _DATEI_RE.fullmatch(datei or ""):
        return None
    p = _wurzel() / (stimme or "").strip().lower() / sid / datei
    return p if p.is_file() else None


def loeschen(stimme: str, sid: str) -> bool:
    sid = (sid or "").strip()
    if not re.fullmatch(r"[0-9a-f]{8,32}", sid):
        return False
    d = _wurzel() / (stimme or "").strip().lower() / sid
    if not d.is_dir():
        return False
    try:
        for f in d.iterdir():
            f.unlink()
        d.rmdir()
        return True
    except OSError:
        return False
