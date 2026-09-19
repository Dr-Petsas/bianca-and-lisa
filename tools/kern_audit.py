"""Souveraenitaets-Audit: echte Anrufe durch den VOLLEN Dialogkern.

Unterschied zu ``tools/kern_replay.py``: dort laeuft nur der reine Reducer mit
synthetisierten Werkzeug-Ergebnissen. HIER laeuft die ganze Kette, wie sie im
Dock/Studio auch laeuft —

    echter Anrufersatz
      -> verstehen.deuten(... llm=hirn.deuten)   (Modell ODER Regeln)
      -> reducer.reduce(state, ev, policy)       (Mandanten-Policy)
      -> gateway_sim (ToolCommand -> ToolOutcome, aus den Anruf-Fakten gestellt)
      -> renderer.rendern(...)                   (gesprochener Satz)
      -> aufsicht (Loop-/Repair-Deckel)

Gemessen wird die Frage des Chefs: **kommt Bianca souveraen durch jedes
Gespraech?** Souveraen heisst hier hart und pruefbar:

  1. kein Absturz (jeder Zug liefert eine Entscheidung),
  2. kein stummer Zug (ausser dem gewollten Halte-Zug),
  3. keine wortgleiche Wiederholung zweier Zuege in Folge,
  4. keine inhaltliche Frage oefter als ``policy.max_rueckfragen + 1`` in Folge
     (darueber MUSS die Aufsicht greifen: Rueckblick, dann ehrliche Abgabe),
  5. kein Haengen im Werkzeug (Retry-Deckel des Reducers).

EHRLICHKEIT ueber die Reichweite (bitte beim Lesen der Zahlen mitdenken):
  * Das ist ein OFF-POLICY-Replay. Der Kern fragt teils etwas anderes als Live
    gefragt hat; der naechste echte Anrufersatz antwortet dann auf die
    Live-Frage, nicht auf die Kern-Frage. Das ist HAERTER als die Wirklichkeit —
    der Kern bekommt dauernd Antworten, die nicht zu seiner Frage passen. Die
    Schleifen-/Stillstands-Zahlen sind damit eine OBERE Schranke.
  * Werkzeuge sind simuliert (``gateway_sim``), aber aus den echten Anruf-Fakten
    gestellt: hat Live gebucht, bucht der Sim; fand Live keinen Termin, findet
    der Sim keinen. Es wird NICHTS geschrieben, keine Cloud Function gerufen.
  * Read-only fuer den Live-Betrieb: dieses Werkzeug schreibt nur in seine
    eigene JSON-Ausgabe, niemals in die Manifeste.

Aufrufe:
    python tools/kern_audit.py lauf --modus regel --json .data/audit-regel.json
    python tools/kern_audit.py lauf --modus llm --stichprobe 80 --parallel 8 \
        --llm-base http://127.0.0.1:18000/v1 --json .data/audit-llm.json
    python tools/kern_audit.py zeige --json .data/audit-regel.json --sid <hex>
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import traceback
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from bianca.controller import policy as _policy  # noqa: E402
from bianca.controller.gateway_sim import Szenario  # noqa: E402
from bianca.controller.orchestrator import TestGespraech  # noqa: E402
from bianca.controller.typen import STEUER_FRAGEN, Policy, TaskStatus  # noqa: E402

# Ein stiller Halte-Zug ist gewollt (Halbsatz/Ansage) — kein Stummheitsfehler.
_STILL_OK = {"warten"}


# --------------------------------------------------------------------------- #
# Korpus.
# --------------------------------------------------------------------------- #
def _manifeste(korpus: Path) -> list[Path]:
    if not korpus.is_dir():
        return []
    return sorted(korpus.rglob("anruf.json"))


def _anrufer_zuege(m: dict) -> list[dict[str, Any]]:
    """Die echten Anrufersaetze in Reihenfolge, mit der Live-Frage davor."""
    out: list[dict[str, Any]] = []
    live_frage = ""
    for z in m.get("zuege") or []:
        if not isinstance(z, dict):
            continue
        text = str(z.get("textIn") or "").strip()
        if text:
            out.append({"nr": z.get("nr"), "text": text, "live_frage_vorher": live_frage})
        if str(z.get("frage") or "").strip():
            live_frage = str(z["frage"]).strip()
    return out


def _live_bild(m: dict) -> dict[str, Any]:
    """Was im ECHTEN Anruf passiert ist — Bezugsgroesse fuer den Vergleich."""
    zuege = [z for z in (m.get("zuege") or []) if isinstance(z, dict)]
    fragen = [str(z.get("frage") or "").strip() for z in zuege]
    fragen = [f for f in fragen if f]

    def _ok(x: Any) -> bool:
        return bool(isinstance(x, dict) and x.get("ok"))

    # Live-Schleife: dieselbe Frage dreimal in Folge (Mass aus kern_replay).
    lauf = best = 1
    for a, b in zip(fragen, fragen[1:]):
        lauf = lauf + 1 if a == b else 1
        best = max(best, lauf)
    # Wortgleiche Wiederholung der gesprochenen Zeile.
    saetze = [_norm(str(z.get("text") or "")) for z in zuege if str(z.get("text") or "").strip()]
    wlauf = wbest = 1
    for a, b in zip(saetze, saetze[1:]):
        wlauf = wlauf + 1 if a == b else 1
        wbest = max(wbest, wlauf)

    booked = _ok(m.get("lastBook")) or any(_ok(z.get("book")) for z in zuege)
    return {
        "frage_max": best,
        "wortgleich_max": wbest,
        "schleife": best >= 3,
        "gebucht": booked,
        "notiz": bool(str(m.get("praxisNotiz") or "").strip()),
        "dauer_s": round(int(m.get("dauerMs") or 0) / 1000),
        "zuege": len(zuege),
    }


def _szenario_von(m: dict) -> Szenario:
    """Simulator aus den belegten Anruf-Fakten stellen (nicht geraten)."""
    zuege = [z for z in (m.get("zuege") or []) if isinstance(z, dict)]
    fragen = {str(z.get("frage") or "").strip() for z in zuege}

    def _ok(x: Any) -> bool:
        return bool(isinstance(x, dict) and x.get("ok"))

    booked = _ok(m.get("lastBook")) or any(_ok(z.get("book")) for z in zuege)
    lb = m.get("lastBook") if isinstance(m.get("lastBook"), dict) else {}
    fehler = str(lb.get("error") or lb.get("grund") or "").lower()
    if booked:
        buchung = "ok"
    elif any(w in fehler for w in ("phone", "handy", "telefon")):
        buchung = "needs_phone"
    elif "slot" in fehler or "available" in fehler:
        buchung = "slot_taken"
    else:
        buchung = "ok"

    # Terminsuche: hat Live etwas gefunden?
    gefunden = (
        _ok(m.get("lastCancel")) or _ok(m.get("lastMove"))
        or bool(fragen & {"auswahl", "termin_ok", "mehrfach_ok"})
    )
    sz = Szenario(freie_slots=3, termine=1 if gefunden else 0, buchung=buchung)

    # Erkannter Anrufer: Live hat die Kontrollfrage gestellt -> Nummer war bekannt.
    name = str(m.get("patientName") or "").strip()
    if name and "anrufer_check" in fragen:
        teile = name.split()
        sz.anrufer_nachname = teile[-1]
        if len(teile) > 1:
            sz.anrufer_vorname = teile[0]
    return sz


_POLICY_CACHE: dict[str, Policy] = {}


def _policy_von(m: dict) -> Policy:
    tid = str(m.get("tenantId") or "").strip()
    if tid in _POLICY_CACHE:
        return _POLICY_CACHE[tid]
    tenant: dict = {}
    if tid:
        try:
            from kern import tenants

            t = tenants.laden(tid)
            tenant = t if isinstance(t, dict) else {}
        except Exception:
            tenant = {}
    pol = _policy.aus_tenant(tenant)
    _POLICY_CACHE[tid] = pol
    return pol


def _norm(s: str) -> str:
    return " ".join(str(s or "").strip().lower().split())


# --------------------------------------------------------------------------- #
# EIN Anruf durch den vollen Kern.
# --------------------------------------------------------------------------- #
def audit_anruf(m: dict, *, llm: Any = None, mit_verlauf: bool = False) -> dict[str, Any]:
    zuege = _anrufer_zuege(m)
    pol = _policy_von(m)
    budget = pol.max_rueckfragen if pol.max_rueckfragen > 0 else 1

    b: dict[str, Any] = {
        "sid": m.get("id") or "",
        "tenant": m.get("tenantId") or "",
        "zuege": len(zuege),
        "modus": "llm" if llm is not None else "regel",
        "budget": budget,
        # Souveraenitaets-Befunde
        "crash": 0,
        "crash_text": "",
        "stumm": 0,
        "wortgleich": 0,        # Zuege, die den Vorzug wortgleich wiederholen
        "wortgleich_max": 1,    # laengster Lauf gleicher Saetze
        "frage_max": 1,         # laengster Lauf gleicher INHALTS-Frage
        "frage_max_id": "",
        "frage_ueber_budget": 0,
        # Aufsicht (genau das, was der Live-Pfad nicht hat)
        "aufsicht": {},
        # Ausgang
        "terminal": False,
        "hangup": False,
        "uebergeben": 0,
        "uebergeben_gruende": [],
        # Wie weit hat der Kern das Gespraech SELBST getragen, bevor er abgegeben
        # oder beendet hat? Nach einer Abgabe uebernimmt der Legacy-Pfad — dort
        # weiterzuspielen waere Messfehler, nicht Wirklichkeit.
        "getragen": 0,
        "ende_bei_zug": 0,
        "ende_art": "",
        "offen_am_ende": "",
        "tasks": [],
        "tools": [],
        "writes": [],
        "off_policy": 0,        # Kern-Frage != Live-Frage (Antwort passt nicht)
        "live": _live_bild(m),
    }
    if not zuege:
        return b

    gespraech = TestGespraech(pol, szenario=_szenario_von(m), llm=llm)
    verlauf: list[dict[str, Any]] = []
    letzter_satz = ""
    lauf_satz = 1
    letzte_frage = ""
    lauf_frage = 1
    aufsicht: Counter[str] = Counter()

    for i, zug in enumerate(zuege):
        try:
            za = gespraech.eingabe(zug["text"])
        except Exception as e:  # Souveraenitaet: ein Absturz ist der harte Fehler
            b["crash"] += 1
            if not b["crash_text"]:
                b["crash_text"] = f"{type(e).__name__}: {e}"[:300]
                b["crash_trace"] = traceback.format_exc()[-1200:]
            break

        akt = str((za.debug or {}).get("speak_akt") or "")
        fid = str((za.debug or {}).get("frage_id") or "")
        satz = _norm(za.antwort)

        # (2) stummer Zug
        if not satz and akt not in _STILL_OK and not za.uebergeben and not za.hangup:
            b["stumm"] += 1

        # (3) wortgleiche Wiederholung
        if satz and satz == letzter_satz:
            b["wortgleich"] += 1
            lauf_satz += 1
        else:
            lauf_satz = 1
        b["wortgleich_max"] = max(b["wortgleich_max"], lauf_satz)
        if satz:
            letzter_satz = satz

        # (4) Frage-Schleife (nur INHALTliche Fragen; Steuerfragen deckelt der Reducer)
        inhalt = fid if (akt == "frage" and fid and fid not in STEUER_FRAGEN) else ""
        if inhalt and inhalt == letzte_frage:
            lauf_frage += 1
        else:
            lauf_frage = 1 if inhalt else 0
        letzte_frage = inhalt
        if lauf_frage > b["frage_max"]:
            b["frage_max"] = lauf_frage
            b["frage_max_id"] = inhalt
        if lauf_frage > budget + 1:
            b["frage_ueber_budget"] += 1

        # Aufsicht-Eingriffe
        grund = str(za.grund or "")
        if grund.startswith("aufsicht:"):
            teile = grund.split(":")
            aufsicht[teile[1] if len(teile) > 1 else "?"] += 1

        if za.tool:
            b["tools"].append(za.tool)
        b["getragen"] = i + 1

        # Off-Policy: was der Kern fragt, ist nicht das, was Live gefragt hat
        live_vorher = str(zuege[i + 1]["live_frage_vorher"] if i + 1 < len(zuege) else "")
        if inhalt and live_vorher and inhalt != live_vorher:
            b["off_policy"] += 1

        if mit_verlauf:
            verlauf.append({
                "anrufer": zug["text"],
                "bianca": za.antwort,
                "akt": akt,
                "frage": fid,
                "grund": grund,
                "tool": za.tool,
                "live_frage_vorher": zug["live_frage_vorher"],
            })

        # Ende der Kern-Zustaendigkeit: ab hier redet nicht mehr der Kern.
        if za.uebergeben:
            b["uebergeben"] += 1
            if grund:
                b["uebergeben_gruende"].append(grund)
            b["ende_bei_zug"], b["ende_art"] = i + 1, "abgabe"
            break
        if za.hangup:
            b["hangup"] = True
            b["ende_bei_zug"], b["ende_art"] = i + 1, "auflegen"
            break

    st = gespraech.state
    b["terminal"] = bool(st.terminal)
    b["aufsicht"] = dict(aufsicht)
    for t in st.tasks:
        b["tasks"].append({"typ": t.typ, "status": t.status.value, "phase": t.phase.value})
    for oc in st.ledger:
        if oc.committed:
            b["writes"].append(oc.name)
    aktiv = st.aktiv()
    if aktiv is not None and aktiv.status == TaskStatus.AKTIV and not st.terminal:
        b["offen_am_ende"] = f"{aktiv.typ}:{aktiv.phase.value}"

    b["souveraen"] = bool(
        b["crash"] == 0
        and b["stumm"] == 0
        and b["wortgleich"] == 0
        and b["frage_ueber_budget"] == 0
    )
    if mit_verlauf:
        b["verlauf"] = verlauf
    return b


# --------------------------------------------------------------------------- #
# Lauf ueber den Korpus.
# --------------------------------------------------------------------------- #
def _llm_haken(base: str) -> Any:
    """vLLM-Haken fuer verstehen.deuten — Basis darf ueberschrieben werden."""
    from kern import llm as _llm

    if base:
        _llm.LLM_BASE = base.rstrip("/")
        _llm._CLIENT = None
    h = _llm.health(timeout=8.0)
    if not h.get("ok"):
        raise SystemExit(f"LLM nicht erreichbar: {h}")
    print(f"  LLM: {h.get('base')}  model={h.get('model')}")
    from bianca.controller import hirn

    return hirn.deuten


def cmd_lauf(args) -> int:
    korpus = Path(args.korpus)
    if not korpus.is_absolute():
        korpus = _ROOT / korpus
    pfade = _manifeste(korpus)
    if not pfade:
        print(f"Keine Manifeste unter {korpus}")
        return 1

    manifeste: list[dict] = []
    test = leer = kaputt = 0
    for p in pfade:
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            kaputt += 1
            continue
        if m.get("testAnruf") and not args.mit_test:
            test += 1
            continue
        if not _anrufer_zuege(m):
            leer += 1
            continue
        manifeste.append(m)

    if args.stichprobe and args.stichprobe < len(manifeste):
        manifeste = _stichprobe(manifeste, args.stichprobe, args.saat)

    llm = _llm_haken(args.llm_base) if args.modus == "llm" else None
    print(f"  Anrufe: {len(manifeste)}  (Test {test}, ohne Anrufertext {leer}, kaputt {kaputt})")
    print(f"  Modus: {args.modus}  parallel={args.parallel}")

    berichte: list[dict[str, Any]] = []

    def _eins(m: dict) -> dict[str, Any]:
        return audit_anruf(m, llm=llm, mit_verlauf=True)

    if args.parallel > 1:
        with ThreadPoolExecutor(max_workers=args.parallel) as ex:
            for i, b in enumerate(ex.map(_eins, manifeste), 1):
                berichte.append(b)
                if i % 25 == 0:
                    print(f"    ... {i}/{len(manifeste)}")
    else:
        for i, m in enumerate(manifeste, 1):
            berichte.append(_eins(m))
            if i % 25 == 0:
                print(f"    ... {i}/{len(manifeste)}")

    ges = _aggregat(berichte)
    _bericht_drucken(ges, berichte, args)

    if args.json:
        outp = Path(args.json)
        if not outp.is_absolute():
            outp = _ROOT / outp
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(
            json.dumps({"summary": ges, "calls": berichte}, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        print(f"\n  Ausgabe: {outp}")
    return 0


def _stichprobe(manifeste: list[dict], n: int, saat: int) -> list[dict]:
    """Geschichtet: je Mandant anteilig, lange Gespraeche bevorzugt mitnehmen."""
    rnd = random.Random(saat)
    nach_mandant: dict[str, list[dict]] = {}
    for m in manifeste:
        nach_mandant.setdefault(str(m.get("tenantId") or "?"), []).append(m)
    out: list[dict] = []
    gesamt = len(manifeste)
    for tid, liste in sorted(nach_mandant.items()):
        quote = max(1, round(n * len(liste) / gesamt))
        # Die laengsten Gespraeche sind die interessanten (dort entstehen Schleifen).
        liste = sorted(liste, key=lambda m: -len(_anrufer_zuege(m)))
        kopf = liste[: max(1, quote // 2)]
        rest = liste[len(kopf):]
        rnd.shuffle(rest)
        out.extend(kopf + rest[: max(0, quote - len(kopf))])
    return out[:n]


def _aggregat(bs: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(bs)
    zuege = sum(b["zuege"] for b in bs)
    g: dict[str, Any] = {
        "anrufe": n,
        "anrufer_zuege": zuege,
        "souveraen": sum(1 for b in bs if b.get("souveraen")),
        "crash": sum(b["crash"] for b in bs),
        "crash_anrufe": sum(1 for b in bs if b["crash"]),
        "stumm": sum(b["stumm"] for b in bs),
        "stumm_anrufe": sum(1 for b in bs if b["stumm"]),
        "wortgleich": sum(b["wortgleich"] for b in bs),
        "wortgleich_anrufe": sum(1 for b in bs if b["wortgleich"]),
        "frage_ueber_budget": sum(b["frage_ueber_budget"] for b in bs),
        "frage_ueber_budget_anrufe": sum(1 for b in bs if b["frage_ueber_budget"]),
        "frage_max": max([b["frage_max"] for b in bs] or [0]),
        "off_policy": sum(b["off_policy"] for b in bs),
        "aufsicht": {},
        "aufsicht_anrufe": sum(1 for b in bs if b["aufsicht"]),
        "terminal": sum(1 for b in bs if b["terminal"]),
        "hangup": sum(1 for b in bs if b["hangup"]),
        "uebergeben_anrufe": sum(1 for b in bs if b["uebergeben"]),
        "ende_art": {},
        "getragen": sum(b["getragen"] for b in bs),
        "uebergabe_gruende": {},
        "offen_am_ende": sum(1 for b in bs if b["offen_am_ende"]),
        "writes": {},
        "tools": {},
        "tasks": {},
        "pro_mandant": {},
        "live": {
            "schleifen_anrufe": sum(1 for b in bs if b["live"]["schleife"]),
            "wortgleich_anrufe": sum(1 for b in bs if b["live"]["wortgleich_max"] >= 2),
            "wortgleich_max": max([b["live"]["wortgleich_max"] for b in bs] or [0]),
            "frage_max": max([b["live"]["frage_max"] for b in bs] or [0]),
            "gebucht": sum(1 for b in bs if b["live"]["gebucht"]),
        },
    }
    for b in bs:
        for k, v in (b["aufsicht"] or {}).items():
            g["aufsicht"][k] = g["aufsicht"].get(k, 0) + v
        for w in b["writes"]:
            g["writes"][w] = g["writes"].get(w, 0) + 1
        for t in b["tools"]:
            g["tools"][t] = g["tools"].get(t, 0) + 1
        for t in b["tasks"]:
            key = f"{t['typ']}:{t['status']}"
            g["tasks"][key] = g["tasks"].get(key, 0) + 1
        for gr in b["uebergeben_gruende"]:
            g["uebergabe_gruende"][gr] = g["uebergabe_gruende"].get(gr, 0) + 1
        art = b["ende_art"] or "bis_zum_letzten_zug"
        g["ende_art"][art] = g["ende_art"].get(art, 0) + 1
        md = g["pro_mandant"].setdefault(
            b["tenant"] or "?",
            {"anrufe": 0, "souveraen": 0, "crash": 0, "wortgleich": 0,
             "ueber_budget": 0, "aufsicht": 0, "live_schleifen": 0},
        )
        md["anrufe"] += 1
        md["souveraen"] += 1 if b.get("souveraen") else 0
        md["crash"] += b["crash"]
        md["wortgleich"] += b["wortgleich"]
        md["ueber_budget"] += b["frage_ueber_budget"]
        md["aufsicht"] += sum((b["aufsicht"] or {}).values())
        md["live_schleifen"] += 1 if b["live"]["schleife"] else 0
    laengen = [b["zuege"] for b in bs if b["zuege"]]
    g["zuege_median"] = statistics.median(laengen) if laengen else 0
    g["zuege_max"] = max(laengen) if laengen else 0
    return g


def _bericht_drucken(g: dict[str, Any], bs: list[dict[str, Any]], args) -> None:
    n = max(1, g["anrufe"])
    print("=" * 68)
    print(f" KERN-AUDIT  modus={args.modus}  anrufe={g['anrufe']}  zuege={g['anrufer_zuege']}")
    print("=" * 68)
    print(f" Souveraen durchgelaufen:      {g['souveraen']}/{g['anrufe']}  ({100*g['souveraen']//n} %)")
    print(" -- die vier harten Fehlklassen ------------------------------------")
    print(f"   Abstuerze:                  {g['crash']} (in {g['crash_anrufe']} Anrufen)")
    print(f"   stumme Zuege:               {g['stumm']} (in {g['stumm_anrufe']} Anrufen)")
    print(f"   wortgleiche Wiederholung:   {g['wortgleich']} (in {g['wortgleich_anrufe']} Anrufen)")
    print(f"   Frage ueber Budget:         {g['frage_ueber_budget']} (in {g['frage_ueber_budget_anrufe']} Anrufen)")
    print(f"   laengster Frage-Lauf:       {g['frage_max']}")
    print(" -- Loop-Aufsicht (der neue Teil) ----------------------------------")
    for k, v in sorted(g["aufsicht"].items(), key=lambda x: -x[1]):
        print(f"   {k:20s} {v}")
    print(f"   Anrufe mit Eingriff:        {g['aufsicht_anrufe']}")
    print(" -- Ausgang --------------------------------------------------------")
    print(f"   vom Kern getragene Zuege:   {g['getragen']}/{g['anrufer_zuege']} "
          f"({100*g['getragen']//max(1,g['anrufer_zuege'])} %)")
    print(f"   Ende der Zustaendigkeit:    {g['ende_art']}")
    print(f"   terminal beendet:           {g['terminal']}")
    print(f"   Abgabe an Legacy:           {g['uebergeben_anrufe']}")
    print(f"   Aufgabe am Ende offen:      {g['offen_am_ende']}")
    print(f"   Schreibvorgaenge (Sim):     {g['writes']}")
    print(f"   Aufgaben-Ausgang:           {dict(sorted(g['tasks'].items(), key=lambda x: -x[1])[:8])}")
    print(" -- Off-Policy-Warnung ---------------------------------------------")
    print(f"   Zuege, in denen der Kern etwas anderes fragte als Live: {g['off_policy']}")
    print("   (die echte Folgeantwort passt dort nicht auf die Kern-Frage —")
    print("    dieses Replay ist damit HAERTER als der echte Anruf)")
    print(" -- Live zum Vergleich (dieselben Anrufe) --------------------------")
    print(f"   Live-Schleifen (Frage 3x):  {g['live']['schleifen_anrufe']} Anrufe")
    print(f"   Live wortgleich 2x:         {g['live']['wortgleich_anrufe']} Anrufe (max {g['live']['wortgleich_max']}x)")
    print(f"   laengster Live-Frage-Lauf:  {g['live']['frage_max']}")
    print(" -- pro Mandant ----------------------------------------------------")
    for tid, d in sorted(g["pro_mandant"].items(), key=lambda x: -x[1]["anrufe"]):
        print(f"   {tid:10s} n={d['anrufe']:4d} souveraen={d['souveraen']:4d} "
              f"crash={d['crash']:3d} wortgl={d['wortgleich']:3d} "
              f"ueberbudget={d['ueber_budget']:3d} aufsicht={d['aufsicht']:4d} "
              f"live-schleifen={d['live_schleifen']:3d}")
    print("=" * 68)

    schlimm = sorted(
        [b for b in bs if not b.get("souveraen")],
        key=lambda b: -(b["crash"] * 100 + b["wortgleich"] * 10 + b["frage_ueber_budget"] + b["stumm"]),
    )[:12]
    if schlimm:
        print(" Nicht souveraene Anrufe (Kopf der Liste):")
        for b in schlimm:
            print(f"   {b['sid'][:12]} {b['tenant']:9s} zuege={b['zuege']:3d} "
                  f"crash={b['crash']} stumm={b['stumm']} wortgl={b['wortgleich']} "
                  f"ueberbudget={b['frage_ueber_budget']} frage={b['frage_max']}x{b['frage_max_id']}"
                  + (f"  {b['crash_text']}" if b["crash_text"] else ""))
        print("=" * 68)


def cmd_zeige(args) -> int:
    p = Path(args.json)
    if not p.is_absolute():
        p = _ROOT / p
    data = json.loads(p.read_text(encoding="utf-8"))
    calls = data.get("calls") or []
    treffer = [c for c in calls if str(c.get("sid", "")).startswith(args.sid)] if args.sid else calls[:1]
    if not treffer:
        print("Kein Anruf mit dieser sid im Bericht.")
        return 1
    for c in treffer[: args.n]:
        print("=" * 68)
        print(f" {c['sid']}  {c['tenant']}  zuege={c['zuege']}  souveraen={c.get('souveraen')}")
        print(f" crash={c['crash']} stumm={c['stumm']} wortgleich={c['wortgleich']} "
              f"ueberbudget={c['frage_ueber_budget']} aufsicht={c['aufsicht']}")
        print("-" * 68)
        for z in c.get("verlauf") or []:
            print(f"  A: {z['anrufer']}")
            marke = f"[{z['akt']}{'/' + z['frage'] if z['frage'] else ''}]"
            if z.get("grund", "").startswith("aufsicht:"):
                marke += f" <<{z['grund']}>>"
            print(f"  B: {z['bianca']}  {marke}")
        if c.get("crash_trace"):
            print("-" * 68)
            print(c["crash_trace"])
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Souveraenitaets-Audit des Dialogkerns an echten Anrufen.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("lauf", help="Korpus durch den vollen Kern spielen")
    pl.add_argument("--korpus", default=".data/korpus/anrufe")
    pl.add_argument("--modus", choices=["regel", "llm"], default="regel")
    pl.add_argument("--llm-base", dest="llm_base", default="")
    pl.add_argument("--stichprobe", type=int, default=0, help="geschichtete Stichprobe (0 = alle)")
    pl.add_argument("--saat", type=int, default=19)
    pl.add_argument("--parallel", type=int, default=1)
    pl.add_argument("--mit-test", dest="mit_test", action="store_true")
    pl.add_argument("--json", default="")
    pl.set_defaults(fn=cmd_lauf)

    pz = sub.add_parser("zeige", help="Verlauf eines Anrufs aus dem Bericht drucken")
    pz.add_argument("--json", required=True)
    pz.add_argument("--sid", default="")
    pz.add_argument("--n", type=int, default=1)
    pz.set_defaults(fn=cmd_zeige)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
