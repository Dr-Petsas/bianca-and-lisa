"""Aufraeum-Skript des Baukasten-Tests: gebuchte TESTTERMINE absagen (W-BK-7).

Praezise ueber die Berichte: jede Story-Buchung traegt die appointmentId
(lastBook/lastMove im lastCall) — genau diese Termine werden per
agentCancelAppointmentById storniert, nie ein fremder Termin. Schon
stornierte IDs merkt sich berichte/aufgeraeumt.json (idempotent).

Optional --namen: Sweep ueber die Runner-Personas (Vorname der Stimme +
Nachname aus dem Pool) fuer verwaiste Buchungen, wenn ein Lauf VOR dem
Bericht starb. Sagt nur KOMMENDE Termine ab und nur bei exaktem
Vor+Nachname-Treffer einer Test-Persona.

Aufruf:
  python -m tests.baukasten.aufraeumen              # alle Berichte
  python -m tests.baukasten.aufraeumen --lauf <id>  # nur ein Lauf
  python -m tests.baukasten.aufraeumen --namen      # zusaetzlich Persona-Sweep
  python -m tests.baukasten.aufraeumen --probe      # nur anzeigen, nichts absagen
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from kern import calendar as kal  # noqa: E402
from kern import tenants  # noqa: E402
from tests.baukasten import saetze  # noqa: E402

BERICHTE_DIR = Path(__file__).resolve().parent / "berichte"
MERKDATEI = BERICHTE_DIR / "aufgeraeumt.json"


def _gemerkt() -> set[str]:
    try:
        return set(json.loads(MERKDATEI.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return set()


def _merken(ids: set[str]) -> None:
    MERKDATEI.parent.mkdir(parents=True, exist_ok=True)
    MERKDATEI.write_text(json.dumps(sorted(ids), ensure_ascii=False, indent=1),
                         encoding="utf-8")


def ids_aus_berichten(lauf: str = "") -> list[dict]:
    """Alle Buchungs-IDs aus den Berichten: [{id, story, slotIso}]."""
    funde: list[dict] = []
    muster = f"{lauf}/*/bericht.json" if lauf else "*/*/bericht.json"
    for pfad in sorted(BERICHTE_DIR.glob(muster)):
        try:
            b = json.loads(pfad.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        lc = b.get("lastCall") or {}
        for key in ("lastBook", "lastMove"):
            eintrag = lc.get(key) or {}
            aid = str(eintrag.get("appointmentId") or "")
            if aid and (eintrag.get("booked") or eintrag.get("moved") or eintrag.get("ok")):
                funde.append({"id": aid, "story": str(b.get("id") or pfad.parent.name),
                              "slotIso": str(eintrag.get("slotIso") or "")})
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
                    funde.append({"id": aid, "story": f"sweep {vorname} {nachname}",
                                  "slotIso": str(a.get("iso") or a.get("date") or "")})
    return funde


def main() -> None:
    p = argparse.ArgumentParser(description="Testtermine des Baukasten-Laufs absagen")
    p.add_argument("--lauf", default="", help="nur Berichte dieses Laufs")
    p.add_argument("--namen", action="store_true", help="zusaetzlich Persona-Sweep")
    p.add_argument("--probe", action="store_true", help="nur anzeigen, nichts absagen")
    a = p.parse_args()

    tenant = tenants.laden("meddent")
    funde = ids_aus_berichten(a.lauf)
    if a.namen:
        funde += persona_termine(tenant)

    gemerkt = _gemerkt()
    offen = [f for f in funde if f["id"] not in gemerkt]
    # Dedupe bei mehreren Berichten mit derselben ID:
    gesehen: set[str] = set()
    offen = [f for f in offen if not (f["id"] in gesehen or gesehen.add(f["id"]))]

    print(f"aufraeumen: {len(funde)} Buchungen gefunden, {len(offen)} offen "
          f"({len(gemerkt)} schon storniert)", flush=True)
    if a.probe:
        for f in offen:
            print(f"  wuerde absagen: {f['id']}  {f['slotIso']}  [{f['story']}]")
        return

    fehler = 0
    for f in offen:
        r = kal.cancel_by_id(tenant, {}, f["id"])
        if r.get("cancelled"):
            gemerkt.add(f["id"])
            print(f"  abgesagt: {f['id']}  {f['slotIso']}  [{f['story']}]", flush=True)
        else:
            fehler += 1
            print(f"  FEHLER:   {f['id']}  {f['slotIso']}  [{f['story']}] -> "
                  f"{r.get('spoken') or r}", flush=True)
    _merken(gemerkt)
    print(f"aufraeumen: fertig — {len(offen) - fehler} abgesagt, {fehler} Fehler", flush=True)
    sys.exit(1 if fehler else 0)


if __name__ == "__main__":
    main()
