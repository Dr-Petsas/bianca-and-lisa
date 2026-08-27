from lisa.greeting import anrede, begruessung, erste_botschaft, vorstellung

FRAU = {"firstName": "Anna", "lastName": "Möllenberg", "name": "Anna Möllenberg", "gender": "f"}
HERR = {"firstName": "Jens", "lastName": "Petsas", "name": "Jens Petsas", "gender": "m"}
OHNE = {"firstName": "Kim", "lastName": "Berger", "name": "Kim Berger", "gender": ""}


def test_anrede_nach_geschlecht():
    assert anrede(FRAU) == "Frau Möllenberg"
    assert anrede(HERR) == "Herr Petsas"


def test_anrede_raet_nicht():
    # Ohne Geschlecht lieber der ganze Name als eine falsche Anrede.
    assert anrede(OHNE) == "Kim Berger"
    assert anrede(None) == ""


def test_vorstellung_mit_behandler():
    v = vorstellung("med dent Zahnklinik", "Dr. Petsas")
    assert v == "hier ist Lisa von der med dent Zahnklinik, ich rufe im Auftrag von Dr. Petsas an"


def test_vorstellung_ohne_behandler():
    v = vorstellung("med dent Zahnklinik", "")
    assert "im Auftrag" not in v
    assert v == "hier ist Lisa von der med dent Zahnklinik"


def test_termin_begruessung_nennt_namen_und_behandler():
    t = begruessung(
        "med dent Zahnklinik",
        "Kontrolltermin vorverlegen — nächste Woche ist ein Platz frei.",
        patient=FRAU,
        behandler="Dr. Petsas",
    )
    assert t.startswith("Guten Tag, Frau Möllenberg, hier ist Lisa von der med dent Zahnklinik")
    assert "im Auftrag von Dr. Petsas" in t
    assert "vormittags oder nachmittags" in t
    # Der Auftrag darf nicht woertlich vorgelesen werden:
    assert "nächste Woche" not in t


def test_begruessung_ohne_patient_bleibt_hoeflich():
    t = begruessung("Demo-Praxis", "Termin bestätigen", behandler="")
    assert t.startswith("Guten Tag, hier ist Lisa von der Demo-Praxis.")


def test_kurze_botschaft():
    assert erste_botschaft("Bitte die Rechnung nochmal schicken. Danke.") == "Bitte die Rechnung nochmal schicken."
