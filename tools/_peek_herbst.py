"""Patrik Herbst: Bianca + Lisa Mitschnitte + CallR (im Container)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

NEEDLE = ("herbst", "narval", "schiene", "patrik", "patrick")


def _dt(s: str):
    t = (s or "").strip()
    if not t:
        return None
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        return None


def _blob(m: dict) -> str:
    teile = [
        str(m.get("patientName") or ""),
        str(m.get("praxisNotiz") or ""),
        str(m.get("auftrag") or ""),
        json.dumps(m.get("anrufer") or {}, ensure_ascii=False),
        json.dumps(m.get("sammler") or {}, ensure_ascii=False),
        json.dumps(m.get("patient") or {}, ensure_ascii=False),
        json.dumps(m.get("lastBook") or {}, ensure_ascii=False),
    ]
    for z in m.get("zuege") or []:
        if isinstance(z, dict):
            teile.append(str(z.get("textIn") or ""))
            teile.append(str(z.get("text") or ""))
    return " ".join(teile).lower()


def _scan(root: Path, label: str) -> list[tuple]:
    hits = []
    if not root.is_dir():
        print(f"{label}: kein_ordner {root}")
        return hits
    alle = []
    for d in root.iterdir():
        p = d / "anruf.json"
        if not p.is_file():
            continue
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        start = _dt(m.get("startedAt") or "")
        blob = _blob(m)
        alle.append((start or datetime.min, d.name, m, blob))
        if any(n in blob for n in NEEDLE):
            hits.append((start or datetime.min, d.name, m, blob))
    alle.sort()
    print(f"=== {label} n={len(alle)} hits={len(hits)}")
    if not hits:
        print(" letzte 15:")
        for start, sid, m, blob in alle[-15:]:
            print(
                (start.isoformat()[:19] if start != datetime.min else "?"),
                sid,
                "name=", m.get("patientName") or "-",
                "pcid=", m.get("phoneCallId") or "-",
                "anrufer=", m.get("anrufer") or "-",
            )
    return hits


def _dump(label: str, sid: str, m: dict) -> None:
    print(f"\n######## {label} {sid}")
    print("started", m.get("startedAt"))
    print("ended", m.get("endedAt"))
    print("name", m.get("patientName"))
    print("pcid", m.get("phoneCallId"))
    print("did", m.get("did"))
    print("anrufer", json.dumps(m.get("anrufer") or {}, ensure_ascii=False))
    print("patient", json.dumps(m.get("patient") or {}, ensure_ascii=False)[:800])
    print("sammler", json.dumps(m.get("sammler") or {}, ensure_ascii=False)[:2000])
    print("praxisNotiz", (m.get("praxisNotiz") or "")[:500])
    print("auftrag", (m.get("auftrag") or "")[:400])
    print("gedaechtnis", (m.get("gedaechtnis") or "")[:800])
    print("gedaechtnisOffen", m.get("gedaechtnisOffen"))
    print("rueckrufMitgeteilt", m.get("rueckrufMitgeteilt"))
    print("rueckrufBuchung", m.get("rueckrufBuchung"))
    print("lastBook", json.dumps(m.get("lastBook") or {}, ensure_ascii=False)[:600])
    print("---TURNS---")
    for i, z in enumerate(m.get("zuege") or []):
        inn = (z.get("textIn") or "").replace("\n", " ")
        out = (z.get("text") or "").replace("\n", " ")
        print(f"{i:02d} {z.get('art')}")
        print(f"   IN : {inn}")
        print(f"   OUT: {out}")


def main() -> None:
    for label, root in (
        ("bianca", Path("/app/.data/anrufe/bianca")),
        ("lisa", Path("/app/.data/anrufe/lisa")),
    ):
        hits = _scan(root, label)
        hits.sort()
        for start, sid, m, _blob in hits[-8:]:
            _dump(label, sid, m)


if __name__ == "__main__":
    main()
