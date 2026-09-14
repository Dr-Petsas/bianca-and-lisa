"""W-MOTIV-KONSISTENT / W-MOTIV-BUCHBAR / W-MOTIV-TELEFON (14.09.2026).

MedDent-Anruf 06:0x (Nacht vor dem Feldtest): "Ich hab Schmerzen" wurde auf
das Terminal-Pseudo-Motiv "Notfall (Selbst-Check-in)" gemappt
(allowOnlineBooking=false). Die Slotsuche fiel auf Kontrolle zurueck und fand
Zeiten, die Buchung lief aber mit dem Pseudo-Motiv — masBookAppointment prueft
die Verfuegbarkeit je Motiv und antwortete "The slot is not available.". Der
Anrufer sagte Ja und hoerte nur "Termin ist gerade weg".

Drei Wachen:
1. Das Pseudo-Motiv der Check-in-Terminals steht NIE im Telefon-Katalog.
2. Das Mapping bevorzugt ueber die GANZE Kette buchbare Motive (nicht nur
   innerhalb einer Stufe) — "Schmerzen" landet auf "KCH akute Beschwerden/
   Notfall", nicht auf einem internen Schmerz-Motiv.
3. Fand erst das Ersatz-Motiv Zeiten, wird GENAU damit gebucht (Pin im
   Sammler); der Wunsch landet als Notiz am Termin. Wechselt der Anrufer den
   Grund, verfaellt der Pin.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bianca import flow, gehirn, hintergrund
from kern import calendar as kal
from kern import motive
from kern.tenants import laden

PETSAS = "zex5bmv5jfIHWVW6zHbg"
PSEUDO = motive.SELFCHECKIN_PSEUDO_ID


def _iso_in(tage: int, h: int, m: int = 0) -> str:
    d = datetime.now(ZoneInfo("Europe/Berlin")).replace(
        hour=h, minute=m, second=0, microsecond=0) + timedelta(days=tage)
    return d.isoformat(timespec="seconds")


def _katalog() -> list[dict]:
    return [
        {"id": PSEUDO, "name": "Notfall (Selbst-Check-in)",
         "nameForPatient": "Notfall", "allowOnlineBooking": False,
         "calendarIds": []},
        {"id": "schmerz-intern", "name": "KCH Schmerzbehandlung intern",
         "nameForPatient": "Schmerzen", "allowOnlineBooking": False,
         "calendarIds": []},
        {"id": "6QHf", "name": "KCH akute Beschwerden/Notfall",
         "nameForPatient": "Akute Schmerzen / Notfall",
         "allowOnlineBooking": True, "calendarIds": []},
        {"id": "kontrolle", "name": "KCH Kontrolluntersuchung",
         "nameForPatient": "Kontrolle", "allowOnlineBooking": True,
         "calendarIds": []},
        {"id": "fuellung-klein", "name": "KCH Füllung klein",
         "nameForPatient": "Füllung", "allowOnlineBooking": False,
         "calendarIds": []},
        {"id": "pzr", "name": "PRO Professionelle Zahnreinigung",
         "nameForPatient": "Zahnreinigung", "allowOnlineBooking": True,
         "calendarIds": []},
    ]


def _sit() -> dict:
    return {
        "tenant": laden("meddent"),
        "messages": [{"role": "system", "content": "x"}],
        "stimme": "Bianca",
        "motivKatalog": _katalog(),
    }


# --- 1. Terminal-Pseudo-Motiv nie am Telefon --------------------------------

def test_pseudo_motiv_faellt_aus_dem_sitzungskatalog():
    sit = _sit()
    ids = {v["id"] for v in motive.katalog(sit)}
    assert PSEUDO not in ids
    assert "6QHf" in ids and "kontrolle" in ids


def test_pseudo_motiv_faellt_schon_beim_holen(monkeypatch):
    class _R:
        status_code = 200

        def json(self):
            return {"status": "success", "motives": _katalog()}

    monkeypatch.setattr(motive.httpx, "post", lambda *a, **k: _R())
    kat = motive.holen({"clientId": "c", "locationId": "l"})
    assert kat and all(v["id"] != PSEUDO for v in kat)
    assert len(kat) == len(_katalog()) - 1


def test_pseudo_motiv_faellt_aus_der_mandanten_liste():
    sit = {"tenant": {"visitMotives": _katalog()}}
    assert all(v["id"] != PSEUDO for v in motive.katalog(sit))


# --- 2. Buchbar zuerst — ueber die ganze Kette -------------------------------

def test_schmerzen_landen_auf_buchbarem_notfall_motiv():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"grund": "akute Beschwerden/Notfall",
              "grundWortlaut": "Ich hab Schmerzen.",
              "motivId": "", "motivName": ""})
    vm = gehirn.motiv_fuer_kalender(sit, PETSAS)
    assert vm, "Schmerzen muessen auf ein Motiv mappen"
    assert vm["id"] == "6QHf", vm
    assert vm.get("allowOnlineBooking") is not False


def test_schmerzen_nie_auf_pseudo_auch_wenn_es_im_sammler_steht():
    """Alte Sitzung (vor dem Deploy) traegt das Pseudo-Motiv als motivId."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"grund": "akute Beschwerden/Notfall",
              "grundWortlaut": "Ich hab Schmerzen.",
              "motivId": PSEUDO, "motivName": "Notfall (Selbst-Check-in)"})
    vm = gehirn.motiv_fuer_kalender(sit, PETSAS)
    assert vm and vm["id"] == "6QHf", vm


def test_nur_unbuchbarer_wunsch_wird_nicht_still_zu_kontrolle():
    """Fuellung gibt es nur intern: das Mapping liefert EHRLICH die Fuellung
    (die Slotsuche sagt dann, dass telefonisch nichts geht bzw. faellt
    sichtbar auf Kontrolle zurueck) — nie still ein anderes Motiv."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"grund": "Füllung", "grundWortlaut": "Ich brauche eine Füllung.",
              "motivId": "", "motivName": ""})
    vm = gehirn.motiv_fuer_kalender(sit, PETSAS)
    assert vm and vm["id"] == "fuellung-klein", vm


# --- 3. Ersatz-Motiv wird gebucht ---------------------------------------------

def _fallback_find(protokoll: list[dict], frisch: list[str]):
    def fake_find(tenant, ctx, **kw):
        protokoll.append(dict(ctx))
        vm = {"id": ctx.get("visitMotiveId"), "name": ctx.get("visitMotiveName")}
        if ctx.get("visitMotiveId") == "kontrolle":
            return {"ok": True, "slots": list(frisch), "motive": vm,
                    "calendar": {"id": ctx.get("calendarId")}}
        return {"ok": True, "slots": [], "motive": vm,
                "calendar": {"id": ctx.get("calendarId")}}
    return fake_find


def _buch_sit() -> dict:
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": True,
              "arzt": {"typ": "genannt", "calendarId": PETSAS,
                       "calendarName": "Dr. Petsas"},
              "grund": "Füllung", "grundWortlaut": "Ich brauche eine Füllung.",
              "motivId": "fuellung-klein", "motivName": "KCH Füllung klein",
              "wunsch": {}, "vorname": "Julia", "nachname": "Berger",
              "buchstabiert": True, "phase": "angebot"})
    return sit


def test_find_slots_behandler_nennt_original_und_ersatz(monkeypatch):
    protokoll: list[dict] = []
    monkeypatch.setattr(kal, "find_slots", _fallback_find(protokoll, [_iso_in(3, 9)]))
    monkeypatch.setattr(kal, "motiv_von",
                        lambda tenant, name: {"id": "kontrolle", "name": "KCH Kontrolluntersuchung"})
    found = kal.find_slots_behandler(
        {"clientId": "c", "locationId": "l"},
        {"calendarId": PETSAS, "calendarName": "Dr. Petsas",
         "visitMotiveId": "fuellung-klein", "visitMotiveName": "KCH Füllung klein"},
    )
    assert found.get("motivFallback") == "kontrolle"
    assert found.get("motive", {}).get("id") == "kontrolle"
    assert found.get("motivOriginal") == {"id": "fuellung-klein", "name": "KCH Füllung klein"}


def test_angebot_pinnt_ersatz_motiv_und_bucht_damit(monkeypatch):
    sit = _buch_sit()
    s = gehirn.sammler(sit)
    frisch = [_iso_in(3, 9), _iso_in(4, 10, 30), _iso_in(5, 14)]
    protokoll: list[dict] = []
    monkeypatch.setattr(flow.kal, "find_slots", _fallback_find(protokoll, frisch))
    monkeypatch.setattr(flow.kal, "motiv_von",
                        lambda tenant, name: {"id": "kontrolle", "name": "KCH Kontrolluntersuchung"})
    ang = flow._angebot(sit)
    assert ang and ang.get("text")
    assert [p["visitMotiveId"] for p in protokoll] == ["fuellung-klein", "kontrolle"]
    # Pin sitzt, Buchungs-Motiv ist das Ersatz-Motiv
    assert s["motivId"] == "kontrolle"
    assert s["motivName"] == "KCH Kontrolluntersuchung"
    assert (s.get("motivFallback") or {}).get("von") == "fuellung-klein"
    assert (s.get("motivFallback") or {}).get("vonName") == "KCH Füllung klein"
    # der Wunsch bleibt fuer die Notiz erhalten
    assert s["grund"] == "Füllung"
    # Vorrat-Stempel passt zum gepinnten Motiv -> kein Neuladen im Buchungs-Zug
    assert sit["vorratFuer"] == hintergrund.vorrat_schluessel(sit)
    assert "|kontrolle|" in sit["vorratFuer"]
    ctx = flow._ctx_bauen(sit)
    assert ctx["visitMotiveId"] == "kontrolle", ctx
    assert ctx["visitMotiveName"] == "KCH Kontrolluntersuchung"


def test_pin_verfaellt_bei_neuem_grund(monkeypatch):
    sit = _buch_sit()
    s = gehirn.sammler(sit)
    monkeypatch.setattr(flow.kal, "find_slots", _fallback_find([], [_iso_in(3, 9)]))
    monkeypatch.setattr(flow.kal, "motiv_von",
                        lambda tenant, name: {"id": "kontrolle", "name": "KCH Kontrolluntersuchung"})
    flow._angebot(sit)
    assert s["motivId"] == "kontrolle"
    # Anrufer: "Ach nein, eigentlich brauche ich eine Zahnreinigung."
    s["grund"] = "Zahnreinigung"
    s["grundWortlaut"] = "Eigentlich brauche ich eine Zahnreinigung."
    ctx = flow._ctx_bauen(sit)
    assert ctx["visitMotiveId"] == "pzr", ctx
    assert s.get("motivFallback") is None


def test_pin_verfaellt_bei_anderem_kalender(monkeypatch):
    sit = _buch_sit()
    s = gehirn.sammler(sit)
    monkeypatch.setattr(flow.kal, "find_slots", _fallback_find([], [_iso_in(3, 9)]))
    monkeypatch.setattr(flow.kal, "motiv_von",
                        lambda tenant, name: {"id": "kontrolle", "name": "KCH Kontrolluntersuchung"})
    flow._angebot(sit)
    assert s["motivId"] == "kontrolle"
    vm = gehirn.motiv_fuer_kalender(sit, "anderer-kalender")
    assert vm and vm["id"] == "fuellung-klein", vm
    assert s.get("motivFallback") is None


def test_hintergrund_vorrat_pinnt_und_stempelt_passend(monkeypatch):
    sit = _buch_sit()
    s = gehirn.sammler(sit)
    s["phase"] = ""
    frisch = [_iso_in(3, 9), _iso_in(4, 10, 30)]
    monkeypatch.setattr(hintergrund.calendar, "find_slots", _fallback_find([], frisch))
    monkeypatch.setattr(hintergrund.calendar, "motiv_von",
                        lambda tenant, name: {"id": "kontrolle", "name": "KCH Kontrolluntersuchung"})
    hintergrund.vorrat_anstossen(sit)
    t0 = time.monotonic()
    while time.monotonic() - t0 < 5.0:
        if sit.get("slotVorrat") and not (sit.get("hgLaeuft") or {}).get("vorrat"):
            break
        time.sleep(0.02)
    assert sit.get("slotVorrat") == frisch
    assert s["motivId"] == "kontrolle"
    assert sit["vorratFuer"] == hintergrund.vorrat_schluessel(sit)
    assert sit["vorratKey"] == sit["vorratFuer"]

    def boom(*a, **k):
        raise AssertionError("kein Neuladen erwartet — Vorrat passt zum Pin")

    monkeypatch.setattr(flow.kal, "find_slots", boom)
    s["phase"] = "angebot"
    ang = flow._angebot(sit)
    assert ang and ang.get("text")
    assert [o["iso"] for o in (sit.get("offered") or [])]


def test_buchung_traegt_wunsch_als_notiz(monkeypatch):
    sit = _buch_sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "phase": "bestaetigen", "frage": "bestaetigung",
              "pzr": "nein", "telefon": "01776004600", "telefonOk": True,
              "slotIso": _iso_in(3, 9)})
    s["motivFallback"] = {"calendarId": PETSAS, "von": "fuellung-klein",
                          "vonName": "KCH Füllung klein",
                          "id": "kontrolle", "name": "KCH Kontrolluntersuchung"}
    s["motivId"], s["motivName"] = "kontrolle", "KCH Kontrolluntersuchung"
    sit["offered"] = [{"iso": s["slotIso"], "spoken": "Donnerstag um neun"}]
    sit["angebotKalender"] = {"calendarId": PETSAS, "calendarName": "Dr. Petsas"}
    gebucht: list[dict] = []
    notizen: list[str] = []

    def fake_book(tenant, ctx, slot_iso=""):
        gebucht.append(dict(ctx))
        return {"ok": True, "booked": True, "slotIso": slot_iso,
                "appointmentId": "apt-1", "spoken": "Der Termin ist fest eingetragen."}

    monkeypatch.setattr(flow.kal, "book_slot", fake_book)
    monkeypatch.setattr(flow.kal, "note_appointment",
                        lambda tenant, ctx, sit2=None, note="": notizen.append(note) or {"ok": True})
    flow.zug(sit, "Ja.")
    z = flow.zug(sit, "Nein, danke.")
    assert s["phase"] == "gebucht", z
    assert gebucht and gebucht[0]["visitMotiveId"] == "kontrolle", gebucht
    assert any("KCH Füllung klein" in n and "KCH Kontrolluntersuchung" in n
               and "telefonisch nichts buchbar" in n for n in notizen), notizen
    # O-Ton kondensiert (kern.notes.grund_kurz): „Füllung“
    assert any("Gewünscht: „Füllung“" in n for n in notizen), notizen
