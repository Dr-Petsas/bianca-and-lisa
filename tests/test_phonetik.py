"""Kölner Phonetik: Meier/Mayer/Maier und eindeutige Stamm-Treffer."""

from kern.phonetik import gleiche_phonetik, koelner, phonetik_treffer, such_varianten


def test_meier_varianten_gleich():
    assert koelner("Meier") == koelner("Mayer") == koelner("Maier") == koelner("Meyer")
    assert gleiche_phonetik("Meier", "Mayer")
    assert gleiche_phonetik("Müller", "Mueller")


def test_schmidt_varianten():
    assert gleiche_phonetik("Schmidt", "Schmitt")
    # Schmid (ohne t) ist ein anderer Code — die Homophon-Suche holt ihn trotzdem.


def test_verschiedene_namen_nicht_gleich():
    assert not gleiche_phonetik("Meier", "Müller")
    assert not gleiche_phonetik("Berger", "Bauer")


def test_such_varianten_homophone():
    alts = [x.lower() for x in such_varianten("Mayer")]
    assert "meier" in alts or "meyer" in alts


def test_phonetik_treffer_eindeutig():
    kandidaten = [
        {"id": "1", "firstName": "Petra", "lastName": "Meier"},
        {"id": "2", "firstName": "Hans", "lastName": "Berger"},
    ]
    hit = phonetik_treffer(kandidaten, vorname="Petra", nachname="Mayer")
    assert hit.get("id") == "1"


def test_phonetik_treffer_zwei_gleich_bleibt_leer():
    kandidaten = [
        {"id": "1", "firstName": "Petra", "lastName": "Meier"},
        {"id": "2", "firstName": "Paul", "lastName": "Mayer"},
    ]
    assert phonetik_treffer(kandidaten, vorname="", nachname="Maier") == {}


def test_phonetik_vorname_muss_passen():
    kandidaten = [
        {"id": "1", "firstName": "Nikki", "lastName": "Johnson"},
        {"id": "2", "firstName": "Don", "lastName": "Johnson"},
    ]
    hit = phonetik_treffer(kandidaten, vorname="Don", nachname="Johnson")
    assert hit.get("id") == "2"
    leer = phonetik_treffer(kandidaten, vorname="Don", nachname="Meier")
    assert not leer


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
    print("test_phonetik: alle gruen")
