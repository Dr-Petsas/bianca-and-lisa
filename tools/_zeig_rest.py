"""Zeigt den einen verbliebenen nicht-souveraenen Anruf im Klartext (read-only)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

pfad = sys.argv[1] if len(sys.argv) > 1 else ".data/audit-regel9.json"
d = json.loads(Path(pfad).read_text(encoding="utf-8"))
rest = [c for c in d["calls"] if not c["souveraen"]]
print(f"Nicht souveraene Anrufe: {len(rest)} von {len(d['calls'])}")
for b in rest:
    print("=" * 70)
    print(f"{b['sid'][:12]}  {b['tenant']}  zuege={b['zuege']}  "
          f"wortgleich={b['wortgleich']} (max {b['wortgleich_max']})  aufsicht={b['aufsicht']}")
    print("-" * 70)
    vor = None
    for i, z in enumerate(b["verlauf"], 1):
        sag = z["bianca"] or "(still)"
        mark = "   <== WORTGLEICH" if z["bianca"] and z["bianca"] == vor else ""
        print(f"{i:2d} A: {z['anrufer'][:72]}")
        print(f"   B: {sag[:110]} [{z['akt']}/{z['frage']}]{mark}")
        vor = z["bianca"]
