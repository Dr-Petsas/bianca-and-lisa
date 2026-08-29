"""Aufraeum-Skript des Baukasten-Tests: gebuchte TESTTERMINE absagen (W-BK-7).

Praezise ueber die Berichte: jede Story-Buchung traegt die appointmentId
(lastBook/lastMove im lastCall) — genau diese Termine werden per
agentCancelAppointmentById storniert, nie ein fremder Termin. Schon
stornierte IDs merkt sich berichte/aufgeraeumt.json (idempotent).

Chef 29.08.2026: nicht SOFORT loeschen — Testtermine bleiben 2 Stunden
im Kalender (Kontrolle), dann Autoloesch. Die Warteschlange liegt in
berichte/autoloesch.json (gebuchtUm + loeschenAb). Der Waechter im
Test-Studio (8097) und im Bianca-Dienst raeumt reife Eintraege.

Optional --namen: Sweep ueber die Runner-Personas (Vorname der Stimme +
Nachname aus dem Pool) fuer verwaiste Buchungen, wenn ein Lauf VOR dem
Bericht starb. Sagt nur KOMMENDE Termine ab und nur bei exaktem
Vor+Nachname-Treffer einer Test-Persona — ebenfalls erst nach 2 Stunden
(erste Sichtung startet die Uhr).

Aufruf:
  python -m tests.baukasten.aufraeumen              # nur Reife (Default 2 h)
  python -m tests.baukasten.aufraeumen --lauf <id>  # nur ein Lauf
  python -m tests.baukasten.aufraeumen --namen      # zusaetzlich Persona-Sweep
  python -m tests.baukasten.aufraeumen --probe      # nur anzeigen
  python -m tests.baukasten.aufraeumen --sofort     # ohne Wartezeit
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from kern import calendar as kal  # noqa: E402
from kern import patients, tenants  # noqa: E402
from tests.baukasten import saetze  # noqa: E402

BERICHTE_DIR = Path(__file__).resolve().parent / "berichte"
MERKDATEI = BERICHTE_DIR / "aufgeraeumt.json"
SCHLANGE = BERICHTE_DIR / "autoloesch.json"
HALTE_S = 2 * 3600  # 2 Stunden im Kalender, dann Autoloesch

_WAECHTER: threading.Thread | None = None
_WAECHTER_LOCK = threading.Lock()


def _jetzt(wert: datetime | str | None = None) -> datetime:
    if wert is None:
        return datetime.now()
    if isinstance(wert, datetime):
        return wert
    return datetime.fromisoformat(str(wert))


def _parse_dt(wert: Any) -> datetime | None:
    if isinstance(wert, datetime):
        return wert
    try:
        return datetime.fromisoformat(str(wert or "").replace("Z", "+00:00").split("+")[0])
    except (TypeError, ValueError):
        return None


def _gemerkt(pfad: Path | None = None) -> set[str]:
    p = pfad or MERKDATEI
    try:
        return set(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, TypeError):
        return set()


def _merken(ids: set[str], pfad: Path | None = None) -> None:
    p = pfad or MERKDATEI
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(sorted(ids), ensure_ascii=False, indent=1),
                 encoding="utf-8")


def schlange_lesen(pfad: Path | None = None) -> list[dict]:
    p = pfad or SCHLANGE
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError, TypeError):
        return []


def schlange_schreiben(eintraege: list[dict], pfad: Path | None = None) -> None:
    p = pfad or SCHLANGE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(eintraege, ensure_ascii=False, indent=1),
                 encoding="utf-8")


def funde_aus_bericht(bericht: dict) -> list[dict]:
    """Buchungs- und neu angelegte Akten-IDs eines Story-Berichts."""
    funde: list[dict] = []
    lc = bericht.get("lastCall") or {}
    gebucht = str(bericht.get("start") or "")
    story = str(bericht.get("id") or "")
    for key in ("lastBook", "lastMove"):
        eintrag = lc.get(key) or {}
        aid = str(eintrag.get("appointmentId") or "")
        if aid and (eintrag.get("booked") or eintrag.get("moved") or eintrag.get("ok")):
            funde.append({
                "id": aid, "art": "termin", "story": story,
                "slotIso": str(eintrag.get("slotIso") or ""),
                "gebuchtUm": gebucht,
            })
    create = lc.get("lastCreate") or {}
    book = lc.get("lastBook") or {}
    neu = bool(create.get("created") or book.get("createdPatient"))
    pid = str(create.get("patientId") or book.get("patientId") or "")
    if neu and not pid:
        pid = str(lc.get("patientId") or "")
    if neu and pid:
        funde.append({
            "id": pid, "art": "patient", "story": story,
            "name": str(lc.get("patientName") or ""),
            "gebuchtUm": gebucht,
        })
    return funde


def ids_aus_berichten(lauf: str = "") -> list[dict]:
    """Alle Buchungs-IDs aus den Berichten: [{id, story, slotIso, gebuchtUm}]."""
    funde: list[dict] = []
    muster = f"{lauf}/*/bericht.json" if lauf else "*/*/bericht.json"
    for pfad in sorted(BERICHTE_DIR.glob(muster)):
        try:
            b = json.loads(pfad.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        funde.extend(funde_aus_bericht(b))
    return funde


def persona_termine(tenant: dict) -> list[dict]:
    """Sweep: kommende Termine aller Test-Personas (exakter Vor+Nachname)."""
    funde: list[dict] = []
    vornamen = sorted(set(saetze.VORNAMEN.values()))
    for nachname in saetze.NACHNAMEN:
        for vorname in vornamen:
            ctx = {"firstName": vorname, "lastName": nachname}
            found = kal.find_patient_appointments(tenant, ctx)
            pat = found.get("patient") or {}
            if (str(pat.get("firstName") or "").lower() != vorname.lower()
                    or str(pat.get("lastName") or "").lower() != nachname.lower()):
                continue
            for a in found.get("appointments") or []:
                aid = str(a.get("id") or a.get("appointmentId") or "")
                if aid:
                    funde.append({"id": aid, "art": "termin",
                                  "story": f"sweep {vorname} {nachname}",
                                  "slotIso": str(a.get("iso") or a.get("date") or "")})
    return funde


def vormerken(funde: list[dict], *, jetzt: datetime | str | None = None,
              halte_s: int = HALTE_S, pfad: Path | None = None) -> list[dict]:
    """Neue Buchungen in die Autoloesch-Schlange — bestehende IDs bleiben."""
    t0 = _jetzt(jetzt)
    def _key(e: dict) -> str:
        return f"{e.get('art') or 'termin'}:{e.get('id')}"

    by_id = {_key(e): e for e in schlange_lesen(pfad) if e.get("id")}
    for f in funde:
        aid = str(f.get("id") or "")
        art = str(f.get("art") or "termin")
        if not aid or _key({"art": art, "id": aid}) in by_id:
            continue
        start = _parse_dt(f.get("gebuchtUm")) or t0
        by_id[_key({"art": art, "id": aid})] = {
            "id": aid,
            "art": art,
            "story": str(f.get("story") or ""),
            "slotIso": str(f.get("slotIso") or ""),
            "name": str(f.get("name") or ""),
            "gebuchtUm": start.isoformat(timespec="seconds"),
            "loeschenAb": (start + timedelta(seconds=halte_s)).isoformat(timespec="seconds"),
        }
    neu = list(by_id.values())
    schlange_schreiben(neu, pfad)
    return neu


def vormerken_aus_bericht(bericht: dict, **kw: Any) -> list[dict]:
    return vormerken(funde_aus_bericht(bericht), **kw)


def reife(eintraege: list[dict] | None = None, *, jetzt: datetime | str | None = None,
          pfad: Path | None = None, merkliste: Path | None = None) -> list[dict]:
    """Eintraege, deren 2-Stunden-Frist abgelaufen ist."""
    t0 = _jetzt(jetzt)
    schon = _gemerkt(merkliste)
    if eintraege is None:
        eintraege = schlange_lesen(pfad)
    out: list[dict] = []
    for e in eintraege:
        aid = str(e.get("id") or "")
        if not aid or f"{e.get('art') or 'termin'}:{aid}" in schon or aid in schon:
            continue
        ab = _parse_dt(e.get("loeschenAb"))
        if ab is not None and ab <= t0:
            out.append(e)
    return out


def _merk_key(eintrag: dict) -> str:
    return f"{eintrag.get('art') or 'termin'}:{eintrag.get('id')}"


def ausfuehren(funde: list[dict], *, probe: bool = False,
               tenant: dict | None = None,
               merkliste: Path | None = None,
               cancel_fn=None, delete_fn=None) -> dict[str, int]:
    """Reife Testtermine absagen und neu angelegte Testakten loeschen."""
    gemerkt = _gemerkt(merkliste)
    offen = [f for f in funde if f.get("id")
             and _merk_key(f) not in gemerkt and f["id"] not in gemerkt]
    gesehen: set[str] = set()
    offen = [f for f in offen if not (_merk_key(f) in gesehen or gesehen.add(_merk_key(f)))]
    # Termine zuerst, dann Akten — sonst bleiben verwaiste Termine.
    offen.sort(key=lambda f: 0 if (f.get("art") or "termin") == "termin" else 1)
    if probe:
        for f in offen:
            was = "Akte" if f.get("art") == "patient" else "Termin"
            print(f"  wuerde {was} loeschen: {f['id']}  {f.get('slotIso') or f.get('name')}  "
                  f"[{f.get('story')}]", flush=True)
        return {"offen": len(offen), "abgesagt": 0, "fehler": 0}

    ten = tenant if tenant is not None else tenants.laden("meddent")

    def _cancel(tid: str) -> dict:
        if cancel_fn:
            return cancel_fn(tid)
        return kal.cancel_by_id(ten, {}, tid)

    def _delete(pid: str) -> dict:
        if delete_fn:
            return delete_fn(pid)
        return patients.akte_loeschen(ten, pid)

    fehler = 0
    abgesagt = 0
    for f in offen:
        art = str(f.get("art") or "termin")
        if art == "patient":
            r = _delete(f["id"])
            ok = isinstance(r, dict) and (r.get("deleted") or r.get("alreadyGone") or r.get("dryRun"))
            label = "Akte geloescht"
        else:
            r = _cancel(f["id"])
            ok = isinstance(r, dict) and r.get("cancelled")
            label = "abgesagt"
        if ok:
            gemerkt.add(_merk_key(f))
            gemerkt.add(f["id"])
            abgesagt += 1
            print(f"  {label}: {f['id']}  {f.get('slotIso') or f.get('name')}  [{f.get('story')}]",
                  flush=True)
        else:
            fehler += 1
            grund = ""
            if isinstance(r, dict):
                grund = str(r.get("spoken") or r.get("error") or r)
            else:
                grund = str(r)
            print(f"  FEHLER:   {f['id']}  {f.get('slotIso') or f.get('name')}  [{f.get('story')}] -> "
                  f"{grund}", flush=True)
    _merken(gemerkt, merkliste)
    return {"offen": len(offen), "abgesagt": abgesagt, "fehler": fehler}


def reife_ausfuehren(*, jetzt: datetime | str | None = None, probe: bool = False,
                     pfad: Path | None = None, merkliste: Path | None = None,
                     tenant: dict | None = None, cancel_fn=None,
                     delete_fn=None) -> dict[str, int]:
    offen = reife(jetzt=jetzt, pfad=pfad, merkliste=merkliste)
    if not offen:
        return {"offen": 0, "abgesagt": 0, "fehler": 0}
    print(f"autoloesch: {len(offen)} Testeintraege aelter als 2 h — raeume auf",
          flush=True)
    return ausfuehren(offen, probe=probe, tenant=tenant, merkliste=merkliste,
                      cancel_fn=cancel_fn, delete_fn=delete_fn)


def waechter_starten(*, interval_s: int = 60) -> threading.Thread:
    """Daemon: jede Minute reife Testtermine loeschen. Pro Prozess nur einer."""
    global _WAECHTER
    with _WAECHTER_LOCK:
        if _WAECHTER is not None and _WAECHTER.is_alive():
            return _WAECHTER

        def _lauf() -> None:
            while True:
                try:
                    reife_ausfuehren()
                except Exception as e:
                    print(f"autoloesch: {type(e).__name__}: {e}", flush=True)
                time.sleep(max(15, int(interval_s)))

        t = threading.Thread(target=_lauf, name="testtermin-autoloesch", daemon=True)
        t.start()
        _WAECHTER = t
        print("autoloesch: Waechter an (Testtermine nach 2 Stunden)", flush=True)
        return t


def main() -> None:
    p = argparse.ArgumentParser(description="Testtermine des Baukasten-Laufs absagen")
    p.add_argument("--lauf", default="", help="nur Berichte dieses Laufs")
    p.add_argument("--namen", action="store_true", help="zusaetzlich Persona-Sweep")
    p.add_argument("--probe", action="store_true", help="nur anzeigen, nichts absagen")
    p.add_argument("--sofort", action="store_true",
                   help="ohne 2-Stunden-Wartezeit (Notaus)")
    p.add_argument("--warte-stunden", type=float, default=2.0,
                   help="wie lange der Termin im Kalender bleibt (Default 2)")
    a = p.parse_args()

    tenant = tenants.laden("meddent")
    funde = ids_aus_berichten(a.lauf)
    if a.namen:
        funde += persona_termine(tenant)

    halte = 0 if a.sofort else int(max(0.0, a.warte_stunden) * 3600)
    vormerken(funde, halte_s=halte)
    offen = reife() if halte else [
        e for e in schlange_lesen() if e.get("id") not in _gemerkt()
    ]
    # Dedupe
    gesehen: set[str] = set()
    offen = [f for f in offen if f.get("id") and not (f["id"] in gesehen or gesehen.add(f["id"]))]

    print(f"aufraeumen: {len(funde)} Buchungen gefunden, {len(offen)} reif "
          f"(halte {halte // 60} min, {len(_gemerkt())} schon storniert)", flush=True)
    erg = ausfuehren(offen, probe=a.probe, tenant=tenant)
    if a.probe:
        return
    print(f"aufraeumen: fertig — {erg['abgesagt']} abgesagt, {erg['fehler']} Fehler",
          flush=True)
    sys.exit(1 if erg["fehler"] else 0)


if __name__ == "__main__":
    main()
