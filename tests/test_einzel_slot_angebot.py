"""Ein Termin pro Angebot, Alternativen bleiben intern verfügbar."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from unittest.mock import patch

from bianca import flow, gehirn, hintergrund, session, verwalten
from kern.slots import (
    fragt_nach_frueherem_slot,
    fruehester_slot_antwort,
    spoken_offer,
)
from kern.tenants import laden


_MONTAG = date.today() + timedelta(days=(7 - date.today().weekday()) % 7 + 7)
_DIENSTAG = _MONTAG + timedelta(days=1)
_MITTWOCH = _MONTAG + timedelta(days=2)


def _iso(tag: date, stunde: int) -> str:
    return datetime.combine(tag, time(stunde)).astimezone().isoformat(timespec="seconds")


MONTAG_09 = _iso(_MONTAG, 9)
DIENSTAG_10 = _iso(_DIENSTAG, 10)
MITTWOCH_15 = _iso(_MITTWOCH, 15)


def _buchung() -> dict:
    sit = session.neu(tenant=laden("meddent"))
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "phase": "",
        "frage": "",
        "warSchonMal": False,
        "arzt": {
            "typ": "gesagt",
            "calendarId": "zex5bmv5jfIHWVW6zHbg",
            "calendarName": "Doktor Michael Petsas",
        },
        "grund": "Kontrolle",
        "grundWortlaut": "Kontrolle",
        "motivId": "qOQCI4vV2EhQVmKmRqdu",
        "motivName": "KCH Kontrolluntersuchung",
        "nachname": "Muster",
        "vorname": "Max",
        "buchstabiert": True,
        "nameVerified": True,
        "versicherung": "gesetzlich",
        "wunsch": {"erstmoeglich": True},
        "wunschText": "frühestmöglich",
    })
    sit["slotVorrat"] = [MONTAG_09, DIENSTAG_10, MITTWOCH_15]
    sit["vorratFuer"] = hintergrund.vorrat_schluessel(sit)
    sit["vorratGemerkt"] = True
    return sit


def test_erstangebot_spricht_und_speichert_genau_einen_termin():
    sit = _buchung()
    aus = flow._angebot(sit)

    assert len(sit["offered"]) == 1
    assert sit["offered"][0]["iso"] == MONTAG_09
    assert [x["iso"] for x in sit["slotAlternativen"]] == [DIENSTAG_10, MITTWOCH_15]
    assert sit["slotVorrat"] == [MONTAG_09, DIENSTAG_10, MITTWOCH_15]
    assert "Passt Ihnen dieser Termin?" in aus["text"]
    assert " oder " not in aus["text"]


def test_blankes_ja_waehlt_nur_den_gesprochenen_termin():
    sit = _buchung()
    flow._angebot(sit)

    aus = flow.zug(sit, "Ja, der passt.")

    assert gehirn.sammler(sit)["slotIso"] == MONTAG_09
    assert "halte ich fest" in aus["text"].lower()


def test_blanke_ablehnung_bietet_den_naechsten_verdeckten_termin():
    sit = _buchung()
    flow._angebot(sit)

    aus = flow._slot_praeferenz_zug(sit, "Nein.")

    assert aus is not None
    assert len(sit["offered"]) == 1
    assert sit["offered"][0]["iso"] == DIENSTAG_10
    assert MONTAG_09 in gehirn.sammler(sit)["wunsch"]["excludeIsos"]


def test_ablehnung_mit_tageszeit_bietet_genau_einen_passenden_termin():
    sit = _buchung()
    flow._angebot(sit)

    aus = flow._slot_praeferenz_zug(sit, "Nein, lieber nachmittags.")

    assert aus is not None
    assert len(sit["offered"]) == 1
    assert sit["offered"][0]["iso"] == MITTWOCH_15


def test_geht_es_nicht_frueher_bleibt_auf_dem_aktuellen_termin():
    sit = _buchung()
    flow._angebot(sit)
    vorher = list(sit["offered"])

    aus = flow.zug(sit, "Geht es nicht früher?")

    assert sit["offered"] == vorher
    assert aus["text"] == (
        "Das ist der frühestmögliche Termin. Vorher habe ich leider nichts frei. "
        "Passt Ihnen dieser Termin?"
    )


def test_frueher_parser_kapert_keine_spaeter_praeferenz():
    assert fragt_nach_frueherem_slot("Gibt es nichts Früheres?")
    assert not fragt_nach_frueherem_slot("Ich kann nicht früher, lieber nachmittags.")
    assert fruehester_slot_antwort() == (
        "Das ist der frühestmögliche Termin. Vorher habe ich leider nichts frei. "
        "Passt Ihnen dieser Termin?"
    )


def test_entfernter_einzeltermin_nennt_das_datum():
    fern = datetime.combine(date.today() + timedelta(days=70), time(9)).astimezone()
    text = spoken_offer([{"iso": fern.isoformat(timespec="seconds")}])
    monate = (
        "Januar", "Februar", "März", "April", "Mai", "Juni",
        "Juli", "August", "September", "Oktober", "November", "Dezember",
    )

    assert monate[fern.month - 1] in text
    assert "Passt Ihnen dieser Termin?" in text


def test_verschieben_bietet_ohne_vorabfrage_genau_einen_termin():
    sit = session.neu(tenant=laden("meddent"))
    s = gehirn.sammler(sit)
    s.update({
        "modus": "verschieben",
        "phase": "wahl",
        "frage": "terminwahl",
        "arzt": {
            "typ": "gesagt",
            "calendarId": "zex5bmv5jfIHWVW6zHbg",
            "calendarName": "Doktor Michael Petsas",
        },
    })
    termin = {
        "id": "alt-1",
        "iso": _iso(_MONTAG, 8),
        "spoken": "am Montag um acht Uhr",
        "calendarId": "zex5bmv5jfIHWVW6zHbg",
        "doctorName": "Doktor Michael Petsas",
        "motivId": "qOQCI4vV2EhQVmKmRqdu",
        "motivName": "KCH Kontrolluntersuchung",
    }
    sit["gefunden"] = [termin]

    with patch.object(verwalten.kal, "find_slots_behandler", return_value={
        "ok": True,
        "slots": [MONTAG_09, DIENSTAG_10, MITTWOCH_15],
    }):
        aus = verwalten._verschieb_wunsch_frage(sit, termin)

    assert len(sit["offered"]) == 1
    assert sit["offered"][0]["iso"] == MONTAG_09
    assert [x["iso"] for x in sit["slotAlternativen"]] == [DIENSTAG_10, MITTWOCH_15]
    assert "vormittags oder nachmittags" not in aus["text"].lower()
    assert "Passt Ihnen dieser Termin?" in aus["text"]
