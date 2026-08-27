from lisa.patients import (
    handy_e164,
    handy_ok,
    ist_dev_handy,
    ist_testakte,
    ist_testname,
    karten_patient,
    ohne_titel,
)


def test_handy_e164():
    assert handy_e164("0177 6004601") == "+491776004601"
    assert handy_e164("+49 177 6004601") == "+491776004601"
    assert handy_e164("00491776004601") == "+491776004601"
    assert handy_ok("01776004601")
    assert not handy_ok("123")


def test_kein_testname_in_kartei():
    assert ist_testname("Anna", "Test")
    assert ist_testname("", "", "Anna Test")
    assert ist_testname("Max", "Mustermann")
    assert not ist_testname("Levi", "Tzannis")


def test_dev_handy_gesperrt():
    assert ist_dev_handy("01776004600")
    assert ist_dev_handy("+49 177 6004600")
    assert not ist_dev_handy("01776004601")


def test_testakte_erkannt():
    # Der echte Vorfall vom 27.08.2026: CampaignR-Fixture in der Live-Kartei.
    fixture = {"id": "campaignr-test-dr-petsas", "firstName": "Dr.", "lastName": "Petsas"}
    assert ist_testakte(fixture)
    assert karten_patient(fixture)["test"] is True
    # Titel-only Vorname ohne Fixture-ID zaehlt ebenfalls als Testsatz.
    assert ist_testakte({"id": "abc123", "firstName": "Dr.", "lastName": "Meier"})
    # Echte Patienten bleiben echt.
    echt = {"id": "xY9", "firstName": "Levi", "lastName": "Tzannis", "birthDate": "1980-01-01"}
    assert not ist_testakte(echt)
    assert karten_patient(echt)["test"] is False


def test_titel_wird_kein_vorname():
    assert ohne_titel("Dr. Petsas") == "Petsas"
    assert ohne_titel("Prof. Dr. med. Anna Meier") == "Anna Meier"
    assert ohne_titel("Levi Tzannis") == "Levi Tzannis"
