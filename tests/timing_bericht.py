"""Zug-Timings der letzten Sitzungen ausgeben (Lisa + Bianca) — wo steckt
die Latenz: stt (Cloud-Transkription), llm oder tts?

    python tests/timing_bericht.py [anzahl_sitzungen]
"""

from __future__ import annotations

import json
import pathlib
import sys

ANZAHL = int(sys.argv[1]) if len(sys.argv) > 1 else 2

for ordner in ("bianca_sessions", "lisa_sessions", "sessions"):
    basis = pathlib.Path(".data") / ordner
    if not basis.is_dir():
        continue
    dateien = sorted(basis.glob("*.json"), key=lambda f: f.stat().st_mtime)
    for p in dateien[-ANZAHL:]:
        try:
            sit = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        zuege = sit.get("zuege") or []
        if not zuege:
            continue
        print(f"\n== {ordner}/{p.name}  start={sit.get('startedAt', '')[:19]}")
        for z in zuege:
            t = z.get("timings") or {}
            rein = (z.get("textIn") or "")[:40]
            raus = (z.get("text") or "")[:55]
            print(f"  {str(z.get('art')):7.7s} "
                  f"stt={t.get('stt')} llm={t.get('llm')} tts={t.get('tts')} "
                  f"total={t.get('total')}  in={rein!r} out={raus!r}")
