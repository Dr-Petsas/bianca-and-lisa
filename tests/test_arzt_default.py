"""W-ARZT-DEFAULT (Chef 03.09.2026) — offline, ohne LLM und ohne Netz.

Chef: "erwähne nicht die Namen in dieser RehenFolge: Dr. Nikolaou,
Dr.Patrikis und Dr. Petsas. sondern umgekehert. [...] Dr. Petsas,
Dr. Patrikis oder Dr. Nikolaou. wenn jemand nicht weiss zu welchem arzt
er soll dann immer bei dr. Petsas buchen."
"""

from bianca import flow, gehirn
from kern import tenants as kern_tenants
from kern.tenants import laden

PETSAS = "zex5bmv5jfIHWVW6zHbg"


def _sit() -> dict:
    return {"tenant": laden("meddent"), "messages": [{"role": "system", "content": "x"}]}


# --- Sprech-Reihenfolge -----------------------------------------------------

def test_behandler_reihe_chef_zuerst():
    t = laden("meddent")
    namen = [c.get("name") for c in kern_tenants.behandler_reihe(t)]
    assert namen == ["Dr. Petsas", "Dr. Patrikis", "Dr. Nikolaou"], namen


def test_arztwahl_frage_nennt_petsas_zuerst():
    frage = gehirn.arztwahl_frage(laden("meddent"))
    assert "Doktor Petsas, Doktor Patrikis oder Doktor Nikolaou" in frage, frage


def test_behandler_alle_im_prompt_richtig_herum():
    from bianca.agent import _behandler_alle
    zeile = _behandler_alle(laden("meddent"))
    assert zeile == "Dr. Petsas, Dr. Patrikis, Dr. Nikolaou", zeile


# --- "Weiss nicht zu welchem Arzt" -> Standard-Behandler ---------------------

def test_arzt_default_ist_petsas():
    d = gehirn.arzt_default(laden("meddent"))
    assert d and d["calendarId"] == PETSAS and d["calendarName"] == "Dr. Petsas"


def test_egal_antwort_setzt_default_behandler():
    """"Ganz egal" auf die Arztwahl-Frage bucht bei Dr. Petsas — nicht mehr
    die globale Schnellster-Arzt-Suche."""
    echt = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    try:
        sit = _sit()
        s = gehirn.sammler(sit)
        s.update({"modus": "buchen", "warSchonMal": False, "frage": "arzt"})
        flow.zug(sit, "Das ist mir ganz egal.")
        a = s["arzt"] or {}
        assert a.get("calendarId") == PETSAS, a
    finally:
        flow.hintergrund.anstossen = echt


def test_eskalation_arzt_frage_landet_bei_petsas():
    sit = _sit()
    gehirn.sammler(sit)["modus"] = "buchen"
    text = flow._eskalieren(sit, "arzt")
    a = gehirn.sammler(sit)["arzt"] or {}
    assert a.get("calendarId") == PETSAS, a
    assert "Doktor Petsas" in text, text


def test_angebot_ohne_arzt_sucht_im_petsas_kalender(monkeypatch):
    """Bis zum Angebot kein Kalender geklaert -> Suche laeuft bei Petsas,
    nicht global (egal=False, calendarId gesetzt)."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": False,
              "arzt": {"typ": "egal"},  # alter Zustand ohne Kalender
              "grund": "Kontrolluntersuchung", "motivId": "kch-1",
              "motivName": "Kontrolluntersuchung", "wunsch": {},
              "vorname": "Julia", "nachname": "Berger", "buchstabiert": True,
              "phase": "angebot"})
    laeufe: list[dict] = []
    slot = (datetime.now(ZoneInfo("Europe/Berlin")).replace(
        hour=9, minute=0, second=0, microsecond=0) + timedelta(days=5)).isoformat(timespec="seconds")

    def fake_find(tenant, ctx, **kw):
        laeufe.append({"ctx": dict(ctx), "egal": kw.get("egal")})
        return {"ok": True, "slots": [slot]}

    monkeypatch.setattr(flow.kal, "find_slots", fake_find)
    flow._angebot(sit)
    assert laeufe, "Angebot muss suchen"
    assert laeufe[0]["egal"] is False
    assert laeufe[0]["ctx"].get("calendarId") == PETSAS, laeufe[0]
