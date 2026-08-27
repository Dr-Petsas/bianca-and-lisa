from lisa.notes import (
    besonderes,
    besondere_zeilen,
    braucht_notiz,
    grund_kurz,
    notiz_anhaengen,
    termin_notiz,
    zusammenfassung,
)


def test_anhaengen_und_kein_doppelt():
    a = notiz_anhaengen("", "Patient hat Angst vor der Spritze")
    assert a.endswith("// Lisa")
    b = notiz_anhaengen(a, "Patient hat Angst vor der Spritze")
    assert b == a


def test_besonderes():
    treffer = besonderes("Ich habe richtig Angst vor der Spritze")
    assert "angst" in treffer
    assert any("spritze" in x for x in treffer)


def test_zusammenfassung_absage_minimal():
    sit = {
        "zuege": [{"textIn": "Den Termin sage ich ab."}],
        "lastCancel": {"name": "cancel_appointment", "ok": True},
    }
    assert zusammenfassung(sit) == "telefonisch Termin abgesagt"
    assert braucht_notiz(sit)


def test_grund_kurz_kondensiert_wortlaut():
    sit = {"sammler": {"grundWortlaut": "Ähm, ich wollte mir die Fingernägel lackieren lassen"}}
    assert grund_kurz(sit) == "Fingernägel lackieren"
    sit = {"sammler": {"grundWortlaut": "ich muss mein Holzbein absägen lassen"}}
    assert grund_kurz(sit) == "Holzbein absägen"
    sit = {"sammler": {"grund": "Kontrolluntersuchung"}}
    assert grund_kurz(sit) == "Kontrolluntersuchung"


def test_termin_notiz_eine_zeile_ohne_datenkern():
    """Chef 27.08.: 'telefonisch Termin vereinbart wegen X // Bianca' — sonst NICHTS.
    Kein Name, keine Nummer, kein Datum, keine Kurzfassung, kein Transkript."""
    sit = {
        "stimme": "Bianca",
        "startedAt": "2026-08-27T16:10:18+00:00",
        "zuege": [
            {"textIn": "Ich wollte mir die Fingernägel lackieren lassen", "text": "Alles klar."},
            {"textIn": "Ja, bitte", "text": "Der Termin ist eingetragen."},
        ],
        "sammler": {"grundWortlaut": "Ich wollte mir die Fingernägel lackieren lassen"},
        "lastBook": {"name": "book_slot", "booked": True},
    }
    text = termin_notiz(sit)
    assert text == "telefonisch Termin vereinbart wegen Fingernägel lackieren // Bianca"
    for verboten in ("Kurzfassung", "Telefonprotokoll", "Patient sagte", "0177", "Pinocchio", "SMS"):
        assert verboten not in text


def test_termin_notiz_auffaelliges_kommt_dazu():
    sit = {
        "stimme": "Bianca",
        "zuege": [
            {"textIn": "Ich habe furchtbare Angst vor Spritzen", "text": "Das notiere ich."},
            {"textIn": "Ja, bitte", "text": "Eingetragen."},
        ],
        "sammler": {"grund": "Kontrolluntersuchung", "grundWortlaut": "eine Kontrolle bitte"},
        "lastBook": {"name": "book_slot", "booked": True},
    }
    zeilen = termin_notiz(sit).splitlines()
    assert zeilen[0] == "telefonisch Termin vereinbart wegen Kontrolle // Bianca"
    assert len(zeilen) == 2
    assert zeilen[1].startswith("Patient erwähnt: „Ich habe furchtbare Angst vor Spritzen")
    assert zeilen[1].endswith("// Bianca")
    assert besondere_zeilen(sit)


def test_termin_notiz_leer_ohne_aktion_und_besonderes():
    sit = {"stimme": "Bianca", "zuege": [{"textIn": "Wie sind Ihre Öffnungszeiten?"}]}
    assert termin_notiz(sit) == ""
    assert not braucht_notiz(sit)
