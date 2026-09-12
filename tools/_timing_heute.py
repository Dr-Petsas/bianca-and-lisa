"""Vergleicht Bianca-Zugzeiten heute Morgen vs. Nachmittag."""
from __future__ import annotations

import json
from pathlib import Path

root = Path("/app/.data/anrufe/bianca")
calls = []
for p in root.iterdir():
    f = p / "anruf.json"
    if not f.exists():
        continue
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        continue
    started = d.get("startedAt") or ""
    if not started.startswith("2026-09-09"):
        continue
    rows = []
    for z in d.get("zuege") or []:
        t = z.get("timings") or {}
        if not isinstance(t.get("total"), (int, float)):
            continue
        rows.append(
            {
                "art": z.get("art"),
                "stt": t.get("stt"),
                "llm": t.get("llm"),
                "tts": t.get("tts"),
                "total": float(t["total"]),
                "in": (z.get("textIn") or "")[:40],
                "out": (z.get("text") or "")[:50],
            }
        )
    if rows:
        calls.append((started, p.name, rows))

calls.sort()
print("calls_today", len(calls))


def summarize(label, xs):
    xs = [float(x) for x in xs if isinstance(x, (int, float))]
    if not xs:
        print(label, "n/a")
        return
    xs.sort()
    p50 = xs[len(xs) // 2]
    p90 = xs[int(len(xs) * 0.9)] if len(xs) > 1 else xs[0]
    print(
        f"{label}: n={len(xs)} avg={sum(xs)/len(xs):.2f} "
        f"p50={p50:.2f} p90={p90:.2f} max={max(xs):.2f}"
    )


def bucket(name, items):
    stt = [r["stt"] for r in items]
    llm = [r["llm"] for r in items]
    tot = [r["total"] for r in items]
    slow = [r for r in items if isinstance(r["stt"], (int, float)) and r["stt"] >= 1.5]
    print(f"\n== {name} turns={len(items)}")
    summarize("stt", stt)
    summarize("llm", llm)
    summarize("total", tot)
    n_stt = sum(1 for x in stt if isinstance(x, (int, float)))
    print("stt>=1.5s", len(slow), f"({100 * len(slow) / max(1, n_stt):.0f}%)")
    for r in sorted(slow, key=lambda x: -float(x["stt"]))[:10]:
        print(f"  slow stt={r['stt']} in={r['in']!r} out={r['out']!r}")


morning, afternoon, evening = [], [], []
for started, name, rows in calls:
    hh = int(started[11:13])
    local = hh + 2  # UTC -> CEST
    listen = [r for r in rows if r.get("art") == "listen"]
    if local < 12:
        morning.extend(listen)
    elif local < 15:
        afternoon.extend(listen)
    else:
        evening.extend(listen)
    stts = [r["stt"] for r in listen if isinstance(r["stt"], (int, float))]
    tots = [r["total"] for r in listen]
    avg_stt = round(sum(stts) / len(stts), 2) if stts else None
    avg_tot = round(sum(tots) / len(tots), 2) if tots else None
    print(
        f"{started[:19]} local~{local:02d} {name[:18]} "
        f"listen={len(listen)} avg_stt={avg_stt} avg_total={avg_tot}"
    )

bucket("MORNING local<12", morning)
bucket("AFTERNOON 12-15", afternoon)
bucket("EVENING >=15", evening)
