"""W-NOTFALL-DEFAULT (08.09.2026): Blessing + Thaler buchten ungesagt Notfall.

Ursache: motiv_von fiel auf visitMotives[0], wenn kein Name „kontroll“ trug.
Bei Thaler/EVA und Blessing stand Akut/Notfall vorne. Niemand hatte
Schmerzen gesagt — die KI suchte und las trotzdem Notfall vor.

Thaler soll wie MedDent fragen: erst Besuchsgrund, dann Slots.
Notfall nur nach Schmerz/Akut/Notfall im Satz.
"""

from __future__ import annotations

from bianca import agent as bianca_agent
from bianca import besuchsgrund, flow, gehirn
from kern import stille
from kern.tenants import ist_akut_motiv, motiv_von


THALER_KAT = [
    {"id": "kch-akute-beschwerden-notfall-30min",
     "name": "KCH Akute Beschwerden / Notfall",
     "nameForPatient": "Akute Beschwerden / Notfall",
     "allowOnlineBooking": True, "calendarIds": []},
    {"id": "ze-beratung", "name": "ZE Beratung",
     "nameForPatient": "Zahnersatz-Beratung",
     "allowOnlineBooking": True, "calendarIds": []},
    {"id": "check", "name": "Recall Check-up",
     "nameForPatient": "Routineuntersuchung",
     "allowOnlineBooking": True, "calendarIds": []},
]

BLESSING_KAT = [
    {"id": "akut", "name": "Akutsprechstunde",
     "nameForPatient": "Akutsprechstunde",
     "allowOnlineBooking": True, "calendarIds": []},
    {"id": "botox", "name": "Botox-Behandlung",
     "nameForPatient": "Botox",
     "allowOnlineBooking": True, "calendarIds": []},
    {"id": "screen", "name": "Hautkrebsscreening",
     "nameForPatient": "Hautkrebs-Vorsorge",
     "allowOnlineBooking": True, "calendarIds": []},
]


def _tenant(kat, **extra):
    t = {
        "clientId": "t", "locationId": "l",
        "visitMotives": list(kat),
        "calendars": [{"id": "cal1", "name": "Dr. Test"}],
        "defaultCalendarId": "cal1",
        "praxisName": "Testpraxis",
    }
    t.update(extra)
    return t


def _sit(kat):
    sit = {
        "tenant": _tenant(kat),
        "messages": [{"role": "system", "content": "x"}],
        "motivKatalog": list(kat),
    }
    return sit


def _ohne_hintergrund(fn):
    echt = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    try:
        return fn()
    finally:
        flow.hintergrund.anstossen = echt


# --- Default darf nie Notfall sein ------------------------------------------

def test_motiv_von_ohne_kontroll_nimmt_nicht_das_erste_wenn_akut():
    t = _tenant(THALER_KAT)
    vm = motiv_von(t, "Kontrolluntersuchung")
    assert vm and vm["id"] != "kch-akute-beschwerden-notfall-30min"
    assert not ist_akut_motiv(vm)
    assert vm["id"] in {"check", "ze-beratung"}


def test_motiv_von_leer_nie_notfall():
    t = _tenant(THALER_KAT)
    vm = motiv_von(t, "")
    assert vm and not ist_akut_motiv(vm)


def test_motiv_von_explizit_notfall_bleibt_erlaubt():
    t = _tenant(THALER_KAT)
    vm = motiv_von(t, "KCH Akute Beschwerden / Notfall")
    assert vm and vm["id"] == "kch-akute-beschwerden-notfall-30min"


def test_blessing_kontroll_setzen_nimmt_screening_nicht_akut():
    sit = _sit(BLESSING_KAT)
    gehirn.kontroll_setzen(sit)
    s = gehirn.sammler(sit)
    assert s["grund"] == "Kontrolle"
    assert s["motivId"] != "akut"
    assert not ist_akut_motiv({"name": s["motivName"], "id": s["motivId"]})


def test_katalog_treffer_ohne_schmerz_nie_notfall():
    vm = besuchsgrund.katalog_treffer(
        "Ja, ist richtig.", katalog=THALER_KAT)
    assert vm is None or not ist_akut_motiv(vm)
    vm2 = besuchsgrund.katalog_treffer(
        "keine akuten Beschwerden", katalog=THALER_KAT)
    assert vm2 is None or not ist_akut_motiv(vm2)


def test_schmerz_darf_notfall_mappen():
    kern, vm = besuchsgrund.deute(_tenant(THALER_KAT), "Ich habe starke Zahnschmerzen.",
                                  katalog=THALER_KAT)
    assert "akut" in kern.lower() or "notfall" in kern.lower()
    assert vm and vm["id"] == "kch-akute-beschwerden-notfall-30min"


# --- Thaler wie MedDent: erst Grund fragen ----------------------------------

def test_thaler_fragt_besuchsgrund_nach_arzt_check():
    def lauf():
        sit = _sit(THALER_KAT)
        s = gehirn.sammler(sit)
        s.update({
            "modus": "buchen", "warSchonMal": True, "bekannt": True,
            "anruferCheck": "ja", "arztCheck": "",
            "vorname": "Michael", "nachname": "Petsas",
            "buchstabiert": True, "telefonOk": True,
            "frage": "arzt_check",
        })
        sit["anruferKartei"] = {
            "calendarId": "cal1", "calendarName": "Thaler",
        }
        z = flow.zug(sit, "Ja, ist richtig.")
        text = ((z or {}).get("text") or "").lower()
        assert "worum" in text or "grund" in text or "kontrolle" in text
        assert "vormittag" not in text
        assert not s["grund"]
        assert s["frage"] == "grund"
    _ohne_hintergrund(lauf)


def test_zahnersatzbesprechen_mappt_auf_ze():
    kern, vm = besuchsgrund.deute(
        _tenant(THALER_KAT),
        "Nein, den Besuchsgrund. Ich möchte zum Zahnersatzbesprechen kommen.",
        katalog=THALER_KAT,
    )
    assert kern == "Zahnersatz-Beratung"
    assert vm and vm["id"] == "ze-beratung"


def test_zahnarztbesprechung_stt_mappt_auf_ze():
    kern, vm = besuchsgrund.deute(
        _tenant(THALER_KAT), "Zahnarztbesprechung bitte.", katalog=THALER_KAT)
    assert kern == "Zahnersatz-Beratung"
    assert vm and vm["id"] == "ze-beratung"


def test_confirm_nein_besuchsgrund_wechselt_motiv():
    def lauf():
        sit = _sit(THALER_KAT)
        s = gehirn.sammler(sit)
        s.update({
            "modus": "buchen", "warSchonMal": True, "bekannt": True,
            "vorname": "Michael", "nachname": "Petsas",
            "buchstabiert": True, "telefonOk": True, "telefon": "0177123",
            "arzt": {"typ": "letzter", "calendarId": "cal1",
                     "calendarName": "Thaler"},
            "grund": "akute Beschwerden/Notfall",
            "motivId": "kch-akute-beschwerden-notfall-30min",
            "motivName": "KCH Akute Beschwerden / Notfall",
            "wunsch": {},
            "slotIso": "2026-09-10T09:30:00+02:00",
            "phase": "bestaetigen", "frage": "bestaetigung",
        })
        sit["offered"] = [{"iso": s["slotIso"], "spoken": "übermorgen um halb zehn"}]
        echt_ang = flow._angebot
        flow._angebot = lambda sit, melde=None: {"text": "Hier sind Zeiten."}
        try:
            z = flow.zug(sit, "Nein, keine akuten Beschwerden. Zahnarztbesprechung bitte.")
        finally:
            flow._angebot = echt_ang
        assert z
        assert s["motivId"] == "ze-beratung"
        assert "notfall" not in (s.get("motivName") or "").lower()
        assert "zahnersatz" in (s.get("grund") or "").lower()
    _ohne_hintergrund(lauf)


# --- Presence-Ja holt die Pflichtfrage zurück -------------------------------

def test_ja_nach_presence_stellt_aenderung_wieder():
    sit = _sit(THALER_KAT)
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen", "phase": "", "frage": "aenderung",
        "warSchonMal": True, "grund": "akute Beschwerden/Notfall",
        "motivId": "kch-akute-beschwerden-notfall-30min",
        "wunsch": {},
    })
    sit["messages"] = [
        {"role": "assistant",
         "content": "Was darf ich ändern — der Zeitpunkt, der Name oder die Nummer? Sind Sie noch dran?"},
    ]
    stille.reset(sit)
    out = bianca_agent.user_turn(sit, "Ja, ich bin noch dran.")
    t = (out.get("text") or "").lower()
    assert "noch dran" not in t
    assert "ändern" in t or "aendern" in t or "besuchsgrund" in t or "korrigier" in t
