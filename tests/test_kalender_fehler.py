"""W-KALENDER-FEHLER (17.09.2026) — offline.

Blessing 15.09.: zehn Anrufe liefen auf Kalender-500er ("Could not load
doctor"). Bianca sagte jedes Mal "Der Terminkalender antwortet gerade nicht.
Die Praxis ruft Sie kurzfristig zurueck — Ihre Nummer habe ich ja" — es gab
KEINE Notiz, keinen Report-Eintrag, und bei unterdrueckter Nummer auch
keine Nummer. Die Praxis konnte nichts tun.

Regel: ein zweiter Wurf faengt den transienten Fehler; bleibt der Kalender
stumm, schreibt der Fluss die ECHTE Rueckruf-Notiz (JSONL + Dock +
praxis_notiz-Tool fuer die Fakten-Wache) und erfragt ohne bekannte Nummer
die Nummer (W-RUECKRUF-NUMMER). Der Vorgang ist danach abgeschlossen —
keine offene Slotwahl, kein Modell.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bianca import flow, gehirn, verwalten
from kern.tenants import laden


def _katalog() -> list[dict]:
    return [{"id": "kontrolle", "name": "KCH Kontrolluntersuchung",
             "nameForPatient": "Kontrolle", "allowOnlineBooking": True, "calendarIds": []}]


def _sit(anrufer_nummer: str = "") -> dict:
    sit = {"tenant": laden("meddent"), "messages": [{"role": "system", "content": "x"}],
           "stimme": "Bianca", "motivKatalog": _katalog()}
    if anrufer_nummer:
        sit["anrufer"] = {"vorname": "Julia", "nachname": "Berger", "telefon": anrufer_nummer}
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": True,
              "arzt": {"typ": "genannt", "calendarId": "zex5bmv5jfIHWVW6zHbg",
                       "calendarName": "Dr. Petsas"},
              "grund": "Kontrolle", "grundWortlaut": "zur Kontrolle",
              "motivId": "kontrolle", "motivName": "KCH Kontrolluntersuchung",
              "vorname": "Julia", "nachname": "Berger", "buchstabiert": True,
              "versicherung": "gesetzlich", "phase": "angebot",
              "wunsch": {"weekday": None, "hourMin": None, "hourMax": None, "hour": None,
                         "minDaysAhead": 0, "date": None, "tage": None, "von": None, "bis": None}})
    return sit


class _CF:
    """Erst n Fehler, dann Slots (oder immer Fehler)."""

    def __init__(self, fehler: int, danach: list[str] | None = None):
        self.fehler = fehler
        self.danach = danach
        self.aufrufe = 0

    def __call__(self, tenant, ctx, *, start_date="", egal=False, source=""):
        self.aufrufe += 1
        if self.aufrufe <= self.fehler:
            return {"ok": False, "error": "Could not load doctor", "dispatch": {"status": 500}}
        return {"ok": True, "slots": list(self.danach or []),
                "calendar": {"id": ctx.get("calendarId")}, "motive": None,
                "doctorName": "", "dispatch": {}}


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


def test_dauerfehler_schreibt_notiz_und_fragt_die_nummer(notizen, monkeypatch):
    cf = _CF(fehler=99)
    monkeypatch.setattr(flow.kal, "_find_slots_seite", cf)
    sit = _sit()
    s = gehirn.sammler(sit)
    ang = flow._angebot(sit)
    assert cf.aufrufe == 2, "genau ein zweiter Wurf, keine Schleife"
    assert "antwortet gerade nicht" in ang["text"]
    assert "Rückrufnotiz" in ang["text"]
    assert "Ihre Nummer habe ich ja" not in ang["text"]
    assert ang["text"].endswith(flow._RUECKRUF_NUMMER_FRAGE)
    assert s["phase"] == "fertig" and s["frage"] == "telefon"
    assert (sit.get("rueckrufNummer") or {}).get("offen")
    n = notizen()
    assert len(n) == 1
    assert n[0]["anliegen"] == "neubuchung"
    assert "Terminkalender nicht erreichbar" in n[0]["status"]
    assert n[0]["behandlung"] == "zur Kontrolle"
    assert "Terminkalender" in sit["praxisNotiz"]
    # Fakten-Wache: das Rueckruf-Versprechen ist per Tool-Ledger belegt
    assert any(t.get("name") == "praxis_notiz" and t.get("ok")
               for t in sit.get("tools") or [])


def test_dauerfehler_mit_anrufer_id_fragt_nicht_und_notiz_traegt_nummer(notizen, monkeypatch):
    monkeypatch.setattr(flow.kal, "_find_slots_seite", _CF(fehler=99))
    sit = _sit(anrufer_nummer="+491771234567")
    ang = flow._angebot(sit)
    assert "Rufnummer" not in ang["text"]
    assert "unter Ihrer Nummer" in ang["text"]
    assert "sonst noch etwas" in ang["text"]
    assert "rueckrufNummer" not in sit
    n = notizen()
    assert n[0]["telefon"] == "01771234567"
    assert "Tel: 01771234567" in sit["praxisNotiz"]


def test_transienter_fehler_zweiter_wurf_bietet_termine_an(notizen, monkeypatch):
    """Erster Wurf 500, zweiter liefert Zeiten: normales Angebot, KEINE Notiz."""
    cf = _CF(fehler=1, danach=["2026-10-05T09:00:00+02:00", "2026-10-05T10:00:00+02:00",
                               "2026-10-06T14:00:00+02:00"])
    monkeypatch.setattr(flow.kal, "_find_slots_seite", cf)
    sit = _sit()
    s = gehirn.sammler(sit)
    ang = flow._angebot(sit)
    assert cf.aufrufe == 2
    assert "antwortet gerade nicht" not in ang["text"]
    assert s["phase"] == "angebot" and s["frage"] == "slotwahl"
    assert len(sit.get("offered") or []) >= 1
    assert notizen() == []


def test_kalender_ok_kein_zweiter_wurf(notizen, monkeypatch):
    """Gegenprobe: laeuft die CF, wird nichts wiederholt (Kosten/Latenz)."""
    cf = _CF(fehler=0, danach=["2026-10-05T09:00:00+02:00"])
    monkeypatch.setattr(flow.kal, "_find_slots_seite", cf)
    sit = _sit()
    flow._angebot(sit)
    assert cf.aufrufe == 1


def test_dauerfehler_folgezug_ist_deterministisch(notizen, monkeypatch):
    """Nach der Notiz gehoert die Nummernantwort dem Rueckruf-Nummern-Zug —
    kein Neustart der Slotsuche, kein Modell."""
    cf = _CF(fehler=99)
    monkeypatch.setattr(flow.kal, "_find_slots_seite", cf)
    sit = _sit()
    flow._angebot(sit)
    vorher = cf.aufrufe
    antwort = flow.zug(sit, "null eins sieben sieben eins zwei drei vier fünf sechs sieben")
    assert antwort is not None
    assert "Stimmt das so" in antwort["text"] or "wiederhole" in antwort["text"].lower()
    assert cf.aufrufe == vorher, "keine erneute Slotsuche auf dem Nummern-Pfad"


def test_dauerfehler_kann_alten_slotvorrat_nicht_maskieren(notizen, monkeypatch):
    """Ein fremder Hintergrund-Vorrat darf einen 500er nie in ein Angebot
    verwandeln. Vor dem Fix blieb er stehen und übersprang den zweiten Wurf."""
    cf = _CF(fehler=99)
    monkeypatch.setattr(flow.kal, "_find_slots_seite", cf)
    sit = _sit()
    alt = "2026-09-21T08:00:00+02:00"
    sit["slotVorrat"] = [alt]
    sit["vorratFuer"] = "anderer-kalender|anderes-motiv"

    ang = flow._angebot(sit)

    assert cf.aufrufe == 2
    assert alt not in str(ang)
    assert not sit.get("slotVorrat")
    assert not sit.get("offered")
    assert len(notizen()) == 1


def test_leere_reload_antwort_verwirft_alten_slotvorrat(notizen, monkeypatch):
    cf = _CF(fehler=0, danach=[])
    monkeypatch.setattr(flow.kal, "_find_slots_seite", cf)
    sit = _sit()
    alt = "2026-09-21T08:00:00+02:00"
    sit["slotVorrat"] = [alt]
    sit["vorratFuer"] = "anderer-kalender|anderes-motiv"

    ang = flow._angebot(sit)

    assert cf.aufrufe >= 1
    assert alt not in str(ang)
    assert not sit.get("slotVorrat")
    assert not sit.get("offered")


def test_notiz_schreibfehler_wird_nicht_als_erfolg_verbucht(monkeypatch):
    class _NichtSchreibbar:
        def mkdir(self, **kwargs):
            raise OSError("Datenträger nicht verfügbar")

    sit = _sit(anrufer_nummer="+491771234567")
    monkeypatch.setattr(verwalten, "DATA_DIR", _NichtSchreibbar())

    assert verwalten.kalender_fehler_notiz(sit) is False
    notiz_tools = [t for t in sit.get("tools") or [] if t.get("name") == "praxis_notiz"]
    assert len(notiz_tools) == 1
    assert notiz_tools[0].get("ok") is False
    assert sit.get("praxisNotizPersistiert") is False


def test_kalenderfehler_verspricht_bei_notiz_schreibfehler_nichts(monkeypatch):
    class _NichtSchreibbar:
        def mkdir(self, **kwargs):
            raise OSError("Datenträger nicht verfügbar")

    monkeypatch.setattr(verwalten, "DATA_DIR", _NichtSchreibbar())
    monkeypatch.setattr(flow.kal, "_find_slots_seite", _CF(fehler=99))
    monkeypatch.setattr(flow.hintergrund, "anstossen", lambda sit: None)
    sit = _sit()

    ang = flow._angebot(sit)

    text = ang["text"].lower()
    assert "nicht speichern" in text
    assert "hinterlassen" not in text
    assert flow._RUECKRUF_NUMMER_FRAGE.lower() not in text
    assert any(t.get("name") == "praxis_notiz" and not t.get("ok")
               for t in sit.get("tools") or [])
