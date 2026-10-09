"""Echter Lisa-Anruf aus dem Dock (W-LISA-DOCK-ECHT 09.10.2026).

Chef: „der button anruf führt gar keinen realen anruf aus“ — und dazu: „ich
suche den Patienten, gebe den Prompt ein und Lisa ruft an“, alternativ mit
frei eingetragener Nummer und Namen. Die Kette läuft über denselben
Outbound-Weg wie die Cloud Function: Vormerkung → Call-File → Abheben →
``/api/start`` mit ``outboundUuid``.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from lisa import agent, dock_anruf, outbound, server, session

DB_GRUSS = ("Zahnärzte im Medical Center, guten Tag! Mein Name ist Bianca. "
            "Was kann ich für Sie tun?")
AUFTRAG = "Wir möchten Ihren Kontrolltermin vorverlegen."


@pytest.fixture(autouse=True)
def _sauber(monkeypatch, tmp_path):
    dock_anruf.zuruecksetzen()
    monkeypatch.setattr(outbound, "_PENDING_DIR", tmp_path / "pending")
    monkeypatch.setattr(server.gedaechtnis, "outbound_offen_legen", lambda meta: None)
    yield
    dock_anruf.zuruecksetzen()


def _ohne_netz(monkeypatch, gewaehlt: list):
    monkeypatch.setattr(server, "_anreichern", lambda sit: None)
    monkeypatch.setattr(server.anliegen, "vorbereiten", lambda sit: None)
    monkeypatch.setattr(agent.gedaechtnis, "kontext_anstossen", lambda sit: None)
    monkeypatch.setattr(server.agentprofil, "fuer_tenant", lambda _id: {
        "_id": "meddent", "_quelle": "cf+datei",
        "praxisName": "Zahnärzte im Medical Center Düsseldorf",
        "praxisNameVon": "den Zahnärzten im Medical Center Düsseldorf",
        "begruessungText": DB_GRUSS, "calendars": [], "visitMotives": [],
    })
    monkeypatch.setattr(outbound, "originate",
                        lambda **kw: gewaehlt.append(kw))
    monkeypatch.setattr(server.DIENST, "stimme", lambda text, karte=None: ("/api/audio/x.wav", 0.1))
    monkeypatch.setattr(server.mitschnitt, "zug", lambda *a, **k: None)


def test_ziel_nimmt_handy_und_sperrt_sondernummern():
    assert dock_anruf.ziel("0177 6004600") == "+491776004600"
    assert dock_anruf.ziel("+43 664 1234567") == "+436641234567"
    for falsch in ("0900 1234567", "0137 1234567", "0180 5123456", "+1 212 5550100", "0177", ""):
        with pytest.raises(ValueError):
            dock_anruf.ziel(falsch)


def test_absender_ist_die_praxis_did():
    assert dock_anruf.absender("meddent") == "+4921154244101"
    assert dock_anruf.absender("ruether") == "+4921154244160"


def test_patient_wird_wirklich_angerufen_und_lisa_stellt_sich_vor(monkeypatch):
    gewaehlt: list = []
    _ohne_netz(monkeypatch, gewaehlt)
    out = server.api_anruf_echt(server.EchtIn(
        tenant="meddent", auftrag=AUFTRAG,
        patient={"id": "p1", "name": "Test Person", "phone": "+491701111111"},
        nummer="0177 6004600",
    ))
    # Die im Feld eingetragene Nummer gewinnt — Absender ist die Praxis.
    assert gewaehlt == [{"to_e164": "+491776004600", "from_did": "+4921154244101",
                         "luuid": out["uuid"]}]
    assert server.api_anruf_echt_status(out["uuid"])["status"] == "klingelt"

    aus = server.api_start(server.StartIn(outboundUuid=out["uuid"]))
    st = server.api_anruf_echt_status(out["uuid"])
    assert st["status"] == "verbunden" and st["sessionId"]
    sit = session.holen(st["sessionId"])
    assert sit["auftrag"] == AUFTRAG
    assert sit["patient"]["name"] == "Test Person"
    assert sit["booking"]["phone"] == "+491776004600"
    assert aus is not None
    text = agent.start_reply(sit)["text"]
    assert "Lisa" in text and "Bianca" not in text


def test_freie_nummer_ohne_kartei(monkeypatch):
    gewaehlt: list = []
    _ohne_netz(monkeypatch, gewaehlt)
    server.api_anruf_echt(server.EchtIn(
        tenant="ruether", auftrag=AUFTRAG, patient={"name": "Erika Muster"},
        nummer="0151 22223333",
    ))
    assert gewaehlt[0]["to_e164"] == "+4915122223333"
    assert gewaehlt[0]["from_did"] == "+4921154244160"


def test_nur_ein_anruf_zur_zeit_und_fehler_ohne_nummer(monkeypatch):
    gewaehlt: list = []
    _ohne_netz(monkeypatch, gewaehlt)
    body = server.EchtIn(tenant="meddent", auftrag=AUFTRAG,
                         patient={"name": "Test Person"}, nummer="0177 6004600")
    server.api_anruf_echt(body)
    with pytest.raises(HTTPException) as e:
        server.api_anruf_echt(body)
    assert e.value.status_code == 409
    dock_anruf.zuruecksetzen()
    with pytest.raises(HTTPException) as e:
        server.api_anruf_echt(server.EchtIn(tenant="meddent", auftrag=AUFTRAG,
                                            patient={"name": "Test Person"}))
    assert e.value.status_code == 400
    assert len(gewaehlt) == 1


def test_auflegen_beim_klingeln_verwirft_die_vormerkung(monkeypatch):
    gewaehlt: list = []
    _ohne_netz(monkeypatch, gewaehlt)
    out = server.api_anruf_echt(server.EchtIn(
        tenant="meddent", auftrag=AUFTRAG, patient={"name": "Test Person"},
        nummer="0177 6004600"))
    assert server.api_anruf_echt_auflegen(out["uuid"])["status"] == "abgebrochen"
    # Hebt der Angerufene doch noch ab, gibt es keine Sitzung mehr.
    with pytest.raises(HTTPException) as e:
        server.api_start(server.StartIn(outboundUuid=out["uuid"]))
    assert e.value.status_code == 404


def test_auflegen_im_gespraech_lisa_verabschiedet_sich(monkeypatch):
    gewaehlt: list = []
    _ohne_netz(monkeypatch, gewaehlt)
    out = server.api_anruf_echt(server.EchtIn(
        tenant="meddent", auftrag=AUFTRAG, patient={"name": "Test Person"},
        nummer="0177 6004600"))
    server.api_start(server.StartIn(outboundUuid=out["uuid"]))
    sid = server.api_anruf_echt_status(out["uuid"])["sessionId"]
    assert server.api_anruf_echt_auflegen(out["uuid"])["status"] == "beendet_wird"
    aus = server.api_stille(server.HangupIn(sessionId=sid))
    assert aus["hangup"] is True
    assert aus["text"] == dock_anruf.ABBRUCH_SATZ
    monkeypatch.setattr(server, "_hangup_fn", lambda sit: {})
    monkeypatch.setattr(server.mitschnitt, "ende", lambda *a, **k: None)
    monkeypatch.setattr(server.gedaechtnis, "report_senden", lambda sit: None)
    server.api_hangup(server.HangupIn(sessionId=sid))
    st = server.api_anruf_echt_status(out["uuid"])
    assert st["status"] == "beendet"
    assert any(z["text"] == dock_anruf.ABBRUCH_SATZ for z in st["zuege"])


def test_klingeln_ohne_abheben_gilt_als_nicht_erreicht(monkeypatch):
    gewaehlt: list = []
    _ohne_netz(monkeypatch, gewaehlt)
    out = server.api_anruf_echt(server.EchtIn(
        tenant="meddent", auftrag=AUFTRAG, patient={"name": "Test Person"},
        nummer="0177 6004600"))
    monkeypatch.setattr(dock_anruf, "_KLINGEL_MAX_S", -1.0)
    assert server.api_anruf_echt_status(out["uuid"])["status"] == "nicht_erreicht"
    # Danach ist die Leitung wieder frei.
    server.api_anruf_echt(server.EchtIn(
        tenant="meddent", auftrag=AUFTRAG, patient={"name": "Test Person"},
        nummer="0177 6004600"))
