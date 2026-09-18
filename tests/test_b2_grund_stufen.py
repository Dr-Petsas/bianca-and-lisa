"""B2 (17.09.2026): "Leistung nicht angeboten" NUR bei klar Fachfremdem.

Blessing-Anrufe 66913eb8 / a467367e: "Dornwarzen am Fuß" landete über den
Fuzzy-Katalog bei "Beratung Behandlung Botox / Filler", der Verhörer
"Matzenbehandlung" (Warzenbehandlung) und "Termin zum Vereisen" bekamen
sofort "Diese Leistung wird in dieser Praxis nicht angeboten" plus dieselbe
Grund-Frage — bis der Wiederholungs-Wächter strich und die Presence-Schleife
lief. Kein Anruf wurde gelöst.

Seitdem drei Stufen für einen Grund, den der Katalog einer Nicht-Zahn-Praxis
nicht kennt:
1. EINMAL fachsicher nachfragen (ohne "nicht angeboten").
2. Erkennbare Hautbeschwerde ODER zweiter unklarer Anlauf -> allgemeine
   Sprechstunde/Kontrolle mit dem O-Ton in der Terminnotiz.
3. Ohne solches Motiv: ehrlich absagen + echte Rückruf-Notiz (Name, Nummer).

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


# --- Stufe 1 + 2: Nachfrage, dann Sprechstunde mit O-Ton ----------------------

def test_stufe1_nachfrage_dann_stufe2_sprechstunde_mit_o_ton():
    sit = _sit()
    s = gehirn.sammler(sit)

    z1 = flow.zug(sit, "Matzenbehandlung.")
    assert z1 and "nicht angeboten" not in z1["text"].lower()
    assert "nicht sicher" in z1["text"].lower()
    assert "ärztin" in z1["text"].lower()
    assert s["frage"] == "grund" and not s["grund"] and not s["motivId"]
    assert sit.get("grundKlaerungen") == 1

    z2 = flow.zug(sit, "Matzenbehandlung.")
    assert z2 and "nicht angeboten" not in z2["text"].lower()
    assert "sprechstunde" in z2["text"].lower()
    assert s["motivId"] == SPRECHSTUNDE
    assert s["grundGenerisch"] is True
    assert s["grundWortlaut"] == "Matzenbehandlung."
    assert "grundKlaerungen" not in sit
    # die Kette laeuft weiter (naechste Pflichtfrage), keine Grund-Schleife
    assert s["frage"] != "grund", (s["frage"], z2["text"])


def test_nachfrage_kommt_nur_einmal_pro_grund():
    sit = _sit()
    frage1 = flow.zug(sit, "Matzenbehandlung.")["text"]
    frage2 = flow.zug(sit, "Matzenbehandlung.")["text"]
    assert frage1 != frage2
    assert "nicht sicher" not in frage2.lower()


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


# --- Stufe 3: kein Auffang-Motiv -> ehrlich + Rueckruf-Notiz ------------------

def test_stufe3_ohne_auffangmotiv_ehrlich_plus_rueckruf(tmp_path, monkeypatch):
    monkeypatch.setattr(flow.verwalten, "DATA_DIR", tmp_path)
    sit = _sit(_ohne_auffang())
    s = gehirn.sammler(sit)

    z1 = flow.zug(sit, "Matzenbehandlung.")
    assert z1 and "nicht sicher" in z1["text"].lower()

    z2 = flow.zug(sit, "Matzenbehandlung.")
    assert z2 and "nicht angeboten" not in z2["text"].lower()
    assert "keinen passenden termin" in z2["text"].lower()
    assert "praxisteam" in z2["text"].lower()
    assert z2["text"].rstrip().endswith("Wie ist Ihr Name?")
    assert s["frage"] == "name"
    assert not s["grund"] and not s["motivId"]
    assert (sit.get("hirnAbgeben") or {}).get("offen") is True
    assert "Matzenbehandlung" in (sit.get("hirnAbgeben") or {}).get("was", "")
    a = hirn.aktiv(sit)
    assert a and a["handlung"] == "ABGEBEN", a

    z3 = flow.zug(sit, "Müller.")
    assert z3 and "nummer" in z3["text"].lower()
    assert s["frage"] == "telefon"

    z4 = flow.zug(sit, "Null eins sieben sieben eins zwei drei vier fünf sechs sieben.")
    assert z4 and "notiert" in z4["text"].lower()
    assert sit.get("praxisNotiz"), "die Rueckruf-Notiz muss ECHT geschrieben sein"
    assert "Matzenbehandlung" in str(sit.get("praxisNotiz"))
    # Blessing (sonstNochNurNachErfolg): kurz abschliessen und auflegen
    assert z4.get("hangup") is True
    assert not (sit.get("hirnAbgeben") or {}).get("offen")


def test_stufe3_erkannter_anrufer_notiz_sofort_und_kein_termin_menue(tmp_path, monkeypatch):
    monkeypatch.setattr(flow.verwalten, "DATA_DIR", tmp_path)
    sit = _sit(_ohne_auffang())
    s = gehirn.sammler(sit)
    s.update({"nachname": "Müller", "vorname": "Anna", "buchstabiert": True,
              "telefon": "01771234567", "telefonOk": True})

    flow.zug(sit, "Matzenbehandlung.")
    z2 = flow.zug(sit, "Matzenbehandlung.")
    assert z2 and "keinen passenden termin" in z2["text"].lower()
    assert "notiert" in z2["text"].lower()
    assert "wie ist ihr name" not in z2["text"].lower()
    assert sit.get("praxisNotiz")
    assert s["phase"] == "fertig" and sit.get("keinSlotFertig") is True
    assert z2.get("hangup") is True  # Blessing schliesst kurz


def test_stufe3_ohne_blessing_kompakt_stellt_registrierte_abschlussfrage(tmp_path, monkeypatch):
    """Ohne sonstNochNurNachErfolg: 'Sonst noch etwas?' ist eine ECHTE
    Formular-Frage — 'Nein, danke.' legt auf, faellt nie ans Modell."""
    monkeypatch.setattr(flow.verwalten, "DATA_DIR", tmp_path)
    t = _ohne_auffang()
    for k in ("sonstNochNurNachErfolg", "gespraechKompakt", "buchungAbschlussKompakt"):
        t.pop(k, None)
    sit = _sit(t)
    s = gehirn.sammler(sit)
    s.update({"nachname": "Müller", "vorname": "Anna", "buchstabiert": True,
              "telefon": "01771234567", "telefonOk": True})

    flow.zug(sit, "Matzenbehandlung.")
    z2 = flow.zug(sit, "Matzenbehandlung.")
    assert z2 and "sonst noch etwas" in z2["text"].lower()
    assert s["frage"] == "sonst_noch"
    z3 = flow.zug(sit, "Nein, danke.")
    assert z3 and z3.get("hangup") is True


def test_stufe3_abgeben_weg_ohne_kompakt_registriert_abschlussfrage(tmp_path, monkeypatch):
    """Der allgemeine ABGEBEN-Weg (Name -> Nummer -> Notiz) haengte die
    Abschluss-Frage frueher von Hand an — 'Nein.' fiel ans Modell."""
    monkeypatch.setattr(flow.verwalten, "DATA_DIR", tmp_path)
    t = _ohne_auffang()
    for k in ("sonstNochNurNachErfolg", "gespraechKompakt", "buchungAbschlussKompakt"):
        t.pop(k, None)
    sit = _sit(t)
    s = gehirn.sammler(sit)
    flow.zug(sit, "Matzenbehandlung.")
    flow.zug(sit, "Matzenbehandlung.")
    flow.zug(sit, "Müller.")
    z4 = flow.zug(sit, "Null eins sieben sieben eins zwei drei vier fünf sechs sieben.")
    assert z4 and "sonst noch etwas" in z4["text"].lower()
    assert s["frage"] == "sonst_noch" and sit.get("abgebenSonstNoch") is True
    z5 = flow.zug(sit, "Nein, das war's.")
    assert z5 and z5.get("hangup") is True
    assert "abgebenSonstNoch" not in sit


def test_stufe3_abschlussfrage_ja_laedt_ein_und_raeumt(tmp_path, monkeypatch):
    monkeypatch.setattr(flow.verwalten, "DATA_DIR", tmp_path)
    t = _ohne_auffang()
    for k in ("sonstNochNurNachErfolg", "gespraechKompakt", "buchungAbschlussKompakt"):
        t.pop(k, None)
    sit = _sit(t)
    s = gehirn.sammler(sit)
    flow.zug(sit, "Matzenbehandlung.")
    flow.zug(sit, "Matzenbehandlung.")
    flow.zug(sit, "Müller.")
    flow.zug(sit, "Null eins sieben sieben eins zwei drei vier fünf sechs sieben.")
    z5 = flow.zug(sit, "Ja.")
    assert z5 and "was kann ich noch" in z5["text"].lower()
    assert s["frage"] == ""
    assert "abgebenSonstNoch" not in sit


# --- Eskalation (zweimal unklar) konvergiert statt zu wiederholen ------------

def test_eskalation_grund_landet_in_der_sprechstunde_statt_derselben_frage():
    sit = _sit()
    s = gehirn.sammler(sit)
    sit["grundKlaerungText"] = "Matzenbehandlung."
    uebergang = flow._eskalieren(sit, "grund")
    assert "sprechstunde" in uebergang.lower()
    assert s["motivId"] == SPRECHSTUNDE and s["grundGenerisch"] is True
    assert s["grundWortlaut"] == "Matzenbehandlung."
    # zug() fragt nach der Eskalation die naechste Pflichtfrage — nie wieder
    # den Grund (die Schleife der Blessing-Anrufe).
    fid2, _frage2 = gehirn.naechste_frage(sit)
    assert fid2 != "grund", fid2


def test_eskalation_grund_ohne_auffangmotiv_geht_in_den_rueckruf(tmp_path, monkeypatch):
    monkeypatch.setattr(flow.verwalten, "DATA_DIR", tmp_path)
    sit = _sit(_ohne_auffang())
    s = gehirn.sammler(sit)
    aus = flow._grund_eskalation_abgeben(sit, "Hm, äh.")
    assert aus and "keinen passenden termin" in aus["text"].lower()
    assert s["frage"] == "name"
    # Zahnpraxis: alter Weg (None), die Eskalation setzt dort Kontrolle
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
    assert not s.get("grundGenerisch")
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
    assert vm and vm["id"] == SPRECHSTUNDE, vm
    assert s["motivId"] == SPRECHSTUNDE


# --- Buchung: O-Ton steht IMMER in der Terminnotiz ---------------------------

def test_buchung_mit_generischem_motiv_traegt_o_ton_als_notiz(monkeypatch):
    sit = _sit()
    s = gehirn.sammler(sit)
    flow.zug(sit, "Matzenbehandlung.")
    flow.zug(sit, "Matzenbehandlung.")
    assert s["motivId"] == SPRECHSTUNDE and s["grundGenerisch"] is True
    s.update({
        "phase": "bestaetigen", "frage": "", "pzr": "nein",
        "nachname": "Müller", "vorname": "Anna", "buchstabiert": True,
        "telefon": "01771234567", "telefonOk": True,
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
    assert gebucht and gebucht[0]["visitMotiveId"] == SPRECHSTUNDE, gebucht
    assert any("Matzenbehandlung" in n and "im Katalog nicht zuordenbar" in n
               and "Sprechstunde" in n for n in notizen), notizen
