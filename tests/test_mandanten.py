"""W-MANDANT-4 (30.08.2026): Mandantenfaehigkeit der TelefonKI.

Prueft offline (httpx gestubbt, Temp-Tenants):
- Gedaechtnis-Header X-Client-Id kommt aus der SITZUNG (sit["tenant"]),
  nicht mehr fest aus der Prozess-Umgebung; Fallback bleibt MAS_CLIENT_ID.
- TTS-Aussprache wird aus den Tenant-JSONs vereinigt (Feld "aussprache");
  ohne das Feld gilt die alte eingebaute Liste.
- tenants.von_did findet den Mandanten zur angerufenen Nummer (SIP-Vorbereitung).
- ANSAGE_PLATZHALTER nennt keinen Behandler mehr.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import kern.gedaechtnis as ged
import kern.tenants as tenants
import kern.tts as tts
from bianca import weiterleiten


def _sit(client_id: str) -> dict:
    return {
        "id": "m1", "stimme": "Bianca",
        "tenant": {"clientId": client_id, "praxisName": "Praxis Zwei"},
        "sammler": {"vorname": "Eva", "nachname": "Muster", "telefon": "0211 555 001",
                    "grund": "Kontrolle", "modus": "buchen"},
        "messages": [{"role": "user", "content": "Ich haette gern einen Termin."}],
        "tools": [{"name": "book_slot", "ok": True}],
        "lastBook": {"booked": True, "slotIso": "2026-09-03T10:00", "dryRun": True},
    }


def test_report_traegt_mandanten_der_sitzung():
    gesehen = []

    class _R:
        status_code = 201

        @staticmethod
        def json():
            return {"ok": True, "created": True}

    echt = ged.httpx.post
    ged.httpx.post = lambda url, **kw: gesehen.append(kw["headers"]) or _R()
    try:
        ged.report_senden(_sit("praxis2"))
        assert gesehen and gesehen[0]["X-Client-Id"] == "praxis2"
    finally:
        ged.httpx.post = echt


def test_report_ohne_tenant_faellt_auf_env_zurueck():
    gesehen = []

    class _R:
        status_code = 201

        @staticmethod
        def json():
            return {"ok": True, "created": True}

    echt = ged.httpx.post
    ged.httpx.post = lambda url, **kw: gesehen.append(kw["headers"]) or _R()
    try:
        sit = _sit("")
        sit["tenant"] = {}
        ged.report_senden(sit)
        assert gesehen and gesehen[0]["X-Client-Id"] == ged.MAS_CLIENT_ID
    finally:
        ged.httpx.post = echt


def test_kontext_abfragen_mit_mandant():
    gesehen = []

    def fake_get(url, params=None, headers=None, **kw):
        gesehen.append((url, headers or {}))

        class _R:
            @staticmethod
            def json():
                return {"ok": True, "found": False, "context": "", "results": [], "events": []}
        return _R()

    echt = ged.httpx.get
    ged.httpx.get = fake_get
    try:
        ged._kontext_holen("02115550001", "Eva Muster", "praxis2")
        assert gesehen, "es muss abgefragt worden sein"
        assert all(h.get("X-Client-Id") == "praxis2" for _, h in gesehen), gesehen
        gesehen.clear()
        ged.ereignisse_holen("02115550001", "Eva Muster", "praxis2")
        assert gesehen and all(h.get("X-Client-Id") == "praxis2" for _, h in gesehen)
    finally:
        ged.httpx.get = echt


def test_aussprache_kommt_aus_tenant_json():
    tts.aussprache_zuruecksetzen()
    try:
        # meddent.json traegt das Feld seit W-MANDANT-4 — die drei Behandler
        # muessen weiter umgeschrieben werden, Vornamen-Regeln bleiben.
        assert tts._normalisieren("Dr. Petsas und Michael") == "Dr. Pet-sas und Micha-el"
        assert tts._normalisieren("Patrikis, Nikolaou") == "Pa-tri-kis, Ni-ko-la-u"
    finally:
        tts.aussprache_zuruecksetzen()


def test_aussprache_fallback_ohne_tenants():
    echt_dir = tenants.TENANTS_DIR
    tts.aussprache_zuruecksetzen()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tenants.TENANTS_DIR = Path(tmp)  # kein Tenant traegt "aussprache"
            assert tts._normalisieren("Petsas") == "Pet-sas", "eingebaute Liste muss greifen"
    finally:
        tenants.TENANTS_DIR = echt_dir
        tts.aussprache_zuruecksetzen()


def test_von_did_findet_mandanten():
    echt_dir = tenants.TENANTS_DIR
    try:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "eins.json").write_text(json.dumps({
                "clientId": "praxis1", "praxisName": "Eins", "dids": ["+49 211 5550100"],
            }), encoding="utf-8")
            (p / "zwei.json").write_text(json.dumps({
                "clientId": "praxis2", "praxisName": "Zwei", "dids": ["02115550200"],
            }), encoding="utf-8")
            tenants.TENANTS_DIR = p
            hit = tenants.von_did("+492115550100")
            assert hit and hit["clientId"] == "praxis1"
            # Landesvorwahl-Toleranz: 0211... trifft +49211...
            hit2 = tenants.von_did("+49 211 555 0200")
            assert hit2 and hit2["clientId"] == "praxis2"
            assert tenants.von_did("+49 211 9999999") is None
            assert tenants.von_did("") is None
    finally:
        tenants.TENANTS_DIR = echt_dir


def test_platzhalter_ansage_ohne_behandler_namen():
    t = weiterleiten.ANSAGE_PLATZHALTER.lower()
    assert "petsas" not in t and "kirri" not in t
    assert "weiterleitung" in t


def test_alle_tenant_dateien_vollstaendig():
    """W-MANDANT-7: Jede Datei in tenants/ ist ein fahrbarer Mandant.

    Die Suite prueft ALLE Tenant-JSONs (nicht nur meddent) — eine kaputte oder
    unvollstaendige Mandanten-Datei faellt so im Gate auf, bevor ein Anruf sie
    laedt. Der Testmandant praxis2 laeuft hier automatisch mit."""
    dateien = sorted(tenants.TENANTS_DIR.glob("*.json"))
    assert dateien, "tenants/ darf nicht leer sein"
    alle_dids: dict[str, str] = {}
    for pfad in dateien:
        t = json.loads(pfad.read_text(encoding="utf-8"))
        for pflicht in ("clientId", "praxisName", "locationId"):
            assert str(t.get(pflicht) or "").strip(), f"{pfad.name}: Feld {pflicht} fehlt"
        assert isinstance(t.get("dids", []), list), f"{pfad.name}: dids muss Liste sein"
        assert isinstance(t.get("calendars", []), list), f"{pfad.name}: calendars muss Liste sein"
        if t.get("aussprache") is not None:
            assert isinstance(t["aussprache"], dict), f"{pfad.name}: aussprache muss Objekt sein"
        for did in t.get("dids") or []:
            ziffern = "".join(c for c in str(did) if c.isdigit())
            assert ziffern, f"{pfad.name}: leere DID"
            assert ziffern not in alle_dids, (
                f"DID {did} doppelt: {pfad.name} und {alle_dids[ziffern]}"
            )
            alle_dids[ziffern] = pfad.name


def test_praxis2_testmandant_laedt():
    """Der stehende Testmandant praxis2 (W-MANDANT-7) verhaelt sich wie ein
    echter Mandant: laden(), von_did() und die Aussprache-Vereinigung greifen."""
    t = tenants.laden("praxis2")
    assert t["clientId"] == "praxis2"
    assert t["behandler"] == "Dr. Vlachos"
    hit = tenants.von_did("+49 999 0000002")
    assert hit and hit["clientId"] == "praxis2"
    tts.aussprache_zuruecksetzen()
    try:
        assert tts._normalisieren("Dr. Vlachos") == "Dr. Wla-chos"
    finally:
        tts.aussprache_zuruecksetzen()
