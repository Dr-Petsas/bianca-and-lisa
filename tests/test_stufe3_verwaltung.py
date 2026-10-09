"""Stufe 3 (08.10.2026): Schleifen aus den Verwaltungs-Anrufen.

3a (5e30be95): keine volle Wiederholung auf die termin_ok-Frage — eine unklare
    Antwort wiederholt nur die Folgefrage (frage bleibt), ein blosser Wochentag
    gibt einen kurzen Filtersatz, die Abschiedserkennung ist breiter.
3b (dbc5e2a8): "Ja" MIT Verhoerer-Stamm ("verscheib") ist kein "passt"; ist die
    Akte gebunden und ein Termin gefunden, wird nie wieder buchstabiert.
3c (90db262e): "ob (mein) (heutiger) Termin (noch) besteht/steht/gilt" ist
    Bestandsauskunft, kein Neubuchungswunsch.
3d (b6c73304): "kein Vormittag" auf das Verschiebe-Angebot ist eine
    Ausschluss-Praeferenz, kein Vormittagswunsch.

Namen pseudonymisiert. Laeuft offline, ohne Netz, ohne Modell.
"""

import pytest

from bianca import gehirn, verwalten
from kern import intent
from kern.tenants import laden


APPT = {
    "id": "apt-s3", "iso": "2026-12-21T10:00", "date": "2026-12-21",
    "calendarId": "cal-fs", "doctorName": "Franziska Schmidt",
    "motivId": "vm-k", "motivName": "Kontrolluntersuchung",
    "spoken": "am Montag, den einundzwanzigsten Dezember um zehn Uhr bei Franziska Schmidt",
    "patientName": "Pseudo Nym",
}


def _sit_termin_ok() -> dict:
    sit = {"tenant": laden("meddent"),
           "messages": [{"role": "system", "content": "x"}],
           "stimme": "bianca",
           "gefunden": [dict(APPT)],
           "booking": {"appointmentId": "apt-s3"}}
    s = gehirn.sammler(sit)
    s.update({"modus": "auskunft", "phase": "fertig", "frage": "termin_ok",
              "nachname": "Nym", "vorname": "Pseudo"})
    return sit


# --- 3a: termin_ok ----------------------------------------------------------

def test_termin_ok_unklar_wiederholt_folgefrage_statt_leeren():
    sit = _sit_termin_ok()
    s = gehirn.sammler(sit)
    aus = verwalten._termin_ok_zug(sit, "Ähm, hm, also.", set())
    assert aus is not None, "unklare Antwort darf nicht an Modell/Anker fallen"
    assert "verschieben oder absagen" in aus["text"]
    assert s["frage"] == "termin_ok", "frage bleibt stehen"


def test_termin_ok_unklar_deckel_gibt_irgendwann_ab():
    sit = _sit_termin_ok()
    s = gehirn.sammler(sit)
    for _ in range(verwalten._TERMIN_OK_WDH_MAX):
        assert verwalten._termin_ok_zug(sit, "Hm.", set()) is not None
    # nach dem Deckel uebernimmt der normale Weg (Hirn/Modell)
    aus = verwalten._termin_ok_zug(sit, "Hm.", set())
    assert aus is None
    assert s["frage"] == ""


def test_termin_ok_blosser_wochentag_passt_kurzer_filtersatz():
    sit = _sit_termin_ok()
    aus = verwalten._termin_ok_zug(sit, "Montag?", set())
    assert aus is not None
    assert "Ja, Ihr Termin ist am Montag" in aus["text"]
    assert "Passt der so" in aus["text"]


def test_termin_ok_falscher_wochentag_ehrlich():
    sit = _sit_termin_ok()
    aus = verwalten._termin_ok_zug(sit, "Dienstag?", set())
    assert aus is not None
    assert "am Dienstag haben Sie keinen Termin" in aus["text"]
    assert "einundzwanzigsten Dezember" in aus["text"]


def test_termin_ok_breiter_abschied_legt_auf():
    for satz in ["Bis dann.", "Machen Sie's gut.", "Das war alles, danke.",
                 "Schönen Feierabend."]:
        sit = _sit_termin_ok()
        aus = verwalten._termin_ok_zug(sit, satz, set())
        assert aus is not None, satz
        assert aus.get("hangup") is not None, satz


# --- 3b: Verhoerer-Stamm + Schreibweise-Sperre ------------------------------

def test_termin_ok_ja_mit_verhoerer_ist_kein_passt():
    sit = _sit_termin_ok()
    s = gehirn.sammler(sit)
    aus = verwalten._termin_ok_zug(sit, "Ja, verscheiben bitte.", set())
    assert aus is not None
    assert "bleibt es dabei" not in aus["text"], "darf nicht als Zustimmung gelten"
    assert "verschieben oder absagen" in aus["text"]
    assert s["frage"] == "termin_aendern"


def test_echtes_ja_bleibt_passt():
    sit = _sit_termin_ok()
    s = gehirn.sammler(sit)
    aus = verwalten._termin_ok_zug(sit, "Ja, passt.", set())
    assert aus is not None
    assert "bleibt es dabei" in aus["text"]
    assert s["frage"] == "sonst_noch"


def test_schreibweise_gesperrt_bei_gebundenem_termin():
    sit = _sit_termin_ok()
    sit["verwKandidat"] = "apt-s3"
    assert verwalten._schreibweise_gesperrt(sit) is True


def test_schreibweise_nicht_gesperrt_ohne_bindung():
    sit = {"tenant": laden("meddent"), "gefunden": [dict(APPT)]}
    assert verwalten._schreibweise_gesperrt(sit) is False


def test_korrektur_frage_fragt_nie_buchstabieren_bei_gebundenem_termin():
    sit = _sit_termin_ok()
    sit["verwKandidat"] = "apt-s3"
    s = gehirn.sammler(sit)
    s["nachname"] = "Nym"
    aus = verwalten._korrektur_frage(sit)
    assert "buchstabier" not in aus["text"].lower()
    assert "einundzwanzigsten Dezember" in aus["text"]


# --- 3c: Bestandsfrage "besteht/steht/gilt" ---------------------------------

LIVE_3C = [
    "Ob mein Termin noch besteht?",
    "Ich wollte wissen, ob der heutige Termin steht.",
    "Ob mein Termin morgen noch gilt?",
    "Ob der Termin noch gilt.",
]
KEIN_3C = [
    "Ob ich einen Termin bekommen kann?",
    "Ich möchte wissen, ob Sie morgen einen Termin frei haben.",
    "Ich hätte gern einen Termin.",
]


def test_3c_regex_erkennt_besteht_steht_gilt():
    for satz in LIVE_3C:
        assert intent._BESTANDSFRAGE_RE.search(satz), satz
        assert gehirn._AUSKUNFT_RE.search(satz), satz


def test_3c_regex_verschont_neubuchung():
    for satz in KEIN_3C:
        # "ob der heutige Termin besteht" trifft, ein Terminwunsch nie
        assert not intent._BESTANDSFRAGE_RE.search(satz), satz


# --- 3d: Tageszeit-Ausschluss beim Verschieben ------------------------------

def test_3d_kein_vormittag_ist_ausschluss_kein_wunsch():
    from kern.slots import slot_praeferenz_aenderung
    a = slot_praeferenz_aenderung("kein Vormittag")
    assert a and a.get("excludeHourRanges"), a
    assert a.get("hourMin") is None and a.get("hourMax") is None


def test_3d_verschieb_angebot_nimmt_praeferenz_und_sucht_neu(monkeypatch):
    sit = {"tenant": laden("meddent"),
           "messages": [{"role": "system", "content": "x"}],
           "stimme": "bianca"}
    s = gehirn.sammler(sit)
    s.update({"modus": "verschieben", "phase": "verschieb_angebot",
              "wunsch": None,
              "arzt": {"calendarId": "cal-fs", "calendarName": "Franziska Schmidt"}})
    sit["offered"] = [{"iso": "2026-12-22T09:00", "spoken": "Dienstag um neun Uhr"},
                      {"iso": "2026-12-22T10:00", "spoken": "Dienstag um zehn Uhr"}]
    sit["verwKandidat"] = "apt-s3"
    sit["gefunden"] = [dict(APPT)]
    sit["booking"] = {"appointmentId": "apt-s3"}

    gerufen = {}

    def _fake_angebot(sit2, melde):
        gerufen["wunsch"] = dict(gehirn.sammler(sit2).get("wunsch") or {})
        return {"text": "neu gesucht"}

    monkeypatch.setattr(verwalten, "_verschieb_angebot", _fake_angebot)
    aus = verwalten.zug(sit, "kein Vormittag", set())
    assert aus and aus["text"] == "neu gesucht"
    assert gerufen["wunsch"].get("excludeHourRanges"), gerufen


# --- 3e: Buchstabiertafel ----------------------------------------------------

def test_3e_tafel_kennt_suedpol_und_kaiser():
    from bianca import buchstaben
    assert buchstaben._TAFEL.get("kaiser") == "k"
    assert buchstaben._TAFEL.get("südpol") == "s"
    assert buchstaben._TAFEL.get("suedpol") == "s"


def test_3e_fuehrender_laut_wird_nicht_verschluckt():
    from bianca import buchstaben
    assert buchstaben.deute("M-A-R-U-D-A")["name"] == "Maruda"
    assert buchstaben.deute("Mm A R U D A")["name"] == "Maruda"
