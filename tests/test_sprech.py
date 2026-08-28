from datetime import date

from lisa.sprech import sanitize, slot_wort, tag_wort, zeit_wort

HEUTE = date(2026, 8, 27)


def test_uhrzeit_worte():
    assert zeit_wort(9, 15) == "neun Uhr fünfzehn"
    assert zeit_wort(13, 0) == "dreizehn Uhr"
    assert zeit_wort(1, 5) == "ein Uhr fünf"
    assert zeit_wort(8, 30) == "acht Uhr dreißig"
    assert zeit_wort(14, 45) == "vierzehn Uhr fünfundvierzig"
    assert zeit_wort(7, 21) == "sieben Uhr einundzwanzig"


def test_tag_relativ_und_absolut():
    assert tag_wort(2026, 8, 27, heute=HEUTE) == "heute"
    assert tag_wort(2026, 8, 28, heute=HEUTE) == "morgen"
    assert tag_wort(2026, 8, 29, heute=HEUTE) == "übermorgen"
    assert tag_wort(2026, 9, 3, heute=HEUTE) == "Donnerstag, den dritten September"
    assert tag_wort(2027, 1, 5, heute=HEUTE) == "Dienstag, den fünften Januar 2027"


def test_slot_wort():
    assert slot_wort("2026-08-28T09:15", heute=HEUTE) == "morgen um neun Uhr fünfzehn"
    assert slot_wort("2026-09-03T14:30", heute=HEUTE) == "am Donnerstag, den dritten September um vierzehn Uhr dreißig"
    assert slot_wort("2026-08-28", heute=HEUTE) == "morgen"


def test_sanitize_iso_und_digitalzeit():
    s = sanitize("Ihr Termin ist am 2026-08-28T09:15.", heute=HEUTE)
    assert s == "Ihr Termin ist morgen um neun Uhr fünfzehn."
    s = sanitize("Der Termin am 2026-08-27 ist abgesagt.", heute=HEUTE)
    assert s == "Der Termin heute ist abgesagt."
    s = sanitize("Frei ist Freitag um 09:15 Uhr oder um 14:00.", heute=HEUTE)
    assert "neun Uhr fünfzehn" in s and "vierzehn Uhr" in s
    assert ":" not in s
    s = sanitize("Passt es um 15 Uhr?", heute=HEUTE)
    assert s == "Passt es um fünfzehn Uhr?"


def test_sanitize_deutsches_datum():
    s = sanitize("Der Termin am 28.08.2026 ist abgesagt.", heute=HEUTE)
    assert s == "Der Termin morgen ist abgesagt."
    s = sanitize("Wir sehen uns am 03.09.", heute=HEUTE)
    assert "dritten September" in s
    # Punkt-Uhrzeit darf KEIN Datum werden:
    s = sanitize("Um 9.12 Uhr bitte.", heute=HEUTE)
    assert s == "Um neun Uhr zwölf bitte."
    # Ziffer vor Monatsnamen (so schreibt das LLM gern):
    s = sanitize("Frei am Donnerstag, den 14. November, um 9:30.", heute=HEUTE)
    assert s == "Frei am Donnerstag, den vierzehnten November, um neun Uhr dreißig."
    # Nominativ nach Wochentag (live 28.08.2026: „am Montag, der 31.8.“):
    s = sanitize("Passt Ihnen am Montag, der 31.8.?", heute=HEUTE)
    assert "den einunddreißigsten August" in s
    assert "der einunddreißigste" not in s
    assert "der 31" not in s
    s = sanitize("am Dienstag, der dritte September", heute=HEUTE)
    assert s == "am Dienstag, den dritten September"


def test_sanitize_technik_und_regie():
    s = sanitize(
        "Frei ist morgen um neun. Frage, welcher Termin passt, und buche ihn dann "
        "SOFORT mit book_slot (Feld slot_iso).",
        heute=HEUTE,
    )
    assert "book_slot" not in s and "slot_iso" not in s
    assert s.startswith("Frei ist morgen um neun")
    s = sanitize("Es gibt freie Timeslots um 14:30.", heute=HEUTE)
    assert s == "Es gibt freie Termine um vierzehn Uhr dreißig."
    s = sanitize("Sage dem Patienten, dass die Praxis sich meldet.", heute=HEUTE)
    assert "Sage dem Patienten" not in s


def test_sanitize_telefonnummer_bleibt():
    s = sanitize("Ihre Nummer ist 0177 6004600, richtig?", heute=HEUTE)
    assert "0177 6004600" in s


def test_sanitize_leer_und_normal():
    assert sanitize("") == ""
    assert sanitize("Guten Tag, hier ist Lisa.") == "Guten Tag, hier ist Lisa."
