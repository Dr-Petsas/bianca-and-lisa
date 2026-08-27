from lisa.notes import besonderes, braucht_notiz, notiz_anhaengen, zusammenfassung


def test_anhaengen_und_kein_doppelt():
    a = notiz_anhaengen("", "Patient hat Angst vor der Spritze")
    assert a.endswith("(Lisa)")
    b = notiz_anhaengen(a, "Patient hat Angst vor der Spritze")
    assert b == a


def test_besonderes():
    treffer = besonderes("Ich habe richtig Angst vor der Spritze")
    assert "angst" in treffer
    assert any("spritze" in x for x in treffer)


def test_zusammenfassung_absage():
    sit = {
        "zuege": [{"textIn": "Den Termin sage ich ab, ich habe Angst"}],
        "lastCancel": {"name": "cancel_appointment", "dryRun": True},
    }
    text = zusammenfassung(sit)
    assert "Absage" in text
    assert "angst" in text.lower()
    assert braucht_notiz(sit)
