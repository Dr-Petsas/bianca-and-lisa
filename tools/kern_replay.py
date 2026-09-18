"""Replay echter Bianca-Anrufe durch den neuen Dialogkern (DIALOG_CONTROLLER).

STRIKT read-only fuer das Live-Verhalten. Dieses Werkzeug ruft KEINE Werkzeuge
auf, bucht nichts, ruft keine Cloud Function. Es liest die aufgezeichneten
Anruf-Manifeste (``.data/anrufe/<stimme>/<sid>/anruf.json``), spielt jeden
Anrufer-Zug durch den reinen Reducer (``bianca/controller/reducer.py``) und
schreibt die hypothetische Kern-Entscheidung ADDITIV je Zug ins Manifest
(``zug["kernReplay"]``) plus eine Kopfzeile (``manifest["kernReplaySummary"]``).
Diese Zusatzfelder sieht nur die ``/anrufe``-Ansicht — der Anruf-Pfad ist davon
voellig unberuehrt.

Zweck (Chef 18.09.2026): "ich will erst schattenlaeufe ... an den echten
anrufen ... wie der neue dialogkern entschieden haette an jeder position ...
dann haben wir den beweis oder weitere hinweise was nicht funktioniert."

Aufrufe:
    python tools/kern_replay.py scan            # heutige Bianca-Anrufe
    python tools/kern_replay.py scan --alle      # alle Tage
    python tools/kern_replay.py scan --tag 20260918
    python tools/kern_replay.py scan --stimme bianca --sid <hex>
    python tools/kern_replay.py qwen             # Qwen-2.-Ohr-Diagnose
    python tools/kern_replay.py scan --json out.json   # Aggregat fuer die E-Mail

Ehrlichkeit ueber die Reichweite:
  * SAMMELPHASE (Reihenfolge der Fragen): der Kern wird aus den real geernteten
    Feldern gefuettert -> der Vergleich der naechsten Frage ist belastbar.
  * NACH dem ersten Werkzeug: die ``ToolOutcome``s werden aus den belegten
    Anruf-Fakten (lastBook/lastCancel/lastMove, slotwahl-Frage) SYNTHETISIERT,
    damit der Kern bis zum terminalen Zug laeuft. Solche Zuege sind mit
    ``"synth": true`` markiert.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Repo-Wurzel in den Pfad (Werkzeug laeuft aus tools/).
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from bianca.controller import policy as _policy  # noqa: E402
from bianca.controller.reducer import reduce as _reduce  # noqa: E402
from bianca.controller.typen import (  # noqa: E402
    Intent,
    Naechste,
    OutcomeStatus,
    Quelle,
    SemanticEvent,
    SlotValue,
    State,
    ToolOutcome,
)


# --------------------------------------------------------------------------- #
# Ablage.
# --------------------------------------------------------------------------- #
def _data_dir() -> Path:
    import os

    d = os.environ.get("MITSCHNITT_DIR") or ".data/anrufe"
    p = Path(d)
    if not p.is_absolute():
        p = _ROOT / p
    return p


# --------------------------------------------------------------------------- #
# Feld-/Fragen-Abbildung Live <-> Kern.
# --------------------------------------------------------------------------- #
# Live-Frage (was Bianca zuletzt fragte) -> Kern-Slot, den der Anrufer nun fuellt.
_FRAGE_SLOT: dict[str, str] = {
    "grund": "besuchsgrund",
    "wunsch": "wunschzeit",
    "arzt": "behandler",
    "arzt_nachfrage": "behandler",
    "nachname": "nachname",
    "buchstabieren": "nachname",
    "nachname_korr": "nachname",
    "vorname": "vorname",
    "versicherung": "versicherung",
    "slotwahl": "terminwahl",
    "telefon": "telefon",
}

# Live-Fragen mit Ja/Nein-Erwartung (Bestaetigungs-Deutung).
_JANEIN = {
    "schonmal", "arzt_check", "anrufer_check", "fuer_wen_check",
    "telefon_check", "versicherung_check", "vorname_check", "nachname_check",
    "bestaetigung", "pzr", "rueckruf_ja", "sonst_noch", "termin_ok",
}

# Kanonische Gruppe (fuer den Divergenzvergleich Live-Frage vs Kern-frage_id).
_KANON: dict[str, str] = {
    "grund": "besuchsgrund", "besuchsgrund": "besuchsgrund",
    "wunsch": "wunschzeit", "wunschzeit": "wunschzeit",
    "arzt": "behandler", "arzt_nachfrage": "behandler", "behandler": "behandler",
    "nachname": "nachname", "buchstabieren": "nachname", "nachname_korr": "nachname",
    "vorname": "vorname",
    "versicherung": "versicherung",
    "slotwahl": "terminwahl", "terminwahl": "terminwahl",
    "telefon": "telefon",
}


def _kanon(frage: str) -> str:
    return _KANON.get((frage or "").strip(), (frage or "").strip())


# --------------------------------------------------------------------------- #
# Intent-Erkennung aus dem ersten Anrufer-Satz + Anruf-Fakten.
# --------------------------------------------------------------------------- #
import re  # noqa: E402

_RE_ABSAGEN = re.compile(r"\b(absag\w*|stornier\w*|cancel\w*|absetz\w*|nicht (kommen|wahrnehmen)|termin.*(löschen|streichen))", re.I)
_RE_VERSCHIEBEN = re.compile(r"\b(verschieb\w*|verleg\w*|umleg\w*|anderen termin|früher\w*|später\w*)\b", re.I)
_RE_VERBINDEN = re.compile(r"\b(verbind\w*|durchstell\w*|weiterleit\w*|sprechen mit (doktor|dr|herr|frau)|ans telefon)\b", re.I)
_RE_DOKUMENT = re.compile(r"\b(rezept(?!ion)\w*|überweis\w*|krankschreib\w*|krankmeld\w*|attest\w*|befund\w*)\b", re.I)
_RE_RUECKRUF = re.compile(r"\b(rückruf\w*|zurückruf\w*|zurück ruf\w*|meldet sich|melde mich)\b", re.I)
_RE_NOTFALL = re.compile(r"\b(notfall\w*|starke schmerz\w*|blut\w*|geschwoll\w*|akut\w*|dringend\w*)\b", re.I)
_RE_AUSKUNFT = re.compile(r"\b(habe ich .*termin|wann (ist|war) (mein|der).*termin|termin.*vergess\w*|welche termine)\b", re.I)
_RE_BUCHEN = re.compile(r"\b(termin\w*|buch\w*|hätte gern\w*|bräuchte\w*|möchte\w*|kontrolle\w*|vorstell\w*)\b", re.I)


def _intent_von(erster_satz: str, hat_book_tool: bool) -> tuple[Intent, str]:
    t = erster_satz or ""
    if _RE_NOTFALL.search(t):
        return Intent.NOTFALL, "keyword"
    if _RE_ABSAGEN.search(t):
        return Intent.ABSAGEN, "keyword"
    if _RE_VERSCHIEBEN.search(t):
        return Intent.VERSCHIEBEN, "keyword"
    if _RE_AUSKUNFT.search(t):
        return Intent.AUSKUNFT, "keyword"
    if _RE_VERBINDEN.search(t):
        return Intent.VERBINDEN, "keyword"
    if _RE_DOKUMENT.search(t):
        return Intent.DOKUMENT, "keyword"
    if _RE_RUECKRUF.search(t):
        return Intent.RUECKRUF, "keyword"
    if _RE_BUCHEN.search(t) or hat_book_tool:
        return Intent.BUCHEN, "keyword" if _RE_BUCHEN.search(t) else "tools"
    return Intent.BUCHEN, "default"


# --------------------------------------------------------------------------- #
# Ja/Nein aus dem Anrufer-Satz (nur wenn eine Ja/Nein-Frage offen war).
# --------------------------------------------------------------------------- #
def _bestaetigung(prev_frage: str, spoken: str) -> bool | None:
    if prev_frage not in _JANEIN:
        return None
    try:
        from bianca import gehirn

        if gehirn.ist_ja(spoken):
            return True
        if gehirn.ist_nein(spoken):
            return False
    except Exception:
        pass
    return None


# --------------------------------------------------------------------------- #
# Werkzeug-Ergebnisse aus den belegten Anruf-Fakten synthetisieren.
# --------------------------------------------------------------------------- #
def _anruf_fakten(m: dict) -> dict[str, Any]:
    zuege = m.get("zuege") or []
    fragen = [str(z.get("frage") or "") for z in zuege if isinstance(z, dict)]

    def _ok(x: Any) -> bool:
        return bool(isinstance(x, dict) and x.get("ok"))

    booked = _ok(m.get("lastBook")) or any(_ok(z.get("book")) for z in zuege if isinstance(z, dict))
    offered = ("slotwahl" in fragen) or booked
    such_found = _ok(m.get("lastCancel")) or _ok(m.get("lastMove")) or ("auswahl" in fragen) or ("termin_ok" in fragen)
    # Buchungsfehler-Art (fuer needs_phone/slot_taken) aus lastBook.
    lb = m.get("lastBook") if isinstance(m.get("lastBook"), dict) else {}
    fehler = str(lb.get("error") or lb.get("grund") or "").lower()
    return {"booked": booked, "offered": offered, "such_found": such_found, "fehler": fehler}


def _synth_outcome(tool: str, spec, fakten: dict[str, Any]) -> ToolOutcome | None:
    if not tool:
        return None
    if spec and tool == spec.offer_tool:
        if fakten["offered"]:
            return ToolOutcome(name=tool, status=OutcomeStatus.OK,
                               payload={"slots": ["s1", "s2", "s3"]})
        return ToolOutcome(name=tool, status=OutcomeStatus.EMPTY)
    if spec and tool == spec.commit_tool:
        if fakten["booked"]:
            return ToolOutcome(name=tool, status=OutcomeStatus.OK, committed=True,
                               payload={"appointmentId": "replay"})
        if "phone" in fakten["fehler"] or "handy" in fakten["fehler"] or "telefon" in fakten["fehler"]:
            return ToolOutcome(name=tool, status=OutcomeStatus.NEEDS_PHONE)
        return ToolOutcome(name=tool, status=OutcomeStatus.SLOT_TAKEN)
    if spec and tool == spec.such_tool:
        if fakten["such_found"]:
            return ToolOutcome(name=tool, status=OutcomeStatus.OK,
                               payload={"appointments": [{"kurz": "Termin"}]})
        return ToolOutcome(name=tool, status=OutcomeStatus.NOT_FOUND)
    if spec and tool == spec.notiz_tool:
        return ToolOutcome(name=tool, status=OutcomeStatus.OK, committed=True)
    return None


# --------------------------------------------------------------------------- #
# Kern-Decision -> kompaktes Manifest-Feld.
# --------------------------------------------------------------------------- #
def _dec_dict(dec) -> dict[str, Any]:
    d: dict[str, Any] = {"naechste": dec.naechste.value}
    if dec.speak:
        d["akt"] = dec.speak.akt.value
        if dec.speak.frage_id:
            d["frage_id"] = dec.speak.frage_id
    if dec.tool:
        d["tool"] = dec.tool.name
    if dec.hangup:
        d["hangup"] = True
    if dec.grund:
        d["grund"] = dec.grund
    return d


# --------------------------------------------------------------------------- #
# Ein Manifest durch den Kern spielen.
# --------------------------------------------------------------------------- #
def _tenant_fuer(m: dict) -> dict:
    tid = str(m.get("tenantId") or "").strip()
    if not tid:
        return {}
    try:
        from kern import tenants

        t = tenants.laden(tid)
        return t if isinstance(t, dict) else {}
    except Exception:
        return {}


def replay_manifest(m: dict) -> dict[str, Any]:
    """Fuellt m['zuege'][*]['kernReplay'] und gibt ein Aggregat des Anrufs zurueck."""
    zuege = m.get("zuege") or []
    caller = [z for z in zuege if isinstance(z, dict) and str(z.get("textIn") or "").strip()]
    agg = {
        "sid": m.get("id") or "",
        "tenantId": m.get("tenantId") or "",
        "zuege_gesamt": len(zuege),
        "anrufer_zuege": len(caller),
        "i1": 0,          # Live-Frage zu bereits gefuelltem Feld
        "schleifen": 0,   # gleiche Live-Frage 3x in Folge
        "divergenzen": 0, # Live-Frage != Kern-Frage (Sammelphase)
        "intent": "",
        "intent_quelle": "",
        "kern_terminal": False,
    }
    if not caller:
        return agg

    hat_book = any(
        "book" in str(t).lower() or "masbook" in str(t).lower()
        for z in zuege if isinstance(z, dict)
        for t in (z.get("tools") or [])
    )
    intent, quelle = _intent_von(caller[0].get("textIn") or "", hat_book)
    agg["intent"] = intent.value
    agg["intent_quelle"] = quelle

    pol = _policy.aus_tenant(_tenant_fuer(m))
    spec = pol.spec(intent.value)
    fakten = _anruf_fakten(m)
    st = State()

    prev_frage = ""            # was Bianca vor diesem Anrufer-Zug fragte
    live_frage_hist: list[str] = []
    gefuellt: dict[str, str] = {}   # rein zur I1-Heuristik (aus prev_frage-Fills)

    for idx, z in enumerate(zuege):
        if not isinstance(z, dict):
            continue
        spoken = str(z.get("textIn") or "").strip()
        live_frage = str(z.get("frage") or "").strip()

        if spoken:
            # --- Slot aus der zuvor offenen Frage ernten ---------------- #
            slots: dict[str, SlotValue] = {}
            slot = _FRAGE_SLOT.get(prev_frage)
            if slot:
                slots[slot] = SlotValue(wert=spoken[:60], quelle=Quelle.GESAGT)
                gefuellt[slot] = spoken[:60]
            best = _bestaetigung(prev_frage, spoken)
            ev = SemanticEvent(intent=intent, slots=slots, bestaetigung=best, roh=spoken[:120])
            st, dec = _reduce(st, ev, pol)
            kr: dict[str, Any] = {"in": _dec_dict(dec)}

            # --- Nach Werkzeug: Outcome synthetisieren, Kern weiterlaufen  #
            runden = 0
            while dec.naechste == Naechste.WERKZEUG and dec.tool and runden < 4:
                oc = _synth_outcome(dec.tool.name, spec, fakten)
                if oc is None:
                    break
                st, dec = _reduce(st, oc, pol)
                kr.setdefault("nach_werkzeug", []).append(
                    {**_dec_dict(dec), "outcome": oc.status.value, "synth": True}
                )
                runden += 1

            # --- Divergenz (nur Sammelphase, beide fragen) -------------- #
            kern_frage = ""
            if dec.speak and dec.speak.frage_id:
                kern_frage = dec.speak.frage_id
            elif kr["in"].get("frage_id"):
                kern_frage = kr["in"]["frage_id"]
            if live_frage and kern_frage and _kanon(live_frage) != _kanon(kern_frage) \
                    and dec.naechste != Naechste.WERKZEUG:
                kr["divergenz"] = {"live": live_frage, "kern": kern_frage}
                agg["divergenzen"] += 1

            if st.terminal:
                agg["kern_terminal"] = True

            z["kernReplay"] = kr

        # --- Live-Gesundheitssignale (unabhaengig vom Kern) ------------- #
        if live_frage:
            # I1: Live fragt ein Feld, das (aus vorherigen Antworten) schon steht.
            lk = _kanon(live_frage)
            if lk in {_kanon(k) for k in gefuellt.keys()} and live_frage in _FRAGE_SLOT:
                z["liveSignal"] = {"i1": {"frage": live_frage}}
                agg["i1"] += 1
            live_frage_hist.append(live_frage)
            if len(live_frage_hist) >= 3 and live_frage_hist[-3:] == [live_frage] * 3:
                z.setdefault("liveSignal", {})["schleife"] = {"frage": live_frage, "n": 3}
                agg["schleifen"] += 1
            prev_frage = live_frage

    m["kernReplaySummary"] = {
        "intent": agg["intent"],
        "intent_quelle": agg["intent_quelle"],
        "anrufer_zuege": agg["anrufer_zuege"],
        "i1": agg["i1"],
        "schleifen": agg["schleifen"],
        "divergenzen": agg["divergenzen"],
        "kern_terminal": agg["kern_terminal"],
        "erzeugt": datetime.now(timezone.utc).isoformat(),
    }
    return agg


# --------------------------------------------------------------------------- #
# Manifeste finden / laden / schreiben.
# --------------------------------------------------------------------------- #
def _manifeste(stimme: str, tag: str, alle: bool, sid: str) -> list[Path]:
    basis = _data_dir() / (stimme or "bianca").strip().lower()
    if not basis.is_dir():
        return []
    if sid:
        p = basis / sid / "anruf.json"
        return [p] if p.is_file() else []
    heute = tag or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out: list[Path] = []
    for d in sorted(basis.iterdir()):
        p = d / "anruf.json"
        if not p.is_file():
            continue
        if alle:
            out.append(p)
            continue
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if str(m.get("startedAt") or "")[:10] == heute[:10]:
            out.append(p)
    return out


def _testanruf(m: dict) -> bool:
    return bool(m.get("testAnruf"))


def cmd_scan(args) -> int:
    pfade = _manifeste(args.stimme, args.tag, args.alle, args.sid)
    if not pfade:
        print(f"Keine Manifeste gefunden (stimme={args.stimme}, tag={args.tag or 'heute'}, alle={args.alle}).")
        return 0

    ges = {
        "anrufe": 0, "echt": 0, "test": 0, "anrufer_zuege": 0,
        "i1": 0, "schleifen": 0, "divergenzen": 0, "kern_terminal": 0,
        "intents": {}, "pro_mandant": {},
    }
    details: list[dict[str, Any]] = []

    for p in pfade:
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  ! {p}: {e}")
            continue
        if _testanruf(m) and not args.mit_test:
            ges["test"] += 1
            continue
        agg = replay_manifest(m)
        if not args.trocken:
            p.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
        ges["anrufe"] += 1
        ges["echt"] += 1
        ges["anrufer_zuege"] += agg["anrufer_zuege"]
        ges["i1"] += agg["i1"]
        ges["schleifen"] += agg["schleifen"]
        ges["divergenzen"] += agg["divergenzen"]
        ges["kern_terminal"] += 1 if agg["kern_terminal"] else 0
        ges["intents"][agg["intent"]] = ges["intents"].get(agg["intent"], 0) + 1
        md = ges["pro_mandant"].setdefault(agg["tenantId"] or "?", {"anrufe": 0, "i1": 0, "schleifen": 0, "divergenzen": 0})
        md["anrufe"] += 1
        md["i1"] += agg["i1"]
        md["schleifen"] += agg["schleifen"]
        md["divergenzen"] += agg["divergenzen"]
        details.append(agg)

    print("=" * 62)
    print(f" KERN-REPLAY  stimme={args.stimme}  tag={args.tag or 'heute'}  alle={args.alle}")
    print("=" * 62)
    print(f" Anrufe (echt):           {ges['echt']}   (Test uebersprungen: {ges['test']})")
    print(f" Anrufer-Zuege gesamt:    {ges['anrufer_zuege']}")
    print(f" Kern erreicht Terminal:  {ges['kern_terminal']}/{ges['echt']}")
    print("-" * 62)
    print(" LIVE-Fehlklassen (im echten Anruf gemessen):")
    print(f"   Frage zu gefuelltem Feld (I1): {ges['i1']}")
    print(f"   Schleife (gleiche Frage 3x):   {ges['schleifen']}")
    print("-" * 62)
    print(f" Divergenz Live-Frage vs Kern-Frage (Sammelphase): {ges['divergenzen']}")
    print("-" * 62)
    print(" Intents:")
    for k, v in sorted(ges["intents"].items(), key=lambda x: -x[1]):
        print(f"   {k:14s} {v}")
    print("-" * 62)
    print(" Pro Mandant:")
    for mid, d in ges["pro_mandant"].items():
        print(f"   {mid:26s} anrufe={d['anrufe']:3d}  I1={d['i1']:3d}  schleifen={d['schleifen']:3d}  div={d['divergenzen']:3d}")
    print("=" * 62)

    if args.json:
        outp = Path(args.json)
        outp.write_text(json.dumps({"summary": ges, "details": details}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f" Aggregat geschrieben: {outp}")
    return 0


# --------------------------------------------------------------------------- #
# Qwen-2.-Ohr-Diagnose aus den echten Manifesten.
# --------------------------------------------------------------------------- #
def cmd_qwen(args) -> int:
    pfade = _manifeste(args.stimme, args.tag, args.alle, args.sid)
    z = {
        "stt_zuege": 0, "mit_qwen_feld": 0,
        "gewinner_parakeet": 0, "gewinner_qwen": 0,
        "qwen_leer": 0, "qwen_gleich": 0, "qwen_anders": 0,
        "qwen_spaet": 0, "qwen_gesperrt": 0, "qwen_uebernommen": 0,
        "korrektur": 0, "parakeet_auffaellig": 0,
        "status": {},
    }
    for p in pfade:
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if _testanruf(m) and not args.mit_test:
            continue
        for zug in m.get("zuege") or []:
            st = zug.get("stt") if isinstance(zug, dict) else None
            if not isinstance(st, dict):
                continue
            z["stt_zuege"] += 1
            q = st.get("qwen") if isinstance(st.get("qwen"), dict) else {}
            p_ = st.get("parakeet") if isinstance(st.get("parakeet"), dict) else {}
            winner = str(st.get("winner") or "")
            if winner == "qwen":
                z["gewinner_qwen"] += 1
            elif winner == "parakeet":
                z["gewinner_parakeet"] += 1
            if q:
                z["mit_qwen_feld"] += 1
                status = str(q.get("status") or "")
                if status:
                    z["status"][status] = z["status"].get(status, 0) + 1
                if q.get("spaet"):
                    z["qwen_spaet"] += 1
                if q.get("sperre"):
                    z["qwen_gesperrt"] += 1
                if q.get("authoritative"):
                    z["qwen_uebernommen"] += 1
                qt = str(q.get("text") or "").strip()
                pt = str(p_.get("text") or st.get("text") or "").strip()
                if not qt:
                    z["qwen_leer"] += 1
                elif pt and qt.lower() == pt.lower():
                    z["qwen_gleich"] += 1
                elif qt:
                    z["qwen_anders"] += 1
            if st.get("korrektur"):
                z["korrektur"] += 1
            if p_.get("suspicious"):
                z["parakeet_auffaellig"] += 1

    print("=" * 62)
    print(f" QWEN-2.-OHR-DIAGNOSE  stimme={args.stimme}  tag={args.tag or 'heute'}  alle={args.alle}")
    print("=" * 62)
    print(f" STT-Zuege gesamt:            {z['stt_zuege']}")
    print(f" davon mit Qwen-Feld:         {z['mit_qwen_feld']}")
    print(f" Gewinner Parakeet:           {z['gewinner_parakeet']}")
    print(f" Gewinner Qwen:               {z['gewinner_qwen']}")
    print(f" Qwen uebernommen (autorit.): {z['qwen_uebernommen']}")
    print("-" * 62)
    print(f" Qwen gleich wie Parakeet:    {z['qwen_gleich']}")
    print(f" Qwen anders:                 {z['qwen_anders']}")
    print(f" Qwen leer:                   {z['qwen_leer']}")
    print(f" Qwen zu spaet:               {z['qwen_spaet']}")
    print(f" Qwen live gesperrt:          {z['qwen_gesperrt']}")
    print(f" Korrektur angewandt:         {z['korrektur']}")
    print(f" Parakeet auffaellig:         {z['parakeet_auffaellig']}")
    print("-" * 62)
    print(" Qwen-Status-Verteilung:")
    for k, v in sorted(z["status"].items(), key=lambda x: -x[1]):
        print(f"   {k:22s} {v}")
    print("=" * 62)
    if args.json:
        Path(args.json).write_text(json.dumps(z, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f" Aggregat geschrieben: {args.json}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Replay echter Anrufe durch den Dialogkern (read-only fuer Live).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def _gemein(p):
        p.add_argument("--stimme", default="bianca")
        p.add_argument("--tag", default="", help="YYYY-MM-DD (Default: heute, UTC)")
        p.add_argument("--alle", action="store_true", help="alle Tage")
        p.add_argument("--sid", default="", help="nur EIN Anruf (hex)")
        p.add_argument("--mit-test", dest="mit_test", action="store_true", help="Testanrufe mitrechnen")
        p.add_argument("--json", default="", help="Aggregat als JSON schreiben")

    ps = sub.add_parser("scan", help="Kern-Entscheidungen je Zug ins Manifest schreiben")
    _gemein(ps)
    ps.add_argument("--trocken", action="store_true", help="nicht ins Manifest schreiben (nur Zahlen)")
    ps.set_defaults(fn=cmd_scan)

    pq = sub.add_parser("qwen", help="Qwen-2.-Ohr aus echten Manifesten diagnostizieren")
    _gemein(pq)
    pq.set_defaults(fn=cmd_qwen)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
