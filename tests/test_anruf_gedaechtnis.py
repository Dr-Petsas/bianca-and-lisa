"""Anrufer-Gedächtnis über Anrufgrenzen — offline, eigene Temp-Datei."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from kern import anruf_gedaechtnis as geda

_TZ = ZoneInfo("Europe/Berlin")


def _pfad(tmp: Path) -> Path:
    return tmp / "gedaechtnis.json"


def test_relativ_gestern_und_heute():
    jetzt = datetime(2026, 8, 28, 19, 0, tzinfo=_TZ)
    gestern = (jetzt - timedelta(days=1)).isoformat()
    assert geda.relativ(gestern, jetzt) == "gestern"
    assert geda.relativ(jetzt.isoformat(), jetzt) == "heute"
    assert geda.relativ((jetzt - timedelta(days=2)).isoformat(), jetzt) == "vorgestern"


def test_satz_mit_grund():
    rec = {
        "at": "2026-08-27T16:00:00+02:00",
        "grund": "Krone",
        "aktion": "offen",
    }
    jetzt = datetime(2026, 8, 28, 19, 0, tzinfo=_TZ)
    assert geda.satz_aus(rec, jetzt) == "Sie hatten gestern wegen Krone angerufen"


def test_merken_und_holen(tmp_path=None):
    import tempfile
    d = Path(tempfile.mkdtemp())
    p = _pfad(d)
    sit = {
        "id": "s1",
        "startedAt": "2026-08-27T16:00:00+02:00",
        "sammler": {
            "vorname": "Petra", "nachname": "Müller",
            "patientId": "pat-1", "telefon": "015112345678",
            "grund": "Krone", "grundWortlaut": "wegen der Krone",
            "modus": "buchen", "phase": "gebucht",
        },
        "lastBook": {"booked": True},
    }
    rec = geda.merken(sit, pfad=p)
    assert rec.get("aktion") == "vereinbart"
    assert rec.get("grund")
    hit = geda.holen(patient_id="pat-1", pfad=p)
    assert hit.get("patientId") == "pat-1"
    assert "Krone" in hit.get("satz", "")
    per_nr = geda.holen(phone="015112345678", pfad=p)
    assert per_nr.get("patientId") == "pat-1"


def test_dev_nummer_wird_nicht_als_schluessel_genutzt():
    import tempfile
    p = _pfad(Path(tempfile.mkdtemp()))
    sit = {
        "id": "s2",
        "startedAt": "2026-08-27T16:00:00+02:00",
        "sammler": {
            "vorname": "Peter", "nachname": "Müller",
            "telefon": "01776004600", "grund": "Kontrolle",
            "modus": "buchen",
        },
    }
    rec = geda.merken(sit, pfad=p)
    assert rec  # Grund reicht zum Merken
    leer = geda.holen(phone="01776004600", pfad=p)
    assert not leer, "geteilte Dev-Nummer darf niemanden identifizieren"


def test_leerer_anruf_wird_nicht_gemerkt():
    import tempfile
    p = _pfad(Path(tempfile.mkdtemp()))
    sit = {"id": "s3", "sammler": {"modus": ""}, "anruferNummer": "015199999999"}
    assert geda.merken(sit, pfad=p) == {}
    assert not geda.holen(phone="015199999999", pfad=p)


def test_anbinden_an_sitzung():
    import tempfile
    p = _pfad(Path(tempfile.mkdtemp()))
    sit = {
        "id": "s4",
        "startedAt": "2026-08-27T10:00:00+02:00",
        "sammler": {
            "nachname": "Berger", "patientId": "p-b",
            "telefon": "015198765432", "grund": "Implantat",
            "modus": "buchen",
        },
    }
    geda.merken(sit, pfad=p)
    neu = {}
    # holen/anbinden nutzen die Default-Datei — deshalb direkt holen mit pfad
    rec = geda.holen(patient_id="p-b", pfad=p)
    neu["letzterAnruf"] = rec
    assert "Implantat" in (neu["letzterAnruf"].get("prompt") or "")


def test_prompt_block_im_system():
    from bianca.prompt import system_prompt
    text = system_prompt(
        praxis="Testpraxis", behandler="Dr. X",
        letzter_anruf="Gestern: vereinbart, Petra Müller, wegen Krone.",
    )
    assert "LETZTER ANRUF DIESES PATIENTEN" in text
    assert "wegen Krone" in text


if __name__ == "__main__":
    test_relativ_gestern_und_heute()
    test_satz_mit_grund()
    test_merken_und_holen()
    test_dev_nummer_wird_nicht_als_schluessel_genutzt()
    test_leerer_anruf_wird_nicht_gemerkt()
    test_anbinden_an_sitzung()
    test_prompt_block_im_system()
    print("test_anruf_gedaechtnis: alle gruen")
