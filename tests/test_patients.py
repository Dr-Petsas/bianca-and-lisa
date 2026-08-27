from lisa.patients import handy_e164, handy_ok, ist_dev_handy, ist_testname


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
