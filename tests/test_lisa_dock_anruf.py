"""Lisa-Dock (Reiter #lisa, 09.10.2026): „Lisa kann nicht mehr anrufen“.

Zwei Befunde aus der Live-Probe gegen 8095:
- Die Eröffnung war Biancas Eingangs-Gruss aus der DB („Zahnärzte im Medical
  Center, guten Tag! Mein Name ist Bianca. Was kann ich für Sie tun?“) statt
  Lisas Vorstellung mit Auftrag.
- Jeder Stille-Stups endete in HTTP 500 (``DIENST.stimme`` liefert zwei
  Werte, ``api_stille`` entpackte drei) — Lisa verstummte, sobald der
  Angerufene schwieg.
"""

from __future__ import annotations

from lisa import agent, server, session

DB_GRUSS = ("Zahnärzte im Medical Center, guten Tag! Mein Name ist Bianca. "
            "Was kann ich für Sie tun?")


def _db_tenant() -> dict:
    return {
        "_id": "meddent",
        "_quelle": "cf+datei",
        "praxisName": "Zahnärzte im Medical Center Düsseldorf",
        "praxisNameVon": "den Zahnärzten im Medical Center Düsseldorf",
        "begruessungText": DB_GRUSS,
        "calendars": [],
        "visitMotives": [],
    }


def _ohne_netz(monkeypatch):
    monkeypatch.setattr(server, "_anreichern", lambda sit: None)
    monkeypatch.setattr(server.anliegen, "vorbereiten", lambda sit: None)
    monkeypatch.setattr(agent.gedaechtnis, "kontext_anstossen", lambda sit: None)


def test_dock_start_spricht_nicht_biancas_eingangsgruss(monkeypatch):
    _ohne_netz(monkeypatch)
    db = _db_tenant()
    monkeypatch.setattr(server.agentprofil, "fuer_tenant", lambda _id: db)
    gesehen = {}

    def _antwort(sit, art, extra=None):
        gesehen["sit"] = sit
        return {"ok": True}

    monkeypatch.setattr(server, "_json_antwort", _antwort)
    server.api_start(server.StartIn(
        tenant="meddent",
        auftrag="Wir möchten Ihren Kontrolltermin vorverlegen.",
        patient={"name": "Test Person"},
    ))
    sit = gesehen["sit"]
    text = agent.start_reply(sit)["text"]
    assert "Bianca" not in text
    assert "Was kann ich für Sie tun" not in text
    assert "Lisa" in text
    # Der gecachte Mandant bleibt unberührt — Bianca braucht ihren Gruss.
    assert db["begruessungText"] == DB_GRUSS


def test_outbound_kampagnen_gruss_bleibt(monkeypatch):
    _ohne_netz(monkeypatch)
    t = _db_tenant()
    t["begruessungText"] = "Guten Tag, hier ist Lisa mit einer Kampagne."
    sit = session.neu(tenant=t, auftrag="x", patient={"name": "Test Person"})
    assert agent.start_reply(sit)["text"].startswith("Guten Tag, hier ist Lisa")


def test_stille_stups_liefert_ton_statt_500(monkeypatch):
    _ohne_netz(monkeypatch)
    sit = session.neu(tenant=_db_tenant(), auftrag="x", patient={"name": "Test Person"})
    monkeypatch.setattr(server, "_stille_fn", lambda s: {"text": "Sind Sie noch dran?"})
    monkeypatch.setattr(server.DIENST, "stimme", lambda text, karte=None: ("/api/audio/x.wav", 0.12))
    monkeypatch.setattr(server.mitschnitt, "zug", lambda *a, **k: None)
    aus = server.api_stille(server.HangupIn(sessionId=sit["id"]))
    assert aus["ok"] and not aus["empty"]
    assert aus["audioUrl"] == "/api/audio/x.wav"
    assert aus["text"] == "Sind Sie noch dran?"
