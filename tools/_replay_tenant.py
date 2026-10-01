"""Mandantenfaehiges Replay gezielter Anrufe gegen die heutige Pipeline.

Schreibt NIE in den Kalender (WRITE_LIVE=0). Faehrt die archivierten
Textzuege (optional erneut durch STT) je Mandant durch den vollen
Dialogfluss und misst die Antwortlatenz pro Zug (Ziel p50<0,9s, p90<=3s;
externe Write-Verifikation ist hier bewusst abgeklemmt).

Nutzung (im Container oder lokal):
    REPLAY_SIDS=28d34ffd,c940da6a REPLAY_STT=0 python tools/_replay_tenant.py
Ohne REPLAY_SIDS werden alle Anrufe unter REPLAY_ROOT genommen.
REPLAY_TENANT erzwingt einen Mandanten, sonst gilt der Mandant je Anruf.
"""

from __future__ import annotations

import json
import os
import signal
import statistics
import sys
import time
import traceback
from pathlib import Path

os.environ["WRITE_LIVE"] = "0"
os.environ["MITSCHNITT"] = "0"
os.environ["MAS_GEDAECHTNIS"] = "0"
os.environ["CALL_AUDIO_UPLOAD"] = "0"

_APP = Path("/app") if Path("/app/bianca").is_dir() else Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_APP))

from kern import calendar, patients  # noqa: E402

calendar.WRITE_LIVE = False
patients.WRITE_LIVE = False

from bianca import agent, hintergrund, session, verwalten  # noqa: E402
from kern import motive  # noqa: E402

hintergrund.anstossen = lambda *a, **k: None
hintergrund.kartei_von_anrufer = lambda *a, **k: None
motive.anstossen = lambda *a, **k: None
verwalten._notiz_schreiben = lambda *a, **k: None
session.sichern = lambda *a, **k: None

_STT = os.environ.get("REPLAY_STT", "0") == "1"
if _STT:
    from kern import stt  # noqa: E402

_WURZEL = Path(os.environ.get("REPLAY_ROOT") or (_APP / ".data" / "anrufe" / "bianca"))
_SIDS = [s.strip() for s in (os.environ.get("REPLAY_SIDS") or "").split(",") if s.strip()]
_TENANT_FIX = (os.environ.get("REPLAY_TENANT") or "").strip() or None


def _s(v) -> str:
    return " ".join(str(v or "").split()).strip()


def _mime(name: str) -> str:
    n = (name or "").lower()
    for end, m in ((".wav", "audio/wav"), (".mp3", "audio/mpeg"),
                   (".m4a", "audio/mp4"), (".ogg", "audio/ogg")):
        if n.endswith(end):
            return m
    return "audio/webm"


def _audio_datei(ein) -> str:
    if isinstance(ein, list) and ein:
        return _s(ein[0].get("datei"))
    if isinstance(ein, dict):
        return _s(ein.get("datei"))
    return ""


def _mit_frist(sek: int, fn):
    hat_alarm = hasattr(signal, "SIGALRM")
    if not hat_alarm:
        return fn()

    def _kill(signum, frame):
        raise TimeoutError(f">{sek}s")

    alt = signal.signal(signal.SIGALRM, _kill)
    signal.alarm(sek)
    try:
        return fn()
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, alt)


def _ordner() -> list[Path]:
    if not _WURZEL.is_dir():
        return []
    aus = []
    for d in sorted(_WURZEL.iterdir()):
        if not (d / "anruf.json").is_file():
            continue
        if _SIDS and not any(d.name.startswith(sid) for sid in _SIDS):
            continue
        aus.append(d)
    return aus


def main() -> int:
    ordner = _ordner()
    print(f"anrufe={len(ordner)} wurzel={_WURZEL} stt={'an' if _STT else 'aus'}", flush=True)
    alle_latenz: list[float] = []
    rows = []
    for d in ordner:
        try:
            m = json.loads((d / "anruf.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        tenant = _TENANT_FIX or _s(m.get("tenant") or m.get("tenantId")) or "meddent"
        zuege = [z for z in (m.get("zuege") or []) if isinstance(z, dict)]
        try:
            sit = session.neu(tenant_id=tenant)
        except Exception as ex:
            print(f"{d.name[:8]} session.neu fail: {ex}", flush=True)
            continue
        sit["messages"] = [{"role": "assistant", "content": _s((zuege[0] or {}).get("text")) or "Guten Tag."}]
        turns = 0
        fehler = ""
        for z in zuege:
            if z.get("art") != "listen":
                continue
            spoken = _s(z.get("textIn"))
            if _STT:
                datei = _audio_datei(z.get("audioIn"))
                if datei and (d / datei).is_file():
                    try:
                        spoken = _s(_mit_frist(25, lambda: stt.transcribe(
                            (d / datei).read_bytes(), mime=_mime(datei), name=datei,
                            keywords="Petsas,Patrikis,Nikolaou",
                        ))) or spoken
                    except Exception as ex:
                        fehler = (fehler + " " if fehler else "") + f"stt:{type(ex).__name__}"
            if not spoken:
                continue
            t0 = time.perf_counter()
            try:
                ant = _mit_frist(25, lambda: agent.user_turn(sit, spoken))
            except Exception as ex:
                fehler = (fehler + " " if fehler else "") + f"zug:{type(ex).__name__}"
                print(f"{d.name[:8]} ZUG fail\n{traceback.format_exc()[-300:]}", flush=True)
                break
            dt = time.perf_counter() - t0
            alle_latenz.append(dt)
            turns += 1
            sit.setdefault("messages", []).append({"role": "user", "content": spoken})
            sit["messages"].append({"role": "assistant", "content": _s((ant or {}).get("text"))})
        rows.append({"sid": d.name[:8], "tenant": tenant, "turns": turns, "fehler": fehler})
        print(f"{d.name[:8]} tenant={tenant} turns={turns} {('FEHLER ' + fehler) if fehler else 'ok'}", flush=True)

    def _pct(xs, p):
        if not xs:
            return 0.0
        xs = sorted(xs)
        k = max(0, min(len(xs) - 1, int(round((p / 100.0) * (len(xs) - 1)))))
        return xs[k]

    print("-" * 60, flush=True)
    if alle_latenz:
        p50 = _pct(alle_latenz, 50)
        p90 = _pct(alle_latenz, 90)
        print(f"turns={len(alle_latenz)} "
              f"p50={p50 * 1000:.0f}ms p90={p90 * 1000:.0f}ms "
              f"max={max(alle_latenz) * 1000:.0f}ms "
              f"mittel={statistics.mean(alle_latenz) * 1000:.0f}ms", flush=True)
        print(f"ziel p50<900ms: {'OK' if p50 < 0.9 else 'VERFEHLT'}; "
              f"ziel p90<=3000ms: {'OK' if p90 <= 3.0 else 'VERFEHLT'}", flush=True)
    fehlerhaft = [r for r in rows if r["fehler"]]
    print(f"anrufe={len(rows)} mit_fehler={len(fehlerhaft)}", flush=True)
    out = Path(os.environ.get("REPLAY_OUT") or "/tmp/replay-tenant.json")
    try:
        out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"-> {out}", flush=True)
    except OSError:
        pass
    return 1 if fehlerhaft else 0


if __name__ == "__main__":
    raise SystemExit(main())
