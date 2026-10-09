"""W-ZWEI-MERKMALE: das reine Merkmale-Modul. Die Gegenproben (ein Merkmal
reicht NIE, nur der Nachname ist kein starker Name) sind der teurere Teil."""

from kern import identitaet_merkmale as im


def _sit(**sammler):
    return {"sammler": dict(sammler), "anrufer": {}, "verwHinweis": {}}


def test_aktiv_default_an_notaus_aus(monkeypatch):
    monkeypatch.delenv("ZWEI_MERKMALE", raising=False)
    assert im.aktiv() is True
    monkeypatch.setenv("ZWEI_MERKMALE", "0")
    assert im.aktiv() is False


def test_reicht_erst_ab_zwei():
    assert im.reicht(set()) is False
    assert im.reicht({"name"}) is False
    assert im.reicht({"name", "zeit"}) is True
    assert im.reicht({"telefon", "geburtsdatum", "name"}) is True


def test_nur_nachname_ist_nie_starker_name():
    assert im.starker_name("", "Berger", "Peter", "Berger") is False
    assert im.starker_name("", "Berger", "", "Berger") is False


def test_voller_name_ab_85_ist_stark():
    assert im.starker_name("Peter", "Berger", "Peter", "Berger") is True
    # Vertipper im Nachnamen, voller Name noch klar
    assert im.starker_name("Peter", "Paesler", "Peter", "Paesla") is True


def test_gleicher_nachname_plus_vorname_ab_80():
    assert im.starker_name("Thomas", "Müller", "Tomas", "Müller") is True
    # gleicher Nachname, voellig anderer Vorname -> nicht stark (Familie)
    assert im.starker_name("Larissa", "Hauck", "Meryem", "Hauck") is False


def test_ein_merkmal_name_reicht_nie():
    sit = _sit(nachname="Berger", vorname="Peter")
    k = {"patientFirstName": "Peter", "patientLastName": "Berger",
         "iso": "2026-11-03T14:00+01:00"}
    m = im.merkmale(sit, k)
    assert m == {"name"}
    assert im.reicht(m) is False


def test_name_plus_genannter_tag_sind_zwei():
    sit = _sit(nachname="Berger", vorname="Peter")
    sit["verwHinweis"] = {"date": "2026-11-03"}
    k = {"patientFirstName": "Peter", "patientLastName": "Berger",
         "iso": "2026-11-03T14:00+01:00", "date": "2026-11-03"}
    m = im.merkmale(sit, k)
    assert m == {"name", "zeit"}
    assert im.reicht(m) is True


def test_genannter_tag_passt_nicht_kein_zeitmerkmal():
    sit = _sit(nachname="Berger", vorname="Peter")
    sit["verwHinweis"] = {"date": "2026-10-13"}
    k = {"patientFirstName": "Peter", "patientLastName": "Berger",
         "iso": "2026-11-03T14:00+01:00", "date": "2026-11-03"}
    m = im.merkmale(sit, k)
    assert "zeit" not in m
    assert m == {"name"}


def test_bestaetigte_nummer_nur_bei_identitaet():
    # anruferCheck ja -> Akten-Nummer gilt
    sit = _sit(anruferCheck="ja", aktePhone="+491701234567")
    assert im.bestaetigte_nummer(sit) == "1701234567"
    # unbestaetigt -> keine
    sit2 = _sit(aktePhone="+491701234567")
    assert im.bestaetigte_nummer(sit2) == ""
    # Drittperson -> nie
    sit3 = _sit(anruferCheck="ja", fuerWen="andere", aktePhone="+491701234567")
    assert im.bestaetigte_nummer(sit3) == ""


def test_telefon_plus_geburtsdatum_sind_zwei():
    sit = _sit(anruferCheck="ja", aktePhone="+491701234567",
               geburtsdatum="1980-05-04")
    k = {"patientPhone": "+491701234567", "patientBirthDate": "1980-05-04"}
    m = im.merkmale(sit, k)
    assert m == {"telefon", "geburtsdatum"}
    assert im.reicht(m) is True


def test_nur_telefon_reicht_nie():
    sit = _sit(anruferCheck="ja", aktePhone="+491701234567")
    k = {"patientPhone": "+491701234567", "patientFirstName": "Anna",
         "patientLastName": "Meier"}
    m = im.merkmale(sit, k)
    assert m == {"telefon"}
    assert im.reicht(m) is False
