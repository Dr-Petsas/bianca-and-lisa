"""Editor des Baukasten-Tests (W-BK-5): Teststudio auf Port 8097.

Eine kleine FastAPI-App neben dem Bianca-Dienst (8098 fuer Tests):
  - /            Editor: Chips fuer alle Story-Attribute, Automatik-Knopf,
                 Wunschtag der kommenden Woche, Stumm/Mithoeren, 10er-Batch.
  - /ergebnisse  Ergebnisseite: Laeufe -> Stories (gruen/rot) -> Bubble-Dialog
                 mit Latenz und Waechter je Antwort, jede Bubble abspielbar.
  - /api/*       Katalog, Lauf-Start, Live-Zustand, Berichte.

Mithoeren beeinflusst die Latenz NICHT: der Browser pollt DIESEN Server
(/api/live) — der Runner wartet nie auf den Browser, die Zuege gegen
Bianca laufen unveraendert in Echtzeit-Taktung.
"""

from __future__ import annotations

import sys
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fastapi import FastAPI  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from tests.baukasten import geschichten, runner, saetze  # noqa: E402

WEB_DIR = Path(__file__).resolve().parent / "editor_web"
BERICHTE_DIR = runner.BERICHTE_DIR
BIANCA_BASIS = "http://127.0.0.1:8098"

app = FastAPI(title="Baukasten-Teststudio")

# ------------------------------------------------------------------ Laufzustand

_lock = threading.Lock()
_zustand: dict[str, Any] = {
    "laeuft": False,
    "laufId": "",
    "storyIdx": 0,
    "storiesGesamt": 0,
    "aktiv": None,       # runner.Anruf des laufenden Anrufs
    "fertig": [],        # Kurz-Ergebnisse der abgeschlossenen Stories
    "fehler": "",
}


def _wochentage_naechste_woche() -> list[dict[str, str]]:
    heute = date.today()
    montag = heute + timedelta(days=7 - heute.weekday())
    out = []
    for i, name in enumerate(["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]):
        d = montag + timedelta(days=i)
        out.append({"tag": name, "datum": d.isoformat(),
                    "anzeige": f"{name} {d.strftime('%d.%m.')}"})
    return out


def _lauf_thread(stories: list[dict], mithoeren: bool) -> None:
    lauf_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    lauf_dir = BERICHTE_DIR / lauf_id
    lauf_dir.mkdir(parents=True, exist_ok=True)
    with _lock:
        _zustand.update({"laeuft": True, "laufId": lauf_id, "storyIdx": 0,
                         "storiesGesamt": len(stories), "fertig": [], "fehler": ""})
    try:
        import json as _json
        import time as _time
        berichte = []
        for i, story in enumerate(stories):
            anruf = runner.Anruf(story, basis=BIANCA_BASIS, lauf_dir=lauf_dir,
                                 echtzeit=True, mithoeren=False)
            with _lock:
                _zustand["storyIdx"] = i + 1
                _zustand["aktiv"] = anruf
            b = anruf.fuehren()
            erg = b.get("ergebnis") or {}
            kurz = {"id": b.get("id"), "ok": bool(erg.get("ok")),
                    "checks": erg.get("checks"), "latenzMaxS": erg.get("latenzMaxS"),
                    "fehler": b.get("fehler") or "", "pfad": f"{b.get('id')}/bericht.json"}
            berichte.append(kurz)
            with _lock:
                _zustand["fertig"] = list(berichte)
                _zustand["aktiv"] = None
            (lauf_dir / "lauf.json").write_text(
                _json.dumps({"laufId": lauf_id,
                             "gestartet": datetime.now().isoformat(timespec="seconds"),
                             "stories": berichte}, ensure_ascii=False, indent=1),
                encoding="utf-8")
            _time.sleep(2.0)
    except Exception as e:  # Lauf-Thread darf nie still sterben
        with _lock:
            _zustand["fehler"] = f"{type(e).__name__}: {e}"
    finally:
        with _lock:
            _zustand["laeuft"] = False
            _zustand["aktiv"] = None


# ------------------------------------------------------------------------- API

@app.get("/api/katalog")
def katalog() -> dict[str, Any]:
    return {
        "stimmen": saetze.STIMMEN_M + saetze.STIMMEN_W,
        "vornamen": saetze.VORNAMEN,
        "nachnamen": saetze.NACHNAMEN,
        "anliegen": list(geschichten.ALLE_ANLIEGEN),
        "gruende": {k: v[1] for k, v in saetze.GRUENDE.items()},
        "behandler": list(geschichten.BEHANDLER),
        "abschweifer": sorted(saetze.ABSCHWEIFER),
        "anker": list(geschichten.ABSCHWEIF_ANKER),
        "tage": _wochentage_naechste_woche(),
        "testnummer": saetze.TESTNUMMER,
        "biancaBasis": BIANCA_BASIS,
    }


class LaufWunsch(BaseModel):
    anzahl: int = 1
    ab: int = 1
    tag: str = "Mittwoch"
    mithoeren: bool = False
    story: dict[str, Any] | None = None  # manuell gebaute Story (Chips)


@app.post("/api/lauf")
def lauf_starten(w: LaufWunsch) -> JSONResponse:
    with _lock:
        if _zustand["laeuft"]:
            return JSONResponse({"ok": False, "fehler": "es läuft schon ein Lauf"}, status_code=409)
    if w.story:
        basis = geschichten.automatik(int(w.story.get("nr") or w.ab), tag=w.tag)
        basis.update({k: v for k, v in w.story.items() if v is not None})
        basis["tag"] = w.tag
        art = str(basis.get("anliegen") or geschichten.TERMIN)
        if art in geschichten.DOKU_ARTEN:
            basis["id"] = f"s{basis['nr']:02d}-{basis['stimme']}-{art}"
        stories = [basis]
    else:
        stories = [geschichten.automatik(nr, tag=w.tag)
                   for nr in range(w.ab, w.ab + max(1, w.anzahl))]
    t = threading.Thread(target=_lauf_thread, args=(stories, w.mithoeren), daemon=True)
    t.start()
    return JSONResponse({"ok": True, "stories": [s["id"] for s in stories]})


@app.get("/api/live")
def live() -> dict[str, Any]:
    with _lock:
        anruf = _zustand["aktiv"]
        out = {
            "laeuft": _zustand["laeuft"],
            "laufId": _zustand["laufId"],
            "storyIdx": _zustand["storyIdx"],
            "storiesGesamt": _zustand["storiesGesamt"],
            "fertig": _zustand["fertig"],
            "fehler": _zustand["fehler"],
            "story": "",
            "zuege": [],
        }
        if anruf is not None:
            out["story"] = str(anruf.story.get("id") or "")
            # Relativ (ohne fuehrenden Slash): funktioniert direkt auf 8097
            # UND hinter der /studio/-Durchreiche des Bianca-Servers.
            basis = f"berichte/{_zustand['laufId']}/{out['story']}"
            zuege = []
            for z in list(anruf.zuege):
                z2 = dict(z)
                if z2.get("audio"):
                    z2["audioUrl"] = f"{basis}/{z2['audio']}"
                zuege.append(z2)
            out["zuege"] = zuege
    return out


@app.get("/api/laeufe")
def laeufe() -> dict[str, Any]:
    import json as _json
    out = []
    for p in sorted(BERICHTE_DIR.glob("*/lauf.json"), reverse=True):
        try:
            d = _json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        stories = d.get("stories") or []
        out.append({"laufId": d.get("laufId") or p.parent.name,
                    "gestartet": d.get("gestartet") or "",
                    "gruen": sum(1 for s in stories if s.get("ok")),
                    "gesamt": len(stories)})
    return {"laeufe": out}


@app.get("/api/lauf/{lauf_id}")
def lauf_details(lauf_id: str) -> dict[str, Any]:
    import json as _json
    p = BERICHTE_DIR / lauf_id / "lauf.json"
    try:
        return _json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"laufId": lauf_id, "stories": []}


@app.get("/api/bericht/{lauf_id}/{story_id}")
def bericht(lauf_id: str, story_id: str) -> dict[str, Any]:
    import json as _json
    p = BERICHTE_DIR / lauf_id / story_id / "bericht.json"
    try:
        return _json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"id": story_id, "zuege": [], "fehler": "Bericht nicht gefunden"}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/ergebnisse")
def ergebnisse() -> FileResponse:
    return FileResponse(WEB_DIR / "ergebnisse.html")


BERICHTE_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/berichte", StaticFiles(directory=str(BERICHTE_DIR)), name="berichte")
app.mount("/web", StaticFiles(directory=str(WEB_DIR)), name="web")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8097)
