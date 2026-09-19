"""Vorschau der zweiten Spalte in ``/anrufe`` — ohne Live-Dienst, ohne echte Anrufe.

Baut zwei erfundene Mitschnitte (einer mit Live-Schleife, einer glatt), schickt
sie durch ``tools/kern_replay.py`` und liefert die ECHTE Seite
(``bianca_web/anrufe.html`` + ``anrufe.js``) gegen eine Mini-API aus. So ist die
neue Spalte (Loop-Aufsicht, Zaehler, Uebergabe, Policy-Kopf) im Browser zu
sehen, ohne den Live-Bianca-Dienst zu starten und ohne ``.data/anrufe``
anzufassen — die Manifeste liegen nur im Speicher.

    python tools\\_probe_anrufe_spalte.py            # nur pruefen, kein Server
    python tools\\_probe_anrufe_spalte.py --serve     # http://127.0.0.1:8199/anrufe
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools import kern_replay as kr  # noqa: E402

WEB = _ROOT / "bianca_web"


def _zug(textIn: str = "", text: str = "", frage: str = "", **rest) -> dict:
    z = {"art": "turn", "offsetMs": 0, "at": "2026-09-19T08:00:00Z"}
    if textIn:
        z["textIn"] = textIn
    z["text"] = text
    z["frage"] = frage
    z.update(rest)
    return z


def _schleifen_anruf() -> dict:
    """Live haengt in der Ja/Nein-Frage — genau der Fall fuer die Aufsicht."""
    zuege = [
        _zug(text="Guten Tag, hier ist Bianca. Wie kann ich helfen?"),
        _zug("Ich haette gern einen Termin zur Kontrolle.",
             "Waren Sie schon einmal bei uns?", "schonmal"),
    ]
    for _ in range(14):
        zuege.append(_zug("haeh?", "Waren Sie schon einmal bei uns?", "schonmal"))
    return {
        "id": "aaaa000000000001",
        "tenantId": "meddent",
        "patientName": "",
        "startedAt": "2026-09-19T08:00:00Z",
        "endedAt": "2026-09-19T08:06:10Z",
        "dauerMs": 370000,
        "zuege": zuege,
    }


def _glatter_anruf() -> dict:
    return {
        "id": "bbbb000000000002",
        "tenantId": "meddent",
        "patientName": "Nikolas Helmich",
        "startedAt": "2026-09-19T09:30:00Z",
        "endedAt": "2026-09-19T09:33:20Z",
        "dauerMs": 200000,
        "lastBook": {"iso": "2026-10-02T13:00:00", "kalender": "Dr. Petsas"},
        "zuege": [
            _zug(text="Guten Tag, hier ist Bianca. Wie kann ich helfen?"),
            _zug("Ich braeuchte einen Termin zur Kontrolle.",
                 "Waren Sie schon einmal bei uns?", "schonmal"),
            _zug("Ja, bei Doktor Petsas.", "Worum geht es denn?", "grund"),
            _zug("Kontrolle bitte.", "Wann passt es Ihnen?", "wunsch"),
            _zug("Naechste Woche Dienstag vormittags.", "Wie ist Ihr Nachname?", "nachname"),
            _zug("Helmich.", "Sind Sie privat oder gesetzlich versichert?", "versicherung"),
            _zug("Gesetzlich.",
                 "Donnerstag um 13 Uhr bei Doktor Petsas — passt das?", "slotwahl"),
            _zug("Ja, passt.", "Ihre Handynummer bitte?", "telefon",
                 tools=[{"name": "masBookAppointment", "ok": True}]),
        ],
    }


def bauen() -> list[dict]:
    aus = []
    for m in (_schleifen_anruf(), _glatter_anruf()):
        kr.replay_manifest(m)
        aus.append(m)
    return aus


def pruefen(manifeste: list[dict]) -> int:
    fehler: list[str] = []

    def ok(bed: bool, text: str) -> None:
        print(("  OK   " if bed else "  FEHL ") + text)
        if not bed:
            fehler.append(text)

    schleife, glatt = manifeste
    s = schleife["kernReplaySummary"]
    print("\n[1] Schleifen-Anruf")
    ok(s["v"] == 2, "Kopfzeile in der neuen Fassung (v2)")
    ok(s["policy"]["quelle"] in ("vertrag", "legacy"),
       f"Policy-Herkunft: {s['policy']['quelle']} / Revision {s['policy']['revision']}")
    ok(s["schleifen"] >= 3, f"Live-Schleife erkannt ({s['schleifen']})")
    ok(s["aufsicht_rueckblick"] >= 1, f"Kern fasst zusammen ({s['aufsicht_rueckblick']}x)")
    ok(s["aufsicht_uebergabe"] >= 1, f"Kern gibt ehrlich ab ({s['aufsicht_uebergabe']}x)")
    ok(0 < s["gerettet"] <= s["schleifen"], f"vermiedene Zuege: {s['gerettet']}")
    stufen: list[str] = []
    for z in schleife["zuege"]:
        k = z.get("kernReplay") or {}
        if k.get("aufsicht") or k.get("stock"):
            print(f"       {k.get('aufsicht') or ''} {k.get('stock') or ''}")
        if k.get("aufsicht"):
            stufen.append(k["aufsicht"]["art"])
    # Reihenfolge der Leiter: erst zusammenfassen, dann abgeben — nie umgekehrt.
    ok(stufen[:2] == ["rueckblick", "uebergabe"], f"Leiter in dieser Reihenfolge: {stufen}")

    print("\n[2] Glatter Anruf")
    g = glatt["kernReplaySummary"]
    ok(g["aufsicht_rueckblick"] == 0 and g["aufsicht_uebergabe"] == 0,
       "keine Aufsicht, wo nichts stockt")
    ok(g["schleifen"] == 0 and g["gerettet"] == 0, "nichts zu retten")
    # Der Zaehler ist kein Rauschen: er erscheint erst ab der zweiten
    # Wiederholung derselben Frage — eine einmal gestellte Frage bleibt still.
    zahlen = [(z.get("kernReplay") or {}).get("stock", {}).get("zahl")
              for m in manifeste for z in m["zuege"]
              if (z.get("kernReplay") or {}).get("stock")]
    ok(all(n >= 2 for n in zahlen), f"Zaehler nur ab der zweiten Runde: {zahlen}")

    print("\n[3] Seite und Mittel")
    for name in ("anrufe.html", "anrufe.js"):
        p = WEB / name
        ok(p.is_file() and p.stat().st_size > 1000, f"bianca_web/{name}")
    js = (WEB / "anrufe.js").read_text(encoding="utf-8")
    for marke in ("_KERN_AUFSICHT", "kernAufsichtText", "vmark aufsicht",
                  "vmark zaehler", "vmark uebergabe"):
        ok(marke in js, f"anrufe.js kennt {marke}")
    html = (WEB / "anrufe.html").read_text(encoding="utf-8")
    ok(".vmark.aufsicht" in html, "Stil fuer die Aufsicht-Marke")

    print("\n" + ("ALLES GRUEN" if not fehler
                  else f"{len(fehler)} FEHLER:\n  - " + "\n  - ".join(fehler)))
    return 1 if fehler else 0


def servieren(manifeste: list[dict], port: int) -> None:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles
    import uvicorn

    nach_id = {m["id"]: m for m in manifeste}
    app = FastAPI()

    @app.get("/api/anrufe")
    def liste(tenant: str = ""):
        return {"ok": True, "anrufe": [{
            "id": m["id"], "tenantId": m.get("tenantId") or "",
            "startedAt": m.get("startedAt") or "", "endedAt": m.get("endedAt"),
            "dauerMs": m.get("dauerMs"), "patientName": m.get("patientName") or "",
            "zuege": len(m.get("zuege") or []), "lastBook": m.get("lastBook"),
            "offen": False, "testAnruf": True, "testName": "Vorschau",
        } for m in manifeste]}

    @app.get("/api/anrufe/{sid}")
    def einer(sid: str):
        m = nach_id.get(sid)
        if not m:
            raise HTTPException(404, "anruf unbekannt")
        return {"ok": True, "anruf": m}

    @app.get("/anrufe")
    @app.get("/")
    def seite():
        return FileResponse(WEB / "anrufe.html", media_type="text/html; charset=utf-8",
                            headers={"Cache-Control": "no-store"})

    app.mount("/", StaticFiles(directory=str(WEB)), name="web")
    print(f"\nVorschau: http://127.0.0.1:{port}/anrufe   (Strg+C beendet)")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--serve", action="store_true", help="Seite lokal ausliefern")
    ap.add_argument("--port", type=int, default=8199)
    ap.add_argument("--json", default="", help="Manifeste zusaetzlich ablegen")
    a = ap.parse_args()
    ms = bauen()
    code = pruefen(ms)
    if a.json:
        Path(a.json).write_text(json.dumps(ms, ensure_ascii=False, indent=1),
                                encoding="utf-8")
    if a.serve:
        servieren(ms, a.port)
    sys.exit(code)
