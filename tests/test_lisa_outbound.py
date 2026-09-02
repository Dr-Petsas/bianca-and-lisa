"""Lisa-Outbound: Pending-Store, Tenant-aus-DB-Bundle, Token-Gate (offline)."""

from __future__ import annotations

import os

import lisa.outbound as out


def test_tenant_von_bundle_aus_agent():
    bundle = {
        "clientId": "cli1",
        "locationId": "loc1",
        "phoneCallId": "pc1",
        "fromDid": "+4921154244101",
        "toE164": "+491701234567",
        "agent": {
            "id": "ag1",
            "clientId": "cli1",
            "locationId": "loc1",
            "name": "Recall Lisa",
            "phoneNumber": "+4921154244101",
            "firstMessage": "Guten Tag, hier ist Lisa von der Testpraxis.",
            "rolePrompt": "Termin nachholen",
            "mainLanguage": "de",
        },
        "patient": {
            "id": "p1",
            "firstName": "Anna",
            "lastName": "Müller",
            "gender": "f",
        },
        "calendars": [{"id": "cal1", "name": "Dr. Test"}],
        "visitMotives": [{"id": "vm1", "name": "Kontrolle"}],
        "doctors": ["Dr. Test"],
    }
    t = out.tenant_von_bundle(bundle)
    assert t["clientId"] == "cli1"
    assert t["locationId"] == "loc1"
    assert t["begruessungText"].startswith("Guten Tag")
    assert t["_quelle"].startswith("cf")
    assert t.get("_phoneCallId") == "pc1"
    assert any(c.get("id") == "cal1" for c in (t.get("calendars") or []))


def test_first_message_override_schlaegt_agent():
    bundle = {
        "clientId": "cli1",
        "locationId": "loc1",
        "agent": {"id": "a", "clientId": "cli1", "locationId": "loc1",
                  "firstMessage": "Agent-Gruss"},
        "firstMessage": "Kampagnen-Gruss",
        "patient": {"firstName": "Max", "lastName": "Mustermann"},
    }
    t = out.tenant_von_bundle(bundle)
    assert t["begruessungText"] == "Kampagnen-Gruss"


def test_pending_einmal_abholbar(tmp_path, monkeypatch):
    monkeypatch.setattr(out, "_PENDING_DIR", tmp_path / "pending")
    out._PENDING.clear()
    uid = "aabbccddeeff00112233445566778899"
    out.pending_setzen(uid, {"phoneCallId": "x", "toE164": "+49170"})
    a = out.pending_holen(uid)
    assert a and a["phoneCallId"] == "x"
    assert out.pending_holen(uid) is None


def test_token_ok_ohne_secret(monkeypatch):
    monkeypatch.setattr(out, "_OUTBOUND_TOKEN", "")
    assert out.token_ok("") is True
    assert out.token_ok("egal") is True


def test_token_ok_mit_secret(monkeypatch):
    monkeypatch.setattr(out, "_OUTBOUND_TOKEN", "geheim")
    assert out.token_ok("geheim") is True
    assert out.token_ok("Bearer geheim") is True
    assert out.token_ok("falsch") is False


def test_callfile_enthaelt_audiosocket_und_callerid():
    text = out._callfile_inhalt(
        to_e164="+491701234567",
        from_did="+4921154244101",
        luuid="aabbccdd-eeff-0011-2233-445566778899",
    )
    assert "PJSIP/zaluma-trunk/sip:+491701234567@vc.zaluma.tel" in text
    assert "Application: AudioSocket" in text
    assert "40102" in text
    assert "+4921154244101" in text


def test_patient_und_auftrag_von_bundle():
    bundle = {
        "toE164": "+491711111111",
        "auftrag": "Bitte Termin verschieben",
        "patient": {"id": "1", "firstName": "Eva", "lastName": "Thaler", "gender": "f"},
    }
    p = out.patient_von_bundle(bundle)
    assert p["name"] == "Eva Thaler"
    assert p["phone"] == "+491711111111"
    assert out.auftrag_von_bundle(bundle) == "Bitte Termin verschieben"
