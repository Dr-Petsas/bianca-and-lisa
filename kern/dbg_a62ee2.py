# #region agent log
"""Debug-Instrumentierung Sitzung a62ee2 — NUR zur Fehlersuche.

Zwei Befunde vom 12.09.2026: Audio-Aussetzer (SIP-Bruecke) und die
Presence-Schleife („Sind Sie noch dran?“ als Antwort auf echt gesprochene
Saetze). Diese Datei wird nach der Verifikation KOMPLETT entfernt.

Schreibt NDJSON, nie werfend, nie auf dem Anruf-Pfad blockierend.
Ziffern werden maskiert — keine Rufnummern im Log.
"""

from __future__ import annotations

import json
import os
import re
import time

_PFAD = os.environ.get("BIANCA_DEBUG_LOG") or "/tmp/debug-a62ee2.log"
_AN = (os.environ.get("BIANCA_DEBUG") or "1").strip() != "0"
_ZAHL_RE = re.compile(r"\d")
_N = {"n": 0}


def kurz(text: object, n: int = 48) -> str:
    """Gekuerzt und ziffernfrei — genug zum Belegen, ohne Rufnummern."""
    t = " ".join(str(text or "").split())
    return _ZAHL_RE.sub("#", t)[:n]


def dbg(hyp: str, ort: str, text: str, daten: dict) -> None:
    if not _AN or _N["n"] >= 4000:
        return
    _N["n"] += 1
    try:
        with open(_PFAD, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "sessionId": "a62ee2", "runId": "run2", "hypothesisId": hyp,
                "location": ort, "message": text, "data": daten,
                "timestamp": int(time.time() * 1000),
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass
# #endregion
