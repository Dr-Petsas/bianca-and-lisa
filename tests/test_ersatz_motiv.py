"""W-ERSATZ-MOTIV (15.09.2026, Praxis Dr. Ruether) — offline.

Liefert ein Spezialfenster keine Zeiten, springt seit dem 08.09.2026 das
Kontroll-Motiv als Ausweich ein (W-SUCHFENSTER / Luelf). Welches Motiv das
ist, suchte `tenants.motiv_von` — und dessen Rueckfall `_sicheres_default`
nimmt ueber `_SAFE_NAME_RE` auch "Besprechung"/"Beratung". In einer Praxis
OHNE Kontroll-Motiv wurde daraus Unsinn: bei Ruether (Gynaekologie) bot Ben
auf den Wunsch "Krebsvorsorge" (nicht online buchbar) Zeiten der
"GYN Endometriose Erstberatung" (45 min) an — eine andere Leistung in einer
anderen Dauer.

Regel: als Ausweich taugt nur ein GENERISCHER Kontroll-/Vorsorge-Termin.
Sonst gibt es keinen Ersatz, und der Anrufer hoert den echten Grund ("darf
ich telefonisch nicht vergeben") statt "im Moment leider kein freier
Termin" — es wird naemlich keiner frei. Die Rueckruf-Notiz bleibt.

Die Gegenproben sind hier der wichtigere Teil: MedDent, Thaler und Blessing
behalten ihren Kontroll-Ausweich unveraendert.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bianca import flow, gehirn, verwalten
from kern import calendar as kal
from kern import tenants
from kern.tenants import laden

RUETHER_CAL = "cal_ruether"


# --- 1. Was taugt als Ausweich? ----------------------------------------------

@pytest.mark.parametrize("name", [
    "KCH Kontrolluntersuchung",
    "Kontrolluntersuchung",
    "IMP Kontrolluntersuchung",
    "GYN Vorsorgeuntersuchung",
    "Nachsorge",
    "Recall",
    "Check-up",
])
def test_kontroll_motive_taugen_als_ersatz(name):
    assert tenants.taugt_als_ersatz({"id": "x", "name": name}) is True


@pytest.mark.parametrize("name", [
    "GYN Endometriose Erstberatung",   # der Live-Fehlgriff bei Ruether
    "GYN Verhuetungsberatung",
    "ZE Besprechung",
    "IMP Besprechung",
    "PRO Professionelle Zahnreinigung",
    "KCH akute Beschwerden/Notfall",
    "Akutsprechstunde",
    "KCH Füllung klein",
])
def test_fachtermine_taugen_nicht_als_ersatz(name):
    assert tenants.taugt_als_ersatz({"id": "x", "name": name}) is False


def test_leeres_motiv_taugt_nie():
    assert tenants.taugt_als_ersatz(None) is False
    assert tenants.taugt_als_ersatz({}) is False


def test_patientenname_zaehlt_mit():
    """Der interne Name ist ein Kuerzel, der Patientenname sagt es klar."""
    vm = {"id": "x", "name": "GYN-01", "nameForPatient": "Vorsorge"}
    assert tenants.taugt_als_ersatz(vm) is True


# --- 2. _kontrolle_ersatz: echter Kontroll-Termin oder nichts ----------------

def _ruether() -> dict:
    """Live-Stand Ruether im Kleinen: KEINE generische Kontrolle im Katalog,
    die Vorsorge ist gesperrt, und kein BUCHBARES Motiv passt auf den Wunsch
    (deshalb bleibt "Krebsvorsorge" durchs Mapping hindurch stehen)."""
    return {
        "clientId": "AWdFeDldR81P3jmiq869",
        "locationId": "loc_d7gfcuss",
        "defaultCalendarId": RUETHER_CAL,
        "calendars": [{"id": RUETHER_CAL, "name": "Dr. Denise Rüther"}],
        "visitMotives": [
            {"id": "endo", "name": "GYN Endometriose Erstberatung",
             "nameForPatient": "Endometriose-Beratung", "duration": 45,
             "allowOnlineBooking": False, "calendarIds": []},
            {"id": "krebs", "name": "GYN Krebsvorsorge",
             "nameForPatient": "Krebsvorsorge", "duration": 20,
             "allowOnlineBooking": False, "calendarIds": []},
            {"id": "akupunktur", "name": "Akupunktur Sitzung",
             "nameForPatient": "Akupunktur", "duration": 30,
             "allowOnlineBooking": True, "calendarIds": []},
        ],
    }


def test_ruether_bekommt_keinen_ausweich():
    such = {"calendarId": RUETHER_CAL, "visitMotiveId": "krebs",
            "visitMotiveName": "GYN Krebsvorsorge"}
    # Gegenprobe zur Ursache: motiv_von liefert weiterhin die Erstberatung …
    assert (tenants.motiv_von(_ruether(), "Kontrolluntersuchung") or {})["id"] == "endo"
    # … aber als AUSWEICH ist sie gesperrt.
    assert kal._kontrolle_ersatz(_ruether(), such) is None


def test_meddent_behaelt_seinen_kontroll_ausweich():
    such = {"calendarId": "zex5bmv5jfIHWVW6zHbg", "visitMotiveId": "fuellung",
            "visitMotiveName": "KCH Füllung klein"}
    alt = kal._kontrolle_ersatz(laden("meddent"), such)
    assert alt and "Kontroll" in alt["visitMotiveName"]


@pytest.mark.parametrize("mandant", ["meddent", "thaler", "blessing"])
def test_zahn_und_haut_mandanten_haben_weiter_einen_ausweich(mandant):
    such = {"calendarId": "x", "visitMotiveId": "gibt-es-nicht",
            "visitMotiveName": "Irgendwas"}
    alt = kal._kontrolle_ersatz(laden(mandant), such)
    assert alt, f"{mandant} verliert seinen Kontroll-Ausweich"
    assert tenants.taugt_als_ersatz(
        tenants.motiv_von(laden(mandant), "Kontrolluntersuchung"))


def test_notaus_stellt_das_alte_verhalten_her(monkeypatch):
    monkeypatch.setattr(kal, "_ERSATZ_STRENG", False)
    such = {"calendarId": RUETHER_CAL, "visitMotiveId": "krebs",
            "visitMotiveName": "GYN Krebsvorsorge"}
    alt = kal._kontrolle_ersatz(_ruether(), such)
    assert alt and alt["visitMotiveId"] == "endo"


# --- 3. Marker: diese Terminart gibt es telefonisch nicht -------------------

def _leere_seite(*a, **k):
    return {"ok": True, "slots": [], "dispatch": {}}


def test_find_slots_behandler_markiert_gesperrtes_motiv(monkeypatch):
    monkeypatch.setattr(kal, "_find_slots_seite", _leere_seite)
    found = kal.find_slots_behandler(
        _ruether(),
        {"calendarId": RUETHER_CAL, "visitMotiveId": "krebs",
         "visitMotiveName": "GYN Krebsvorsorge"},
    )
    assert found.get("motivNichtTelefonisch") == "Krebsvorsorge"
    assert not found.get("motivFallback")


def test_find_slots_raeume_markiert_gesperrtes_motiv(monkeypatch):
    monkeypatch.setattr(kal, "_find_slots_seite", _leere_seite)
    found = kal.find_slots_raeume(
        _ruether(),
        {"visitMotiveId": "krebs", "visitMotiveName": "GYN Krebsvorsorge"},
        [{"id": RUETHER_CAL, "name": "Dr. Denise Rüther"}],
    )
    assert found.get("motivNichtTelefonisch") == "Krebsvorsorge"


def test_buchbares_motiv_ohne_zeiten_wird_nicht_markiert(monkeypatch):
    """Nur ausgebucht: da wird wirklich wieder einer frei — kein Marker."""
    monkeypatch.setattr(kal, "_find_slots_seite", _leere_seite)
    found = kal.find_slots_behandler(
        _ruether(),
        {"calendarId": RUETHER_CAL, "visitMotiveId": "akupunktur",
         "visitMotiveName": "Akupunktur Sitzung"},
    )
    assert not found.get("motivNichtTelefonisch")


def test_meddent_leeres_fenster_traegt_keinen_marker(monkeypatch):
    """Gegenprobe: mit Ausweich-Motiv wird nie markiert."""
    monkeypatch.setattr(kal, "_find_slots_seite", _leere_seite)
    found = kal.find_slots_behandler(
        laden("meddent"),
        {"calendarId": "zex5bmv5jfIHWVW6zHbg", "visitMotiveId": "fuellung",
         "visitMotiveName": "KCH Füllung klein"},
    )
    assert not found.get("motivNichtTelefonisch")


# --- 4. Was der Anrufer hoert ------------------------------------------------

@pytest.fixture
def notizen(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(verwalten, "DATA_DIR", tmp_path)
    monkeypatch.setattr(flow.kal, "_find_slots_seite", _leere_seite)
    monkeypatch.setattr(flow.hintergrund, "anstossen", lambda sit: None)
    datei = tmp_path / "praxis_notizen.jsonl"

    def lesen() -> list[dict]:
        if not datei.exists():
            return []
        return [json.loads(z) for z in datei.read_text(encoding="utf-8").splitlines()
                if z.strip()]
    return lesen


def _sit(motiv_id: str, motiv_name: str, tenant: dict | None = None) -> dict:
    t = tenant or _ruether()
    sit = {"tenant": t, "messages": [{"role": "system", "content": "x"}],
           "stimme": "Ben",
           "anrufer": {"vorname": "Julia", "nachname": "Berger",
                       "telefon": "+491771234567"},
           "motivKatalog": t["visitMotives"]}
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": True,
              "arzt": {"typ": "genannt", "calendarId": RUETHER_CAL,
                       "calendarName": "Dr. Denise Rüther"},
              "grund": motiv_name, "grundWortlaut": motiv_name,
              "motivId": motiv_id, "motivName": motiv_name,
              "vorname": "Julia", "nachname": "Berger", "buchstabiert": True,
              "versicherung": "gesetzlich", "phase": "angebot",
              "wunsch": {"weekday": None, "hourMin": None, "hourMax": None,
                         "hour": None, "minDaysAhead": 0, "date": None,
                         "tage": None, "von": None, "bis": None}})
    return sit


def test_krebsvorsorge_hoert_den_echten_grund(notizen):
    sit = _sit("krebs", "GYN Krebsvorsorge")
    ang = flow._angebot(sit)
    text = ang["text"]
    assert "telefonisch nicht vergeben" in text
    assert "Krebsvorsorge" in text
    assert "keinen freien Termin" not in text
    # Die Notiz bleibt — die Praxis weiss von dem Wunsch.
    n = notizen()
    assert len(n) == 1 and "Krebsvorsorge" in json.dumps(n[0], ensure_ascii=False)
    # und Ben bietet nie Endometriose-Zeiten an
    assert "Endometriose" not in text
    assert not sit.get("offered")


def test_ausgebucht_bleibt_beim_alten_satz(notizen):
    """Gegenprobe: buchbares Motiv ohne Zeiten — Wortlaut unveraendert."""
    sit = _sit("akupunktur", "Akupunktur Sitzung")
    text = flow._angebot(sit)["text"]
    assert "keinen freien Termin" in text
    assert "telefonisch nicht vergeben" not in text


def test_meddent_kontrolle_bleibt_unveraendert(notizen):
    """Gegenprobe Zahnarzt: derselbe leere Kalender, alter Wortlaut."""
    sit = _sit("kontrolle", "KCH Kontrolluntersuchung", tenant=laden("meddent"))
    gehirn.sammler(sit)["arzt"]["calendarId"] = "zex5bmv5jfIHWVW6zHbg"
    text = flow._angebot(sit)["text"]
    assert "keinen freien Termin" in text
    assert "telefonisch nicht vergeben" not in text
