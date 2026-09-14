"""W-BESTAND-ANSAGE (14.09.2026): Anruf 9dd61a59 (Thaler, Ingrid Hösl).

Live: "Ich habe meinen Termin vergessen … Oktober eventuell? Habe ich da
einen Termin?" — die Bestandsfrage wurde nicht als solche erkannt, das Modell
uebernahm. Nach dem Vorlesen ("Ihr nächster Termin: 21. Dezember …") stellte
die Maschine KEINE Folgefrage (frage=""), das "Bis alles gut, alles gut." des
Anrufers lief ans Modell, und die Fakten-Wache strich das richtige "Im Oktober
haben Sie keinen Termin" (die Suche HATTE einen Termin gefunden — nur nicht im
Oktober). Der Anruf endete mit drei Modell-Zuegen statt eines Satzes.

Regeln seitdem:
- Bestandsfrage: "Termin vergessen", "Habe ich da einen Termin?" (Intent UND
  Regex-Rueckfall) — nie "vergessen, einen Termin zu MACHEN".
- Ansage nennt den Besuchsgrund und schliesst mit der Frage "Passt der so,
  oder verschieben/absagen?" (frage=termin_ok) — es sei denn, ein geparktes
  Anliegen springt zurueck (dann fragt DAS).
- "alles gut"/"passt"/"in Ordnung" (auch mit wiederholtem Datum) = Zustimmung,
  Nein = "verschieben oder absagen?", verschieben/absagen = Strecke,
  "Wiederhören" = Schluss — alles deterministisch, ohne Modell.
- Fakten-Wache: eine Zeitraum-Verneinung ist WAHR, wenn kein gefundener
  Termin im genannten Zeitraum liegt; ihr "keinen Termin" ist kein Slot-Claim.

Laeuft ohne Netz: LLM darf NIE laufen, Kalender-Suche gestummt.
"""

import json
import os

import pytest

from bianca import agent, flow, gehirn, verwalten
from kern import fakten_wache, hirn, intent
from kern.tenants import laden


DEZ = {
    "ok": True,
    "patient": {"id": "pat-h", "firstName": "Ingrid", "lastName": "Hösl"},
    "appointments": [{
        "id": "apt-dez", "iso": "2026-12-21T10:00", "date": "2026-12-21",
        "calendarId": "cal-fs", "doctorName": "Franziska Schmidt",
        "motivId": "vm-pzr",
        "motivName": "Professionelle Zahnreinigung (PZR) + Vorsorge",
        "spoken": "am Montag, den einundzwanzigsten Dezember um zehn Uhr bei Franziska Schmidt",
    }],
}


def _sit() -> dict:
    sit = {"tenant": laden("meddent"),
           "messages": [{"role": "system", "content": "x"}],
           "stimme": "bianca"}
    hirn.init(sit)
    sit["anrufer"] = {"vorname": "Ingrid", "nachname": "Hösl",
                      "patientId": "pat-h", "geschlecht": "female",
                      "telefon": "+491701234567"}
    return sit


@pytest.fixture
def ohne_netz(monkeypatch):
    """LLM = Testbruch, Kalender = Dezember-Termin, Hintergrund stumm."""
    from kern import llm

    def _knall(*a, **k):
        raise AssertionError("LLM darf hier nicht laufen")

    monkeypatch.setattr(llm, "chat", _knall)
    monkeypatch.setattr(llm, "chat_stream", _knall)
    monkeypatch.setattr(flow.hintergrund, "anstossen", lambda sit: None)
    monkeypatch.setattr(verwalten.hintergrund, "anstossen", lambda sit: None)
    monkeypatch.setattr(verwalten.kal, "find_patient_appointments",
                        lambda t, c: json.loads(json.dumps(DEZ)))
    monkeypatch.setenv("HIRN_AUTO_RESUME", "enforce")
    yield


def _zug(sit: dict, satz: str) -> dict:
    aus = agent.user_turn(sit, satz)
    assert aus is not None, satz
    return aus


# --- 1) Bestandsfrage erkennen: Intent UND Regex-Rueckfall -----------------

LIVE_BESTAND = [
    "Ich habe meinen Termin vergessen, jetzt würde.",
    "aber ich habe ihn vergessen. Oktober eventuell? Habe ich da einen Termin?",
    "Habe ich da einen Termin?",
    "Ich habe den Termin verschwitzt.",
    "Habe ich bei Ihnen einen Termin?",
]
KEIN_BESTAND = [
    "Ich habe vergessen, einen Termin zu machen.",
    "Ich hätte gern einen Termin.",
    "Ich brauche einen Termin im Oktober.",
    "Nicht vergessen: die Zahnreinigung bitte mit.",
]


def test_bestandsfrage_regex_kennt_vergessen_und_da():
    for satz in LIVE_BESTAND:
        assert intent._BESTANDSFRAGE_RE.search(satz), satz
        assert gehirn._AUSKUNFT_RE.search(satz), satz


def test_bestandsfrage_regex_verschont_neubuchung():
    for satz in KEIN_BESTAND:
        assert not intent._BESTANDSFRAGE_RE.search(satz), satz
        assert not gehirn._AUSKUNFT_RE.search(satz), satz


def test_intent_deutet_vergessenen_termin_als_auskunft():
    for satz in LIVE_BESTAND[:3]:
        sit = _sit()
        d = intent.erkennen(sit, satz)
        assert d["handlung"] == "WISSEN", (satz, d)
        assert d["gegenstand"] == "VORGANG", (satz, d)


# --- 2) Zustimmung erkennen: "alles gut" mit Fuellwoertern/Datum -------------

def test_ist_passt_live_saetze():
    termine = DEZ["appointments"]
    for satz in ["Bis alles gut, alles gut.",
                 "Alles gut, es ist in Ordnung, 21. Dezember.",
                 "Ja, passt so, danke.",
                 "Alles gut.",
                 "Der bleibt so."]:
        assert verwalten._ist_passt(satz, termine), satz


def test_ist_passt_nicht_bei_sachinhalt():
    termine = DEZ["appointments"]
    for satz in ["Alles gut, und im November?",
                 "Alles gut, aber ich möchte ihn verschieben.",
                 "Alles gut, 3. Januar.",       # anderes Datum als der Termin
                 "Passt, und meine Nummer hat sich geändert.",
                 "Nein."]:
        assert not verwalten._ist_passt(satz, termine), satz


# --- 3) Ansage: Besuchsgrund + Folgefrage, Oktober-Vorsatz ------------------

def test_ansage_nennt_grund_und_stellt_folgefrage(ohne_netz):
    sit = _sit()
    _zug(sit, "Ich habe meinen Termin vergessen, jetzt würde.")
    s = gehirn.sammler(sit)
    assert s["modus"] == "auskunft" and s["frage"] == "anrufer_check"
    aus = _zug(sit, "Ja.")
    assert "einundzwanzigsten Dezember" in aus["text"]
    assert "Zahnreinigung" in aus["text"]
    assert "(PZR)" not in aus["text"]          # Kuerzel nicht vorlesen
    assert "Passt der so" in aus["text"]
    assert s["frage"] == "termin_ok"


def test_ansage_oktober_ehrlich_mit_naechstem_termin(ohne_netz):
    sit = _sit()
    _zug(sit, "Oktober eventuell? Habe ich da einen Termin?")
    aus = _zug(sit, "Ja.")
    assert aus["text"].startswith("Im Oktober sehe ich keinen Termin für Sie")
    assert "einundzwanzigsten Dezember" in aus["text"]
    s = gehirn.sammler(sit)
    assert s["wunsch"] is None, "Oktober ist Bestands-Hinweis, kein Neubuchungs-Wunsch"
    assert s["frage"] == "termin_ok"


# --- 4) Der Live-Anruf, Zug fuer Zug, ohne Modell ----------------------------

def test_live_anruf_9dd61a59_laeuft_deterministisch(ohne_netz):
    sit = _sit()
    _zug(sit, "Ich habe meinen Termin vergessen, jetzt würde.")
    _zug(sit, "Ja.")
    s = gehirn.sammler(sit)

    aus = _zug(sit, "Bis alles gut, alles gut.")
    assert "bleibt es dabei" in aus["text"]
    assert s["frage"] == "sonst_noch"

    aus = _zug(sit, "Alles gut, es ist in Ordnung, 21. Dezember.")
    assert aus.get("hangup") is True
    assert "Wiederhören" in aus["text"]
    assert s["wunsch"] is None, "das wiederholte Datum darf kein Wunsch werden"


def test_wiederhoeren_auf_passt_frage_legt_auf(ohne_netz):
    sit = _sit()
    _zug(sit, "Habe ich da einen Termin?")
    _zug(sit, "Ja.")
    aus = _zug(sit, "Alles gut, Dankeschön, Wiederhören.")
    assert aus.get("hangup") is True


def test_nein_danke_heisst_nichts_aendern(ohne_netz):
    sit = _sit()
    _zug(sit, "Habe ich da einen Termin?")
    _zug(sit, "Ja.")
    s = gehirn.sammler(sit)
    aus = _zug(sit, "Nein danke.")
    assert "bleibt bestehen" in aus["text"]
    assert s["frage"] == "sonst_noch"
    aus = _zug(sit, "Nein, das war's.")
    assert aus.get("hangup") is True


def test_nein_fuehrt_zu_verschieben_oder_absagen(ohne_netz):
    sit = _sit()
    _zug(sit, "Habe ich da einen Termin?")
    _zug(sit, "Ja.")
    s = gehirn.sammler(sit)
    aus = _zug(sit, "Nein.")
    assert "verschieben oder absagen" in aus["text"]
    assert s["frage"] == "termin_aendern"
    _zug(sit, "Absagen bitte.")
    assert s["modus"] == "absagen"


def test_verschieben_wechselt_in_die_strecke(ohne_netz):
    sit = _sit()
    _zug(sit, "Habe ich da einen Termin?")
    _zug(sit, "Ja.")
    aus = _zug(sit, "Den möchte ich verschieben.")
    s = gehirn.sammler(sit)
    assert s["modus"] == "verschieben"
    assert "einundzwanzigsten Dezember" in aus["text"]
    assert "?" in aus["text"]                  # fragt den Neu-Wunsch


def test_nachfrage_anderer_monat_bleibt_bestand(ohne_netz):
    sit = _sit()
    _zug(sit, "Habe ich da einen Termin?")
    _zug(sit, "Ja.")
    s = gehirn.sammler(sit)
    aus = _zug(sit, "Und im November?")
    assert aus["text"].startswith("Im November sehe ich keinen Termin")
    assert s["wunsch"] is None
    aus = _zug(sit, "Und im Dezember?")
    assert aus["text"].startswith("Im Dezember sehe ich einen Termin")
    assert s["frage"] == "termin_ok"


# --- 5) Anker/Wiederholungs-Waechter kennen die neuen Fragen ----------------

def test_folgefragen_haben_kanon_und_kern():
    sit = _sit()
    for fid in ("termin_ok", "termin_aendern", "sonst_noch"):
        frage = agent._kanonische_frage(sit, fid)
        assert frage, fid
        assert __import__("re").search(agent._FRAGE_KERN[fid], frage, __import__("re").I), (fid, frage)
        assert fid in intent._FORMULAR_FRAGEN
        assert fid in gehirn._STILLE_KURZ


# --- 6) Geparkte Buchung: KEINE eigene Folgefrage, Ruecksprung fragt --------

def test_ansage_mit_geparkter_buchung_stellt_keine_eigene_frage(ohne_netz):
    sit = _sit()
    hirn.anliegen_hinzufuegen(
        sit, hirn._anliegen("ANLEGEN", "VORGANG", spiegel="Termin morgen"),
        aktivieren=True,
    )
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen", "phase": "angebot", "frage": "slotwahl",
        "vorname": "Ingrid", "nachname": "Hösl", "patientId": "pat-h",
        "anruferCheck": True, "warSchonMal": True, "bekannt": True,
        "buchstabiert": True, "grund": "Kontrolle",
    })
    sit["offered"] = [{"iso": "2026-09-16T09:00", "spoken": "Mittwoch um neun Uhr"}]
    aus = _zug(sit, "Habe ich da eigentlich einen Termin?")
    assert "einundzwanzigsten Dezember" in aus["text"]
    assert "Passt der so" not in aus["text"], "zwei Fragen hintereinander = Monolog"
    assert "zurück zu Ihrem Termin" in aus["text"]


# --- 7) Fakten-Wache: Zeitraum-Verneinung ist belegt --------------------------

def _sit_wache() -> dict:
    return {"tools": [{"name": "agentFindPatientAppointments", "ok": True,
                       "resultCount": 1}],
            "gefunden": DEZ["appointments"]}


def test_fakten_wache_laesst_belegte_zeitraum_verneinung_durch():
    sit = _sit_wache()
    for txt in ["Im Oktober haben Sie keinen Termin. Ihr nächster Termin ist am 21. Dezember.",
                "Im Oktober sehe ich keinen Termin für Sie.",
                "Am Dienstag haben Sie keinen Termin."]:
        assert fakten_wache.unbelegte_behauptung(sit, txt) == "", txt


def test_fakten_wache_streicht_falsche_verneinung_weiter():
    sit = _sit_wache()
    for txt in ["Sie haben keinen Termin.",
                "Im Dezember haben Sie keinen Termin.",
                "Am Montag haben Sie keinen Termin."]:   # 21.12.2026 ist ein Montag
        assert fakten_wache.unbelegte_behauptung(sit, txt) == "bestand", txt


def test_fakten_wache_ohne_suche_bleibt_streng():
    sit = {"tools": [], "gefunden": []}
    assert fakten_wache.unbelegte_behauptung(
        sit, "Im Oktober haben Sie keinen Termin.") in {"bestand", "slots"}
