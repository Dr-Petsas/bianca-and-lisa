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


def test_heute_zeile_fuer_den_prompt():
    # Chef 30.08.2026: Bianca/Lisa wussten nicht, welcher Tag heute ist —
    # der Datums-Anker gehoert in jeden Systemprompt.
    from datetime import datetime

    from kern.sprech import heute_zeile

    z = heute_zeile(datetime(2026, 8, 29, 5, 3))
    assert z == ("Heute ist Samstag, der 29. August 2026, es ist 05:03 Uhr. "
                 "Morgen ist Sonntag, der 30. August.")
    # Jahreswechsel: "morgen" springt sauber ins neue Jahr.
    assert "Morgen ist Freitag, der 1. Januar." in heute_zeile(datetime(2026, 12, 31, 23, 59))


# --- W-TTS-NAHT (31.08.2026): Satz-Split mit Grenz-Wache ---------------------
# Portiert aus phone_agent tts_chunks: nie hinter Ordnungszahl/Abkuerzung
# splitten — sonst rendert die Stimme halbe Phrasen ("im 3." | "Stock").


def test_tts_saetze_normal_split():
    from kern.sprech import tts_saetze

    assert tts_saetze("Das passt gut. Wann koennen Sie?") == \
        ["Das passt gut.", "Wann koennen Sie?"]
    assert tts_saetze("") == []
    assert tts_saetze("Ein Satz ohne Ende") == ["Ein Satz ohne Ende"]


def test_tts_saetze_ordnungszahl_kein_schnitt():
    from kern.sprech import tts_saetze

    assert tts_saetze("Wir sind im 3. Stock. Kommen Sie hoch.") == \
        ["Wir sind im 3. Stock.", "Kommen Sie hoch."]


def test_tts_saetze_abkuerzung_kein_schnitt():
    from kern.sprech import tts_saetze

    # "St."/"Nr." und Strassennamen auf "-str." sind kein Satzende.
    assert tts_saetze("Die Praxis am St. Martins-Platz. Bis morgen.") == \
        ["Die Praxis am St. Martins-Platz.", "Bis morgen."]
    assert tts_saetze("Die Bahnhofstr. Zwoelf kennen Sie ja. Bis dann.") == \
        ["Die Bahnhofstr. Zwoelf kennen Sie ja.", "Bis dann."]


def test_kein_satzende_wache():
    from kern.sprech import kein_satzende

    assert kein_satzende("Wir sind im 3")            # Ordnungszahl
    assert kein_satzende("am St")                    # Abkuerzung
    assert kein_satzende("in der Bahnhofstr")        # Strassenname
    assert kein_satzende("wie z")                    # Einzelbuchstabe
    assert not kein_satzende("Das passt gut")        # echtes Satzende


def test_prompts_tragen_das_datum():
    from bianca.prompt import system_prompt as bianca_prompt
    from lisa.prompt import system_prompt as lisa_prompt

    b = bianca_prompt(praxis="Testpraxis", behandler="Dr. Test")
    l = lisa_prompt(praxis="Testpraxis", behandler="Dr. Test",
                    auftrag="Termin vereinbaren", patient="Peter Berger")
    for p in (b, l):
        assert "HEUTE" in p and "Heute ist " in p and "Morgen ist " in p
