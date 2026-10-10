"""Verschieben (Bianca-Seite) + Platzhalter-Rückkehr (10.10.2026).

- 4cd6db61: die Verschiebe-Suche bot einen Kassen-Slot an, das Verschieben
  prüfte den Zielslot aber mit der Versicherung des Termin-Patienten
  (privat) und verwarf ihn. Jetzt geht der Typ des Termin-Patienten mit in
  die Suche (W-VERSCHIEB-VORPRUEFUNG).
- 5d4d505d: „nicht bestätigt / bereits bearbeitet“ kam erst nach der
  Slotwahl. Die Vorprüfung erkennt die Plattformsperre VOR dem Angebot.
- 6d62cca2: nach einem Aufgabenwechsel bot Bianca den eben abgelehnten
  14:20-Slot erneut an — der Checkpoint stammte von vor der Ablehnung
  (W-SPERRE-ANRUFWEIT).
- 92e777c3 (Blessing): mitten im Slotangebot „… Frau Doktor Blessing
  sprechen können?“ — nach dem Platzhalter kam nur „Kann ich sonst etwas
  für Sie tun?“, die Buchung war weg (W-PLATZHALTER-RUECKKEHR).

Offline: kein LLM, kein Netz, keine Writes.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from bianca import agent, gehirn, session, verwalten, weiterleiten
from kern import calendar as kal
from kern import hirn, llm
from kern.tenants import laden


def _kein_llm(monkeypatch) -> None:
    def platzt(*a, **k):
        raise AssertionError("dieser Weg muss ohne LLM laufen")
    monkeypatch.setattr(llm, "chat", platzt)
    monkeypatch.setattr(llm, "chat_stream", platzt)


# ---------------------------------------------------------------------------
# Vorprüfung: liest den Termin so, wie die Plattform prüft
# ---------------------------------------------------------------------------

def _doc(monkeypatch, termin: dict | None, ok: bool = True, missing: bool = False):
    def lesen(tenant, aid, **k):
        if not ok:
            return {"ok": False, "error": "http_500"}
        if missing:
            return {"ok": True, "missing": True, "appointmentId": aid}
        return {"ok": True, "deleted": False, "appointment": dict(termin or {})}
    monkeypatch.setattr(kal, "_firestore_appointment_by_id", lesen)


def test_privatpatient_sucht_mit_privat(monkeypatch):
    _doc(monkeypatch, {"status": "confirmed", "patientStatus": 0, "privateInsurance": True})
    res = kal.verschieb_vorpruefung({}, "apt-1")
    assert res == {"ok": True, "gesperrt": False, "insuranceType": "private_self_payer"}


@pytest.mark.parametrize("pi", [False, None])
def test_kasse_oder_unbekannt_wie_die_plattform_gesetzlich(monkeypatch, pi):
    # Plattform: privateInsurance === true ? privat : gesetzlich
    _doc(monkeypatch, {"status": "confirmed", "patientStatus": None, "privateInsurance": pi})
    res = kal.verschieb_vorpruefung({}, "apt-1")
    assert res["ok"] and not res["gesperrt"]
    assert res["insuranceType"] == "public_insurance"


@pytest.mark.parametrize("status,ps", [
    ("pending", 0), ("cancelled", None), ("confirmed", 2), ("confirmed", 4),
])
def test_plattformsperre_wird_erkannt(monkeypatch, status, ps):
    _doc(monkeypatch, {"status": status, "patientStatus": ps})
    assert kal.verschieb_vorpruefung({}, "apt-1")["gesperrt"] is True


@pytest.mark.parametrize("ps", [None, "", 0])
def test_fehlender_patientstatus_sperrt_nicht(monkeypatch, ps):
    _doc(monkeypatch, {"status": "confirmed", "patientStatus": ps})
    assert kal.verschieb_vorpruefung({}, "apt-1")["gesperrt"] is False


def test_lesefehler_und_fehlendes_dokument_wissen_nichts(monkeypatch):
    _doc(monkeypatch, None, ok=False)
    assert kal.verschieb_vorpruefung({}, "apt-1") == {"ok": False}
    _doc(monkeypatch, None, missing=True)
    assert kal.verschieb_vorpruefung({}, "apt-1") == {"ok": False}


def test_notaus(monkeypatch):
    monkeypatch.setenv("VERSCHIEB_VORPRUEFUNG", "0")
    _doc(monkeypatch, {"status": "pending"})
    assert kal.verschieb_vorpruefung({}, "apt-1") == {"ok": False}


def test_suchrumpf_traegt_den_typ_nur_wenn_bekannt(monkeypatch):
    bodies = []
    monkeypatch.setattr(kal, "_cf_call", lambda name, body: (bodies.append(body) or (500, {}, {})))
    t = {"clientId": "c", "locationId": "l"}
    kal._find_slots_seite(t, {"calendarId": "k", "patientInsuranceType": "private_self_payer"})
    kal._find_slots_seite(t, {"calendarId": "k"})
    kal._find_slots_seite(t, {"calendarId": "k", "patientInsuranceType": "all"})
    assert bodies[0]["patientInsuranceType"] == "private_self_payer"
    assert "patientInsuranceType" not in bodies[1]
    assert "patientInsuranceType" not in bodies[2]


# ---------------------------------------------------------------------------
# Verschiebe-Angebot: Typ geht mit, Sperre kommt vor dem Angebot
# ---------------------------------------------------------------------------

_TERMIN = {
    "id": "apt-verschieb",
    "iso": "2026-10-13T09:45+02:00",
    "date": "2026-10-13",
    "calendarId": "cal-petsas",
    "doctorName": "Doktor Petsas",
    "motivId": "motiv-kontrolle",
    "motivName": "Kontrolle",
    "spoken": "am Dienstag, den dreizehnten Oktober um neun Uhr fünfundvierzig "
              "bei Doktor Petsas",
    "patientId": "patient-x",
    "patientFirstName": "Anna",
    "patientLastName": "Beispiel",
    "patientName": "Anna Beispiel",
}


def _verschieb_sit(monkeypatch, pruefung: dict, such: list, notizen: list):
    sit = {"tenant": laden("meddent"), "messages": [{"role": "system", "content": "x"}]}
    s = gehirn.sammler(sit)
    s["modus"] = "verschieben"
    sit["verwaltenTermin"] = _TERMIN["id"]
    sit["gefunden"] = [dict(_TERMIN)]
    aufrufe = []

    def vorpruefen(tenant, aid):
        aufrufe.append(aid)
        return dict(pruefung)

    monkeypatch.setattr(verwalten.kal, "verschieb_vorpruefung", vorpruefen)
    monkeypatch.setattr(
        verwalten.kal, "find_slots_behandler",
        lambda tenant, ctx, **k: (such.append(dict(ctx))
                                  or {"ok": True, "slots": ["2026-10-20T14:20:00+02:00"]}),
    )
    monkeypatch.setattr(verwalten, "_notiz_schreiben",
                        lambda *a, **k: (notizen.append(k) or True))
    return sit, s, aufrufe


def test_4cd6db61_privatpatient_suche_traegt_privat(monkeypatch):
    such, notizen = [], []
    sit, s, aufrufe = _verschieb_sit(
        monkeypatch, {"ok": True, "gesperrt": False, "insuranceType": "private_self_payer"},
        such, notizen)
    aus = verwalten._verschieb_angebot(sit, None)
    assert such and such[0]["patientInsuranceType"] == "private_self_payer"
    assert s["frage"] == "slotwahl", aus
    # Einmal je Bestandstermin gelesen, nicht bei jeder Neusuche.
    verwalten._verschieb_angebot(sit, None)
    assert aufrufe == ["apt-verschieb"]
    assert not notizen


def test_unbekannt_sucht_wie_bisher_ohne_typ(monkeypatch):
    such, notizen = [], []
    sit, s, _ = _verschieb_sit(monkeypatch, {"ok": False}, such, notizen)
    verwalten._verschieb_angebot(sit, None)
    assert "patientInsuranceType" not in such[0]
    assert s["frage"] == "slotwahl"


def test_5d4d505d_gesperrter_termin_ehrlich_vor_dem_angebot(monkeypatch):
    such, notizen = [], []
    sit, s, _ = _verschieb_sit(
        monkeypatch, {"ok": True, "gesperrt": True, "insuranceType": "public_insurance"},
        such, notizen)
    aus = verwalten._verschieb_angebot(sit, None)
    assert not such, "kein Slot anbieten, den die Plattform ohnehin verwirft"
    assert aus["text"].startswith(verwalten._VERSCHIEBEN_GESPERRT)
    assert notizen and notizen[-1]["anliegen"] == "verschieben"
    assert s["frage"] == "sonst_noch"
    assert not sit.get("offered")


def test_testlauf_liest_nicht(monkeypatch):
    such, notizen = [], []
    sit, _, aufrufe = _verschieb_sit(
        monkeypatch, {"ok": True, "gesperrt": True}, such, notizen)
    sit["testNoWrite"] = True
    verwalten._verschieb_angebot(sit, None)
    assert aufrufe == [] and such


# ---------------------------------------------------------------------------
# 6d62cca2: Sperren überleben das Zurücklegen eines Checkpoints
# ---------------------------------------------------------------------------

def test_6d62cca2_abgelehnter_slot_bleibt_nach_checkpoint_gesperrt(monkeypatch):
    sit = session.neu(tenant=dict(laden("meddent")))
    sit["slotGesperrt"] = ["2026-10-20T10:00"]
    cp = hirn._checkpoint_machen(sit)
    # Danach lehnte die Plattform 14:20 ab, ein Write war gescheitert.
    sit["slotGesperrt"] = ["2026-10-20T10:00", "2026-10-20T14:20"]
    sit["moveFails"] = 1
    hirn._checkpoint_zuruecklegen(sit, cp)
    assert sit["slotGesperrt"] == ["2026-10-20T10:00", "2026-10-20T14:20"]
    # moveFails bleibt aufgabenlokal (test_auto_resume: Termin A vs. B).
    assert "moveFails" not in sit


def test_checkpoint_ohne_sperren_bleibt_sauber():
    sit = session.neu(tenant=dict(laden("meddent")))
    cp = hirn._checkpoint_machen(sit)
    sit["angebotZuletzt"] = ["x"]
    hirn._checkpoint_zuruecklegen(sit, cp)
    assert "slotGesperrt" not in sit and "moveFails" not in sit
    assert "angebotZuletzt" not in sit


def test_sperre_anrufweit_notaus(monkeypatch):
    monkeypatch.setenv("SPERRE_ANRUFWEIT", "0")
    sit = session.neu(tenant=dict(laden("meddent")))
    cp = hirn._checkpoint_machen(sit)
    sit["slotGesperrt"] = ["2026-10-20T14:20"]
    hirn._checkpoint_zuruecklegen(sit, cp)
    assert "slotGesperrt" not in sit


# ---------------------------------------------------------------------------
# 92e777c3: nach dem Platzhalter geht die Buchung weiter
# ---------------------------------------------------------------------------

def _sit_buchung(mandant: str) -> dict:
    t = dict(laden(mandant))
    t["weiterleitungen"] = []
    sit = session.neu(tenant=t)
    sit["clientKind"] = "sip"
    sit["messages"] = [{"role": "system", "content": "x"},
                       {"role": "assistant", "content": "Guten Tag, was kann ich für Sie tun?"}]
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    s["nachname"] = "Heide"
    s["warSchonMal"] = True
    s["frage"] = "vorname"
    sit["flussFrage"] = "Und Ihr Vorname?"
    hirn.anwenden(sit, {"zug": "wechseln", "handlung": "ANLEGEN", "gegenstand": "VORGANG",
                        "ersatz": None, "spiegel": "Termin buchen"})
    return sit


@pytest.mark.parametrize("mandant,satz", [
    ("blessing", "Kann ich Frau Doktor Blessing sprechen?"),
    ("meddent", "Verbinden Sie mich bitte mit Doktor Petsas."),
])
def test_92e777c3_platzhalter_holt_die_buchung_zurueck(monkeypatch, mandant, satz):
    _kein_llm(monkeypatch)
    sit = _sit_buchung(mandant)
    aus = agent.user_turn(sit, satz)
    text = aus.get("text") or ""
    assert text.startswith(weiterleiten.ANSAGE_PLATZHALTER_KURZ), text
    assert "Kann ich sonst etwas" not in text, text
    # Brücke + die offene Frage der Buchung (je Mandant eine andere Reihenfolge).
    assert "zurück zu Ihrem Termin" in text and text.endswith("?"), text
    assert gehirn.sammler(sit).get("frage"), "die Frage muss registriert sein"
    assert not aus.get("transfer") and not aus.get("hangup")
    assert "_platzhalterWieder" not in aus
    a = hirn.aktiv(sit) or {}
    assert a.get("handlung") == "ANLEGEN", a
    assert gehirn.sammler(sit)["nachname"] == "Heide"


def test_platzhalter_ohne_geparktes_anliegen_bleibt_wie_bisher(monkeypatch):
    _kein_llm(monkeypatch)
    t = dict(laden("blessing"))
    t["weiterleitungen"] = []
    sit = session.neu(tenant=t)
    sit["clientKind"] = "sip"
    sit["messages"] = [{"role": "system", "content": "x"},
                       {"role": "assistant", "content": "Guten Tag, was kann ich für Sie tun?"}]
    aus = agent.user_turn(sit, "Kann ich Frau Doktor Blessing sprechen?")
    assert aus.get("text") == weiterleiten.ANSAGE_PLATZHALTER, aus


def test_platzhalter_rueckkehr_notaus(monkeypatch):
    _kein_llm(monkeypatch)
    monkeypatch.setenv("PLATZHALTER_RUECKKEHR", "0")
    sit = _sit_buchung("blessing")
    aus = agent.user_turn(sit, "Kann ich Frau Doktor Blessing sprechen?")
    assert aus.get("text") == weiterleiten.ANSAGE_PLATZHALTER, aus
