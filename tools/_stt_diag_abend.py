from pathlib import Path
import json

root = Path("/app/.data/anrufe/bianca")
for p in sorted(root.iterdir(), key=lambda x: x.stat().st_mtime):
    f = p / "anruf.json"
    if not f.exists():
        continue
    d = json.loads(f.read_text(encoding="utf-8"))
    s = d.get("startedAt") or ""
    if not s.startswith("2026-09-09"):
        continue
    local = int(s[11:13]) + 2
    if local < 16:
        continue
    zuege = d.get("zuege") or []
    stts = [
        (z.get("timings") or {}).get("stt")
        for z in zuege
        if z.get("art") == "listen"
    ]
    stts = [x for x in stts if isinstance(x, (int, float))]
    if not stts:
        continue
    print(
        s[:19],
        "local",
        local,
        p.name[:16],
        "n",
        len(stts),
        "avg",
        round(sum(stts) / len(stts), 2),
        "max",
        max(stts),
    )
    for z in zuege:
        if z.get("art") != "listen":
            continue
        t = z.get("timings") or {}
        stt = t.get("stt")
        if isinstance(stt, (int, float)) and stt >= 1.5:
            print(
                "  SLOW",
                stt,
                "llm",
                t.get("llm"),
                "total",
                t.get("total"),
                repr((z.get("textIn") or "")[:50]),
            )
