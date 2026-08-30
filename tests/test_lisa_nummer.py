"""Lisa: falsche Rufnummer aufnehmen, Zeit lassen, Partner nicht überschreiben."""

from __future__ import annotations

from lisa import identitaet, nummer


def _sit() -> dict:
    return {
        "tenant": {"praxisName": "Testpraxis"},
        "patient": {
            "name": "Levi Tzannis",
            "firstName": "Levi",
            "lastName": "Tzannis",
            "id": "pat-1",
            "phone": "0123456789",
        },
        "booking": {"patientId": "pat-1", "phone": "0123456789"},
        "idCheck": identitaet.NUMMER,
        "lisaNummer": {},
    }


def test_frage_laesst_zeit():
    sit = _sit()
    text = nummer.frage_nach_nummer(sit, wer="Petra")
    assert "Levi Tzannis" in text
    assert "Zeit" in text or "Handy" in text
    assert sit["lisaNummer"]["phase"] == nummer.FRAGEN
    assert sit["lisaNummer"]["werSagt"] == "Petra"
    st = nummer.stille_fuer(sit)
    assert st["stilleMs"] >= 1300
    assert st["stilleWarteMs"] >= 8000


def test_suchen_gibt_mehr_ruhe():
    sit = _sit()
    nummer.frage_nach_nummer(sit)
    zug = nummer.naechster_zug(sit, "Moment, ich suche im Handy.")
    assert "warte" in zug["text"].lower() or "zeit" in zug["text"].lower()
    assert nummer.sucht(sit)
    st = nummer.stille_fuer(sit)
    assert st["stilleWarteMs"] >= 15000


def test_diktat_und_akte_update():
    sit = _sit()
    nummer.frage_nach_nummer(sit)
    echt = nummer.patients.telefon_aktualisieren
    nummer.patients.telefon_aktualisieren = lambda *a, **k: {
        "ok": True, "patientId": "pat-1", "mobilePhoneNumber": "+491771112233",
    }
    try:
        eins = nummer.naechster_zug(sit, "null eins sieben sieben eins eins eins zwei zwei drei drei")
        assert "Stimmt das so" in eins["text"]
        zwei = nummer.naechster_zug(sit, "Ja, stimmt.")
        assert "Partner" in zwei["text"] or "eigene" in zwei["text"]
        drei = nummer.naechster_zug(sit, "Die von Levi, bitte in der Akte.")
        assert sit["lisaNummer"]["phase"] == nummer.FERTIG
        assert "eingetragen" in drei["text"].lower() or "umgetragen" in drei["text"].lower()
        assert sit["patient"]["phone"].startswith("0") or sit["booking"]["phone"]
    finally:
        nummer.patients.telefon_aktualisieren = echt


def test_partner_nummer_nicht_in_akte():
    sit = _sit()
    nummer.frage_nach_nummer(sit, wer="Petra")
    gerufen = []
    echt = nummer.patients.telefon_aktualisieren
    nummer.patients.telefon_aktualisieren = lambda *a, **k: gerufen.append(1) or {"ok": True}
    try:
        nummer.naechster_zug(sit, "0177 600 4600")
        nummer.naechster_zug(sit, "Ja.")
        zug = nummer.naechster_zug(sit, "Das ist meine, vom Partner.")
        assert not gerufen
        assert "partner" in (sit.get("praxisNotiz") or "").lower() or "eigene" in zug["text"].lower()
        assert sit["lisaNummer"]["rolle"] == "partner"
    finally:
        nummer.patients.telefon_aktualisieren = echt


def test_weiss_nicht_kein_erfinden():
    sit = _sit()
    nummer.frage_nach_nummer(sit)
    zug = nummer.naechster_zug(sit, "Weiß ich nicht, habe die Nummer nicht.")
    assert sit["lisaNummer"]["phase"] == nummer.FERTIG
    assert "anderen weg" in zug["text"].lower()


def test_mitte_im_gespraech_falsche_nummer():
    sit = {
        "tenant": {},
        "patient": {"name": "Levi Tzannis", "id": "pat-1"},
        "booking": {},
        "idCheck": identitaet.FERTIG,
    }
    zug = nummer.naechster_zug(sit, "Die Nummer ist falsch, rufen Sie uns unter einer anderen an.")
    assert zug and "nummer" in zug["text"].lower()
    assert nummer.aktiv(sit)


def test_identitaet_dann_nummer_diktat():
    sit = {
        "tenant": {"behandler": "Dr. T"},
        "patient": {"name": "Levi Tzannis", "firstName": "Levi", "lastName": "Tzannis", "gender": "m"},
        "auftrag": "Recall",
        "anliegen": "Ich rufe wegen Recall an.",
        "idCheck": identitaet.FRAGE,
    }
    identitaet.naechster_zug(sit, "Das bin ich nicht, ich heiße Petra.")
    assert sit["idCheck"] == identitaet.NUMMER
    zwei = identitaet.naechster_zug(sit, "Moment, ich gucke auf den Zettel.")
    assert nummer.sucht(sit)
    assert "Kontrolltermin" not in (zwei.get("text") or "")
