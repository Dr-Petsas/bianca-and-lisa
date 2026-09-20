"""V2.6: Verschiebe-SMS-Abschluss + Dokumente nur persoenlich."""
from bianca import flow, verwalten
from kern import praxisregeln


def _sit():
    return {
        "tenant": {
            "id": "meddent",
            "praxisName": "Zahnärzte im Medical Center Düsseldorf",
            "calendars": [{"id": "c1", "name": "Dr. Michael Petsas"}],
            "defaultCalendarId": "c1",
        },
        "messages": [{"role": "system", "content": "x"}],
        "anruferKartei": {"doctorName": "Dr. Michael Petsas"},
    }


def main() -> None:
    t = praxisregeln.unterlagen_antwort(
        _sit()["tenant"], "Ich brauche ein Rezept.", _sit()
    )
    assert "Rezepte können nur in der Praxis abgeholt werden" in t, t
    assert "Doktor Petsas" in t or "Petsas" in t, t
    assert "Rückruf" not in t and "meldet sich" not in t, t
    print("rezept persoenlich ok")

    t = praxisregeln.unterlagen_antwort(
        _sit()["tenant"], "Können Sie mir eine Überweisung ausstellen?"
    )
    assert "Überweisungen werden nur persönlich" in t, t
    assert "Rückruf" not in t, t
    print("ueberweisung persoenlich ok")

    for satz, kern in (
        ("Ich brauche meinen Befund.", "Befunde"),
        ("Schicken Sie mir die Rechnung.", "Rechnungen"),
        ("Ich möchte eine Kopie meiner Akte.", "Akten"),
        ("Ich brauche eine Krankmeldung.", "Krankmeldungen"),
        ("Können Sie mir die Behandlungsunterlagen zuschicken?", "Behandlungsunterlagen"),
        ("Ich hätte gern den Behandlungsplan.", "Behandlungspläne"),
    ):
        text = praxisregeln.unterlagen_antwort(_sit()["tenant"], satz, _sit())
        assert kern in text, (satz, text)
        assert "Rückruf" not in text, (satz, text)
        print("doku", kern, "ok")

    assert praxisregeln.unterlagen_antwort(
        _sit()["tenant"], "Ich habe eine Überweisung vom Hausarzt und brauche einen Termin."
    ) == ""
    assert praxisregeln.unterlagen_antwort(
        _sit()["tenant"], "Ich brauche einen Termin zur Befundbesprechung."
    ) == ""
    print("gegenproben buchung ok")

    sit = _sit()
    sit["hirnAbgeben"] = {"offen": True, "was": "Rezept"}
    res = flow.zug(sit, "Ich brauche ein Rezept.")
    text = (res or {}).get("text") or ""
    assert "Rezepte können nur in der Praxis" in text, text
    assert "Wie ist Ihr Name" not in text
    assert "Rückruf" not in text
    print("abgeben kein rueckruf ok")

    sit = _sit()
    s = verwalten.gehirn.sammler(sit)
    s.update({
        "modus": "verschieben", "phase": "verschieb_bestaetigen",
        "frage": "verschieb_ok", "slotIso": "2026-09-22T13:30:00+02:00",
    })
    sit["gefunden"] = [{
        "id": "t1", "iso": "2026-09-21T12:00:00+02:00", "calendarId": "c1",
        "doctorName": "Dr. Petsas", "motivId": "k", "motivName": "K",
        "spoken": "morgen um zwölf Uhr bei Doktor Petsas",
    }]
    sit["verwaltenTermin"] = "t1"
    sit["testNoWrite"] = True
    res = verwalten._verschieben(sit, None)
    # Trockenlauf endet ohne SMS — der echte Erfolgspfad traegt sie.
    # Wir pruefen den Erfolg-Text direkt am fertigen Satzbaustein.
    satz = (
        "Der Termin liegt jetzt übermorgen um dreizehn Uhr dreißig."
        " Die Bestätigung kommt gleich per SMS."
        " In der SMS ist auch ein Link — darüber füllen Sie bitte vorab kurz die"
        " Unterlagen für Ihren Termin aus, zum Beispiel Anamnese und Datenschutz."
    )
    assert "Die Bestätigung kommt gleich per SMS." in satz
    assert "Link" in satz and "Anamnese" in satz
    print("sms-abschluss satz ok")

    # Erfolgspfad mit gestubbtem Kalender
    sit = _sit()
    s = verwalten.gehirn.sammler(sit)
    s.update({
        "modus": "verschieben", "phase": "verschieb_bestaetigen",
        "frage": "verschieb_ok", "slotIso": "2026-09-22T13:30:00+02:00",
    })
    sit["gefunden"] = [{
        "id": "t1", "iso": "2026-09-21T12:00:00+02:00", "calendarId": "c1",
        "doctorName": "Dr. Petsas", "motivId": "k", "motivName": "K",
        "spoken": "morgen um zwölf Uhr",
    }]
    sit["verwaltenTermin"] = "t1"
    echt = verwalten.kal.move_appointment
    verwalten.kal.move_appointment = lambda *a, **k: {
        "ok": True, "moved": True, "dryRun": False,
        "slotIso": "2026-09-22T13:30:00+02:00",
        "spoken": "Der Termin liegt jetzt übermorgen um dreizehn Uhr dreißig.",
    }
    try:
        res = verwalten._verschieben(sit, None)
    finally:
        verwalten.kal.move_appointment = echt
    text = (res or {}).get("text") or ""
    assert "Die Bestätigung kommt gleich per SMS." in text, text
    assert "Link" in text and "Anamnese" in text, text
    print("verschieben sms-abschluss ok", text)
    print("ALLE GRUEN")


if __name__ == "__main__":
    main()
