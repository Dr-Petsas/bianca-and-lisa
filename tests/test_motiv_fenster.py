"""W-MOTIV-FENSTER (Chef 03.09.2026): erst der Besuchsgrund, DANN die Slots.

Chef: "wenn du VOR dem Besuchsgrund nach terminslots suchst, kannst du gar
nicht die spezialsprechzeiten beruecksichtigen. du musst erst wissen welcher
besuchsgrund gefordert ist [...] ohne kenntnis des grundes tappst du im
dunkeln."

Zwei Wachen:
1. hintergrund.vorrat_schluessel liefert "" ohne gemapptes Motiv — der
   Hintergrund-Vorrat sucht also nie mehr blind mit dem Kontroll-Default.
2. flow._angebot nutzt einen Vorrat nur, wenn sit["vorratFuer"] zum
   aktuellen Rahmen (Kalender + Motiv + Startdatum) passt — sonst laedt der
   Zug synchron mit dem richtigen Motiv nach.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bianca import flow, gehirn, hintergrund
from kern.tenants import laden


def _sit() -> dict:
    return {"tenant": laden("meddent"), "messages": [{"role": "system", "content": "x"}]}


def _iso_in(tage: int, h: int, m: int = 0) -> str:
    d = datetime.now(ZoneInfo("Europe/Berlin")).replace(
        hour=h, minute=m, second=0, microsecond=0) + timedelta(days=tage)
    return d.isoformat(timespec="seconds")


# --- 1. Kein Vorrat ohne Besuchsgrund ---------------------------------------

def test_kein_schluessel_ohne_motiv_trotz_kalender():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"warSchonMal": True,
              "arzt": {"typ": "genannt", "calendarId": "cal1",
                       "calendarName": "Dr. Petsas"}})
    assert hintergrund.vorrat_schluessel(sit) == ""


def test_kein_schluessel_ohne_motiv_auch_bei_egal():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"warSchonMal": False, "arzt": {"typ": "egal"}})
    assert hintergrund.vorrat_schluessel(sit) == ""


def test_schluessel_steht_mit_motiv_und_kalender():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"warSchonMal": True, "motivId": "vm1", "motivName": "Kontrolle",
              "arzt": {"typ": "genannt", "calendarId": "cal1",
                       "calendarName": "Dr. Petsas"}})
    assert hintergrund.vorrat_schluessel(sit).startswith("cal1|vm1|")


def test_vorrat_anstossen_wartet_auf_motiv(monkeypatch):
    """Ohne Motiv darf vorrat_anstossen KEINEN Suchlauf starten."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": True,
              "arzt": {"typ": "genannt", "calendarId": "cal1",
                       "calendarName": "Dr. Petsas"}})
    laeufe: list = []
    monkeypatch.setattr(
        hintergrund.calendar, "find_slots",
        lambda *a, **k: laeufe.append(1) or {"ok": True, "slots": []})
    hintergrund.vorrat_anstossen(sit)
    assert not sit.get("vorratKey")
    assert laeufe == []


# --- 2. Angebot verwirft Vorrat aus fremdem Motiv-Fenster -------------------

_PETSAS = "zex5bmv5jfIHWVW6zHbg"


def _buch_sit() -> dict:
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": True,
              "arzt": {"typ": "genannt", "calendarId": _PETSAS,
                       "calendarName": "Dr. Petsas"},
              "grund": "Zahnreinigung", "motivId": "vmPZR",
              "motivName": "Zahnreinigung", "wunsch": {},
              "vorname": "Julia", "nachname": "Berger", "buchstabiert": True,
              "phase": "angebot"})
    return sit


def test_angebot_verwirft_vorrat_aus_fremdem_fenster(monkeypatch):
    """Der Vorrat stammt aus einem anderen Rahmen (z. B. Blind-Lauf mit
    Kontroll-Motiv) — _angebot muss frisch laden statt ihn anzubieten."""
    sit = _buch_sit()
    alt = [_iso_in(3, 9, 0), _iso_in(4, 10, 30)]
    sit["slotVorrat"] = list(alt)
    sit["vorratFuer"] = f"{_PETSAS}|vmKontrolle|2026-09-03"  # fremder Rahmen
    frisch = [_iso_in(5, 14, 0), _iso_in(6, 15, 30), _iso_in(7, 11, 0)]
    calls: list[dict] = []

    def fake_find(tenant, ctx, **kw):
        calls.append(dict(ctx))
        return {"ok": True, "slots": list(frisch)}

    monkeypatch.setattr(flow.kal, "find_slots", fake_find)
    ang = flow._angebot(sit)
    assert calls, "Angebot muss mit dem richtigen Motiv frisch laden"
    assert ang and ang.get("text")
    offered = [o["iso"] for o in (sit.get("offered") or [])]
    assert offered and all(o in frisch for o in offered), offered
    assert not any(o in alt for o in offered), offered


def test_angebot_nutzt_passenden_vorrat_ohne_neuladen(monkeypatch):
    """Stimmt der Rahmen-Marker, wird der Vorrat OHNE zweiten CF-Call
    angeboten (Latenz-Gewinn des Hintergrund-Vorrats bleibt erhalten)."""
    sit = _buch_sit()
    sit["slotVorrat"] = [_iso_in(3, 9, 0), _iso_in(4, 10, 30), _iso_in(5, 14, 0)]
    sit["vorratGemerkt"] = True
    sit["vorratFuer"] = hintergrund.vorrat_schluessel(sit)
    assert sit["vorratFuer"], "Rahmen muss stehen"

    def boom(*a, **k):
        raise AssertionError("kein Neuladen erwartet — Vorrat passt")

    monkeypatch.setattr(flow.kal, "find_slots", boom)
    ang = flow._angebot(sit)
    assert ang and ang.get("text")
    offered = [o["iso"] for o in (sit.get("offered") or [])]
    assert offered, "Vorrat muss angeboten werden"
