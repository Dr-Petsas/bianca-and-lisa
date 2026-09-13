"""W-EINGEHEN: kein Zug, der nur aus einer nackten Frage besteht.

Chef 13.09.2026 (woertlich): "genau dafuer brauchen wir, dass auf das gesagte
eingegangen wird […] weil dann wuerde es endlich ein Gespraech!!! und kein
Monolog. […] es gibt keinen Waechter, der pro Zug erzwingt, dass die Antwort
erkennbar auf den letzten Satz eingeht. Das muss deshalb angepasst werden ….
nur so entsteht KONVERSATION."

Die Gegenproben wiegen hier schwerer als der Eingriff: ein DOPPELTER Bezug
("Verstehe. Alles klar. …") klingt schlimmer als keiner, und vor eine Frage
des ANRUFERS darf nie ein "Verstehe." gesetzt werden — das waere eine
Scheinantwort.
"""

from kern import eingehen


# --- Wann ist eine Antwort eine nackte Frage? ------------------------------

def test_nackte_frage_erkannt():
    for text in ("Und der Vorname?",
                 "Waren Sie schon einmal bei uns?",
                 "Wie ist Ihr Nachname? Und der Vorname?"):
        assert eingehen.nur_frage(text) is True, text


def test_antwort_mit_aussagesatz_geht_schon_ein():
    for text in ("Danke. Und der Vorname?",
                 "Dann halte ich fest: morgen um neun. Soll ich das eintragen?",
                 "Ich wiederhole die Nummer. 0 1 7 7. Stimmt das so?",
                 "Alles klar, dann ohne Zahnreinigung."):
        assert eingehen.nur_frage(text) is False, text


# --- Wann muss ueberhaupt eingegangen werden? ------------------------------

def test_fueller_brauchen_keinen_bezug():
    for satz in ("Ja.", "Nein", "Hm.", "ok", "Genau.", "Ja, gut.", ""):
        assert eingehen.substanziell(satz) is False, satz


def test_inhalt_braucht_bezug():
    for satz in ("Meine Frau ist krank geworden.", "Kontrolle.",
                 "Ich bin gerade im Auto.", "0177 6004600"):
        assert eingehen.substanziell(satz) is True, satz


def test_nackte_frage_nach_inhalt_ist_der_fall():
    assert eingehen.pruefen("Ich bin gerade im Auto.", "Und der Vorname?") == "nackte-frage"


def test_bereits_vorhandener_bezug_bleibt_unangetastet():
    for text in ("Gerne, wann passt es Ihnen?",
                 "Alles klar. Und der Vorname?",
                 "Entschuldigung, wie war der Nachname?",
                 "Verstehe. Wann passt es Ihnen?"):
        assert eingehen.pruefen("Mein Auto ist kaputt.", text) == "", text


def test_presence_stups_bekommt_keinen_bezug():
    assert eingehen.pruefen("Mein Auto ist kaputt.", "Sind Sie noch dran?") == ""


def test_frage_des_anrufers_wird_nur_protokolliert():
    # Ein "Verstehe." davor wuerde eine Antwort vortaeuschen, die nicht kommt.
    assert eingehen.pruefen("Was kostet das denn?", "Und der Vorname?") == "frage-offen"
    sit: dict = {}
    text, grund = eingehen.anwenden(sit, "Was kostet das denn?", "Und der Vorname?")
    assert (text, grund) == ("Und der Vorname?", "eingehen-frage-offen")


# --- Wirkung ---------------------------------------------------------------

def test_bezug_wird_vorangestellt_und_rotiert():
    sit: dict = {}
    erste, grund = eingehen.anwenden(sit, "Ich bin gerade im Auto.", "Und der Vorname?")
    assert grund == "eingehen"
    assert erste.endswith("Und der Vorname?") and erste != "Und der Vorname?"
    zweite, _ = eingehen.anwenden(sit, "Ich bin gerade im Auto.", "Und der Vorname?")
    assert zweite != erste, "derselbe Bezug zweimal in Folge wird zur Masche"


def test_wunsch_bekommt_gerne():
    sit: dict = {}
    text, _ = eingehen.anwenden(
        sit, "Ich möchte einen Termin.", "Waren Sie schon einmal bei uns?")
    assert text.startswith("Gerne."), text


def test_beschwerde_bekommt_mitgefuehl():
    sit: dict = {}
    text, _ = eingehen.anwenden(
        sit, "Ich habe zwei Stunden gewartet.", "Und der Vorname?",
        art="beschwerde")
    assert "leid" in text.lower(), text


def test_notaus_off(monkeypatch):
    monkeypatch.setenv("EINGEHEN", "0")
    sit: dict = {}
    assert eingehen.anwenden(sit, "Mein Auto ist kaputt.", "Und der Vorname?") == (
        "Und der Vorname?", "")


def test_shadow_meldet_aber_aendert_nichts(monkeypatch):
    monkeypatch.setenv("EINGEHEN", "shadow")
    sit: dict = {}
    text, grund = eingehen.anwenden(sit, "Mein Auto ist kaputt.", "Und der Vorname?")
    assert (text, grund) == ("Und der Vorname?", "eingehen-shadow")


# --- Einbau in den Maschinen-Zug ------------------------------------------

def test_maschinen_zug_geht_ein(monkeypatch):
    from bianca import agent, gehirn
    from kern import gedaechtnis
    monkeypatch.setattr(gedaechtnis, "kontext_anstossen", lambda sit: None)
    sit = {"tenant": {"praxisName": "Testpraxis"}}
    gehirn.sammler(sit)["modus"] = "buchen"
    msgs = [{"role": "system", "content": "x"},
            {"role": "user", "content": "Ich bin gerade unterwegs im Auto."}]
    aus = agent._maschinen_antwort(sit, {"text": "Und der Vorname?"}, msgs)
    assert aus["text"].endswith("Und der Vorname?")
    assert aus["text"] != "Und der Vorname?", aus["text"]
    assert any(x.get("w") == "eingehen" for x in sit.get("_spur") or [])
    # Der Bezug steht auch im Verlauf — sonst sieht das Modell ihn nie.
    assert msgs[-1]["role"] == "assistant"
    assert msgs[-1]["content"] == aus["text"]


def test_maschinen_zug_mit_quittung_bleibt_unveraendert(monkeypatch):
    from bianca import agent, gehirn
    from kern import gedaechtnis
    monkeypatch.setattr(gedaechtnis, "kontext_anstossen", lambda sit: None)
    sit = {"tenant": {"praxisName": "Testpraxis"}}
    gehirn.sammler(sit)["modus"] = "buchen"
    msgs = [{"role": "system", "content": "x"},
            {"role": "user", "content": "Stefan Rateike."}]
    aus = agent._maschinen_antwort(
        sit, {"text": "Danke, Stefan Rateike. Welche Handynummer darf ich eintragen?"},
        msgs)
    assert aus["text"].startswith("Danke, Stefan Rateike.")
