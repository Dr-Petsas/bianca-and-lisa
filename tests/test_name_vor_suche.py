"""Unbekannte Nachnamen: erst Tafel, dann Suche. Ein Kartei-Name, Qwen nur als zweite Lesart."""

import pytest

from bianca import flow, gehirn, hintergrund, verwalten
from kern import qwen_korrektor, stt
from kern.tenants import laden


@pytest.fixture(autouse=True)
def _ohne_namenslink(monkeypatch):
    monkeypatch.setenv("NAMENS_LINK", "0")
    monkeypatch.setattr(flow.hintergrund, "anstossen", lambda *a, **k: None)


def _buchung(mandant: str = "meddent") -> dict:
    sit = {"tenant": laden(mandant), "messages": []}
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "warSchonMal": False,
        "arzt": {"typ": "genannt", "calendarId": "kal", "calendarName": "Doktor Petsas"},
        "grund": "Kontrolluntersuchung",
        "motivId": "kontroll",
        "motivName": "Kontrolle",
        "wunsch": {},
    })
    return sit


def test_gesprochener_name_startet_keine_karteisuche(monkeypatch):
    sit = _buchung()
    aufgerufen = []
    monkeypatch.setattr(
        hintergrund.patients, "patient_aufloesen",
        lambda *_a, **_k: aufgerufen.append(1) or {},
    )
    s = gehirn.sammler(sit)
    s["frage"], _ = gehirn.naechste_frage(sit)
    aus = flow.zug(sit, "Tannis.")
    hintergrund.kartei_anstossen(sit)
    assert aufgerufen == []
    assert s["nachname"] == "Tannis"
    assert s["buchstabiert"] is False
    assert s["frage"] == "buchstabieren"
    assert aus and "Buchstabe für Buchstabe" in aus["text"]


def test_ja_auf_die_tafel_gibt_die_suche_frei(monkeypatch):
    sit = _buchung()
    aufgerufen = []
    monkeypatch.setattr(
        hintergrund.patients, "patient_aufloesen",
        lambda *_a, **_k: aufgerufen.append(1) or {"id": ""},
    )
    s = gehirn.sammler(sit)
    s["frage"], _ = gehirn.naechste_frage(sit)
    flow.zug(sit, "Tannis.")
    flow.zug(sit, "T-A-N-N-I-S, fertig.")
    assert s["frage"] == "nachname_check"
    assert aufgerufen == []
    flow.zug(sit, "Ja.")
    assert aufgerufen == []
    assert s["nachnameCheck"] == "ja"
    assert gehirn.name_suche_frei(sit) is True


def test_bekannte_rufnummer_ueberspringt_das_buchstabieren():
    sit = _buchung()
    s = gehirn.sammler(sit)
    s["nachname"] = "Petsas"
    s["anruferCheck"] = "ja"
    s["patientId"] = "akte-1"
    sit["anrufer"] = {"nachname": "Petsas"}
    assert gehirn.name_suche_frei(sit) is True


def test_dritttermin_buchstabiert_trotz_erkannter_rufnummer():
    sit = _buchung()
    s = gehirn.sammler(sit)
    s["nachname"] = "Tannis"
    s["anruferCheck"] = "ja"
    s["patientId"] = "akte-vater"
    s["fuerWen"] = "sohn"
    assert gehirn.name_suche_frei(sit) is False


def test_hotword_ist_nur_der_eine_bestaetigte_nachname():
    sit = {
        "tenant": laden("meddent"),
        "sammler": {"frage": "nachname", "anruferCheck": "ja"},
        "anrufer": {"nachname": "Petsas"},
    }
    kw = stt.keywords_fuer_sitzung(sit)
    assert kw.endswith(",Petsas") or kw.endswith("Petsas")
    assert "Thaler" not in kw.split(",")
    telefon = dict(sit)
    telefon["sammler"] = {"frage": "telefon", "anruferCheck": "ja"}
    tel_kw = stt.keywords_fuer_sitzung(telefon)
    assert "Petsas" not in tel_kw.split(",")
    dritt = dict(sit)
    dritt["sammler"] = {"frage": "nachname", "anruferCheck": "ja", "fuerWen": "sohn"}
    assert "Petsas" not in stt.keywords_fuer_sitzung(dritt).split(",")
    ohne_ja = dict(sit)
    ohne_ja["sammler"] = {"frage": "nachname", "anruferCheck": ""}
    assert "Petsas" not in stt.keywords_fuer_sitzung(ohne_ja).split(",")


def test_qwen_satz_ist_kein_namensvorschlag():
    sit = {"qwenSpaet": [{
        "gesperrt": "namensfrage:nachname",
        "qwen": "Da sagt Gott.",
    }]}
    assert qwen_korrektor.namens_vorschlag(sit, "Casacop") == ""


def test_qwen_einzelname_wird_vorgelesen_und_erst_nach_ja_gespeichert():
    sit = {"tenant": laden("meddent"), "messages": [], "qwenSpaet": [{
        "gesperrt": "namensfrage:nachname",
        "qwen": "Vidovic",
    }]}
    s = gehirn.sammler(sit)
    s["modus"] = "absagen"
    s["nachname"] = "Diderich"
    s["vorname"] = "Anna"
    aus = verwalten._korrektur_frage(sit)
    assert s["frage"] == "qwen_name"
    assert s["nachname"] == "Diderich"
    assert "Vidovic" in aus["text"]
    assert "Ist das richtig?" in aus["text"]
    assert not sit.get("verwKorrektur")

    unklar = verwalten._qwen_name_zug(sit, "Wie bitte?", None)
    assert s["nachname"] == "Diderich"
    assert "Vidovic" in unklar["text"]

    nein = verwalten._qwen_name_zug(sit, "Nein.", None)
    assert s["nachname"] == "Diderich"
    assert s["frage"] == "nachname"
    assert "buchstabieren" in nein["text"].lower() or "Nachnamen" in nein["text"]


def test_qwen_ja_uebernimmt_den_namen():
    sit = {"tenant": laden("meddent"), "messages": [], "qwenSpaet": [{
        "gesperrt": "namensfrage:nachname",
        "qwen": "Vidovic",
    }]}
    s = gehirn.sammler(sit)
    s["modus"] = "absagen"
    s["nachname"] = "Diderich"
    s["frage"] = "qwen_name"
    sit["qwenNameVorschlag"] = "Vidovic"
    gesehen = []

    def _finden(sit_arg, _melde):
        gesehen.append(gehirn.sammler(sit_arg)["nachname"])
        return {"text": "gefunden"}

    original = verwalten._dispatch
    verwalten._dispatch = lambda sit_arg, melde: _finden(sit_arg, melde)
    try:
        aus = verwalten._qwen_name_zug(sit, "Ja.", None)
    finally:
        verwalten._dispatch = original
    assert gesehen == ["Vidovic"]
    assert s["nachname"] == "Vidovic"
    assert s["nachnameCheck"] == "ja"
    assert aus["text"] == "gefunden"
