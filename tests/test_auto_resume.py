"""W-HIRN-AUTORESUME (09.09.2026): eingeschobene Anliegen zuverlaessig
fortsetzen. Tasklokale Checkpoints schuetzen Patienten-/Slotzustaende, nach
phase=fertig rueckt LIFO das zuletzt geparkte Anliegen nach. Dreistufiger
Notaus HIRN_AUTO_RESUME=off|shadow|enforce (Default off = Alt-Verhalten).

Offline, kein Netz, kein LLM.
"""

from bianca import agent
from kern import hirn
from kern.tenants import laden


def _sit() -> dict:
    sit = {
        "stimme": "Bianca",
        "tenant": laden("meddent"),
        "messages": [{"role": "system", "content": "x"}],
    }
    hirn.init(sit)
    return sit


def _deutung(handlung: str, gegenstand: str = "VORGANG", *, zug: str = "wechseln",
             ersatz=None, spiegel: str = "") -> dict:
    return {"kanal": "ok", "zug": zug, "handlung": handlung,
            "gegenstand": gegenstand, "fuer": "selbst",
            "ersatz": ersatz, "spiegel": spiegel}


def _buchung_mit_daten(sit: dict) -> None:
    hirn.anwenden(sit, _deutung("ANLEGEN", zug="wechseln", spiegel="Kontrolltermin"))
    s = sit["sammler"]
    s.update({"grund": "Kontrolle", "vorname": "Anna", "nachname": "Berger",
              "frage": "wunsch"})
    sit["offered"] = [{"iso": "2026-09-10T09:00", "spoken": "morgen um neun"}]


# --- off: keine Verhaltensaenderung -----------------------------------------

def test_off_legt_keinen_checkpoint_an(monkeypatch):
    monkeypatch.setenv("HIRN_AUTO_RESUME", "off")
    sit = _sit()
    _buchung_mit_daten(sit)
    hirn.anwenden(sit, _deutung("AENDERN", ersatz=False, spiegel="Termin absagen"))
    geparkt = [a for a in sit["hirn"]["anliegen"] if a["status"] == "geparkt"]
    assert geparkt and "checkpoint" not in geparkt[0]


def test_off_springt_nicht_zurueck(monkeypatch):
    monkeypatch.setenv("HIRN_AUTO_RESUME", "off")
    sit = _sit()
    _buchung_mit_daten(sit)
    hirn.anwenden(sit, _deutung("AENDERN", ersatz=False))
    sit["sammler"]["phase"] = "fertig"
    assert hirn.abschluss_ruecksprung_live(sit) is None


# --- enforce: Checkpoint + LIFO-Ruecksprung ---------------------------------

def test_enforce_checkpoint_schuetzt_geparktes_anliegen(monkeypatch):
    monkeypatch.setenv("HIRN_AUTO_RESUME", "enforce")
    sit = _sit()
    _buchung_mit_daten(sit)
    # Absage schiebt sich dazwischen -> Buchung wird geparkt (mit Checkpoint).
    hirn.anwenden(sit, _deutung("AENDERN", ersatz=False, spiegel="Termin absagen"))
    assert sit["sammler"]["modus"] == "absagen"
    # Die Absage verstellt Grund/Name — das darf die Buchung NICHT verlieren.
    sit["sammler"].update({"grund": "", "vorname": "", "nachname": "",
                           "phase": "fertig"})
    resumed = hirn.abschluss_ruecksprung_live(sit)
    assert resumed and resumed["handlung"] == "ANLEGEN"
    s = sit["sammler"]
    assert s["modus"] == "buchen"
    assert s["grund"] == "Kontrolle" and s["vorname"] == "Anna"
    assert s["frage"] == "wunsch"
    assert sit["offered"] and sit["offered"][0]["iso"] == "2026-09-10T09:00"


def test_enforce_lifo_reaktiviert_zuletzt_geparktes(monkeypatch):
    monkeypatch.setenv("HIRN_AUTO_RESUME", "enforce")
    sit = _sit()
    hirn.anwenden(sit, _deutung("ANLEGEN", spiegel="neuer Termin"))         # a1
    hirn.anwenden(sit, _deutung("AENDERN", ersatz=False, spiegel="absagen")) # a2 (parkt a1)
    hirn.anwenden(sit, _deutung("ERREICHEN", "PERSON", spiegel="Doktor"))    # a3 (parkt a2)
    sit["sammler"]["phase"] = "fertig"
    resumed = hirn.abschluss_ruecksprung_live(sit)
    # LIFO: zuletzt geparkt war a2 (AENDERN), nicht a1.
    assert resumed and resumed["handlung"] == "AENDERN"
    a1 = [a for a in sit["hirn"]["anliegen"] if a["handlung"] == "ANLEGEN"][0]
    assert a1["status"] == "geparkt"


def test_gebucht_wird_nicht_automatisch_fortgesetzt(monkeypatch):
    monkeypatch.setenv("HIRN_AUTO_RESUME", "enforce")
    sit = _sit()
    hirn.anwenden(sit, _deutung("AENDERN", ersatz=False, spiegel="absagen"))  # aktiv
    hirn.anwenden(sit, _deutung("ANLEGEN", spiegel="neuer Termin"))           # parkt absage
    sit["sammler"]["phase"] = "gebucht"  # Buchung sitzt, Maschine fragt selbst
    assert hirn.abschluss_ruecksprung_live(sit) is None
    geparkt = [a for a in sit["hirn"]["anliegen"] if a["status"] == "geparkt"]
    assert geparkt and geparkt[0]["handlung"] == "AENDERN"


# --- shadow: nur beobachten, keine Mutation ---------------------------------

def test_shadow_zeichnet_nur_auf(monkeypatch):
    monkeypatch.setenv("HIRN_AUTO_RESUME", "shadow")
    sit = _sit()
    _buchung_mit_daten(sit)
    hirn.anwenden(sit, _deutung("AENDERN", ersatz=False, spiegel="absagen"))
    sit["sammler"]["phase"] = "fertig"
    ziel = hirn.wuerde_zuruecksprigen(sit)
    assert ziel and ziel["handlung"] == "ANLEGEN"          # WUERDE zurueckspringen
    assert hirn.abschluss_ruecksprung_live(sit) is None    # tut es aber nicht
    assert sit["sammler"]["modus"] == "absagen"            # Zustand unveraendert


# --- Agent: genau eine Rueckkehrbruecke -------------------------------------

def test_agent_haengt_rueckkehrbruecke_einmal_an(monkeypatch):
    monkeypatch.setenv("HIRN_AUTO_RESUME", "enforce")
    sit = _sit()
    _buchung_mit_daten(sit)
    hirn.anwenden(sit, _deutung("AENDERN", ersatz=False, spiegel="absagen"))
    sit["sammler"]["phase"] = "fertig"
    fl = agent._auto_resume_anhaengen(sit, {"text": "Der Termin ist abgesagt.", "book": None})
    assert "zurück zu Ihrem Termin" in fl["text"].lower() \
        or "zurück zu ihrem termin" in fl["text"].lower()
    assert sit["sammler"]["modus"] == "buchen"
    # Zweiter Aufruf springt nicht erneut (Anliegen ist reaktiviert, nicht fertig).
    fl2 = agent._auto_resume_anhaengen(sit, {"text": "Weiter.", "book": None})
    assert fl2["text"] == "Weiter."


def test_agent_kein_ruecksprung_bei_transfer(monkeypatch):
    monkeypatch.setenv("HIRN_AUTO_RESUME", "enforce")
    sit = _sit()
    _buchung_mit_daten(sit)
    hirn.anwenden(sit, _deutung("AENDERN", ersatz=False, spiegel="absagen"))
    sit["sammler"]["phase"] = "fertig"
    fl = {"text": "", "transfer": {"nummer": "+49211302", "name": "Petsas"}}
    aus = agent._auto_resume_anhaengen(sit, fl)
    assert aus is fl  # unveraendert, kein Bruecken-Anhang mitten im Transfer
