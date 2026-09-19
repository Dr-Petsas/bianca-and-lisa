"""Live-Probe: spricht der Dialogkern durch ``agent.user_turn``?

Kein Netz, kein Modell, kein echter Kalender — ``kern.calendar`` wird durch
einen Stub ersetzt, der plausible Slots liefert und jede Buchung als Trockenlauf
quittiert. Gezeigt wird genau das, was am Telefon gesprochen wuerde.

    python tools\\_probe_kern_live.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["CONTROLLER_ENFORCE"] = "1"
os.environ["WRITE_LIVE"] = "0"
os.environ.setdefault("CONTROLLER_LIVE_DIR", ".data/controller-live-probe")


class _KalenderStub:
    """Minimaler kern.calendar-Ersatz. Liest nichts, schreibt nichts."""

    def offer_slots(self, tenant, ctx, wish_text=""):
        return {
            "ok": True,
            "slots": [
                {"iso": "2026-09-23T09:00:00+02:00", "spoken": "Mittwoch, 23. September, neun Uhr"},
                {"iso": "2026-09-23T14:30:00+02:00", "spoken": "Mittwoch, 23. September, vierzehn Uhr dreissig"},
                {"iso": "2026-09-24T11:00:00+02:00", "spoken": "Donnerstag, 24. September, elf Uhr"},
            ],
            "wishMatched": True,
        }

    def find_patient_appointments(self, tenant, ctx):
        return {
            "ok": True,
            "appointments": [{
                "id": "a1", "iso": "2026-10-21T13:00:00+02:00", "date": "2026-10-21",
                "doctorName": "Doktor Petsas", "motivName": "KCH Kontrolluntersuchung",
                "calendarId": "cal-petsas",
                "spoken": "Dienstag, 21. Oktober, dreizehn Uhr bei Doktor Petsas",
            }],
            "patient": {"id": "p1"},
        }

    # Die Schreibwege quittieren wie ein GLUECKTER Kalender-Write. Nur so zeigt
    # die Probe die Schluss-Saetze; ein `dryRun` waere ehrlicherweise KEIN
    # Commit und wuerde (richtig) in die Rueckruf-Notiz laufen.
    def book_slot(self, tenant, ctx, slot_iso=""):
        return {"booked": True, "appointmentId": "neu-1", "slotIso": slot_iso}

    def cancel_by_id(self, tenant, ctx, aid):
        return {"cancelled": True, "appointmentId": aid}

    def move_appointment(self, tenant, ctx, slot_iso=""):
        return {"moved": True, "appointmentId": "a1", "slotIso": slot_iso}

    def note_appointment(self, tenant, ctx, sit, note=""):
        return {"ok": True}


def main() -> int:
    from bianca import agent
    from bianca.controller import live
    from bianca.controller.orchestrator import TestGespraech
    from bianca.controller import policy as _policy
    from bianca.controller.tool_gateway import ToolGateway
    from kern.tenants import laden

    stub = _KalenderStub()

    def _lauf(sit):
        g = sit.get("_kernLauf")
        if isinstance(g, TestGespraech):
            return g
        tenant = sit.get("tenant") or {}
        gw = ToolGateway(tenant, nur_lesen=False, sit=sit, kalender=stub,
                         protokoll=live._protokoll_hook(sit))
        g = TestGespraech(_policy.aus_tenant(tenant), llm=None, gateway=gw)
        live._vorbelegen(g, sit)
        sit["_kernLauf"] = g
        return g

    live.lauf = _lauf  # nur in dieser Probe

    gespraeche = {
        "Buchung, Neupatient": [
            "Guten Tag, ich braeuchte einen Termin.",
            "Nein, ich bin neu.",
            "Zur Kontrolle.",
            "Bei Doktor Petsas.",
            "Am Mittwoch vormittags.",
            "Meier.",
            "Peter.",
            "Gesetzlich.",
            "Der erste bitte.",
            "01776004600",
            "Ja, richtig.",
            "Ja.",
        ],
        "Absage": [
            "Ich moechte meinen Termin absagen.",
            "Meier.",
            "Ja, den meine ich.",
            "Ja, bitte absagen.",
        ],
        "Meta: wiederholen, abbrechen": [
            "Ich braeuchte einen Termin.",
            "Wie bitte?",
            "Vergessen Sie's.",
        ],
    }

    fehler = 0
    for titel, saetze in gespraeche.items():
        print("=" * 72)
        print(titel)
        print("=" * 72)
        sit = {
            "id": f"probe-{titel[:6]}",
            "stimme": "Bianca",
            "tenant": laden("meddent"),
            "messages": [{"role": "system", "content": "x"}],
            "_testNoWrite": True,
        }
        for satz in saetze:
            print(f"  ANRUFER : {satz}")
            try:
                aus = agent.user_turn(sit, satz)
            except Exception as exc:  # noqa: BLE001
                print(f"  ** FEHLER: {exc!r}")
                fehler += 1
                break
            text = (aus or {}).get("text") or ""
            kern = "KERN " if live.uebernimmt(sit) else "LEGACY"
            if not text and (aus or {}).get("warte"):
                print(f"  {kern}  : (still, hoert weiter)")
            elif not text:
                print(f"  {kern}  : ** STUMM **")
                fehler += 1
            else:
                print(f"  {kern}  : {text}")
            if (aus or {}).get("hangup"):
                print("  (aufgelegt)")
                break
        print()
    print(f"Fehler: {fehler}")
    return 1 if fehler else 0


if __name__ == "__main__":
    raise SystemExit(main())
