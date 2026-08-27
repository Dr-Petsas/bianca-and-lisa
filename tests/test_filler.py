from lisa import filler


def test_terminfrage_wird_erkannt():
    for satz in [
        "Haben Sie kommende Woche vormittags etwas frei?",
        "Geht auch Montag?",
        "Gibt es einen Termin gegen neun Uhr?",
        "Können wir den Termin verschieben?",
        "Ich muss den Termin leider absagen.",
    ]:
        assert filler.vermutet(satz) == "suchen", satz


def test_aktenfrage_wird_erkannt():
    assert filler.vermutet("Welchen Termin habe ich denn?") == "akte"
    assert filler.vermutet("Wann habe ich nochmal meinen Termin?") == "akte"


def test_geplauder_bekommt_keinen_fueller():
    for satz in ["Guten Tag.", "Wer sind Sie denn?", "Danke, das war alles.", ""]:
        assert filler.vermutet(satz) == "", satz


def test_zusage_nur_bei_offenem_angebot_und_dann_neutral():
    assert filler.vermutet("Ja, den nehme ich.") == ""
    # Mit offenem Angebot kommt ein Werkzeug — aber der geratene Satz darf
    # die Buchung NICHT behaupten, also nur die neutrale Gruppe.
    g = filler.vermutet("Ja, den nehme ich.", angebot_offen=True)
    assert g == "allgemein"
    assert g in filler.VORAB_ERLAUBT


def test_geratene_gruppen_behaupten_keine_handlung():
    verboten = ("trage", "eingetragen", "gebucht", "abgesagt", "angelegt", "verschoben")
    for gruppe in filler.VORAB_ERLAUBT:
        for satz in filler.GRUPPEN[gruppe]:
            klein = satz.lower()
            for wort in verboten:
                assert wort not in klein, f"{gruppe}: {satz}"


def test_tool_gruppen_vollstaendig():
    for tool in ["offer_slots", "book_slot", "cancel_appointment",
                 "move_appointment", "list_appointments", "create_patient"]:
        gruppe = filler.fuer_tool(tool)
        assert gruppe in filler.GRUPPEN
        assert filler.satz(gruppe, 0)
    assert filler.fuer_tool("unbekannt") == "allgemein"


def test_rotation_wechselt_den_satz():
    a = filler.satz("suchen", 0)
    b = filler.satz("suchen", 1)
    assert a != b
    assert filler.satz("suchen", len(filler.GRUPPEN["suchen"])) == a


def test_alle_saetze_eindeutig():
    saetze = filler.alle_saetze()
    assert len(saetze) == len(set(saetze))
    assert len(saetze) >= 12
    for s in saetze:
        assert s.endswith((".", "!", "?")), s


def test_saetze_kurz_genug_um_die_antwort_nicht_zu_ueberdauern():
    for gruppe, liste in filler.GRUPPEN.items():
        grenze = filler.MAX_VORAB if gruppe in filler.VORAB_ERLAUBT else filler.MAX_TOOL
        for s in liste:
            assert len(s) <= grenze, f"{gruppe}: {len(s)} Zeichen — {s}"


def test_saetze_gehen_unveraendert_durch_die_sprech_schicht():
    # Sonst passt die vorgerenderte Audio nicht zum gesprochenen Text.
    from lisa.sprech import sanitize
    for s in filler.alle_saetze():
        assert sanitize(s) == s, s
