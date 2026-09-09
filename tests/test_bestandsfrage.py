"""W-BESTANDSFRAGE (09.09.2026): Frage nach schon gebuchten Terminen mitten
in einer Buchung.

Live Petsas 08.09.2026 (Anruf a1d77850…): der Anrufer fragte VIERMAL nach
seinen bestehenden Terminen ("Habe ich noch einen anderen Termin diese
Woche?", "Wann ist denn der andere Termin?", "Ich glaube, ich hatte noch
einen anderen Termin gebucht.") — Bianca hing im Buchungs-Slotangebot fest,
das Frei-LLM ERFAND jedes Mal "keine weiteren Termine im System", OHNE je
den Kalender zu lesen (kein agentFindPatientAppointments).

Fix: die Intent-Schicht erkennt die Bestandstermin-Frage auch mitten in der
Buchung als WISSEN x VORGANG -> Hirn parkt die Buchung, verwalten liest die
Termine wirklich (agentFindPatientAppointments), sagt sie an, danach fuehrt
Auto-Resume zur Buchung zurueck.

Laeuft ohne Netz: das LLM darf NIE laufen (der Fluss antwortet
deterministisch), die Kalender-Suche wird gestummt.
"""

import os

from bianca import agent, flow, gehirn, verwalten
from kern import hirn, intent
from kern.tenants import laden


def _sit() -> dict:
    return {"tenant": laden("meddent"),
            "messages": [{"role": "system", "content": "x"}],
            "stimme": "bianca"}


def _mitten_in_buchung() -> dict:
    """Sitzung wie im Live-Fall: Anrufer als Petsas erkannt, Buchung laeuft,
    Slots werden gerade angeboten (Angebot offen)."""
    sit = _sit()
    hirn.init(sit)
    hirn.anliegen_hinzufuegen(
        sit, hirn._anliegen("ANLEGEN", "VORGANG", spiegel="Termin morgen"),
        aktivieren=True,
    )
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen", "phase": "angebot", "frage": "slotwahl",
        "vorname": "Michael", "nachname": "Petsas", "patientId": "pat-9",
        "anruferCheck": True, "warSchonMal": True, "bekannt": True,
        "buchstabiert": True, "grund": "Kontrolle",
    })
    sit["offered"] = [
        {"iso": "2026-09-10T09:00", "spoken": "morgen um neun Uhr"},
        {"iso": "2026-09-10T12:00", "spoken": "morgen um zwölf Uhr"},
    ]
    return sit


# Ein bestehender Termin im Kalender: Donnerstag um halb zwölf (11:30).
DONNERSTAG = {
    "ok": True,
    "patient": {"id": "pat-9", "firstName": "Michael", "lastName": "Petsas"},
    "appointments": [{
        "id": "apt-do", "iso": "2026-09-11T11:30", "date": "2026-09-11",
        "calendarId": "zex5bmv5jfIHWVW6zHbg", "doctorName": "Dr. Petsas",
        "motivId": "vm-1", "motivName": "01 Kontrolluntersuchung",
        "spoken": "am Donnerstag um halb zwölf bei Dr. Petsas",
    }],
}


LIVE_TREFFER = [
    "Nein, habe ich noch andere Termine eigentlich?",
    "Habe ich noch einen anderen Termin diese Woche?",
    "Wann ist denn der andere Termin?",
    "Ich glaube, ich hatte noch einen anderen Termin gebucht.",
    "Habe ich denn schon einen Termin?",
    "Welche Termine habe ich noch?",
    "Wann ist mein Termin?",
]
KEIN_TREFFER = [
    "Ich hätte gerne einen Termin morgen.",
    "Ich brauche einen Termin.",
    "Ja, den Termin morgen um neun.",
    "Ich möchte einen Termin vereinbaren.",
    "Eine Kontrolle.",
    "Nein, ohne Zahnreinigung.",
    "Ja, für mich selbst ist der Termin.",
]


# --- 1) Regex: Bestandsfrage sicher erkennen, Buchungswunsch nicht ----------

def test_bestandsfrage_regex_trifft_live_saetze():
    for satz in LIVE_TREFFER:
        assert intent._BESTANDSFRAGE_RE.search(satz), satz


def test_bestandsfrage_regex_verschont_buchungswunsch():
    for satz in KEIN_TREFFER:
        assert not intent._BESTANDSFRAGE_RE.search(satz), satz


# --- 2) Intent: mitten in der Buchung -> WISSEN x VORGANG (Auskunft) ---------

def test_intent_deutet_bestandsfrage_als_wissen_vorgang():
    for satz in ["Habe ich noch einen anderen Termin diese Woche?",
                 "Wann ist denn der andere Termin?",
                 "Ich glaube, ich hatte noch einen anderen Termin gebucht."]:
        sit = _mitten_in_buchung()
        d = intent.erkennen(sit, satz)
        assert d["handlung"] == "WISSEN", (satz, d)
        assert d["gegenstand"] == "VORGANG", (satz, d)
        assert d["zug"] == "wechseln", (satz, d)


def test_intent_haelt_slotwahl_antwort():
    """Eine echte Slot-Antwort bleibt Buchung — kein Fehlwechsel."""
    sit = _mitten_in_buchung()
    d = intent.erkennen(sit, "Morgen um neun.")
    assert d["zug"] in {"verfeinern", "halten"}
    assert d["handlung"] == "KEINE"


# --- 3) Hirn: Buchung parken (mit Checkpoint), Auskunft aktiv ----------------

def test_hirn_parkt_buchung_und_schaltet_auf_auskunft():
    alt = os.environ.get("HIRN_AUTO_RESUME")
    os.environ["HIRN_AUTO_RESUME"] = "enforce"
    try:
        sit = _mitten_in_buchung()
        d = intent.erkennen(sit, "Habe ich noch einen anderen Termin diese Woche?")
        hirn.anwenden(sit, d)
        s = gehirn.sammler(sit)
        assert s["modus"] == "auskunft"
        assert sit.get("hirnModusNeu") is True
        anliegen = sit["hirn"]["anliegen"]
        anlegen = [a for a in anliegen if a["handlung"] == "ANLEGEN"][0]
        wissen = [a for a in anliegen if a["handlung"] == "WISSEN"][0]
        assert anlegen["status"] == "geparkt"
        assert wissen["status"] == "aktiv"
        # Checkpoint der Buchung gesichert (Slotangebot + Grund).
        assert isinstance(anlegen.get("checkpoint"), dict)
    finally:
        if alt is None:
            os.environ.pop("HIRN_AUTO_RESUME", None)
        else:
            os.environ["HIRN_AUTO_RESUME"] = alt


# --- 4) verwalten: bekannter Anrufer -> Termine WIRKLICH lesen und ansagen ---

def test_verwalten_auskunft_liest_bestehenden_termin():
    echt_find = verwalten.kal.find_patient_appointments
    gerufen = []

    def _find(t, c):
        gerufen.append(dict(c))
        return dict(DONNERSTAG)

    verwalten.kal.find_patient_appointments = _find
    try:
        sit = _mitten_in_buchung()
        s = gehirn.sammler(sit)
        # Hirn hat auf Auskunft geschaltet:
        s["modus"] = "auskunft"
        s["phase"] = ""
        s["frage"] = ""
        z = verwalten.zug(sit, "Habe ich noch einen anderen Termin diese Woche?",
                          {"modus"})
        assert gerufen, "agentFindPatientAppointments wurde nicht aufgerufen"
        assert gerufen[-1].get("lastName") == "Petsas"
        assert z and "halb zwölf" in z["text"], z
        assert "Donnerstag" in z["text"], z
    finally:
        verwalten.kal.find_patient_appointments = echt_find


# --- 5) Agent Ende-zu-Ende: sieht den Termin, KEIN LLM, danach zurueck -------

def test_agent_sieht_bestandstermin_ohne_llm_und_kehrt_zurueck():
    from kern import llm

    def _knall(*a, **k):
        raise AssertionError("LLM darf bei der Bestandsfrage nicht laufen")

    echt_find = verwalten.kal.find_patient_appointments
    echt_chat, echt_stream = llm.chat, llm.chat_stream
    echt_anstossen = verwalten.hintergrund.anstossen
    alt = os.environ.get("HIRN_AUTO_RESUME")
    os.environ["HIRN_AUTO_RESUME"] = "enforce"
    verwalten.kal.find_patient_appointments = lambda t, c: dict(DONNERSTAG)
    llm.chat = _knall
    llm.chat_stream = _knall
    verwalten.hintergrund.anstossen = lambda sit: None
    try:
        sit = _mitten_in_buchung()
        aus = agent.user_turn(sit, "Habe ich noch einen anderen Termin diese Woche?")
        # Bianca sieht den bestehenden Donnerstag-Termin und sagt ihn an.
        assert "halb zwölf" in aus["text"], aus
        # und kehrt danach zur Buchung zurueck (Auto-Resume).
        assert "zurück zu Ihrem Termin" in aus["text"], aus
    finally:
        verwalten.kal.find_patient_appointments = echt_find
        llm.chat = echt_chat
        llm.chat_stream = echt_stream
        verwalten.hintergrund.anstossen = echt_anstossen
        if alt is None:
            os.environ.pop("HIRN_AUTO_RESUME", None)
        else:
            os.environ["HIRN_AUTO_RESUME"] = alt
