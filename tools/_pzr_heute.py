"""Heutige Bianca-Anrufe: PZR mitverkauft?"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/app/.data/anrufe/bianca")
AB = datetime(2026, 9, 9, 22, 0, 0, tzinfo=timezone.utc)


def _dt(s: str):
    t = (s or "").strip().replace("Z", "+00:00")
    if not t:
        return None
    try:
        start = datetime.fromisoformat(t)
    except ValueError:
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    return start


def _blob(m: dict) -> str:
    teile = [
        json.dumps(m.get("lastBook") or {}, ensure_ascii=False),
        json.dumps(m.get("lastNote") or {}, ensure_ascii=False),
        json.dumps(m.get("praxisNotiz") or {}, ensure_ascii=False),
        json.dumps(m.get("tools") or [], ensure_ascii=False),
        json.dumps(m.get("sammler") or {}, ensure_ascii=False),
    ]
    for z in m.get("zuege") or []:
        if isinstance(z, dict):
            teile.append(str(z.get("textIn") or ""))
            teile.append(str(z.get("text") or ""))
    return " ".join(teile)


def main() -> None:
    rows = []
    if ROOT.is_dir():
        for d in ROOT.iterdir():
            p = d / "anruf.json"
            if not p.is_file():
                continue
            try:
                m = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            start = _dt(m.get("startedAt") or "")
            if not start or start < AB:
                continue
            rows.append((start, d.name, m))
    rows.sort()
    print("HEUTE_ANRUFE", len(rows))

    hits = []
    asked = []
    for start, sid, m in rows:
        samm = m.get("sammler") if isinstance(m.get("sammler"), dict) else {}
        low = _blob(m).lower()
        pzr_state = samm.get("pzr")
        plus = "plus pzr" in low
        asked_pzr = any(
            x in low
            for x in (
                "zahnreinigung",
                "professionelle zahnreinigung",
                "pzr mit",
                "reinigung dazu",
                "zähne noch professionell",
                "zaehne noch professionell",
            )
        )
        if pzr_state == "ja" or plus or "plus pzr heute" in low:
            hits.append((start, sid, m, pzr_state, plus))
        if asked_pzr or pzr_state:
            asked.append((start, sid, m, pzr_state, asked_pzr, plus, bool(m.get("lastBook"))))

    print("PZR_JA_ODER_PLUS", len(hits))
    for start, sid, m, pzr_state, plus in hits:
        samm = m.get("sammler") if isinstance(m.get("sammler"), dict) else {}
        print("==== HIT")
        print(start.isoformat()[:19], sid)
        print("name=", m.get("patientName"), "pcid=", m.get("phoneCallId"))
        print(
            "pzr=",
            pzr_state,
            "plus=",
            plus,
            "grund=",
            samm.get("grund"),
            "motiv=",
            samm.get("motivName"),
            "phase=",
            samm.get("phase"),
        )
        print("lastBook=", json.dumps(m.get("lastBook") or {}, ensure_ascii=False)[:800])
        print("lastNote=", json.dumps(m.get("lastNote") or {}, ensure_ascii=False)[:500])
        for z in m.get("zuege") or []:
            if not isinstance(z, dict):
                continue
            inn = z.get("textIn") or ""
            out = z.get("text") or ""
            if any(x in (inn + out).lower() for x in ("pzr", "zahnrein", "reinigung")):
                print(" IN", inn[:220])
                print(" OUT", out[:260])

    print("PZR_GEFRAGT_ODER_STATE", len(asked))
    for start, sid, m, pzr_state, asked_pzr, plus, booked in asked:
        samm = m.get("sammler") if isinstance(m.get("sammler"), dict) else {}
        print(
            "-",
            start.isoformat()[11:19],
            (m.get("patientName") or "-")[:30],
            "pzr=",
            pzr_state,
            "asked=",
            asked_pzr,
            "plus=",
            plus,
            "book=",
            booked,
            "grund=",
            (samm.get("grund") or "-")[:40],
            "motiv=",
            (samm.get("motivName") or "-")[:40],
            sid,
        )


if __name__ == "__main__":
    main()
