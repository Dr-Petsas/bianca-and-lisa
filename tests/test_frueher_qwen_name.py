"""Anrufe 06.10.2026: „früher bitte“ im Slotangebot und die Qwen-Namensschleife.

W-FRUEHER-EHRLICH (58bed965, dbbd63d4, a454b45c): auf „Nein, ich brauche einen
früheren“ / „das ist zu spät“ / „dieses Jahr noch“ bot Bianca einen noch
SPÄTEREN Termin an. W-QWEN-NAME-ALLE-MODI (17d53232, 7fbed2d9, af10c094): bei
der Terminauskunft löste jedes „Nein“ auf „Ich habe auch X verstanden. Ist das
richtig?“ eine neue Suche aus und dieselbe Frage kam bis zu siebenmal.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from bianca import agent, flow, gehirn, hintergrund, session, verwalten
from kern import calendar, qwen_korrektor
from kern.tenants import laden


def _iso(tage: int, stunde: int, minute: int = 0) -> str:
    tag = datetime.now(gehirn.TZ).date() + timedelta(days=tage)
    return f"{tag.isoformat()}T{stunde:02d}:{minute:02d}:00+02:00"


def _leerer_wunsch() -> dict:
    return {"weekday": None, "hourMin": None, "hourMax": None, "hour": None,
            "minDaysAhead": 0, "date": None, "tage": None, "von": None, "bis": None}


def _angebot_sit(tenant: str, offered: list[str], vorrat: list[str] | None = None) -> dict:
    sit = session.neu(tenant=laden(tenant))
    agent.start_reply(sit)
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen", "phase": "angebot", "frage": "slotwahl",
        "warSchonMal": True,
        "arzt": {"typ": "genannt", "calendarId": "kal-1", "calendarName": "Doktor Test"},
        "grund": "Kontrolle", "grundWortlaut": "Kontrolle",
        "motivId": "kontrolle", "motivName": "Kontrolle",
        "vorname": "Julia", "nachname": "Berger", "buchstabiert": True,
        "versicherung": "gesetzlich",
        "wunsch": _leerer_wunsch(),
    })
    sit["slotVorrat"] = list(vorrat if vorrat is not None else offered)
    sit["offered"] = [{"iso": i, "spoken": flow.spoken_slot(i)} for i in offered]
    sit["vorratFuer"] = hintergrund.vorrat_schluessel(sit)
    sit["vorratGemerkt"] = True
    return sit


@pytest.fixture
def notizen(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(verwalten, "DATA_DIR", tmp_path)
    monkeypatch.setattr(flow.hintergrund, "anstossen", lambda sit: None)
    datei = tmp_path / "praxis_notizen.jsonl"

    def lesen() -> list[dict]:
        if not datei.exists():
            return []
        return [json.loads(z) for z in datei.read_text(encoding="utf-8").splitlines() if z.strip()]
    return lesen


# --- Erkennung: Live-Wortlaute und Gegenproben ------------------------------

def test_live_saetze_wollen_frueher():
    dez = [_iso(60, 16, 10)]
    for satz in (
        "Nein, ich brauche einen früheren.",
        "Nee, das ist zu spät.",
        "Nein, das ist viel zu spät.",
        "Nein, ich brauche früher einen Termin.",
        "Früher bitte.",
        "Das dauert mir zu lange.",
    ):
        assert flow.will_frueher(satz, dez), satz


def test_jahr_und_monat_nur_wenn_das_angebot_spaeter_liegt():
    naechstes_jahr = datetime.now(gehirn.TZ).year + 1
    januar = [f"{naechstes_jahr}-01-12T10:00:00+01:00"]
    for satz in (
        "Nein, ich bräucht in diesem Jahr noch einen Termin.",
        f"Ich brauche bitte einen Termin in {naechstes_jahr - 1} und nicht {naechstes_jahr}.",
        "Dieses Jahr hätte ich gerne, am besten diesen Monat.",
    ):
        assert flow.will_frueher(satz, januar), satz
    # Gegenprobe: das Angebot liegt schon in diesem Jahr.
    bald = [_iso(3, 10)]
    if bald[0][:4] == str(naechstes_jahr - 1):
        assert not flow.will_frueher("Dieses Jahr noch, bitte.", bald)
    assert not flow.will_frueher(f"Nicht {naechstes_jahr}.", januar)


def test_gegenproben_sind_kein_frueher_wunsch():
    zwei = [_iso(10, 9), _iso(12, 15)]
    for satz in (
        "Ich kann nicht früher.",
        "Früher war ich bei Doktor Petsas.",
        "Den früheren nehme ich.",
        "Lieber später.",
        "Nicht so früh bitte.",
        "Ja, passt.",
        "Am Dienstag lieber.",
    ):
        assert not flow.will_frueher(satz, zwei), satz


# --- Verhalten im Angebot --------------------------------------------------

def test_58bed965_frueher_bietet_nie_den_spaeteren_slot(notizen):
    erst, spaeter = _iso(5, 16, 10), _iso(5, 16, 20)
    sit = _angebot_sit("meddent", [erst], vorrat=[erst, spaeter])
    aus = flow.zug(sit, "Nein, ich brauche einen früheren.")
    assert "Früher habe ich leider keinen freien Termin" in aus["text"]
    assert [o["iso"] for o in sit["offered"]] == [erst]
    assert flow.spoken_slot(spaeter) not in aus["text"]
    assert gehirn.sammler(sit)["frage"] == "slotwahl"
    assert notizen() == []


def test_zweites_zu_spaet_schreibt_echte_rueckrufnotiz(notizen):
    erst = _iso(90, 10)
    sit = _angebot_sit("blessing", [erst])
    flow.zug(sit, "Nein, das ist zu spät.")
    aus = flow.zug(sit, "Nein, das ist viel zu spät.")
    assert "früheren Termin" in aus["text"]
    assert "meldet sich" in aus["text"]
    s = gehirn.sammler(sit)
    assert s["phase"] == "fertig"
    assert sit["offered"] == []
    zeilen = notizen()
    assert len(zeilen) == 1
    assert "Früherer Termin gewünscht" in json.dumps(zeilen[0], ensure_ascii=False)


def test_frueherer_slot_aus_dem_vorrat_wird_angeboten(notizen):
    morgens, nachmittags = _iso(5, 9), _iso(5, 16, 10)
    sit = _angebot_sit("meddent", [nachmittags], vorrat=[morgens, nachmittags])
    aus = flow.zug(sit, "Nee, das ist zu spät.")
    assert aus["text"].startswith("Früher hätte ich")
    assert [o["iso"] for o in sit["offered"]] == [morgens]


def test_gesperrter_slot_kommt_nicht_als_frueherer_zurueck(notizen):
    morgens, nachmittags = _iso(5, 9), _iso(5, 16, 10)
    sit = _angebot_sit("meddent", [nachmittags], vorrat=[morgens, nachmittags])
    sit["slotGesperrt"] = [morgens]
    aus = flow.zug(sit, "Nee, das ist zu spät.")
    assert "Früher habe ich leider keinen freien Termin" in aus["text"]


def test_spaeter_suchstart_wird_einmal_geloest(monkeypatch, notizen):
    erst = _iso(40, 10)
    sit = _angebot_sit("meddent", [erst])
    s = gehirn.sammler(sit)
    s["wunsch"] = dict(_leerer_wunsch(), date=erst[:10])
    gerufen = []

    def _angebot(sit_arg, melde=None):
        gerufen.append(dict(gehirn.sammler(sit_arg)["wunsch"]))
        return {"text": "neues Angebot"}

    monkeypatch.setattr(flow, "_angebot", _angebot)
    aus = flow._frueher_zug(sit, "Das ist zu spät.")
    assert aus == {"text": "neues Angebot"}
    assert gerufen and gerufen[0].get("date") is None


def test_auswahl_aus_mehreren_bleibt_auswahl():
    sit = _angebot_sit("meddent", [_iso(10, 9), _iso(12, 15)])
    assert flow._frueher_zug(sit, "Den früheren nehme ich.") is None


def test_notaus_frueher(monkeypatch):
    monkeypatch.setenv("FRUEHER_EHRLICH", "0")
    sit = _angebot_sit("meddent", [_iso(5, 16, 10)])
    assert flow._frueher_zug(sit, "Nein, ich brauche einen früheren.") is None


# --- Qwen-Namensfrage bei der Terminauskunft --------------------------------

def _auskunft_sit(monkeypatch) -> tuple[dict, list[str]]:
    gesucht: list[str] = []

    def _nicht_gefunden(tenant, ctx, *a, **k):
        gesucht.append(str(ctx.get("lastName") or ""))
        return {"ok": True, "notFound": True, "appointments": [], "httpStatus": 404}

    monkeypatch.setattr(calendar, "find_patient_appointments", _nicht_gefunden)
    monkeypatch.setattr(calendar, "find_appointments_by_date",
                        lambda *a, **k: {"ok": True, "appointments": []})
    monkeypatch.setattr(qwen_korrektor, "namens_vorschlag", lambda sit, name: "Arztfeld")
    sit = {"tenant": laden("blessing"), "messages": [], "stimme": "bianca", "tools": []}
    s = gehirn.sammler(sit)
    s.update({"modus": "auskunft", "nachname": "Fahrfeld", "vorname": "Agnes", "phase": ""})
    sit["verwAktiv"] = True
    erst = verwalten._dispatch(sit, None)
    assert "Arztfeld" in erst["text"] and s["frage"] == "qwen_name"
    return sit, gesucht


def test_af10c094_nein_auf_qwen_vorschlag_sucht_nicht_erneut(monkeypatch):
    sit, gesucht = _auskunft_sit(monkeypatch)
    vorher = len(gesucht)
    aus = flow.zug(sit, "Nein.")
    assert len(gesucht) == vorher
    assert "Arztfeld" not in aus["text"]
    assert gehirn.sammler(sit)["frage"] == "nachname"


def test_7fbed2d9_korrektur_im_nein_wird_gesucht(monkeypatch):
    sit, gesucht = _auskunft_sit(monkeypatch)
    aus = flow.zug(sit, "Nein, es ist nicht richtig, ich heiße Erfeld.")
    assert gesucht[-1] == "Erfeld"
    assert "Arztfeld" not in aus["text"]


def test_qwen_vorschlag_kommt_nie_zweimal(monkeypatch):
    sit, gesucht = _auskunft_sit(monkeypatch)
    texte = [flow.zug(sit, satz)["text"] for satz in ("Nein.", "Nein.", "Nein, ist nicht richtig.")]
    assert all("Arztfeld" not in t for t in texte)


def test_notaus_qwen_name(monkeypatch):
    monkeypatch.setenv("QWEN_NAME_EINMAL", "0")
    monkeypatch.setattr(qwen_korrektor, "namens_vorschlag", lambda sit, name: "Busch")
    sit = {"tenant": laden("meddent"), "messages": []}
    s = gehirn.sammler(sit)
    s.update({"modus": "absagen", "nachname": "Pusch"})
    verwalten._korrektur_frage(sit)
    assert s["frage"] == "qwen_name"
    assert not sit.get("qwenNameVerbraucht")
