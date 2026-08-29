"""Einmaliger Kartei-Sweep: Geschlecht aller Bestandsakten richtigstellen.

Chef 30.08.2026: "es sollten auch einmal alle kartei karten mit einem sweep
auf das richtige geschlecht eingestellt werden. danach kann der live
geschlechtswächter beim neuanlegen von patienten ja über das geschlecht
wachen."

Hintergrund: Das Pickadoc-Patientenmodell defaultet auf WEIBLICH — Akten,
bei denen nie jemand das Geschlecht gepflegt hat, stehen darum als "f" in
der Kartei (Anschreiben: "Sehr geehrte Frau Peter Berger"). Dieser Sweep
stellt sie anhand des Vornamens richtig; ab dann haelt der Vornamen-Waechter
(kern/vornamen.py, in Bianca/Lisa live) Neuanlagen sauber.

Regeln (konservativ — im Zweifel NICHT schreiben):
- "d" (divers) in der Akte: NIE anfassen (bewusste Eintragung).
- Feld leer:      setzen, wenn der Waechter ein Geschlecht liefert
                  (kuratierte Liste ODER konservative -a-Heuristik).
- Feld m/f:       nur umdrehen, wenn die KURATIERTE Liste eindeutig
                  widerspricht (aus_liste) — die Heuristik kippt nie einen
                  gesetzten Eintrag, solche Faelle landen nur im Bericht.
- Unklare Vornamen (Kim, Sascha, ...): nichts schreiben, im Bericht listen.

Aufruf (Repo-Wurzel):
  python -m tools.geschlecht_sweep                  # Dry-Run + Bericht
  python -m tools.geschlecht_sweep --schreiben      # echter Lauf
  python -m tools.geschlecht_sweep --tenant meddent
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

_WURZEL = Path(__file__).resolve().parent.parent
if str(_WURZEL) not in sys.path:
    sys.path.insert(0, str(_WURZEL))

import httpx

from kern import vornamen
from kern.config import CF_BASE
from kern.tenants import laden


def entscheiden(akte_gender: str, vorname: str) -> tuple[str, str]:
    """Reine Entscheidungslogik je Akte: (aktion, neues_geschlecht).

    Aktionen: divers | stimmt | korrigieren | verdacht | belassen |
              setzen | unklar — geschrieben wird NUR bei setzen/korrigieren.
    """
    a = (akte_gender or "").strip().lower()
    if a == "d":
        return ("divers", "")
    voll = vornamen.geschlecht(vorname)      # Liste + -a-Heuristik
    liste = vornamen.aus_liste(vorname)      # nur kuratiert
    if a in ("m", "f"):
        if liste and liste != a:
            return ("korrigieren", liste)
        if voll and voll != a:
            return ("verdacht", voll)        # nur Heuristik dagegen: Bericht
        if voll == a:
            return ("stimmt", "")
        return ("belassen", "")              # Vorname unklar, Eintrag bleibt
    if voll:
        return ("setzen", voll)
    return ("unklar", "")


def _seiten(clientId: str, locationId: str) -> list[dict]:
    """Alle Akten (id, firstName, gender) seitenweise von der Plattform."""
    alle: list[dict] = []
    start_after = ""
    for _ in range(200):  # Schutzdeckel: 200 x 500 = 100k Akten
        r = httpx.post(
            f"{CF_BASE}/masPatientsGenderPage",
            json={"clientId": clientId, "locationId": locationId,
                  "pageSize": 500, "startAfter": start_after},
            timeout=60.0,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("status") != "success":
            raise RuntimeError(f"masPatientsGenderPage: {data}")
        alle.extend(data.get("patients") or [])
        start_after = data.get("nextStartAfter") or ""
        if not start_after:
            break
    return alle


def _schreiben(clientId: str, locationId: str, updates: list[dict]) -> tuple[int, list[str]]:
    """Updates in 400er-Batches an masUpdatePatientGender."""
    geschrieben = 0
    uebersprungen: list[str] = []
    for i in range(0, len(updates), 400):
        teil = updates[i:i + 400]
        r = httpx.post(
            f"{CF_BASE}/masUpdatePatientGender",
            json={"clientId": clientId, "locationId": locationId,
                  "updates": [{"patientId": u["id"], "gender": u["neu"]} for u in teil]},
            timeout=120.0,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("status") != "success":
            raise RuntimeError(f"masUpdatePatientGender: {data}")
        geschrieben += int(data.get("updated") or 0)
        uebersprungen.extend(data.get("skipped") or [])
        print(f"  Batch {i // 400 + 1}: {data.get('updated')} geschrieben", flush=True)
    return geschrieben, uebersprungen


def main() -> int:
    ap = argparse.ArgumentParser(description="Kartei-Sweep: Geschlecht aus Vornamen")
    ap.add_argument("--tenant", default="meddent")
    ap.add_argument("--schreiben", action="store_true",
                    help="wirklich schreiben (ohne: Dry-Run mit Bericht)")
    args = ap.parse_args()

    tenant = laden(args.tenant)
    clientId = str(tenant.get("clientId") or "").strip()
    locationId = str(tenant.get("locationId") or "").strip()
    if not clientId or not locationId:
        print(f"Tenant {args.tenant}: clientId/locationId fehlen", flush=True)
        return 1

    print(f"Lade Akten fuer {args.tenant} ({clientId}/{locationId}) ...", flush=True)
    akten = _seiten(clientId, locationId)
    print(f"{len(akten)} Akten geladen.", flush=True)

    eimer: dict[str, list[dict]] = {}
    for p in akten:
        aktion, neu = entscheiden(p.get("gender") or "", p.get("firstName") or "")
        eintrag = {"id": p["id"], "vorname": p.get("firstName") or "",
                   "akte": (p.get("gender") or ""), "neu": neu}
        eimer.setdefault(aktion, []).append(eintrag)

    zu_schreiben = eimer.get("setzen", []) + eimer.get("korrigieren", [])
    print("")
    print("=== Sweep-Bilanz ===")
    for aktion in ("stimmt", "setzen", "korrigieren", "verdacht", "unklar", "belassen", "divers"):
        n = len(eimer.get(aktion, []))
        if n:
            print(f"  {aktion:12s} {n}")
    print(f"  -> zu schreiben: {len(zu_schreiben)}")

    if eimer.get("korrigieren"):
        print("\nKorrekturen (Akte widerspricht kuratiertem Vornamen):")
        for e in eimer["korrigieren"][:25]:
            print(f"  {e['vorname']!r}: {e['akte'] or '-'} -> {e['neu']}  ({e['id']})")
        if len(eimer["korrigieren"]) > 25:
            print(f"  ... und {len(eimer['korrigieren']) - 25} weitere (siehe Bericht)")
    if eimer.get("verdacht"):
        print("\nVerdacht (nur Heuristik widerspricht — wird NICHT geschrieben):")
        for e in eimer["verdacht"][:15]:
            print(f"  {e['vorname']!r}: Akte {e['akte']}, Heuristik {e['neu']}  ({e['id']})")
    if eimer.get("unklar"):
        beispiele = ", ".join(sorted({e["vorname"] for e in eimer["unklar"] if e["vorname"]})[:20])
        print(f"\nUnklare Vornamen ohne Eintrag ({len(eimer['unklar'])}): {beispiele}")

    berichts_dir = _WURZEL / ".data" / "geschlecht-sweep"
    berichts_dir.mkdir(parents=True, exist_ok=True)
    stempel = datetime.now().strftime("%Y%m%d-%H%M%S")
    modus = "schreiben" if args.schreiben else "dryrun"
    bericht = berichts_dir / f"{args.tenant}-{stempel}-{modus}.json"
    bericht.write_text(json.dumps({
        "tenant": args.tenant, "zeit": stempel, "modus": modus,
        "gesamt": len(akten),
        "bilanz": {k: len(v) for k, v in eimer.items()},
        "eimer": eimer,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nBericht: {bericht}")

    if not args.schreiben:
        print("\nDRY-RUN — nichts geschrieben. Echter Lauf: --schreiben")
        return 0
    if not zu_schreiben:
        print("\nNichts zu schreiben — Kartei ist konsistent.")
        return 0

    print(f"\nSchreibe {len(zu_schreiben)} Akten ...", flush=True)
    geschrieben, uebersprungen = _schreiben(clientId, locationId, zu_schreiben)
    print(f"Fertig: {geschrieben} Akten aktualisiert, {len(uebersprungen)} uebersprungen.")
    if uebersprungen:
        print(f"Uebersprungen (Akte weg?): {uebersprungen}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
