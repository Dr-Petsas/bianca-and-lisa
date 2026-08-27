"""Identitaetscheck: richtige Person, falsche Person, Dritter am Apparat."""

from lisa import identitaet
from lisa.greeting import begruessung

PATIENT = {"name": "Levi Tzannis", "firstName": "Levi", "lastName": "Tzannis", "gender": "m"}
TENANT = {"praxisName": "med dent Zahnklinik", "behandler": "Dr. Petsas"}


def _sitzung(anliegen: str = "Ich rufe im Auftrag von Dr. Petsas an, um Ihnen einen Kontrolltermin anzubieten. Passt Ihnen vormittags oder nachmittags besser?") -> dict:
    return {
        "tenant": dict(TENANT),
        "patient": dict(PATIENT),
        "auftrag": "Kontrolltermin anbieten, letzte Kontrolle drei Jahre her",
        "anliegen": anliegen,
        "idCheck": identitaet.FRAGE,
    }


def test_begruessung_fragt_nach_der_person():
    text = begruessung("med dent Zahnklinik", "Kontrolltermin anbieten",
                       patient=PATIENT, behandler="Dr. Petsas")
    assert text == "Guten Tag, hier ist Lisa von der med dent Zahnklinik. Spreche ich mit Levi Tzannis?"
    # Anliegen und Behandler kommen NICHT vor der Bestaetigung.
    assert "Auftrag" not in text
    assert "Kontrolltermin" not in text


def test_ohne_vollen_namen_alter_ablauf():
    assert not identitaet.moeglich({"name": "Tzannis"})
    text = begruessung("med dent Zahnklinik", "Kontrolltermin anbieten",
                       patient={"name": "Tzannis", "lastName": "Tzannis", "gender": "m"},
                       behandler="Dr. Petsas")
    assert "Spreche ich mit" not in text
    assert "Herr Tzannis" in text


def test_ja_fuehrt_zu_anrede_und_anliegen():
    sit = _sitzung()
    zug = identitaet.naechster_zug(sit, "Ja, der bin ich.")
    assert zug["text"].startswith("Guten Tag, Herr Tzannis.")
    assert "im Auftrag von Dr. Petsas" in zug["text"]
    assert sit["idCheck"] == identitaet.FERTIG
    assert sit["idErgebnis"] == "bestaetigt"
    # Danach ist das Modell dran.
    assert identitaet.naechster_zug(sit, "Vormittags bitte") is None


def test_nein_fragt_nach_der_zielperson():
    sit = _sitzung()
    zug = identitaet.naechster_zug(sit, "Nein.")
    assert "Kann ich Levi Tzannis sprechen?" in zug["text"]
    assert sit["idCheck"] == identitaet.HOLEN
    # Kein Anliegen an den Falschen.
    assert "Kontrolltermin" not in zug["text"]


def test_dritter_uebernimmt_das_gespraech():
    for satz in [
        "Das ist mein Sohn, worum geht es?",
        "Der schläft gerade.",
        "Er ist nicht da.",
        "Sie können auch mit mir sprechen.",
        "Ich bin seine Mutter, ich richte es ihm aus.",
        "Er ist bei der Arbeit.",
    ]:
        sit = _sitzung()
        zug = identitaet.naechster_zug(sit, satz)
        assert sit["idCheck"] == identitaet.FERTIG, satz
        assert sit["idErgebnis"] == "dritter", satz
        # Anliegen kommt, aber ohne fremde Anrede mit Patientennamen.
        assert "Kontrolltermin" in zug["text"], satz
        assert "Herr Tzannis" not in zug["text"], satz


def test_person_wird_geholt():
    sit = _sitzung()
    zug = identitaet.naechster_zug(sit, "Einen Moment, ich hole ihn.")
    assert "ich warte" in zug["text"].lower()
    assert sit["idCheck"] == identitaet.WARTEN
    assert "Kontrolltermin" not in zug["text"]
    # Jetzt ist die Zielperson dran.
    zwei = identitaet.naechster_zug(sit, "Hallo, ja?")
    assert zwei["text"].startswith("Guten Tag, Herr Tzannis.")
    assert sit["idErgebnis"] == "bestaetigt"


def test_geholt_aber_doch_nicht_da():
    sit = _sitzung()
    identitaet.naechster_zug(sit, "Moment bitte.")
    zug = identitaet.naechster_zug(sit, "Er kann gerade nicht, er schläft.")
    assert sit["idErgebnis"] == "dritter"
    assert "Herr Tzannis" not in zug["text"]


def test_unklar_fasst_einmal_nach():
    sit = _sitzung()
    eins = identitaet.naechster_zug(sit, "Hmm?")
    assert "spreche ich mit levi tzannis" in eins["text"].lower()
    assert sit["idCheck"] == identitaet.FRAGE
    zwei = identitaet.naechster_zug(sit, "Ähm.")
    assert sit["idCheck"] == identitaet.FERTIG
    assert "Kontrolltermin" in zwei["text"]


def test_nein_dann_das_bin_ich_doch():
    sit = _sitzung()
    identitaet.naechster_zug(sit, "Nein.")
    zug = identitaet.naechster_zug(sit, "Ach so, ja, das bin ich.")
    assert zug["text"].startswith("Guten Tag, Herr Tzannis.")
    assert sit["idErgebnis"] == "bestaetigt"


def test_deutung():
    assert identitaet.deute("Ja genau") == "ja"
    assert identitaet.deute("Am Apparat") == "ja"
    assert identitaet.deute("Nein, falsch verbunden") == "nein"
    assert identitaet.deute("Moment, ich gebe ihn Ihnen") == "holen"
    assert identitaet.deute("Das ist meine Tochter") == "dritter"
    # "Nein, das ist mein Sohn" -> nicht doppelt fragen, direkt weitermachen.
    assert identitaet.deute("Nein, das ist mein Sohn") == "dritter"
    assert identitaet.deute("Wer will das wissen") == "unklar"


def test_notfalltext_ohne_modell():
    from lisa.anliegen import notfalltext

    sit = _sitzung(anliegen="")
    text = notfalltext(sit)
    assert "im Auftrag von Dr. Petsas" in text
    assert "vormittags oder nachmittags" in text
    # identitaet greift auf den Notfalltext zurueck, wenn nichts vorbereitet ist.
    zug = identitaet.naechster_zug(sit, "Ja.")
    assert "im Auftrag von Dr. Petsas" in zug["text"]


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
    print("test_identitaet: alle gruen")
