"""MedDent 19.09.2026 21:42 (Anruf d6611fca) — "Mir Sicher" darf kein Name sein.

Live gehoert wurde wortgleich: "Ich bin mir nicht sicher, ob ich einen Termin bei
Ihnen habe." Die Namens-Ernte las das als Vorname "Mir" + Nachname "Sicher"
(Geschlecht geraten: weiblich), suchte damit zweimal ins Leere
(``agentFindPatientAppointments`` -> 404) und fragte den Nachnamen ab — obwohl
der Anrufer ueber die Rufnummer laengst als Herr Petsas erkannt war. Gesprochen
wurde deshalb "Danke, Mir Sicher. Unter Mir Sicher finde ich gerade keinen
Termin." und einen Zug spaeter "Danke, Mir Petsas."; der Anrufer legte auf.

Die Gegenproben sind der teurere Teil: ein echter Name muss weiter geerntet
werden, auch wenn er mit "Mir…" beginnt oder "Sicher" heisst.
"""

from bianca import gehirn


def _ernten(satz: str, frage: str = "") -> dict:
    sit: dict = {}
    s = gehirn.sammler(sit)
    s["frage"] = frage
    gehirn.einsammeln(sit, satz)
    return s


def test_bin_mir_nicht_sicher_erntet_keinen_namen():
    sam = _ernten("Ich bin mir nicht sicher, ob ich einen Termin bei Ihnen habe.")
    assert not sam.get("vorname")
    assert not sam.get("nachname")
    # Das Anliegen selbst bleibt erkannt: Frage nach dem BESTEHENDEN Termin.
    assert sam.get("modus") == "auskunft"


def test_bin_mir_sicher_erntet_keinen_namen():
    sam = _ernten("Ich bin mir sicher, ich war letztes Jahr bei Doktor Petsas.")
    assert not sam.get("vorname")
    assert not sam.get("nachname")


def test_sind_uns_erntet_keinen_namen():
    sam = _ernten("Wir sind uns noch nicht begegnet.")
    assert not sam.get("vorname")
    assert not sam.get("nachname")


def test_bin_nicht_sicher_ohne_mir_erntet_keinen_namen():
    sam = _ernten("Ich bin nicht sicher, ob das der richtige Termin war.")
    assert not sam.get("vorname")
    assert not sam.get("nachname")


def test_echter_name_bleibt():
    sam = _ernten("Ich bin Michael Petsas.")
    assert sam.get("vorname") == "Michael"
    assert sam.get("nachname") == "Petsas"


def test_vorname_mit_mir_am_anfang_bleibt():
    # "Mirko" darf nicht am Reflexiv-Muster haengenbleiben.
    sam = _ernten("Ich heisse Mirko Sauer.")
    assert sam.get("vorname") == "Mirko"
    assert sam.get("nachname") == "Sauer"


def test_nachname_sicher_auf_die_namensfrage_bleibt():
    # Der Nachname "Sicher" darf nicht am neuen Muster haengen: das greift nur
    # nach "bin mir" bzw. "bin nicht". (Das nackte "Sicher" ist seit langem ein
    # Ja-Wort und war nie ein Name — hier steht deshalb der volle Name.)
    sam = _ernten("Michael Sicher", frage="nachname")
    assert sam.get("nachname") == "Sicher"
    assert sam.get("vorname") == "Michael"
