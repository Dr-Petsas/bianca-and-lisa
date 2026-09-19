"""Zaehlt Problem-Muster in den heutigen Thaler-Anrufen."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/app/.data/anrufe/bianca")
AB = datetime(2026, 9, 14, 22, 0, 0, tzinfo=timezone.utc)
BIS = datetime(2026, 9, 15, 22, 0, 0, tzinfo=timezone.utc)
CLIENT = "7tTnJZfJkb801r2rmYed"


def _dt(s: str):
    t = (s or "").strip().replace("Z", "+00:00")
    if not t:
        return None
    try:
        x = datetime.fromisoformat(t)
    except ValueError:
        return None
    if x.tzinfo is None:
        x = x.replace(tzinfo=timezone.utc)
    return x


def _tenant(m: dict) -> dict:
    t = m.get("tenant")
    return t if isinstance(t, dict) else {}


def _is_thaler(m: dict) -> bool:
    t = _tenant(m)
    tid = str(m.get("tenantId") or t.get("id") or t.get("tenantId") or "").lower()
    cid = str(t.get("clientId") or m.get("clientId") or "")
    praxis = str(t.get("praxisName") or t.get("praxisNameMelde") or "")
    zuege = m.get("zuege") or []
    gruss = ""
    if zuege and isinstance(zuege[0], dict):
        gruss = str(zuege[0].get("text") or "")
    return (
        tid == "thaler"
        or cid == CLIENT
        or "thaler" in praxis.lower()
        or "thaler zahnmedizin" in gruss.lower()
    )


def _outs(m: dict) -> list[str]:
    rows = []
    for z in m.get("zuege") or []:
        if isinstance(z, dict):
            rows.append(str(z.get("text") or ""))
    return rows


def _ins(m: dict) -> list[str]:
    rows = []
    for z in m.get("zuege") or []:
        if isinstance(z, dict):
            rows.append(str(z.get("textIn") or ""))
    return rows


def _waechter(m: dict) -> list[str]:
    rows = []
    for z in m.get("zuege") or []:
        if not isinstance(z, dict):
            continue
        for x in z.get("waechter") or []:
            if isinstance(x, dict) and x.get("w"):
                rows.append(str(x.get("w")))
    return rows


def main() -> None:
    calls = []
    for d in ROOT.iterdir():
        p = d / "anruf.json"
        if not p.is_file():
            continue
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        start = _dt(m.get("startedAt") or "")
        if not start or start < AB or start >= BIS or not _is_thaler(m):
            continue
        calls.append((start, d.name, m))
    calls.sort()

    n = len(calls)
    with_in = 0
    empty = 0
    book_ok = 0
    book_fail = 0
    cancel_ok = 0
    note = 0
    pats = {
        "neue": [],
        "unklar": [],
        "sermon": [],
        "pzr": [],
        "doktor_notiz": [],
        "erkannt": [],
        "selbst": [],
        "sonst_noch": [],
        "dran": [],
        "leerer_out": [],
        "handy_frage": [],
        "werkzeug": [],
        "verbinden": [],
        "rechnung": [],
        "zeiten": [],
        "nichts_frei": [],
    }
    for start, sid, m in calls:
        ins = _ins(m)
        outs = _outs(m)
        spoken_in = [x for x in ins if x.strip()]
        if spoken_in:
            with_in += 1
        else:
            empty += 1
        if (m.get("lastBook") or {}).get("ok") or (m.get("lastBook") or {}).get("booked"):
            book_ok += 1
        elif m.get("lastBook"):
            book_fail += 1
        if m.get("lastCancel"):
            cancel_ok += 1
        if m.get("lastNote") or m.get("praxisNotiz"):
            note += 1
        blob = "\n".join(outs).lower()
        inn = "\n".join(ins).lower()
        w = _waechter(m)
        short = sid[:8]
        if "ich bin die neue" in blob:
            pats["neue"].append(short)
        if "was meinen sie damit" in blob:
            pats["unklar"].append(short)
        if "entlaste die anmeldung" in blob or "medizinische versorgung der patienten" in blob:
            pats["sermon"].append(short)
        if "zahnreinigung mit dazu" in blob:
            pats["pzr"].append(short)
        if "notiz für den doktor" in blob or "notiz fuer den doktor" in blob:
            pats["doktor_notiz"].append(short)
        if "richtig erkannt" in blob:
            pats["erkannt"].append(short)
        if "für sie selbst" in blob or "fuer sie selbst" in blob:
            pats["selbst"].append(short)
        if "sonst noch etwas" in blob:
            pats["sonst_noch"].append(short)
        if "sind sie noch dran" in blob:
            pats["dran"].append(short)
        leer = 0
        for z in m.get("zuege") or []:
            if not isinstance(z, dict):
                continue
            if z.get("art") == "listen" and (z.get("textIn") or "").strip() and not (z.get("text") or "").strip():
                leer += 1
        if leer:
            pats["leerer_out"].append("%s:%d" % (short, leer))
        if "handynummer" in blob:
            pats["handy_frage"].append(short)
        if "dieses werkzeug kenne ich" in blob:
            pats["werkzeug"].append(short)
        if any(x in blob for x in ("verbinden", "durchstellen", "zu welchem unserer ärzte", "zu welchem unserer aerzte")):
            pats["verbinden"].append(short)
        if "rechnung" in w or "über rechnungen darf ich" in blob:
            pats["rechnung"].append(short)
        if re.search(r"von .* bis .* uhr", blob) and ("offen" in inn or "aufhören" in inn or "geöffnet" in inn or "morgen" in inn):
            pats["zeiten"].append(short)
        if "nichts frei" in blob or "nichts freies" in blob:
            pats["nichts_frei"].append(short)

    print("calls", n, "mit_anrufer", with_in, "leer", empty)
    print("book_ok", book_ok, "book_fail", book_fail, "cancel", cancel_ok, "note", note)
    for k, v in pats.items():
        print("%s n_calls=%d items=%s" % (k, len(v), ", ".join(v)))


if __name__ == "__main__":
    main()
