from lisa.greeting import begruessung, erste_botschaft


def test_termin_ohne_auftrag_vorlesen():
    t = begruessung("med dent Zahnklinik", "Kontrolltermin vorverlegen — nächste Woche ist ein Platz frei.")
    assert t.startswith("Guten Tag, hier ist Lisa aus der med dent Zahnklinik.")
    assert "vormittags oder nachmittags" in t
    assert "nächste Woche" not in t


def test_kurze_botschaft():
    assert erste_botschaft("Bitte die Rechnung nochmal schicken. Danke.") == "Bitte die Rechnung nochmal schicken."
