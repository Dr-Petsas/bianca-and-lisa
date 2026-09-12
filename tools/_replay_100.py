"""100 Problemzuege: Original vs heutige Pipeline. Schreibt NIE in den Kalender."""

from __future__ import annotations

import json
import os
import re
import signal
import sys
import traceback
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
from kern import motive

hintergrund.anstossen = lambda *a, **k: None
hintergrund.kartei_von_anrufer = lambda *a, **k: None
motive.anstossen = lambda *a, **k: None
verwalten._notiz_schreiben = lambda *a, **k: None
session.sichern = lambda *a, **k: None

_WURZEL = Path(os.environ.get("REPLAY_ROOT") or (DATA_DIR / "anrufe" / "bianca"))
_ZIEL = int(os.environ.get("REPLAY_N") or "100")

_PROBLEM = re.compile(
    r"nicht verstanden|akustisch nicht|wie bitte|falsch verstanden|"
    r"gerade weg|keinen Termin|noch einmal|buchstabier|"
    r"Entschuldigung|habe ich Sie|Sind Sie noch dran|"
    r"Das habe ich nicht verstanden|unklar",
    re.I,
)
_TEL = re.compile(r"(?:\+?\d[\d\s/-]{6,}\d)")


def _s(v) -> str:
    return " ".join(str(v or "").split()).strip()


def _mask(t: str) -> str:
    return _TEL.sub(lambda m: m.group(0)[:3] + "…" if len(m.group(0)) > 6 else "…", t or "")


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


def _score(z: dict, m: dict) -> int:
    n = 0
    tin, txt = _s(z.get("textIn")), _s(z.get("text"))
    if z.get("waechter"):
        n += 4
    if _PROBLEM.search(txt) or _PROBLEM.search(tin):
        n += 3
    if not tin and _audio_datei(z.get("audioIn")):
        n += 3
    if (m.get("praxisNotiz") or "") and z.get("art") == "listen":
        n += 1
    tools = z.get("tools") or []
    if any(isinstance(t, dict) and t.get("ok") is False for t in tools):
        n += 2
    if "gerade weg" in txt.lower() or "slot" in str(z.get("book") or "").lower():
        n += 2
    if len(tin) <= 2 and _audio_datei(z.get("audioIn")):
        n += 2
    return n


def _kandidaten() -> list[dict]:
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
        zuege = [z for z in (m.get("zuege") or []) if isinstance(z, dict)]
        for i, z in enumerate(zuege):
            if z.get("art") != "listen":
                continue
            datei = _audio_datei(z.get("audioIn"))
            if not datei or not (d / datei).is_file():
                continue
            sc = _score(z, m)
            if sc <= 0:
                continue
            aus.append({
                "sid": d.name,
                "started": _s(m.get("startedAt"))[:19],
                "idx": i,
                "score": sc,
                "zuege": zuege,
                "ordner": d,
                "datei": datei,
                "textIn": _s(z.get("textIn")),
                "text": _s(z.get("text")),
                "frage": _s(z.get("frage")),
                "waechter": z.get("waechter") or [],
            })
    aus.sort(key=lambda e: (-e["score"], e["started"]))
    # hoechstens 2 Zuege je Anruf, sonst 100x derselbe Call
    genommen, je = [], {}
    for e in aus:
        n = je.get(e["sid"], 0)
        if n >= 2:
            continue
        je[e["sid"]] = n + 1
        genommen.append(e)
        if len(genommen) >= _ZIEL:
            break
    return genommen


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


def _start() -> dict:
    sit = session.neu(tenant_id="meddent")
    sit["messages"] = [{"role": "assistant", "content": "Guten Tag."}]
    return sit


def _replay_vorher(sit: dict, zuege: list, bis: int) -> None:
    for z in zuege[:bis]:
        if z.get("art") != "listen":
            continue
        tin = _s(z.get("textIn"))
        if not tin:
            continue
        try:
            fl = __import__("bianca.flow", fromlist=["zug"]).zug(sit, tin)
            if fl and _s(fl.get("text")):
                sit.setdefault("messages", []).append({"role": "user", "content": tin})
                sit["messages"].append({"role": "assistant", "content": _s(fl["text"])})
            else:
                sit.setdefault("messages", []).append({"role": "user", "content": tin})
        except Exception:
            sit.setdefault("messages", []).append({"role": "user", "content": tin})


def main() -> int:
    ks = _kandidaten()
    print(f"kandidaten={len(ks)} wurzel={_WURZEL}", flush=True)
    rows = []
    for n, e in enumerate(ks, 1):
        blob = (e["ordner"] / e["datei"]).read_bytes()
        stt_heute = ""
        err = ""
        try:
            stt_heute = _mit_frist(20, lambda: stt.transcribe(
                blob, mime=_mime(e["datei"]), name=e["datei"],
                keywords="Petsas,Patrikis,Nikolaou",
            ))
        except Exception as ex:
            err = f"stt:{type(ex).__name__}"
            print(f"{n}/{len(ks)} STT fail {e['sid']} {ex}", flush=True)
        antwort_heute = ""
        try:
            sit = _start()
            _replay_vorher(sit, e["zuege"], e["idx"])
            spoken = stt_heute or e["textIn"]
            if spoken:
                ant = _mit_frist(25, lambda: agent.user_turn(sit, spoken))
                antwort_heute = _s((ant or {}).get("text"))
        except Exception as ex:
            err = (err + " " if err else "") + f"zug:{type(ex).__name__}"
            print(f"{n}/{len(ks)} ZUG fail {e['sid']}\n{traceback.format_exc()[-400:]}", flush=True)
        gleich_stt = _s(stt_heute).lower() == _s(e["textIn"]).lower()
        gleich_ant = _s(antwort_heute).lower() == _s(e["text"]).lower()
        rows.append({
            "nr": n,
            "sid": e["sid"][:8],
            "wann": e["started"],
            "score": e["score"],
            "input_orig": _mask(e["textIn"]),
            "stt_heute": _mask(stt_heute),
            "antwort_orig": _mask(e["text"]),
            "antwort_heute": _mask(antwort_heute),
            "stt_gleich": gleich_stt,
            "antwort_gleich": gleich_ant,
            "frage": e["frage"],
            "fehler": err,
        })
        print(f"{n}/{len(ks)} {e['sid'][:8]} stt={'=' if gleich_stt else '!'} ant={'=' if gleich_ant else '!'}", flush=True)

    out = Path(os.environ.get("REPLAY_OUT") or "/tmp/replay-100.json")
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    n_stt = sum(1 for r in rows if r["stt_heute"] and not r["stt_gleich"])
    n_ant = sum(1 for r in rows if r["antwort_heute"] and not r["antwort_gleich"])
    print(f"fertig n={len(rows)} stt_anders={n_stt} antwort_anders={n_ant} -> {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
