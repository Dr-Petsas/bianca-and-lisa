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


def test_suche_eindeutig_verwirft_fremden_namen_live_0219():
    """Live 29.08.2026 02:19: 'Peter Muller' traf als EINZIGER Suchtreffer
    'Petra Müller' — der Ein-Treffer-Kurzschluss haette Termin und
    Bestaetigungs-SMS auf die falsche Akte gelegt. Ein Treffer zaehlt nur
    noch mit passendem Namen (umlaut-tolerant)."""
    from kern import patients as patmod
    echt = patmod.search_patients
    patmod.search_patients = lambda tenant, q: {"ok": True, "patients": [
        {"id": "6cMY", "firstName": "Petra", "lastName": "Müller",
         "mobilePhoneNumber": "+4915223361764"},
    ]}
    try:
        assert patmod._suche_eindeutig({}, "Peter", "Muller") is None
        assert patmod._suche_eindeutig({}, "Petra", "Muller")["id"] == "6cMY"
        assert patmod._suche_eindeutig({}, "Petra", "Mueller")["id"] == "6cMY"
    finally:
        patmod.search_patients = echt


def test_aufloesen_bindet_umlaut_akte_trotz_buchstabierter_form():
    """Buchstabiert 'M U L L E R' -> die echte 'Müller'-Akte muss weiter
    binden (Vorname stimmt); 'Petra' zur 'Peter'-Akte bleibt verworfen."""
    from kern import patients as patmod
    echt = patmod.search_patients
    patmod.search_patients = lambda tenant, q: {"ok": True, "patients": [
        {"id": "Uz5O", "firstName": "Peter", "lastName": "Müller",
         "mobilePhoneNumber": "0123456789"},
    ]}
    try:
        auf = patmod.patient_aufloesen({}, {
            "firstName": "Peter", "lastName": "Muller", "name": "Peter Muller",
        })
        assert auf.get("id") == "Uz5O"
        auf2 = patmod.patient_aufloesen({}, {
            "firstName": "Petra", "lastName": "Muller", "name": "Petra Muller",
        })
        assert not auf2.get("id")
    finally:
        patmod.search_patients = echt


def test_name_norm_umlaut_varianten():
    from kern.patients import _name_norm
    assert _name_norm("Müller") == _name_norm("Mueller") == _name_norm("Muller")
    assert _name_norm("Süß") == _name_norm("Suess")
    assert _name_norm("Peter") != _name_norm("Petra")
