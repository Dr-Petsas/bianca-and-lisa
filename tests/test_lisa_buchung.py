"""W-LISA-BUCHUNG (09.10.2026): Lisa bucht mit Biancas Buchungsmaschine.

Anruf bb329162: der Chef-Auftrag nannte einen freigewordenen OP-Termin am
4.11. Lisa erfand „4.11. um 11 Uhr“, kannte das Motiv nicht (gebucht haette
sie eine Kontrolle) und fragte nach jedem Ja „welchen Termin darf ich fest
eintragen?“. Hier laufen die wortgleichen Patientensaetze durch den neuen Weg.
"""

from __future__ import annotations

import pytest

from bianca import gehirn
from kern import calendar as kal
from kern import motive
from lisa import agent, identitaet, session, termin

AUFTRAG_BB329162 = (
    "Ruf denPatienten an, ein Termin ist am 4.11.. zur Operation freigeworden. "
    "an dem termin könnte der patient seine implantate eingesetzt bekommen. "
    "mache den termin mit ihm aus"
)
PETSAS = "zex5bmv5jfIHWVW6zHbg"
PATRIKIS = "RHYdoQFD7oAhqIepLzC2"
KATALOG = [
    {"id": "kch", "name": "KCH Kontrolluntersuchung", "allowOnlineBooking": True, "calendarIds": []},
    {"id": "opk", "name": "IMP Implantation OP klein", "allowOnlineBooking": False, "calendarIds": []},
    {"id": "opg", "name": "IMP Implantation OP groß", "allowOnlineBooking": False, "calendarIds": []},
    {"id": "sin", "name": "IMP Sinuslift OP", "allowOnlineBooking": False, "calendarIds": []},
    {"id": "bes", "name": "IMP Besprechung", "allowOnlineBooking": True, "calendarIds": []},
    {"id": "pzr", "name": "PRO professionelle Zahnreinigung", "allowOnlineBooking": True, "calendarIds": []},
]
TENANT = {
    "_id": "meddent", "_quelle": "cf+datei",
    "praxisName": "Zahnärzte im Medical Center Düsseldorf",
    "praxisNameVon": "den Zahnärzten im Medical Center Düsseldorf",
    "behandler": "Dr. Petsas",
    "clientId": "c1", "locationId": "l1",
    "defaultCalendarId": PETSAS,
    "calendars": [
        {"id": PETSAS, "name": "Doktor Michael Petsas"},
        {"id": PATRIKIS, "name": "Doktor Theodosios Patrikis"},
    ],
    "visitMotives": [],
}
SLOTS = ["2026-11-04T09:00:00+01:00", "2026-11-04T11:00:00+01:00", "2026-11-05T10:00:00+01:00"]


@pytest.fixture
def netz(monkeypatch):
    aufrufe: dict = {"suche": [], "buchung": []}
    monkeypatch.setattr(motive, "holen", lambda tenant: [dict(v) for v in KATALOG])

    def suche(tenant, ctx, **kw):
        aufrufe["suche"].append({"ctx": dict(ctx), **kw})
        return {"ok": True, "slots": [{"iso": x} for x in SLOTS]}

    def buchen(tenant, ctx, *, slot_iso=""):
        aufrufe["buchung"].append({"ctx": dict(ctx), "slot": slot_iso})
        return {"ok": True, "booked": True, "slotIso": slot_iso, "appointmentId": "a1",
                "spoken": "Ihr Termin ist eingetragen."}

    monkeypatch.setattr(kal, "find_slots_behandler", suche)
    monkeypatch.setattr(kal, "find_slots", suche)
    monkeypatch.setattr(kal, "book_slot", buchen)
    monkeypatch.setattr(agent.gedaechtnis, "kontext_anstossen", lambda sit: None)

    def kein_llm(*a, **k):
        raise AssertionError("das freie Modell darf im Buchungsfluss nicht laufen")

    monkeypatch.setattr(agent.llm, "chat", kein_llm)
    monkeypatch.setattr(agent.llm, "chat_stream", kein_llm)
    return aufrufe


def _sitzung(auftrag: str = AUFTRAG_BB329162) -> dict:
    sit = session.neu(
        tenant=dict(TENANT), auftrag=auftrag,
        patient={"id": "p1", "name": "Michael Petsas", "firstName": "Michael",
                 "lastName": "Petsas", "phone": "+491776004600", "gender": "male"},
        offered=[{"iso": "2026-10-20T08:00:00+02:00", "spoken": "Dienstag um acht"}],
    )
    # Startgruss + Identitaet liegen hinter uns (eigene Tests in test_lisa_dock_*).
    sit["messages"] = [{"role": "system", "content": "x"},
                       {"role": "assistant", "content": "Guten Tag, Herr Petsas."}]
    sit["idCheck"] = identitaet.FERTIG
    sit["idErgebnis"] = "bestaetigt"
    for _ in range(40):
        if isinstance(sit.get("motivKatalog"), list):
            break
        import time
        time.sleep(0.05)
    return sit


def test_auftrag_erkennung():
    assert termin.ist_buchungsauftrag(AUFTRAG_BB329162)
    assert termin.ist_buchungsauftrag("Bitte einen Kontrolltermin ausmachen")
    assert termin.ist_buchungsauftrag("Zahnreinigung vereinbaren, die ist überfällig")
    assert not termin.ist_buchungsauftrag("Ruf an und erinner ihn an den Termin morgen")
    assert not termin.ist_buchungsauftrag("Bitte den Termin am Donnerstag absagen")
    assert not termin.ist_buchungsauftrag("Wir möchten Ihren Kontrolltermin vorverlegen.")
    assert not termin.ist_buchungsauftrag("Frag nach, wie es nach der OP geht")


def test_motiv_aus_auftrag_ist_die_op_nicht_die_kontrolle():
    vm = termin.motiv_aus_auftrag(AUFTRAG_BB329162, KATALOG, PETSAS)
    assert vm and vm["name"] == "IMP Implantation OP klein"
    gross = termin.motiv_aus_auftrag("Termin für die große Implantat-OP ausmachen", KATALOG)
    assert gross and gross["name"] == "IMP Implantation OP groß"
    kontrolle = termin.motiv_aus_auftrag("Bitte einen Kontrolltermin ausmachen", KATALOG)
    assert kontrolle and kontrolle["name"] == "KCH Kontrolluntersuchung"
    # Ein Wort allein reicht nie fuer ein Motiv mit mehreren Kennwoertern.
    assert termin.motiv_aus_auftrag("Termin für die OP ausmachen", KATALOG) is None


def test_bb329162_wortgleich_bucht_op_am_4_11(netz):
    sit = _sitzung()
    assert sit.get("lisaTermin") is True

    a1 = agent.user_turn(sit, "Oh, Ja, um wie viel Uhr?")
    s = gehirn.sammler(sit)
    assert s["motivName"] == "IMP Implantation OP klein"
    assert netz["suche"], "die Slotsuche muss laufen"
    such = netz["suche"][-1]
    assert such["ctx"]["visitMotiveId"] == "opk"
    assert such["ctx"]["arztAuftrag"] is True
    assert such["ctx"]["calendarId"] == PETSAS
    assert such["start_date"] == "2026-11-04"
    assert "November" in a1["text"] and "?" in a1["text"]
    assert "welchen Termin darf ich" not in a1["text"]

    a2 = agent.user_turn(sit, "Ja, das passt mir.")
    assert not netz["buchung"], "erst nach der Ruecklese wird gebucht"
    assert "eintragen" in a2["text"].lower() or "?" in a2["text"]

    a3 = agent.user_turn(sit, "Ja.")
    assert netz["buchung"], f"nach dem Ja muss gebucht werden: {a3}"
    b = netz["buchung"][-1]
    assert b["slot"].startswith("2026-11-04")
    assert b["ctx"]["visitMotiveId"] == "opk"
    assert b["ctx"]["arztAuftrag"] is True
    assert b["ctx"]["patientId"] == "p1"
    assert "welchen Termin darf ich" not in a3["text"]


def test_bb329162_patient_nennt_selbst_elf_uhr(netz):
    sit = _sitzung()
    a1 = agent.user_turn(sit, "Ja, um 4.11. um 11. Uhr")
    assert "elf Uhr" in a1["text"]
    a2 = agent.user_turn(sit, "Ja.")
    assert "eintragen" in a2["text"]
    agent.user_turn(sit, "Ja.")
    assert netz["buchung"], "nach Zusage muss gebucht werden"
    assert netz["buchung"][-1]["slot"].startswith("2026-11-04T11:00")
    assert netz["buchung"][-1]["ctx"]["visitMotiveId"] == "opk"


def test_alter_kontroll_vorrat_wird_verworfen(netz):
    sit = _sitzung()
    agent.user_turn(sit, "Oh, Ja, um wie viel Uhr?")
    assert all("2026-10-20" not in str(x) for x in sit.get("offered") or [])
    assert sit["booking"].get("slotIso", "") in ("", None)


def test_nein_zum_angebot_laesst_das_modell_sprechen(netz, monkeypatch):
    sit = _sitzung()
    gerufen = []
    monkeypatch.setattr(agent.llm, "chat",
                        lambda msgs, tools=None, **k: gerufen.append(tools) or {"ok": True, "text": "Alles klar, dann wünsche ich Ihnen einen schönen Tag."})
    out = agent.user_turn(sit, "Nein danke, ich brauche keinen Termin.")
    assert sit.get("lisaTerminAus") is True
    assert not netz["buchung"] and not netz["suche"]
    assert out["text"]


def test_modell_zusage_im_buchungsfluss_faellt(netz):
    sit = _sitzung()
    agent.user_turn(sit, "Oh, Ja, um wie viel Uhr?")
    neu = termin.nach_modell(sit, "Ich trage Sie am 4.11. um 11 Uhr ein.", nutzertext="Und wie lange dauert das?")
    assert "trage" not in neu
    assert neu.endswith("?")


def test_ohne_buchungsauftrag_bleibt_lisa_beim_alten(netz):
    sit = _sitzung("Ruf an und erinner ihn an den Termin morgen")
    assert not sit.get("lisaTermin")
    assert termin.zug(sit, "Ja, danke.") is None


def test_notaus(monkeypatch, netz):
    monkeypatch.setenv("LISA_BUCHUNG", "0")
    sit = _sitzung()
    assert not sit.get("lisaTermin")


def test_doctor_order_geht_mit_token_an_die_cf(monkeypatch):
    gesendet = {}

    class R:
        status_code = 200

        def json(self):
            return {"status": "success", "freeTimeSlots": []}

    class Client:
        def post(self, url, json=None, headers=None, timeout=None):
            gesendet.update(url=url, body=json, headers=headers or {})
            return R()

    monkeypatch.setattr(kal, "PHONE_CALL_TOKEN", "tok")
    monkeypatch.setattr(kal, "_CF_CLIENT", Client())
    kal._cf_post("getFreeTimeSlots", {"doctorOrder": True})
    assert gesendet["body"]["doctorOrder"] is True
    assert "tok" in str(gesendet["headers"])
    gesendet.clear()
    kal._cf_post("getFreeTimeSlots", {"x": 1})
    assert "tok" not in str(gesendet["headers"])
