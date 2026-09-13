"""W-STANDORT (13.09.2026): Öffnungszeiten aus den Standorteinstellungen.

Chef: „öffnungszeiten bitte aus den Standorteinstellungen ablesen und im
prompt verankern bei blessing und thaler". Offline — Firestore ist gemockt,
die Dokument-Form ist die echte (Probe 13.09.2026 gegen docgenda).
"""
from __future__ import annotations

import datetime

import pytest

from kern import praxisregeln, standort, wissen


def _tag(von: tuple[int, int] | None, bis: tuple[int, int] | None,
         pause: tuple[tuple[int, int], tuple[int, int]] | None = None) -> dict:
    if von is None:
        return {"hasOpen": False, "hasPause": False,
                "open": {"start": {"hour": 8, "minute": 0}, "end": {"hour": 18, "minute": 0}},
                "pause": {"start": {"hour": 8, "minute": 0}, "end": {"hour": 18, "minute": 0}}}
    d = {"hasOpen": True, "hasPause": False,
         "open": {"start": {"hour": von[0], "minute": von[1]}, "end": {"hour": bis[0], "minute": bis[1]}},
         "pause": {"start": {"hour": 8, "minute": 0}, "end": {"hour": 18, "minute": 0}}}
    if pause:
        d["hasPause"] = True
        d["pause"] = {"start": {"hour": pause[0][0], "minute": pause[0][1]},
                      "end": {"hour": pause[1][0], "minute": pause[1][1]}}
    return d


THALER = {
    "enabled": True,
    "monday": _tag((7, 30), (17, 0), ((13, 30), (14, 0))),
    "tuesday": _tag((9, 30), (19, 0), ((14, 30), (15, 0))),
    "wednesday": _tag((7, 30), (17, 0), ((13, 30), (14, 0))),
    "thursday": _tag((9, 30), (19, 0), ((14, 30), (15, 0))),
    "friday": _tag(None, None),
    "saturday": _tag(None, None),
    "sunday": _tag(None, None),
}

BLESSING = {
    "enabled": True,
    "monday": _tag((8, 30), (17, 0), ((12, 30), (14, 0))),
    "tuesday": _tag((8, 30), (19, 0), ((12, 0), (14, 0))),
    "wednesday": _tag((8, 30), (13, 0)),
    "thursday": _tag((8, 30), (17, 30), ((13, 0), (14, 0))),
    "friday": _tag((8, 30), (12, 0)),
    "saturday": _tag(None, None),
    "sunday": _tag(None, None),
}

PORTAL_DEFAULT = {"enabled": False, **{t: _tag((8, 0), (18, 0)) for t in standort._TAG_EN}}


@pytest.fixture(autouse=True)
def _frisch(monkeypatch):
    standort.cache_leeren()
    monkeypatch.setattr(standort, "an", lambda: True)
    yield
    standort.cache_leeren()


def _mock_doc(monkeypatch, opening, name="Praxis", telefon="0815"):
    aufrufe: list[tuple[str, str]] = []

    def _dok(cid, lid):
        aufrufe.append((cid, lid))
        return {"name": name, "street": "Weg 1", "postalCode": "12345", "city": "Ort",
                "phoneNumber": telefon, "openingHours": opening}
    monkeypatch.setattr(standort, "_dokument", _dok)
    return aufrufe


# --- Zeiten normalisieren ---------------------------------------------------

def test_zeiten_von_teilt_pause_in_zwei_spannen_und_markiert_geschlossen():
    z = standort.zeiten_von(THALER)
    assert z["montag"] == [("07:30", "13:30"), ("14:00", "17:00")]
    assert z["dienstag"] == [("09:30", "14:30"), ("15:00", "19:00")]
    assert z["freitag"] == []
    assert z["sonntag"] == []


def test_portal_default_gilt_als_nicht_gepflegt():
    assert standort.zeiten_von(PORTAL_DEFAULT) is None


def test_enabled_am_standort_wird_ignoriert():
    # ClientLocation.fromObject setzt enabled immer true — der gespeicherte
    # Wert traegt keine Information; gepflegte Zeiten zaehlen trotzdem.
    z = standort.zeiten_von({**BLESSING, "enabled": False})
    assert z and z["mittwoch"] == [("08:30", "13:00")]


def test_unplausible_zeiten_liefern_nichts():
    kaputt = {**THALER, "monday": _tag((17, 0), (7, 30))}
    assert standort.zeiten_von(kaputt) is None
    assert standort.zeiten_von("quatsch") is None
    assert standort.zeiten_von(None) is None


# --- Sprech- und Prompt-Form -----------------------------------------------

def test_sprechform_gruppiert_gleiche_tage_und_nennt_geschlossen():
    text = standort.sprechform(standort.zeiten_von(THALER))
    assert text == (
        "Montag und Mittwoch von 7:30 Uhr bis 13:30 Uhr und von 14 Uhr bis 17 Uhr, "
        "Dienstag und Donnerstag von 9:30 Uhr bis 14:30 Uhr und von 15 Uhr bis 19 Uhr, "
        "Freitag geschlossen"
    )


def test_sprechform_fasst_wochenblock_zusammen():
    z = {t: [("09:00", "17:00")] for t in standort.TAGE[:5]}
    z.update({"samstag": [], "sonntag": []})
    assert standort.sprechform(z) == "Montag bis Freitag von 9 Uhr bis 17 Uhr"


def test_prompt_block_eine_zeile_je_tag():
    block = standort.prompt_block(standort.zeiten_von(BLESSING))
    assert block.startswith(standort.PROMPT_MARKER)
    assert "Montag: 08:30-12:30 Uhr, 14:00-17:00 Uhr" in block
    assert "Mittwoch: 08:30-13:00 Uhr" in block
    assert "Samstag: geschlossen" in block


# --- offen? -----------------------------------------------------------------

def test_offen_rechnet_mit_pause_und_geschlossenem_tag():
    z = standort.zeiten_von(THALER)
    assert standort.offen(z, datetime.datetime(2026, 9, 14, 8, 0)) is True      # Mo
    assert standort.offen(z, datetime.datetime(2026, 9, 14, 13, 45)) is False   # Mo Pause
    assert standort.offen(z, datetime.datetime(2026, 9, 18, 10, 0)) is False    # Fr zu
    assert standort.offen(None, datetime.datetime(2026, 9, 14, 8, 0)) is None


# --- Laden / Cache ----------------------------------------------------------

def test_laden_cacht_und_liest_nur_einmal(monkeypatch):
    aufrufe = _mock_doc(monkeypatch, THALER, name="Eva Thaler")
    a = standort.laden("c1", "l1")
    b = standort.laden("c1", "l1")
    assert a is not None and a["name"] == "Eva Thaler" and a["text"].startswith("Montag und Mittwoch")
    assert a == b
    assert aufrufe == [("c1", "l1")]


def test_laden_fehler_haelt_alten_stand(monkeypatch):
    _mock_doc(monkeypatch, THALER)
    a = standort.laden("c1", "l1")
    assert a and a["zeiten"]

    def _kaputt(cid, lid):
        raise RuntimeError("firestore weg")
    monkeypatch.setattr(standort, "_dokument", _kaputt)
    standort._CACHE["c1/l1"]["t"] -= 10_000  # abgelaufen
    b = standort.laden("c1", "l1")            # stale sofort, Refresh im Hintergrund
    assert b == a


def test_laden_ohne_ids_oder_aus_liefert_nichts(monkeypatch):
    aufrufe = _mock_doc(monkeypatch, THALER)
    assert standort.laden("", "l1") is None
    monkeypatch.setattr(standort, "an", lambda: False)
    assert standort.laden("c1", "l1") is None
    assert aufrufe == []


def test_laden_fehlschlag_ohne_stand_wird_negativ_gecacht(monkeypatch):
    zaehler = {"n": 0}

    def _kaputt(cid, lid):
        zaehler["n"] += 1
        raise RuntimeError("weg")
    monkeypatch.setattr(standort, "_dokument", _kaputt)
    assert standort.laden("c1", "l1") is None
    assert standort.laden("c1", "l1") is None
    assert zaehler["n"] == 1


# --- anreichern -------------------------------------------------------------

def test_anreichern_haengt_block_an_thaler_prompt_einmal(monkeypatch):
    _mock_doc(monkeypatch, THALER, name="Eva Thaler")
    t = {"clientId": "c1", "locationId": "l1",
         "dbPrompt": "SPRECHZEITEN\nMontag\n7.30 - 13.30 Uhr & 14 - 17 Uhr\nFreitag Nach Vereinbarung"}
    standort.anreichern(t)
    standort.anreichern(t)
    assert t["standort"]["name"] == "Eva Thaler"
    assert t["dbPrompt"].count(standort.PROMPT_MARKER) == 1
    assert "Freitag: geschlossen" in t["dbPrompt"]
    # der alte Fliesstext bleibt stehen — der Block ist als verbindlich markiert
    assert "SPRECHZEITEN" in t["dbPrompt"]


def test_anreichern_blessing_sprechzeiten_ohne_wert_gilt_nicht_als_explizit(monkeypatch):
    _mock_doc(monkeypatch, BLESSING, name="Blessing")
    t = {"clientId": "c1", "locationId": "l1",
         "dbPrompt": "- Sprechzeiten: \n   Montag 8.30 - 12.30 Uhr  und 14:00 bis 17:00 Uhr"}
    standort.anreichern(t)
    assert standort.PROMPT_MARKER in t["dbPrompt"]


def test_anreichern_meddent_explizite_zeile_bleibt_unangetastet(monkeypatch):
    _mock_doc(monkeypatch, {**BLESSING}, name="Zahnärzte")
    prompt = "- Öffnungszeiten:  Mo - Do: 08:00 - 18:00 Uhr,  Fr: 08:00 - 16:00 Uhr und nach Vereinbarung"
    t = {"clientId": "c1", "locationId": "l1", "dbPrompt": prompt}
    standort.anreichern(t)
    assert t["dbPrompt"] == prompt          # byte-identisch
    assert t["standort"]["name"] == "Zahnärzte"  # Fakten liegen trotzdem bereit


def test_anreichern_ohne_dokument_laesst_tenant_in_ruhe(monkeypatch):
    monkeypatch.setattr(standort, "_dokument", lambda cid, lid: None)
    t = {"clientId": "c1", "locationId": "l1", "dbPrompt": "x"}
    assert standort.anreichern(t) is t
    assert "standort" not in t and t["dbPrompt"] == "x"
    assert standort.anreichern(None) is None


# --- Wirkung: wissen + praxisregeln ------------------------------------------

def test_praxis_antwort_spricht_standort_zeiten_wenn_prompt_keine_einzeiler_hat(monkeypatch):
    _mock_doc(monkeypatch, THALER)
    t = {"clientId": "c1", "locationId": "l1", "dbPrompt": "SPRECHZEITEN\nMontag\n7.30 - 13.30 Uhr",
         "wissen": {"oeffnungszeiten": "Mo - Fr: 08:00 - 18:00 Uhr"}}
    standort.anreichern(t)
    text, bedient = wissen.praxis_antwort(t, "Wie sind Ihre Öffnungszeiten?")
    assert bedient == {"oeffnungszeiten"}
    assert "Freitag geschlossen" in text
    assert "18:00" not in text  # lokales wissen ist nur noch Rueckfall


def test_praxis_antwort_prompt_einzeiler_schlaegt_standort(monkeypatch):
    _mock_doc(monkeypatch, BLESSING)
    t = {"clientId": "c1", "locationId": "l1",
         "dbPrompt": "- Öffnungszeiten: Mo - Do: 08:00 - 18:00 Uhr, Fr: 08:00 - 16:00 Uhr"}
    standort.anreichern(t)
    text, _ = wissen.praxis_antwort(t, "Wann haben Sie geöffnet?")
    assert "montags bis donnerstags von 08:00 bis 18:00 Uhr" in text
    assert "12:30" not in text


def test_praxis_offen_nutzt_standort_zeiten(monkeypatch):
    _mock_doc(monkeypatch, BLESSING)
    t = {"clientId": "c1", "locationId": "l1", "dbPrompt": praxisregeln.NOTFALL_MARKER}
    standort.anreichern(t)
    assert praxisregeln.praxis_offen(t, datetime.datetime(2026, 9, 14, 9, 0)) is True    # Mo 9:00
    assert praxisregeln.praxis_offen(t, datetime.datetime(2026, 9, 14, 13, 0)) is False  # Mo Pause
    assert praxisregeln.praxis_offen(t, datetime.datetime(2026, 9, 18, 13, 0)) is False  # Fr nach 12
    assert praxisregeln.praxis_offen(t, datetime.datetime(2026, 9, 19, 10, 0)) is False  # Sa


def test_praxis_offen_ohne_standort_wie_bisher():
    t = {"dbPrompt": "- Sprechzeiten:\n   Montag 8.30 - 12.30 Uhr und 14:00 bis 17:00 Uhr"}
    assert praxisregeln.praxis_offen(t, datetime.datetime(2026, 9, 14, 9, 0)) is True
    assert praxisregeln.praxis_offen(t, datetime.datetime(2026, 9, 14, 13, 0)) is False
    assert praxisregeln.praxis_offen({"dbPrompt": ""}, datetime.datetime(2026, 9, 14, 9, 0)) is None
