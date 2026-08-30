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

import httpx  # noqa: E402
from fastapi import FastAPI, File, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from tests.baukasten import aufraeumen, auftrag, geschichten, klang, runner, saetze, selbst  # noqa: E402

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
    "warm": None,        # {story, i, n, text} waehrend TTS-Vorwaermen
    "auftrag": None,     # Einzellauf: Punkte fuer Grok (None beim 10er-Batch)
    "modus": "",         # "lauf" | "selbst"
    "marken": [],        # [{idx, wer, text, kommentar}] waehrend des Gespraechs
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


def _eins_rendern(story: dict, text: str, *, i: int, n: int, art: str) -> None:
    stimme = str(story.get("stimme") or "markus")
    with _lock:
        _zustand["warm"] = {
            "story": story.get("id") or "",
            "i": i, "n": n, "text": text, "art": art,
        }
    pfad = klang.audio_holen(stimme, text)
    if story.get("telefonQualitaet"):
        pfad = klang.telefon_datei(pfad)
    if not pfad.is_file() or pfad.stat().st_size <= 44:
        raise RuntimeError(f"kein Audio fuer {text!r}")


def _audio_vorwaermen(story: dict) -> None:
    """Freifelder ZUERST und zwingend, danach Katalog. Ohne Freifeld-WAV kein Anruf."""
    geschichten.story_frei_normieren(story)
    frei = geschichten.frei_saetze(story)
    rest = [t for t in geschichten.saetze_fuer_audio(story) if t not in set(frei)]
    fehl = []
    for i, t in enumerate(frei):
        try:
            _eins_rendern(story, t, i=i + 1, n=len(frei) or 1, art="freifeld")
        except Exception as e:
            fehl.append(f"{t!r}: {type(e).__name__}: {e}")
            print(f"baukasten-warm FREIFELD: {type(e).__name__}: {e}", flush=True)
    if fehl:
        raise RuntimeError("Freifeld-Audio vor dem Start fehlgeschlagen — "
                           + " | ".join(fehl))
    for i, t in enumerate(rest):
        try:
            _eins_rendern(story, t, i=i + 1, n=len(rest) or 1, art="katalog")
        except Exception as e:
            print(f"baukasten-warm katalog: {type(e).__name__}: {e}", flush=True)
    with _lock:
        _zustand["warm"] = None


def _auftrag_ablegen(bericht: dict, lauf_id: str) -> None:
    try:
        with _lock:
            marken = list(_zustand.get("marken") or [])
        paket = auftrag.schreiben(bericht, lauf_id, marken=marken)
        with _lock:
            _zustand["auftrag"] = paket
    except Exception as e:
        print(f"baukasten-auftrag: {type(e).__name__}: {e}", flush=True)


def _lauf_thread(stories: list[dict], mithoeren: bool) -> None:
    lauf_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    lauf_dir = BERICHTE_DIR / lauf_id
    lauf_dir.mkdir(parents=True, exist_ok=True)
    with _lock:
        _zustand.update({"laeuft": True, "laufId": lauf_id, "storyIdx": 0,
                         "storiesGesamt": len(stories), "fertig": [], "fehler": "",
                         "warm": None, "auftrag": None, "modus": "lauf",
                         "marken": []})
    try:
        import json as _json
        import time as _time
        berichte = []
        letzter_bericht: dict[str, Any] | None = None
        for i, story in enumerate(stories):
            with _lock:
                _zustand["storyIdx"] = i + 1
                _zustand["aktiv"] = None
            try:
                _audio_vorwaermen(story)
                with _lock:
                    _zustand["fehler"] = ""
            except Exception as e:
                kurz = {"id": story.get("id"), "ok": False, "checks": [],
                        "latenzMaxS": 0, "fehler": str(e), "pfad": ""}
                berichte.append(kurz)
                letzter_bericht = auftrag.ersatz(story, str(e))
                with _lock:
                    _zustand["fertig"] = list(berichte)
                    _zustand["fehler"] = str(e)
                    _zustand["warm"] = None
                if len(stories) == 1:
                    _auftrag_ablegen(letzter_bericht, lauf_id)
                continue
            anruf = runner.Anruf(story, basis=BIANCA_BASIS, lauf_dir=lauf_dir,
                                 echtzeit=True, mithoeren=False)
            with _lock:
                _zustand["aktiv"] = anruf
                _zustand["warm"] = None
            b = anruf.fuehren()
            letzter_bericht = b
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
            if len(stories) == 1:
                _auftrag_ablegen(b, lauf_id)
            _time.sleep(2.0)
    except Exception as e:  # Lauf-Thread darf nie still sterben
        with _lock:
            _zustand["fehler"] = f"{type(e).__name__}: {e}"
    finally:
        with _lock:
            _zustand["laeuft"] = False
            _zustand["aktiv"] = None
            _zustand["warm"] = None
            if _zustand.get("modus") == "lauf":
                _zustand["modus"] = ""


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
    telefonQualitaet: bool = False  # 8 kHz / 8 bit Anrufer-Audio
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
    for s in stories:
        geschichten.story_frei_normieren(s)
    if w.telefonQualitaet:
        for s in stories:
            s["telefonQualitaet"] = True
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
            "warm": _zustand.get("warm"),
            "auftrag": _zustand.get("auftrag"),
            "modus": _zustand.get("modus") or "",
            "marken": list(_zustand.get("marken") or []),
        }
        if anruf is not None:
            out["story"] = str(anruf.story.get("id") or "")
            # api/ton schliesst offene Stream-Header und laeuft relativ
            # sowohl auf 8097 als auch hinter /studio/ auf 8096.
            zuege = []
            for z in list(anruf.zuege):
                z2 = dict(z)
                name = Path(str(z2.get("audio") or "")).name
                if name:
                    z2["audioUrl"] = f"api/ton/{_zustand['laufId']}/{out['story']}/{name}"
                zuege.append(z2)
            out["zuege"] = zuege
    return out


@app.get("/api/ton/{lauf_id}/{story_id}/{name}")
def ton(lauf_id: str, story_id: str, name: str) -> Response:
    """Abspielbares Audio einer Bubble: Stream-WAV-Header wird geschlossen,
    damit der Browser wirklich Toene macht (nicht nur den Play-Knopf zeigt)."""
    if "/" in name or "\\" in name or name in {".", ".."}:
        return Response(status_code=404)
    p = BERICHTE_DIR / lauf_id / story_id / "audio" / name
    if not p.is_file():
        return Response(status_code=404)
    blob = p.read_bytes()
    if blob[:4] == b"RIFF":
        blob = klang.wav_schliessen(blob)
        return Response(blob, media_type="audio/wav",
                        headers={"Cache-Control": "no-store", "Accept-Ranges": "bytes"})
    return Response(blob, media_type="audio/mpeg",
                    headers={"Cache-Control": "no-store"})


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


@app.get("/api/auftrag")
def auftrag_lesen() -> dict[str, Any]:
    with _lock:
        paket = _zustand.get("auftrag")
    if paket:
        return paket
    return auftrag.lesen() or {"ok": False, "tickets": [], "markdown": ""}


class AuftragHinweis(BaseModel):
    hinweis: str = ""
    marken: list[dict[str, Any]] | None = None


class AuftragMarke(BaseModel):
    idx: int
    text: str = ""
    wer: str = "Bianca"
    kommentar: str = ""


class SelbstZug(BaseModel):
    text: str = ""


def _marken_upsert(ein: dict[str, Any]) -> list[dict[str, Any]]:
    with _lock:
        marken = [m for m in (_zustand.get("marken") or [])
                  if int(m.get("idx") or -1) != int(ein.get("idx") or -1)]
        if str(ein.get("kommentar") or "").strip():
            marken.append(ein)
        marken = auftrag._norm_marken(marken)
        _zustand["marken"] = marken
        return list(marken)


@app.post("/api/auftrag")
def auftrag_hinweis(w: AuftragHinweis) -> JSONResponse:
    if w.marken is not None:
        with _lock:
            _zustand["marken"] = auftrag._norm_marken(w.marken)
        paket = auftrag.marken_setzen(w.marken)
        if paket and w.hinweis.strip():
            paket = auftrag.hinweis_setzen(w.hinweis)
    else:
        paket = auftrag.hinweis_setzen(w.hinweis)
    if not paket:
        return JSONResponse({"ok": False, "fehler": "kein Einzellauf-Auftrag da"},
                            status_code=404)
    with _lock:
        _zustand["auftrag"] = paket
    return JSONResponse(paket)


@app.post("/api/auftrag/marke")
def auftrag_marke(w: AuftragMarke) -> JSONResponse:
    marken = _marken_upsert({
        "idx": w.idx, "text": w.text, "wer": w.wer, "kommentar": w.kommentar,
    })
    paket = auftrag.marken_setzen(marken)
    if paket:
        with _lock:
            _zustand["auftrag"] = paket
    return JSONResponse({"ok": True, "marken": marken, "auftrag": paket})


@app.post("/api/selbst/start")
def selbst_start() -> JSONResponse:
    with _lock:
        if _zustand["laeuft"]:
            return JSONResponse({"ok": False, "fehler": "es läuft schon ein Anruf"},
                                status_code=409)
        anruf = selbst.LiveAnruf()
        lauf_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        _zustand.update({
            "laeuft": True, "laufId": lauf_id, "storyIdx": 1, "storiesGesamt": 1,
            "fertig": [], "fehler": "", "warm": None, "auftrag": None,
            "modus": "selbst", "marken": [], "aktiv": anruf,
        })
    try:
        antwort = selbst.start(anruf, basis=BIANCA_BASIS)
    except Exception as e:
        with _lock:
            _zustand.update({"laeuft": False, "aktiv": None, "modus": "",
                             "fehler": str(e)})
        anruf.schliessen()
        return JSONResponse({"ok": False, "fehler": str(e)}, status_code=502)
    return JSONResponse({"ok": True, "laufId": lauf_id, **antwort})


@app.post("/api/selbst/zug")
def selbst_zug_text(w: SelbstZug) -> JSONResponse:
    text = str(w.text or "").strip()
    with _lock:
        anruf = _zustand.get("aktiv")
        if _zustand.get("modus") != "selbst" or not isinstance(anruf, selbst.LiveAnruf):
            return JSONResponse({"ok": False, "fehler": "kein Selbst-Anruf"},
                                status_code=409)
    if not text:
        return JSONResponse({"ok": False, "fehler": "kein Text"}, status_code=400)
    try:
        final = selbst.zug_text(anruf, text, basis=BIANCA_BASIS)
    except Exception as e:
        return JSONResponse({"ok": False, "fehler": str(e)}, status_code=502)
    return JSONResponse({"ok": True, **final})


@app.post("/api/selbst/hoeren")
async def selbst_zug_audio(audio: UploadFile = File(...)) -> JSONResponse:
    with _lock:
        anruf = _zustand.get("aktiv")
        if _zustand.get("modus") != "selbst" or not isinstance(anruf, selbst.LiveAnruf):
            return JSONResponse({"ok": False, "fehler": "kein Selbst-Anruf"},
                                status_code=409)
    blob = await audio.read()
    try:
        final = selbst.zug_audio(
            anruf, blob, audio.content_type or "application/octet-stream",
            audio.filename or "turn.webm", basis=BIANCA_BASIS)
    except Exception as e:
        return JSONResponse({"ok": False, "fehler": str(e)}, status_code=502)
    return JSONResponse({"ok": True, **final})


@app.post("/api/selbst/hangup")
def selbst_hangup() -> JSONResponse:
    with _lock:
        anruf = _zustand.get("aktiv")
        lauf_id = _zustand.get("laufId") or ""
        if _zustand.get("modus") != "selbst" or not isinstance(anruf, selbst.LiveAnruf):
            return JSONResponse({"ok": True, "leer": True})
        _zustand["aktiv"] = None
    selbst.auflegen(anruf, basis=BIANCA_BASIS)
    bericht = selbst.bericht_bauen(anruf)
    _auftrag_ablegen(bericht, lauf_id)
    with _lock:
        _zustand.update({"laeuft": False, "modus": "", "aktiv": None})
        paket = _zustand.get("auftrag")
    return JSONResponse({"ok": True, "auftrag": paket})


@app.get("/api/selbst/ton/{art}/{name}")
def selbst_ton(art: str, name: str) -> Response:
    if art not in {"audio", "audio-stream"} or "/" in name or "\\" in name:
        return Response(status_code=404)
    try:
        r = httpx.get(f"{BIANCA_BASIS}/api/{art}/{name}", timeout=90.0)
    except httpx.HTTPError:
        return Response(status_code=502)
    if r.status_code != 200:
        return Response(status_code=r.status_code)
    mime = r.headers.get("content-type") or "audio/wav"
    return Response(r.content, media_type=mime,
                    headers={"Cache-Control": "no-store"})


@app.on_event("startup")
def _autoloesch_start() -> None:
    """Testtermine aus dem Studio nach 2 Stunden wieder aus dem Kalender."""
    aufraeumen.waechter_starten()


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
