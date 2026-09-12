"""Schreibt Replay-JSON in replay.html (ersetzt alten DATA-Block)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
src = Path(sys.argv[1]) if len(sys.argv) > 1 else root / ".data" / "replay-mitternacht.json"
rows = json.loads(src.read_text(encoding="utf-8"))
html = (root / "web" / "replay.html").read_text(encoding="utf-8")
payload = json.dumps(rows, ensure_ascii=False).replace("<", "\\u003c")
new = '<script id="DATA" type="application/json">' + payload + "</script>"
html, n = re.subn(
    r'<script id="DATA" type="application/json">.*?</script>',
    new,
    html,
    count=1,
    flags=re.S,
)
if n != 1:
    raise SystemExit(f"DATA-Block nicht ersetzt (n={n})")
html = html.replace("100 Problemfälle · Bianca Replay", "Anrufe seit Mitternacht · Bianca Replay")
html = re.sub(r"<h1>.*?</h1>", "<h1>Anrufe seit Mitternacht</h1>", html, count=1)
html = re.sub(
    r'<div class="sub">.*?</div>',
    '<div class="sub">Originale Transkripte — bleiben gespeichert, nichts wird gelöscht</div>',
    html,
    count=1,
)
(root / "web" / "replay.html").write_text(html, encoding="utf-8")
(root / "bianca_web" / "replay.html").write_text(html, encoding="utf-8")
print("rows", len(rows), "bytes", len(html.encode("utf-8")))
print("stt_anders", sum(1 for r in rows if not r.get("stt_gleich")))
print("ant_anders", sum(1 for r in rows if not r.get("antwort_gleich")))
print("fehler", sum(1 for r in rows if r.get("fehler")))
