"""W-HIRN-GATE: keine Frage zu einem Wert, der schon im Session-Hirn steht.

Chef 13.09.2026 (Anruf 1fbda5db, woertlich): "es darf keine frage gestellt
werden, zu der es bereits einen wert gibt […] jede frage muss erst im session
hirn ueberprueft werden bevor bianca sie stellt, ob antworten vorhanden sind."

Fuer die Maschine gilt das durch Bauart: ``gehirn.naechste_frage`` ist eine
if-Kette, in der jeder Zweig genau das Feld prueft, nach dem er fragt. Genau
das haelt dieser Test fest — Feld fuer Feld, damit eine kuenftige Frage ohne
Waechter hier auffliegt und nicht erst im Feldtest.

Die Doppelfragen des Live-Anrufs kamen von den beiden ANDEREN Wegen:
- das MODELL fragte (Zahnreinigung in Zug 8) -> `kern/frage_gate.py`,
- ein Einwand LOESCHTE einen feststehenden Wert (Vorname) -> W-NAME-EINWAND-2.
Beide haben ihre eigenen Regressionen (`test_frage_gate`, `test_anruf_rateike`).
"""

from bianca import gehirn


def _sit(**felder):
    sit = {"tenant": {
        "praxisName": "Testpraxis",
        "calendars": [{"id": "c1", "name": "Doktor Michael Petsas"},
                      {"id": "c2", "name": "Doktor Theodosios Patrikis"}],
        "defaultCalendarId": "c1",
    }}
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", **felder})
    return sit, s


# Vollstaendig ausgefuellter Bestandsfall: nichts ist mehr offen.
def _voll(**mehr):
    felder = {
        "warSchonMal": True,
        "arzt": {"typ": "genannt", "calendarId": "c1",
                 "calendarName": "Doktor Michael Petsas"},
        "nachname": "Rateike", "buchstabiert": True,
        "vorname": "Stefan", "vornameQuelle": "gesagt",
        "grund": "Kontrolle", "motivId": "kontrolle",
        "motivName": "KCH Kontrolle",
        "wunsch": {}, "wunschText": "morgen",
        "telefon": "01776004600", "telefonOk": True,
        "versicherung": "gesetzlich", "versicherungOk": True,
        "pzr": "nein", "bleaching": "nein", "rueckblick": "fertig",
    }
    felder.update(mehr)
    return _sit(**felder)


def test_voller_datensatz_laesst_keine_pflichtfrage_offen():
    sit, _ = _voll()
    fid, frage = gehirn.naechste_frage(sit)
    assert fid == "", f"fragt {fid!r}: {frage!r}"


# (Feld im Sammler, fid der Frage) — jeder Eintrag ist eine eigene Wache:
# ist der Wert da, darf GENAU diese Frage nicht mehr kommen.
_PAARE = [
    ("warSchonMal", "schonmal"),
    ("arzt", "arzt"),
    ("nachname", "nachname"),
    ("vorname", "vorname"),
    ("grund", "grund"),
    ("wunsch", "wunsch"),
    ("telefonOk", "telefon"),
    ("versicherung", "versicherung"),
    ("pzr", "pzr"),
]


def test_kein_feld_wird_doppelt_gefragt():
    """Jedes belegte Feld: die zugehoerige Frage kommt nie."""
    for feld, fid_verboten in _PAARE:
        sit, _ = _voll()
        fid, frage = gehirn.naechste_frage(sit)
        assert fid != fid_verboten, f"{feld} steht, fragt aber {fid!r}: {frage!r}"


def test_fehlendes_feld_wird_sehr_wohl_gefragt():
    """Gegenprobe — der Waechter darf nicht einfach alles verschlucken."""
    for feld, leer, fid_erwartet in [
        ("warSchonMal", None, "schonmal"),
        ("grund", "", "grund"),
        ("wunsch", None, "wunsch"),
    ]:
        sit, s = _voll()
        s[feld] = leer
        fid, _frage = gehirn.naechste_frage(sit)
        assert fid == fid_erwartet, f"{feld} fehlt, fragt aber {fid!r}"


# --- Kartei-Wert wird bestaetigt, nicht gefragt (Chef-Beispiel) -----------

def test_kartei_vorname_wird_bestaetigt_statt_gefragt():
    sit, s = _voll(vorname="Maximilian", vornameQuelle="akte", vornameCheck="",
                   bekannt=True, patientId="p1")
    fid, frage = gehirn.naechste_frage(sit)
    assert fid == "vorname_check"
    assert "Maximilian" in frage and frage.rstrip().endswith("richtig?")
    # Ja: der Wert bleibt und wird nie wieder angesprochen.
    s["frage"] = "vorname_check"
    gehirn.einsammeln(sit, "Ja, genau.")
    assert (s["vorname"], s["vornameCheck"]) == ("Maximilian", "ja")
    assert gehirn.naechste_frage(sit)[0] == ""


def test_nein_auf_die_kartei_bestaetigung_raeumt_nur_den_vornamen():
    sit, s = _voll(vorname="Maximilian", vornameQuelle="akte",
                   bekannt=True, patientId="p1", frage="vorname_check")
    gehirn.einsammeln(sit, "Nein, das ist falsch.")
    assert s["vorname"] == ""
    # Alles andere bleibt stehen — das war die Live-Katastrophe.
    assert s["nachname"] == "Rateike"
    assert s["telefonOk"] is True
    assert s["grund"] == "Kontrolle"
    assert gehirn.naechste_frage(sit)[0] == "vorname"


def test_gesagter_vorname_wird_nicht_rueckgefragt():
    # Nur KARTEI-Werte werden bestaetigt. Wer seinen Vornamen selbst genannt
    # hat, wird nicht behelligt (sonst ein Zug mehr in jedem Anruf).
    sit, s = _voll()
    s["frage"] = "vorname"
    s["vorname"] = ""
    gehirn.einsammeln(sit, "Stefan.")
    assert s["vorname"] == "Stefan"
    assert s["vornameQuelle"] == "gesagt"
    assert gehirn.naechste_frage(sit)[0] == ""


def test_erkannter_anrufer_bestaetigt_den_namen_nur_einmal():
    # Die Identitaetsfrage ("Habe ich Sie richtig erkannt?") deckt den Namen
    # schon ab — danach darf keine zweite Vornamen-Rueckfrage kommen.
    sit, s = _voll(vorname="", nachname="", warSchonMal=None, buchstabiert=False)
    sit["anrufer"] = {"vorname": "Maximilian", "nachname": "Rateike",
                      "patientId": "p1", "telefon": "+491776004600"}
    s["frage"] = "anrufer_check"
    gehirn.einsammeln(sit, "Ja, richtig.")
    assert s["vorname"] == "Maximilian"
    assert s["vornameCheck"] == "ja"
    fid, _ = gehirn.naechste_frage(sit)
    assert fid != "vorname_check"


def test_stille_schwelle_und_wortformen_sind_registriert():
    # Ja/Nein-Frage: 350 ms Ruhe reichen als Zugende, und der
    # Wiederholungs-Waechter kennt Ersatzformen (sonst wird die Frage
    # gestrichen statt umformuliert).
    assert gehirn.stille_ms({"frage": "vorname_check"}) == 350
    assert gehirn.FRAGE_VARIANTEN.get("vorname_check")
