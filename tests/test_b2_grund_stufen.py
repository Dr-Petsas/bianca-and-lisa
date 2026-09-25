"""V5.5-Fachfallback: "Leistung nicht angeboten" NUR bei klar Fachfremdem.

Blessing-Anrufe 66913eb8 / a467367e: "Dornwarzen am Fuß" landete über den
Fuzzy-Katalog bei "Beratung Behandlung Botox / Filler", der Verhörer
"Matzenbehandlung" (Warzenbehandlung) und "Termin zum Vereisen" bekamen
sofort "Diese Leistung wird in dieser Praxis nicht angeboten" plus dieselbe
Grund-Frage — bis der Wiederholungs-Wächter strich und die Presence-Schleife
lief. Kein Anruf wurde gelöst.

Der kanonische V5.5-Vertrag konvergiert unbekannte, nicht fachfremde Gründe
sofort auf das sichere Kontrollmotiv und hält den O-Ton für die Terminnotiz.
Erkennbare Hautbeschwerden dürfen auf die allgemeine Sprechstunde. Eine
separate B2-Nachfrage-/Rückrufmaschine gehört nicht zum V5.5-Produktionspfad.

Die Absage "nicht angeboten" bleibt für klar Fachfremdes (Zahnwunsch beim
Hautarzt). MedDent/Thaler (Zahn) laufen byte-identisch weiter.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from bianca import agent, besuchsgrund, flow, gehirn, session
from kern import hirn
from kern.tenants import laden

SPRECHSTUNDE = "5PuSqKkTtTgYuaYhajm5"
BOTOX = "2oJ9lYZK9KEABwxezFWZ"
BLESSING_KAL = "8krcWh7AuXEfgWc1blzQ"


@pytest.fixture(autouse=True)
def _kein_intent_nachzug(monkeypatch):
    monkeypatch.setenv("INTENT_NACHZUG", "0")
    monkeypatch.setenv("NAMENS_LINK", "0")


@pytest.fixture(autouse=True)
def _kein_llm(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("B2-Stufen laufen deterministisch — nie ans Modell")
    monkeypatch.setattr(agent.llm, "chat_stream", boom)
    monkeypatch.setattr(agent.llm, "chat", boom)


def _sit(tenant: dict | None = None) -> dict:
    sit = session.neu(tenant=tenant or laden("blessing"))
    agent.start_reply(sit)
    hirn.anliegen_hinzufuegen(
        sit,
        hirn.anliegen_neu("ANLEGEN", "VORGANG", spiegel="Termin vereinbaren"),
        aktivieren=True,
    )
    gehirn.sammler(sit).update({
        "modus": "buchen",
        "phase": "",
        "frage": "grund",
        "warSchonMal": False,
    })
    return sit


def _ohne_auffang() -> dict:
    """Blessing-Kopie ohne Sprechstunde/Kontrolle: Stufe 3 statt Stufe 2."""
    t = copy.deepcopy(laden("blessing"))
    t["visitMotives"] = [
        v for v in t["visitMotives"]
        if v["name"] not in ("Sprechstunde", "Kontrolle", "Kontrolluntersuchung")
    ]
    return t


def _iso_in(tage: int, h: int, m: int = 0) -> str:
    d = datetime.now(ZoneInfo("Europe/Berlin")).replace(
        hour=h, minute=m, second=0, microsecond=0) + timedelta(days=tage)
    return d.isoformat(timespec="seconds")


# --- Mapping: Hautbeschwerden -> Sprechstunde, nie Botox ---------------------

@pytest.mark.parametrize(
    "gesagt",
    [
        "Dornwarzen am Fuß.",
        "Ich brauche einen Termin zum Vereisen.",
        "Ich habe Warzen.",
        "Meine Haut juckt seit Tagen.",
        "Ich habe eine Warze am Finger, die weg soll.",
    ],
)
def test_hautbeschwerde_landet_in_der_sprechstunde_nie_bei_botox(gesagt):
    t = laden("blessing")
    kern, vm = besuchsgrund.deute(t, gesagt, katalog=t["visitMotives"])
    assert vm, (gesagt, kern)
    assert vm["id"] != BOTOX, (gesagt, vm)
    assert vm["id"] == SPRECHSTUNDE, (gesagt, kern, vm)


def test_verhoerer_trifft_kein_katalogmotiv():
    """"Matzenbehandlung" (STT für Warzenbehandlung) traf live über das
    generische Namens-Wort "Behandlung" Botox/Filler — jetzt kein Treffer."""
    t = laden("blessing")
    kern, vm = besuchsgrund.deute(t, "Matzenbehandlung.", katalog=t["visitMotives"])
    assert not vm, (kern, vm)


def test_generisches_motiv_ist_die_sprechstunde():
    t = laden("blessing")
    vm = besuchsgrund.generisches_motiv(t, katalog=t["visitMotives"])
    assert vm and vm["id"] == SPRECHSTUNDE
    assert besuchsgrund.generisches_motiv(
        _ohne_auffang(), katalog=_ohne_auffang()["visitMotives"]) is None


def test_ist_derma_beschwerde_nur_mit_opt_in():
    t = laden("blessing")
    assert besuchsgrund.ist_derma_beschwerde(t, "Dornwarzen am Fuß.")
    assert not besuchsgrund.ist_derma_beschwerde(t, "Matzenbehandlung.")
    assert not besuchsgrund.ist_derma_beschwerde(t, "Ich möchte eine Zahnreinigung.")
    assert not besuchsgrund.ist_derma_beschwerde(laden("meddent"), "Meine Haut juckt.")


# --- Sicherer V5.5-Fallback mit O-Ton ----------------------------------------

def test_unbekannter_grund_konvergiert_sofort_auf_kontrolle_mit_o_ton():
    sit = _sit()
    s = gehirn.sammler(sit)

    z1 = flow.zug(sit, "Matzenbehandlung.")
    assert z1 and "nicht angeboten" not in z1["text"].lower()
    assert "nicht sicher" not in z1["text"].lower()
    assert "kontroll" in s["motivName"].lower()
    assert s["grundGenerisch"] is True
    assert s["grundWortlaut"] == "Matzenbehandlung."
    assert "grundKlaerungen" not in sit
    assert s["frage"] != "grund", (s["frage"], z1["text"])


def test_unbekannter_grund_oeffnet_keine_nachfrageschleife():
    sit = _sit()
    frage1 = flow.zug(sit, "Matzenbehandlung.")
    assert frage1 and gehirn.sammler(sit)["frage"] != "grund"
    assert "grundKlaerungen" not in sit


def test_direkte_hautbeschwerde_ohne_umweg():
    sit = _sit()
    s = gehirn.sammler(sit)
    z1 = flow.zug(sit, "Dornwarzen am Fuß.")
    assert z1 and "nicht angeboten" not in z1["text"].lower()
    assert "nicht sicher" not in z1["text"].lower()
    assert s["motivId"] == SPRECHSTUNDE
    assert not s.get("grundGenerisch")
    assert "grundKlaerungen" not in sit
    assert s["frage"] != "grund"


def test_frage_des_anrufers_wird_nicht_als_grund_geerntet():
    sit = _sit()
    s = gehirn.sammler(sit)
    gehirn.einsammeln(sit, "Was kostet das denn?")
    assert not s["grund"] and not s["motivId"]
    assert "grundKlaerungen" not in sit
    # ein zoegernder Grund mit Fragezeichen der STT bleibt ein Grund
    gehirn.einsammeln(sit, "Dornwarzen?")
    assert s["motivId"] == SPRECHSTUNDE


def test_grund_ist_frage_kennt_die_typischen_formen():
    assert gehirn._grund_ist_frage("Was kostet das?")
    assert gehirn._grund_ist_frage("Kann ich auch vormittags kommen?")
    assert gehirn._grund_ist_frage("Wie lange dauert das?")
    assert not gehirn._grund_ist_frage("Dornwarzen?")
    assert not gehirn._grund_ist_frage("Kontrolle.")
    assert not gehirn._grund_ist_frage("Ja.")


# --- Kein fremder B2-Rückrufpfad im kanonischen V5.5-Fluss ------------------

def test_unbekannter_grund_oeffnet_keinen_abgeben_oder_notizpfad(tmp_path, monkeypatch):
    monkeypatch.setattr(flow.verwalten, "DATA_DIR", tmp_path)
    sit = _sit(_ohne_auffang())
    s = gehirn.sammler(sit)

    z1 = flow.zug(sit, "Matzenbehandlung.")
    assert z1 and "nicht angeboten" not in z1["text"].lower()
    assert not s["motivId"] and s["grundGenerisch"] is True
    assert s["grundWortlaut"] == "Matzenbehandlung."
    assert not sit.get("hirnAbgeben")
    assert not sit.get("praxisNotiz")


def test_unbekannter_grund_bleibt_auch_mit_bekannten_kontaktdaten_im_terminpfad(
        tmp_path, monkeypatch):
    monkeypatch.setattr(flow.verwalten, "DATA_DIR", tmp_path)
    sit = _sit(_ohne_auffang())
    s = gehirn.sammler(sit)
    s.update({"nachname": "Müller", "vorname": "Anna", "buchstabiert": True,
              "telefon": "01771234567", "telefonOk": True})

    z1 = flow.zug(sit, "Matzenbehandlung.")
    assert z1 and s["frage"] != "grund"
    assert not s["motivId"] and s["grundGenerisch"] is True
    assert not sit.get("praxisNotiz")
    assert not z1.get("hangup")


# --- Eskalation (zweimal unklar) konvergiert statt zu wiederholen ------------

def test_eskalation_grund_landet_in_der_kontrolle_statt_derselben_frage():
    sit = _sit()
    s = gehirn.sammler(sit)
    sit["grundKlaerungText"] = "Matzenbehandlung."
    uebergang = flow._eskalieren(sit, "grund")
    assert "kontrolle" in uebergang.lower()
    assert "kontroll" in s["motivName"].lower() and s["grundGenerisch"] is True
    assert s["grundWortlaut"] == "Matzenbehandlung."
    # zug() fragt nach der Eskalation die naechste Pflichtfrage — nie wieder
    # den Grund (die Schleife der Blessing-Anrufe).
    fid2, _frage2 = gehirn.naechste_frage(sit)
    assert fid2 != "grund", fid2


def test_eskalation_grund_oeffnet_keinen_fremden_rueckrufpfad(tmp_path, monkeypatch):
    monkeypatch.setattr(flow.verwalten, "DATA_DIR", tmp_path)
    sit = _sit(_ohne_auffang())
    s = gehirn.sammler(sit)
    aus = flow._grund_eskalation_abgeben(sit, "Hm, äh.")
    assert aus is None
    assert not sit.get("hirnAbgeben") and not sit.get("praxisNotiz")
    assert flow._grund_eskalation_abgeben(_sit(laden("meddent")), "Hm.") is None


# --- Gegenproben ---------------------------------------------------------------

def test_fachfremder_zahnwunsch_bleibt_abgelehnt_ohne_nachfrage():
    sit = _sit()
    s = gehirn.sammler(sit)
    aus = flow.zug(sit, "Ich möchte eine Zahnreinigung.")
    assert aus and "nicht angeboten" in aus["text"].lower()
    assert not s["grund"] and not s["motivId"]
    assert "grundKlaerungen" not in sit


def test_meddent_unbekannter_grund_bleibt_kontroll_fallback():
    sit = _sit(laden("meddent"))
    s = gehirn.sammler(sit)
    aus = flow.zug(sit, "Matzenbehandlung.")
    assert aus and "nicht sicher" not in aus["text"].lower()
    assert "nicht angeboten" not in aus["text"].lower()
    assert s["grund"] == "Matzenbehandlung."
    assert "kontroll" in s["motivName"].lower()
    assert s.get("grundGenerisch") is True
    assert "grundKlaerungen" not in sit


def test_klarer_katalog_treffer_raeumt_generisch_flag():
    sit = _sit()
    s = gehirn.sammler(sit)
    flow.zug(sit, "Matzenbehandlung.")
    flow.zug(sit, "Matzenbehandlung.")
    assert s["grundGenerisch"] is True
    # Anrufer korrigiert auf einen echten Katalog-Grund
    gehirn.einsammeln(sit, "Ach, eigentlich geht es um Nagelpilz.")
    assert s["motivName"] == "Nagelpilz"
    assert s["grundGenerisch"] is False


def test_motiv_fuer_kalender_haelt_generisches_motiv():
    """Der O-Ton darf beim Kontext-Bau nicht erneut unscharf gegen den
    Katalog gerieben werden (live: Matzenbehandlung -> Botox)."""
    sit = _sit()
    s = gehirn.sammler(sit)
    flow.zug(sit, "Matzenbehandlung.")
    flow.zug(sit, "Matzenbehandlung.")
    vm = gehirn.motiv_fuer_kalender(sit, BLESSING_KAL)
    assert vm and "kontroll" in vm["name"].lower(), vm
    assert s["motivId"] == vm["id"]


# --- Buchung: O-Ton steht IMMER in der Terminnotiz ---------------------------

def test_buchung_mit_generischem_motiv_traegt_o_ton_als_notiz(monkeypatch):
    sit = _sit()
    s = gehirn.sammler(sit)
    flow.zug(sit, "Matzenbehandlung.")
    flow.zug(sit, "Matzenbehandlung.")
    assert "kontroll" in s["motivName"].lower() and s["grundGenerisch"] is True
    kontroll_id = s["motivId"]
    s.update({
        "phase": "bestaetigen", "frage": "", "pzr": "nein",
        "nachname": "Müller", "vorname": "Anna", "buchstabiert": True,
        "telefon": "01771234567", "telefonOk": True,
        "phoneConfirmed": "01771234567", "phoneInChart": "01771234567",
        "arzt": {"typ": "einzig", "calendarId": BLESSING_KAL,
                 "calendarName": "Doktor Charlotte Blessing"},
        "slotIso": _iso_in(3, 9),
    })
    sit["offered"] = [{"iso": s["slotIso"], "spoken": "Donnerstag um neun"}]
    sit["angebotKalender"] = {"calendarId": BLESSING_KAL,
                              "calendarName": "Doktor Charlotte Blessing"}
    gebucht: list[dict] = []
    notizen: list[str] = []

    def fake_book(tenant, ctx, slot_iso=""):
        gebucht.append(dict(ctx))
        return {"ok": True, "booked": True, "slotIso": slot_iso,
                "appointmentId": "apt-1", "spoken": "Der Termin ist fest eingetragen."}

    monkeypatch.setattr(flow.kal, "book_slot", fake_book)
    monkeypatch.setattr(
        flow.kal, "note_appointment",
        lambda tenant, ctx, sit2=None, note="": notizen.append(note) or {"ok": True})

    aus = flow._buchen(sit)
    assert s["phase"] == "gebucht", aus
    assert gebucht and gebucht[0]["visitMotiveId"] == kontroll_id, gebucht
    assert any("Matzenbehandlung" in n and "im Katalog nicht zuordenbar" in n
               and "Kontrolle" in n for n in notizen), notizen
