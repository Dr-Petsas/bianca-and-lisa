from lisa.notes import (
    besonderes,
    braucht_notiz,
    notiz_anhaengen,
    protokoll,
    termin_notiz,
    zusammenfassung,
)


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


_SIT = {
    "startedAt": "2026-08-27T05:34:31+00:00",
    "zuege": [
        {"art": "start", "textIn": "", "text": "Guten Tag, hier ist Lisa."},
        {"art": "listen", "textIn": "Vormittags", "text": "Ich habe neun Uhr fünfzehn frei."},
        {"art": "listen", "textIn": "Neun Uhr fünfundvierzig", "text": "Der Termin ist eingetragen."},
    ],
    "lastBook": {"name": "book_slot", "booked": True},
}


def test_protokoll_zeilen():
    text = protokoll(_SIT)
    zeilen = text.splitlines()
    assert zeilen[0] == "Lisa: Guten Tag, hier ist Lisa."
    assert "Patient: Vormittags" in zeilen
    assert zeilen[-1] == "Lisa: Der Termin ist eingetragen."


def test_protokoll_kappt_am_ende():
    lang = {"zuege": [{"textIn": f"Satz {i}", "text": f"Antwort {i}"} for i in range(200)]}
    text = protokoll(lang, limit=400)
    assert len(text) <= 410
    assert text.startswith("…")
    assert "Antwort 199" in text  # Ende (Buchung/Bestaetigung) bleibt erhalten


def test_termin_notiz_mit_protokoll_und_stempel():
    text = termin_notiz(_SIT)
    zeilen = text.splitlines()
    assert zeilen[0].startswith("Neuer Termin am Telefon.")
    assert zeilen[0].endswith("(Lisa)")
    # UTC 05:34 -> Berlin 07:34
    assert "— Telefonprotokoll Lisa 27.08.2026 07:34 —" in zeilen
    assert "Patient: Neun Uhr fünfundvierzig" in zeilen
