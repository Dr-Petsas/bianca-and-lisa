"""Blessing: abgelehnte Wochentage/Tageszeiten werden nie erneut angeboten."""

from __future__ import annotations

from bianca import agent, flow, gehirn, hintergrund, session, verwalten
from kern.slots import (
    pick_slots,
    slot_praeferenz_aenderung,
    wunsch_mit_slot_praeferenz,
)
from kern.tenants import laden


DONNERSTAG_11 = "2026-12-03T11:30:00+01:00"
DONNERSTAG_14 = "2026-12-03T14:40:00+01:00"
MONTAG_11 = "2026-12-07T11:15:00+01:00"
MONTAG_14 = "2026-12-07T14:15:00+01:00"
DIENSTAG_15 = "2026-12-08T15:00:00+01:00"
MITTWOCH_16 = "2026-12-09T16:00:00+01:00"
FREITAG_14 = "2026-12-11T14:30:00+01:00"
ALLE = [
    DONNERSTAG_11,
    DONNERSTAG_14,
    MONTAG_11,
    MONTAG_14,
    DIENSTAG_15,
    MITTWOCH_16,
    FREITAG_14,
]


def _sit() -> dict:
    sit = session.neu(tenant=laden("blessing"))
    agent.start_reply(sit)
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "phase": "angebot",
        "frage": "slotwahl",
        "warSchonMal": False,
        "arzt": {
            "typ": "einzig",
            "calendarId": "8krcWh7AuXEfgWc1blzQ",
            "calendarName": "Doktor Charlotte Blessing",
        },
        "grund": "Kontrolle",
        "grundWortlaut": "Kontrolle",
        "motivId": "UnfQ5DOaMx9FLiTC3L9b",
        "motivName": "Kontrolle",
        "wunsch": {
            "weekday": None,
            "hourMin": None,
            "hourMax": None,
            "hour": None,
            "minDaysAhead": 0,
            "date": None,
            "tage": None,
            "von": None,
            "bis": None,
        },
    })
    sit["slotVorrat"] = list(ALLE)
    sit["offered"] = [
        {"iso": DONNERSTAG_11, "spoken": "Donnerstag um elf Uhr dreißig"},
        {"iso": DONNERSTAG_14, "spoken": "Donnerstag um vierzehn Uhr vierzig"},
        {"iso": MONTAG_11, "spoken": "Montag um elf Uhr fünfzehn"},
    ]
    sit["vorratFuer"] = hintergrund.vorrat_schluessel(sit)
    sit["vorratGemerkt"] = True
    return sit


def test_schalter_gilt_seit_a6_fuer_alle_mandanten():
    # A6 (17.09.2026): der Merker ist Standard; ein Mandant kann ihn nur noch
    # AUSDRUECKLICH abschalten (False). Blessing traegt weiter True.
    assert laden("blessing").get("slotPraeferenzenFesthalten") is True
    for tenant_id in ("meddent", "thaler", "ruether"):
        assert laden(tenant_id).get("slotPraeferenzenFesthalten") is not False


def test_live_saetze_sperren_donnerstag():
    for text in (
        "Nicht Donnerstag. Donnerstag ist falsch, weil Donnerstag hat eine lange Schule.",
        "Nee, keinen Donnerstag, keinen Donnerstag.",
        "Donnerstag geht nicht, Donnerstag hat eine lange Ganztagsschule.",
        "Keine Donnerstag bitte, keinen Donnerstag!",
    ):
        aenderung = slot_praeferenz_aenderung(text)
        assert aenderung is not None, text
        assert 4 in aenderung["excludeWeekdays"], (text, aenderung)


def test_live_mehrfachwahl_haelt_erlaubte_tage_und_nicht_donnerstag():
    aenderung = slot_praeferenz_aenderung(
        "Montag, Dienstag, Mittwoch Nachmittag oder Freitagnachmittag, "
        "aber nicht Donnerstag."
    )

    assert aenderung["weekdays"] == [1, 2, 3, 5]
    assert aenderung["excludeWeekdays"] == [4]
    assert (aenderung["hourMin"], aenderung["hourMax"]) == (12, 18)


def test_elf_uhr_ist_vormittag_nachmittag_gewinnt():
    aenderung = slot_praeferenz_aenderung(
        "Nicht elf Uhr, nein, elf Uhr ist Vormittag, bitte Nachmittag."
    )

    assert aenderung is not None
    assert (aenderung["hourMin"], aenderung["hourMax"]) == (12, 18)
    assert 11 in aenderung["excludeHours"]


def test_ausschluesse_bleiben_ueber_mehrere_zuege():
    wunsch = wunsch_mit_slot_praeferenz(
        {},
        slot_praeferenz_aenderung("Bitte nicht Donnerstag."),
    )
    wunsch = wunsch_mit_slot_praeferenz(
        wunsch,
        slot_praeferenz_aenderung(
            "Montag, Dienstag oder Freitag Nachmittag, aber nicht Donnerstag."
        ),
    )

    assert wunsch["excludeWeekdays"] == [4]
    assert wunsch["weekdays"] == [1, 2, 5]
    assert (wunsch["hourMin"], wunsch["hourMax"]) == (12, 18)


def test_pick_slots_verletzt_harte_grenzen_auch_im_fallback_nicht():
    wish = {
        "excludeWeekdays": [4],
        "weekdays": [1, 2, 3, 5],
        "hourMin": 12,
        "hourMax": 18,
    }

    picked = pick_slots(ALLE, wish=wish, now_ms=0)

    assert picked["wishMatched"] is True
    assert picked["slots"]
    assert all(x["iso"] not in {DONNERSTAG_11, DONNERSTAG_14, MONTAG_11}
               for x in picked["slots"])


def test_nur_donnerstag_liefert_keinen_verbotenen_ausweichslot():
    picked = pick_slots(
        [DONNERSTAG_11, DONNERSTAG_14],
        wish={"excludeWeekdays": [4]},
        now_ms=0,
    )

    assert picked == {"slots": [], "wishMatched": False}


def test_flow_bietet_nach_live_korrektur_nur_erlaubte_nachmittage():
    sit = _sit()

    aus = flow._slot_praeferenz_zug(
        sit,
        "Montag, Dienstag, Mittwoch Nachmittag oder Freitagnachmittag, "
        "aber nicht Donnerstag.",
    )

    assert aus is not None
    assert "Donnerstag scheidet aus" in aus["text"]
    assert sit["offered"]
    assert all(x["iso"][11:13] >= "12" for x in sit["offered"])
    assert all(x["iso"][:10] != "2026-12-03" for x in sit["offered"])


def test_anderer_tag_sperrt_die_tage_des_bisherigen_angebots():
    sit = _sit()
    sit["offered"] = sit["offered"][:2]  # beide Donnerstag

    aus = flow._slot_praeferenz_zug(sit, "Ein anderer Tag in der Woche.")

    assert aus is not None
    assert 4 in gehirn.sammler(sit)["wunsch"]["excludeWeekdays"]
    assert all(x["iso"][:10] != "2026-12-03" for x in sit["offered"])


def test_opt_out_altpfad_waehlt_einen_konkret_genannten_slot():
    # Nur ein AUSDRUECKLICHES Opt-out (False) schaltet den Merker ab — dann
    # gilt der alte Weg: Auswahl per _slot_wahl, Ablehnung ohne Merker.
    sit = _sit()
    sit["tenant"] = dict(laden("meddent"), slotPraeferenzenFesthalten=False)

    assert flow._slot_praeferenz_zug(sit, "Nicht Donnerstag.") is None
    assert flow._slot_wahl("Montag um elf Uhr fünfzehn.", sit["offered"]) == MONTAG_11


def test_meddent_merkt_abgelehnten_donnerstag_wie_blessing():
    sit = _sit()
    sit["tenant"] = laden("meddent")

    aus = flow._slot_praeferenz_zug(sit, "Nicht Donnerstag.")

    assert aus is not None
    assert 4 in gehirn.sammler(sit)["wunsch"]["excludeWeekdays"]
    assert sit["offered"]
    assert all(x["iso"][:10] != "2026-12-03" for x in sit["offered"])


def test_verschieben_faellt_nie_auf_abgelehnten_donnerstag_zurueck(monkeypatch):
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({
        "modus": "verschieben",
        "phase": "verschieb_wunsch",
        "frage": "wunsch",
        "wunsch": {"excludeWeekdays": [4]},
    })
    sit["gefunden"] = [{
        "id": "bestand-1",
        "iso": "2026-10-21T11:00:00+02:00",
        "calendarId": "8krcWh7AuXEfgWc1blzQ",
        "doctorName": "Doktor Blessing",
        "motivId": "UnfQ5DOaMx9FLiTC3L9b",
        "motivName": "Kontrolle",
        "spoken": "am einundzwanzigsten Oktober um elf Uhr",
    }]
    sit["verwaltenTermin"] = "bestand-1"
    monkeypatch.setattr(
        verwalten.kal,
        "find_slots_behandler",
        lambda *_args, **_kwargs: {
            "ok": True,
            "slots": [DONNERSTAG_11, DONNERSTAG_14],
        },
    )

    aus = verwalten._verschieb_angebot(sit, None)

    assert "nichts Freies" in aus["text"]
    assert sit["offered"] == []
    assert s["phase"] == "verschieb_wunsch"
