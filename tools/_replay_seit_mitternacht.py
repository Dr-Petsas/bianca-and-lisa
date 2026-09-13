"""Alle Bianca-Anrufe seit Mitternacht (CEST): Audio durch heutige Pipeline.

Schreibt NIE in den Kalender. Vorab/Hallo landet in antwort_heute.
"""

from __future__ import annotations

import json
import os
import re
import signal
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

os.environ["WRITE_LIVE"] = "0"
os.environ["MITSCHNITT"] = "0"
os.environ["MAS_GEDAECHTNIS"] = "0"
os.environ["CALL_AUDIO_UPLOAD"] = "0"

_APP = Path("/app") if Path("/app/bianca").is_dir() else Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_APP))

from kern import calendar, patients, stt
from kern.config import DATA_DIR

calendar.WRITE_LIVE = False
patients.WRITE_LIVE = False

from bianca import agent, hintergrund, session
from bianca import verwalten
from kern import filler, motive

hintergrund.anstossen = lambda *a, **k: None
hintergrund.kartei_von_anrufer = lambda *a, **k: None
motive.anstossen = lambda *a, **k: None
verwalten._notiz_schreiben = lambda *a, **k: None
session.sichern = lambda *a, **k: None

_WURZEL = Path(os.environ.get("REPLAY_ROOT") or (DATA_DIR / "anrufe" / "bianca"))
# 08.09.2026 00:00 CEST
_AB = datetime(2026, 9, 7, 22, 0, 0, tzinfo=timezone.utc)
_TEL = re.compile(r"(?:\+?\d[\d\s/-]{6,}\d)")


def _s(v) -> str:
    return " ".join(str(v or "").split()).strip()


def _mask(t: str) -> str:
    return _TEL.sub(lambda m: m.group(0)[:3] + "…" if len(m.group(0)) > 6 else "…", t or "")


def _dt(s: str) -> datetime | None:
    t = (s or "").strip()
    if not t:
        return None
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        return None


def _audio_datei(ein) -> str:
    if isinstance(ein, list) and ein:
        return _s(ein[0].get("datei"))
    if isinstance(ein, dict):
        return _s(ein.get("datei"))
    return ""


def _mime(name: str) -> str:
    n = name.lower()
    if n.endswith(".wav"):
        return "audio/wav"
    if n.endswith(".mp3"):
        return "audio/mpeg"
    if n.endswith(".m4a"):
        return "audio/mp4"
    if n.endswith(".ogg"):
        return "audio/ogg"
    return "audio/webm"


def _mit_frist(sek: int, fn):
    def _kill(signum, frame):
        raise TimeoutError(f">{sek}s")
    alt = signal.signal(signal.SIGALRM, _kill)
    signal.alarm(sek)
    try:
        return fn()
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, alt)


def _anrufer_aus(m: dict) -> dict:
    """Diese Nacht-Anrufe kamen mit CF-pre (Petsas). Manifest speichert das nicht."""
    if isinstance(m.get("anrufer"), dict) and m["anrufer"].get("nachname"):
        return dict(m["anrufer"])
    name = _s(m.get("patientName"))
    teile = name.split()
    if len(teile) < 2:
        return {}
    return {
        "vorname": teile[0],
        "nachname": " ".join(teile[1:]),
        "geschlecht": "male" if teile[0].casefold() == "michael" else "",
        "telefon": "+491776004600",
        "patientId": _s(m.get("patientId")),
    }


def _anrufe() -> list[dict]:
    aus = []
    if not _WURZEL.is_dir():
        return aus
    for d in _WURZEL.iterdir():
        p = d / "anruf.json"
        if not p.is_file():
            continue
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        start = _dt(m.get("startedAt") or "")
        if not start or start < _AB:
            continue
        zuege = [z for z in (m.get("zuege") or []) if isinstance(z, dict)]
        aus.append({
            "sid": d.name,
            "started": _s(m.get("startedAt"))[:19],
            "name": _s(m.get("patientName")),
            "anrufer": _anrufer_aus(m),
            "zuege": zuege,
            "ordner": d,
        })
    aus.sort(key=lambda e: e["started"])
    return aus


def _start(anrufer: dict) -> dict:
    sit = session.neu(tenant_id="meddent")
    sit["messages"] = [{"role": "assistant", "content": "Guten Tag."}]
    if anrufer:
        sit["anrufer"] = dict(anrufer)
    return sit


def main() -> int:
    anrufe = _anrufe()
    print(f"anrufe={len(anrufe)} wurzel={_WURZEL} ab={_AB.isoformat()}", flush=True)
    rows = []
    n = 0
    for a in anrufe:
        sit = _start(a.get("anrufer") or {})
        for i, z in enumerate(a["zuege"]):
            if z.get("art") != "listen":
                continue
            datei = _audio_datei(z.get("audioIn"))
            blob = b""
            if datei and (a["ordner"] / datei).is_file():
                blob = (a["ordner"] / datei).read_bytes()
            n += 1
            stt_heute = ""
            err = ""
            if blob:
                try:
                    stt_heute = _mit_frist(20, lambda: stt.transcribe(
                        blob, mime=_mime(datei), name=datei,
                        keywords="Petsas,Patrikis,Nikolaou",
                    ))
                except Exception as ex:
                    err = f"stt:{type(ex).__name__}"
                    print(f"{n} STT fail {a['sid'][:8]} {ex}", flush=True)
            spoken = stt_heute or _s(z.get("textIn"))
            vorab_teile: list[str] = []
            antwort_heute = ""
            try:
                if spoken:
                    ant = _mit_frist(25, lambda: agent.user_turn(
                        sit, spoken, vorab=vorab_teile.append,
                    ))
                    job = _s((ant or {}).get("text"))
                    antwort_heute = filler.transkript_mund(vorab_teile, "", job)
                    if job:
                        sit.setdefault("messages", []).append(
                            {"role": "assistant", "content": antwort_heute or job}
                        )
            except Exception as ex:
                err = (err + " " if err else "") + f"zug:{type(ex).__name__}"
                print(f"{n} ZUG fail {a['sid'][:8]}\n{traceback.format_exc()[-400:]}", flush=True)
            tin = _s(z.get("textIn"))
            txt = _s(z.get("text"))
            rows.append({
                "nr": n,
                "sid": a["sid"][:8],
                "wann": a["started"],
                "score": 0,
                "input_orig": _mask(tin),
                "stt_heute": _mask(stt_heute),
                "antwort_orig": _mask(txt),
                "antwort_heute": _mask(antwort_heute),
                "stt_gleich": _s(stt_heute).lower() == tin.lower() if stt_heute else False,
                "antwort_gleich": _s(antwort_heute).lower() == txt.lower() if antwort_heute else False,
                "frage": _s(z.get("frage")),
                "fehler": err,
            })
            print(
                f"{n} {a['sid'][:8]} stt={'=' if rows[-1]['stt_gleich'] else '!'} "
                f"ant={'=' if rows[-1]['antwort_gleich'] else '!'}",
                flush=True,
            )

    out = Path(os.environ.get("REPLAY_OUT") or "/tmp/replay-mitternacht.json")
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"fertig n={len(rows)} -> {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
