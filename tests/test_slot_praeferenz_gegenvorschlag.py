"""A6 (17.09.2026): Ablehnung MIT Gegenvorschlag waehlt direkt, statt neu zu suchen.

Befund BEFUND-BIANCA-ALLE-ANRUFE-2026-09-17: "Nicht Donnerstag, lieber Montag"
loeste bei MedDent/Thaler eine komplette Neusuche aus, obwohl der Montag schon
im Angebot stand — eine Ehrenrunde pro Korrektur. Die Uhrzeit im
Gegenvorschlag ("nicht um elf, lieber um zwei") ging dabei ganz verloren.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from bianca import agent, flow, gehirn, hintergrund, session
from kern.slots import slot_praeferenz_aenderung, wunsch_mit_slot_praeferenz
from kern.tenants import laden


_IN_ZWEI_WOCHEN = date.today() + timedelta(days=14)
_MONTAG = _IN_ZWEI_WOCHEN - timedelta(days=_IN_ZWEI_WOCHEN.weekday())
_DIENSTAG = _MONTAG + timedelta(days=1)
_MITTWOCH = _MONTAG + timedelta(days=2)
_DONNERSTAG = _MONTAG + timedelta(days=3)


def _iso(tag: date, stunde: int, minute: int = 0) -> str:
    return datetime.combine(tag, time(stunde, minute)).astimezone().isoformat(timespec="seconds")


MONTAG_09 = _iso(_MONTAG, 9)
DONNERSTAG_11 = _iso(_DONNERSTAG, 11)
DONNERSTAG_14 = _iso(_DONNERSTAG, 14, 40)
DIENSTAG_10 = _iso(_DIENSTAG, 10)
MITTWOCH_15 = _iso(_MITTWOCH, 15)
OFFERED = [MONTAG_09, DONNERSTAG_11, DONNERSTAG_14]


def _sit(tenant_id: str = "meddent") -> dict:
    sit = session.neu(tenant=laden(tenant_id))
    agent.start_reply(sit)
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "phase": "angebot",
        "frage": "slotwahl",
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
        "wunsch": {
            "weekday": None, "hourMin": None, "hourMax": None, "hour": None,
            "minDaysAhead": 0, "date": None, "tage": None, "von": None, "bis": None,
        },
    })
    sit["slotVorrat"] = list(OFFERED) + [DIENSTAG_10, MITTWOCH_15]
    sit["offered"] = [
        {"iso": MONTAG_09, "spoken": "Montag um neun Uhr"},
        {"iso": DONNERSTAG_11, "spoken": "Donnerstag um elf Uhr"},
        {"iso": DONNERSTAG_14, "spoken": "Donnerstag um vierzehn Uhr vierzig"},
    ]
    sit["vorratFuer"] = hintergrund.vorrat_schluessel(sit)
    sit["vorratGemerkt"] = True
    return sit


# --- Parser: Gegenvorschlag wird gelesen -----------------------------------

def test_gegenvorschlag_stunde_wird_erkannt():
    a = slot_praeferenz_aenderung("Nicht um elf Uhr, lieber um zwei.", offered_isos=OFFERED)
    assert a is not None
    assert a["excludeHours"] == [11]
    assert a["hour"] == 14


def test_gegenvorschlag_stunde_ersetzt_alte_tageszeit_im_wunsch():
    a = slot_praeferenz_aenderung("Nicht um elf Uhr, lieber um zwei.")
    w = wunsch_mit_slot_praeferenz({"hourMin": 8, "hourMax": 12}, a)
    assert w["hour"] == 14
    assert w["hourMin"] is None and w["hourMax"] is None
    assert w["excludeHours"] == [11]


def test_gegenvorschlag_stunde_nie_wenn_selbst_abgelehnt():
    # "um elf nicht" — elf darf nicht zugleich Wunsch-Stunde werden.
    a = slot_praeferenz_aenderung("Um elf Uhr nicht.")
    assert a is not None
    assert a["excludeHours"] == [11]
    assert "hour" not in a


def test_tag_und_datum_desselben_tages_sind_eine_nennung():
    # "Donnerstag, der X." ist EINE Auswahl, keine zwei Alternativen.
    text = f"Donnerstag, der {_DONNERSTAG.day}."
    assert slot_praeferenz_aenderung(
        text, offered_isos=OFFERED, heute=date.today()
    ) is None


def test_zwei_tage_ohne_ablehnung_sind_alternativen():
    a = slot_praeferenz_aenderung("Dienstag oder Mittwoch", offered_isos=OFFERED)
    assert a is not None
    assert a["weekdays"] == [2, 3]
    assert "excludeWeekdays" not in a


# --- Kandidat: genau EIN ueberlebender Slot passt ---------------------------

def test_kandidat_tag_gegenvorschlag():
    a = slot_praeferenz_aenderung("Nicht Donnerstag, lieber Montag.", offered_isos=OFFERED)
    assert flow._praef_kandidat(OFFERED, a) == MONTAG_09


def test_kandidat_stunden_gegenvorschlag():
    a = slot_praeferenz_aenderung("Nicht um elf Uhr, lieber um zwei.", offered_isos=OFFERED)
    assert flow._praef_kandidat(OFFERED, a) == DONNERSTAG_14


def test_kandidat_nur_ablehnung_waehlt_nichts():
    # "Nicht Donnerstag" laesst Montag uebrig — aber der Anrufer hat ihn
    # nicht GEWAEHLT. Kein stilles Zugreifen.
    a = slot_praeferenz_aenderung("Nicht Donnerstag.", offered_isos=OFFERED)
    assert flow._praef_kandidat(OFFERED, a) == ""


def test_kandidat_mehrdeutig_waehlt_nichts():
    # "nicht um elf, lieber Donnerstag" — Donnerstag 14:40 bleibt als einziger
    # Donnerstag: eindeutig. Aber "lieber Donnerstag" bei ZWEI Donnerstagen
    # ohne Stunden-Ausschluss ist mehrdeutig.
    a = slot_praeferenz_aenderung("Nicht Montag, lieber Donnerstag.", offered_isos=OFFERED)
    assert flow._praef_kandidat(OFFERED, a) == ""


def test_kandidat_gegenvorschlag_ohne_angebot_waehlt_nichts():
    a = slot_praeferenz_aenderung("Nicht Donnerstag, lieber Dienstag.", offered_isos=OFFERED)
    assert flow._praef_kandidat(OFFERED, a) == ""


# --- Fluss: direkte Wahl statt Neusuche -------------------------------------

def test_fluss_nicht_donnerstag_lieber_montag_waehlt_montag_direkt():
    sit = _sit()
    aus = flow._slot_praeferenz_zug(sit, "Nicht Donnerstag, lieber Montag.")
    s = gehirn.sammler(sit)
    assert aus is not None
    assert s["slotIso"] == MONTAG_09
    assert s["phase"] == "bestaetigen"
    # Ablehnung bleibt trotzdem gemerkt (falls der Montag spaeter wegfaellt).
    assert 4 in s["wunsch"]["excludeWeekdays"]
    assert "Donnerstag" not in aus["text"] or "Montag" in aus["text"]


def test_fluss_nicht_elf_lieber_zwei_waehlt_donnerstag_vierzehn_direkt():
    sit = _sit()
    aus = flow._slot_praeferenz_zug(sit, "Nicht um elf Uhr, lieber um zwei.")
    s = gehirn.sammler(sit)
    assert aus is not None
    assert s["slotIso"] == DONNERSTAG_14
    assert s["phase"] == "bestaetigen"
    assert 11 in s["wunsch"]["excludeHours"]


def test_fluss_reine_auswahl_mit_datum_bleibt_slot_wahl():
    sit = _sit()
    text = f"Donnerstag, der {_DONNERSTAG.day}."
    # Kein Praeferenz-Zug (keine Neusuche): das ist eine Auswahl fuer _slot_wahl.
    assert flow._slot_praeferenz_zug(sit, text) is None
    # Zwei Donnerstage im Angebot: _slot_wahl bleibt ehrlich unklar ("") —
    # die Maschine fragt nach der Uhrzeit, statt zu raten.
    assert flow._slot_wahl(text, sit["offered"]) == ""
    # Ein Donnerstag im Angebot: eindeutige Wahl.
    einer = [sit["offered"][0], sit["offered"][2]]
    assert flow._slot_wahl(text, einer) == DONNERSTAG_14


def test_fluss_alternativtage_ohne_treffer_suchen_neu_mit_beiden_tagen():
    sit = _sit()
    aus = flow._slot_praeferenz_zug(sit, "Dienstag oder Mittwoch.")
    s = gehirn.sammler(sit)
    assert aus is not None
    assert s["wunsch"]["weekdays"] == [2, 3]
    erwartete_tage = {DIENSTAG_10[:10], MITTWOCH_15[:10]}
    assert all(x["iso"][:10] in erwartete_tage for x in sit["offered"])


def test_fluss_thaler_gleiches_verhalten():
    sit = _sit("thaler")
    aus = flow._slot_praeferenz_zug(sit, "Nicht Donnerstag, lieber Montag.")
    assert aus is not None
    assert gehirn.sammler(sit)["slotIso"] == MONTAG_09
