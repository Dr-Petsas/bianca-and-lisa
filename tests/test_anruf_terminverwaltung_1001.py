"""W-TERMINVERWALTUNG-1001 (01.10.2026): die drei Fehler-Live-Anrufe vom
01.10. als deterministische Gegenproben.

- 953f6b66 (MedDent): „hier ist … Anna. Ich habe einen Termin heute.“ lief
  NICHT als Bestandsauskunft — die Maschine fragte nach Telefonnummer und
  Behandler statt den Termin zu lesen. Jetzt ist die Aussage „ich habe (einen)
  Termin heute/morgen“ eine Bestandsfrage (Auskunft), ohne das vage
  „ich habe einen Termin, weiß den Tag nicht“ den Opt-in-Mandanten zu nehmen.
- 4b86b5dd (MedDent): „Ich möchte den Termin verschieben“ drehte sich fünfmal
  mit der wortgleichen „Zu diesem Wunsch finde ich gerade nichts Freies“-
  Ansage. Eine identische Leersuche wird nicht wiederholt; nach spätestens
  zwei verschiedenen Leersuchen gibt es eine echte Rückrufnotiz und den
  Abschluss.
- 6e3337e1 (Thaler): ein Schmerzpatient bekam wortlos einen Normaltermin elf
  Tage später als „frühester passender Termin“. Jetzt wird ein weit
  entfernter Akuttermin einmal ehrlich benannt.

Alles deterministisch — kein freies LLM, keine echten Kalender-Writes.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest

from bianca import agent, flow, gehirn, hintergrund, session, verwalten
from kern import intent
from kern.tenants import laden


# ---------------------------------------------------------------------------
# 953f6b66 — „Ich habe einen Termin heute.“ ist Bestandsauskunft
# ---------------------------------------------------------------------------

def _sit(tenant: str = "meddent") -> dict:
    return {
        "tenant": laden(tenant),
        "messages": [{"role": "system", "content": "x"}],
    }


LIVE_953F6B66 = [
    "Guten Tag, hier ist Schiriati Anna. Ich habe einen Termin heute.",
    "Ich habe einen Termin heute.",
    "Ich habe heute einen Termin.",
    "Ich habe einen Termin morgen.",
]
KEINE_BESTANDSAUSSAGE = [
    # bewusst den Opt-in-Mandanten vorbehalten / Neubuchung / Verschieben
    "Ich habe einen Termin, ich weiss aber den Tag nicht mehr.",
    "Ich habe bei Ihnen einen Termin am 21. Oktober, den möchte ich verschieben.",
    "Ich hätte gern einen Termin.",
    "Ich brauche einen Termin im Oktober.",
    "Ich habe vergessen, einen Termin zu machen.",
]


@pytest.mark.parametrize("satz", LIVE_953F6B66)
def test_termin_heute_aussage_ist_bestandsfrage(satz):
    sit = _sit("meddent")
    assert intent._BESTANDSFRAGE_RE.search(satz), satz
    assert intent.ist_bestandsfrage(sit, satz), satz


@pytest.mark.parametrize("satz", KEINE_BESTANDSAUSSAGE)
def test_vage_oder_wunsch_bleibt_keine_bestandsaussage_bei_meddent(satz):
    sit = _sit("meddent")
    assert not intent._BESTANDSFRAGE_RE.search(satz), satz
    assert not intent.ist_bestandsfrage(sit, satz), satz


def test_termin_heute_wird_als_auskunft_gedeutet():
    sit = _sit("meddent")
    d = intent.erkennen(sit, "Ich habe einen Termin heute.")
    assert d["handlung"] == "WISSEN", d
    assert d["gegenstand"] == "VORGANG", d


# ---------------------------------------------------------------------------
# 4b86b5dd — Verschieben ohne freien Platz läuft nicht in die Endlosschleife
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


def _verschieb_sit(monkeypatch, notizen):
    sit = _sit("meddent")
    s = gehirn.sammler(sit)
    s["modus"] = "verschieben"
    sit["verwaltenTermin"] = _TERMIN["id"]
    sit["gefunden"] = [dict(_TERMIN)]
    # Kalender erreichbar, aber ohne freie Zeiten.
    monkeypatch.setattr(
        verwalten.kal, "find_slots_behandler",
        lambda *a, **k: {"ok": True, "slots": []},
    )
    monkeypatch.setattr(
        verwalten, "_notiz_schreiben",
        lambda *a, **k: (notizen.append(k) or True),
    )
    return sit, s


def test_erste_leersuche_fragt_einmal_nach_anderem_tag(monkeypatch):
    notizen = []
    sit, s = _verschieb_sit(monkeypatch, notizen)
    aus = verwalten._verschieb_angebot(sit, None)
    assert "nichts Freies" in aus["text"]
    assert "anderer Tag" in aus["text"] or "andere Tageszeit" in aus["text"]
    assert s["frage"] == "wunsch"
    assert not notizen, "die erste Leersuche hinterlässt noch keine Notiz"


def test_identische_leersuche_wird_nicht_wiederholt_sondern_notiert(monkeypatch):
    notizen = []
    sit, s = _verschieb_sit(monkeypatch, notizen)
    # Erste Leersuche: fragt nach anderem Tag.
    verwalten._verschieb_angebot(sit, None)
    # Zweite Leersuche mit identischem Rahmen (kein neuer Wunsch): abbrechen.
    aus = verwalten._verschieb_angebot(sit, None)
    assert "Rückrufnotiz" in aus["text"]
    assert s["frage"] == "sonst_noch"
    assert sit.get("verwAbschlussOffen") is True
    assert notizen, "nach der Wiederholung muss eine echte Rückrufnotiz stehen"
    assert notizen[-1].get("anliegen") == "verschieben"


def test_mehrere_verschiedene_leersuchen_enden_in_rueckrufnotiz(monkeypatch):
    notizen = []
    sit, s = _verschieb_sit(monkeypatch, notizen)
    # Jede Runde ein WIRKLICH anderer Wunsch -> drei verschiedene Leersuchen.
    s["wunsch"] = {"tage": ["montag"]}
    verwalten._verschieb_angebot(sit, None)
    assert s["frage"] == "wunsch"
    s["wunsch"] = {"tage": ["dienstag"]}
    verwalten._verschieb_angebot(sit, None)
    assert s["frage"] == "wunsch"
    s["wunsch"] = {"tage": ["mittwoch"]}
    aus = verwalten._verschieb_angebot(sit, None)
    assert "Rückrufnotiz" in aus["text"]
    assert s["frage"] == "sonst_noch"
    assert notizen


def test_echte_slots_setzen_den_leersuch_zaehler_zurueck(monkeypatch):
    notizen = []
    sit, s = _verschieb_sit(monkeypatch, notizen)
    verwalten._verschieb_angebot(sit, None)  # eine Leersuche
    assert sit.get("verschiebLeerN")
    # Jetzt liefert der Kalender wieder Zeiten.
    monkeypatch.setattr(
        verwalten.kal, "find_slots_behandler",
        lambda *a, **k: {
            "ok": True,
            "slots": ["2026-10-20T11:00:00+02:00", "2026-10-21T09:00:00+02:00"],
        },
    )
    s["wunsch"] = None
    aus = verwalten._verschieb_angebot(sit, None)
    assert s["frage"] == "slotwahl"
    assert "verschiebLeerN" not in sit
    assert "Rückrufnotiz" not in aus["text"]


# ---------------------------------------------------------------------------
# 6e3337e1 — Akut-/Schmerzfall bekommt einen weit entfernten Termin nicht
#            mehr wortlos als „frühester passender Termin“
# ---------------------------------------------------------------------------

def _iso(tag: date, stunde: int) -> str:
    return datetime.combine(tag, time(stunde)).astimezone().isoformat(timespec="seconds")


def _werktag(tage_ab_heute: int) -> date:
    d = date.today() + timedelta(days=tage_ab_heute)
    while d.weekday() >= 5:  # Sa/So meiden
        d += timedelta(days=1)
    return d


def _buchung(monkeypatch, tenant: str, grund: str, slot_iso: str) -> dict:
    # Jede Slot-Quelle liefert deterministisch genau den einen Termin — egal,
    # ob der Fluss den Vorrat neu lädt (Motivauflösung ändert den Vorratsschlüssel).
    monkeypatch.setattr(flow.hintergrund, "anstossen", lambda *a, **k: None)
    for name in ("find_slots", "find_slots_behandler", "find_slots_raeume"):
        monkeypatch.setattr(
            flow.kal, name,
            lambda *a, **k: {"ok": True, "slots": [slot_iso]},
        )
    sit = session.neu(tenant=laden(tenant))
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "phase": "",
        "frage": "",
        "warSchonMal": True,
        "arzt": {
            "typ": "gesagt",
            "calendarId": "cal-thaler-1",
            "calendarName": "Frau Thaler",
        },
        "grund": grund,
        "grundWortlaut": grund,
        "motivId": "motiv-x",
        "motivName": grund,
        "nachname": "Muster",
        "vorname": "Max",
        "buchstabiert": True,
        "nameVerified": True,
        "versicherung": "gesetzlich",
        "wunsch": {"erstmoeglich": True},
        "wunschText": "frühestmöglich",
    })
    sit["slotVorrat"] = [slot_iso]
    sit["vorratFuer"] = hintergrund.vorrat_schluessel(sit)
    sit["vorratGemerkt"] = True
    return sit


def test_akuter_fall_mit_weitem_termin_wird_ehrlich_benannt(monkeypatch):
    weit = _iso(_werktag(11), 11)
    sit = _buchung(monkeypatch, "thaler", "Schmerzen", weit)
    aus = flow._angebot(sit)
    assert "Bei akuten Beschwerden" in aus["text"], aus["text"]
    assert sit["offered"] and sit["offered"][0]["iso"][:16] == weit[:16]


def test_akuter_fall_mit_nahem_termin_bleibt_ohne_sonderhinweis(monkeypatch):
    nah = _iso(_werktag(1), 11)
    sit = _buchung(monkeypatch, "thaler", "Schmerzen", nah)
    aus = flow._angebot(sit)
    assert "Bei akuten Beschwerden" not in aus["text"], aus["text"]
    assert sit["offered"] and sit["offered"][0]["iso"][:16] == nah[:16]


def test_nicht_akuter_fall_mit_weitem_termin_bekommt_keinen_akuthinweis(monkeypatch):
    weit = _iso(_werktag(11), 11)
    sit = _buchung(monkeypatch, "thaler", "Kontrolle", weit)
    aus = flow._angebot(sit)
    assert "Bei akuten Beschwerden" not in aus["text"], aus["text"]


# ---------------------------------------------------------------------------
# 062c4e1f — „Vitamin“ ist in der Zahnpraxis der Hörfehler für „Termin“
# ---------------------------------------------------------------------------

VITAMIN_ALS_TERMIN = [
    "Ich brauche einen Vitamin für den Doktor Petsas.",
    "Ich möchte meinen Vitamin verschieben.",
    "Ich möchte den Vitamin absagen.",
    "Wann bekomme ich Vitamin?",
    "Vitamin.",
]
ECHTE_VITAMINE = [
    "Ich brauche Vitamin D.",
    "Haben Sie etwas gegen Vitaminmangel?",
    "Ich nehme Vitamine.",
]


@pytest.mark.parametrize("satz", VITAMIN_ALS_TERMIN)
def test_vitamin_wird_in_zahnpraxis_zu_termin(satz):
    sit = _sit("meddent")
    neu = agent._vitamin_termin_korrektur(sit, satz)
    assert "vitamin" not in neu.lower(), (satz, neu)
    assert "termin" in neu.lower(), (satz, neu)


@pytest.mark.parametrize("satz", ECHTE_VITAMINE)
def test_echte_vitamin_begriffe_bleiben_unveraendert(satz):
    sit = _sit("meddent")
    assert agent._vitamin_termin_korrektur(sit, satz) == satz, satz


def test_vitamin_korrektur_nur_in_der_zahnpraxis():
    # Nicht-Zahn-Fach (Hautarzt Blessing) spricht sehr wohl über Vitamine.
    sit = _sit("blessing")
    satz = "Ich brauche einen Vitamin für den Doktor."
    assert agent._vitamin_termin_korrektur(sit, satz) == satz
