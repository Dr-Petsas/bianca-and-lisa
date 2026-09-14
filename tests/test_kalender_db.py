"""kalender_db.in_tenant_mergen — Firestore-Funktionsname schlaegt CF-Besitzername.

Live 14.09.2026 (Nacht vor dem Feldtest, read-only geprueft auf pickadoc1):
die CF `onPickadocPhoneCall` liefert Thalers Kalender nach BESITZER
("Eva Thaler", "Franziska Schmidt"), Firestore fuehrt denselben zweiten
Kalender als "Prophylaxe". Weil die Id schon in der Liste stand, haengte der
Merge nichts an und der Personenname blieb — `zimmer_map.raeume(t, "pzr")`
lieferte Eva Thaler: JEDE telefonisch gebuchte Zahnreinigung waere im
Kalender der Zahnaerztin statt in der Prophylaxe gelandet.
"""

from kern import kalender_db, tenants as kern_tenants, zimmer_map
from kern.zimmer_map import THALER_CLIENT

EVA = "QfAXRMiLpJVESMCFBLF6"
PROPHY = "xTz59BMpyKF6xCvURrGT"


def _cf_tenant() -> dict:
    return {
        "clientId": THALER_CLIENT,
        "locationId": "loc_m219jgfb",
        "praxisName": "Thaler Zahnmedizin",
        "defaultCalendarId": EVA,
        "calendars": [
            {"id": EVA, "name": "Eva Thaler"},
            {"id": PROPHY, "name": "Franziska Schmidt"},
        ],
    }


def _firestore_stand(*_a, **_k) -> dict:
    return {
        "calendars": [{"id": PROPHY, "name": "Prophylaxe"}],
        "rooms": [{"id": "r2", "name": "Zi2 PZR"}, {"id": "r4", "name": "Zi4 Thaler"}],
    }


def test_funktionskalender_wird_umbenannt_statt_uebersprungen(monkeypatch):
    monkeypatch.setattr(kalender_db, "_stand", _firestore_stand)
    t = _cf_tenant()
    kalender_db.in_tenant_mergen(t)
    namen = {c["id"]: c["name"] for c in t["calendars"]}
    assert namen == {EVA: "Eva Thaler", PROPHY: "Prophylaxe"}, namen
    assert len(t["calendars"]) == 2  # nichts doppelt angehaengt
    assert [r["name"] for r in t["rooms"]] == ["Zi2 PZR", "Zi4 Thaler"]


def test_pzr_landet_nach_merge_in_der_prophylaxe(monkeypatch):
    monkeypatch.setattr(kalender_db, "_stand", _firestore_stand)
    t = _cf_tenant()
    kalender_db.in_tenant_mergen(t)
    assert [c["id"] for c in zimmer_map.raeume(t, "pzr")] == [PROPHY]
    assert [c["id"] for c in zimmer_map.raeume(t, "behandlung")] == [EVA]
    assert [c["id"] for c in zimmer_map.raeume(t, "akut")] == [EVA]
    # Prophylaxe ist kein Behandler: Behandlerliste = nur die Zahnaerztin.
    assert [c["id"] for c in kern_tenants.behandler_kalender(t)] == [EVA]


def test_ohne_merge_bleibt_der_alte_fehler_sichtbar(monkeypatch):
    """Gegenprobe: genau so lief es live — der Test dokumentiert den Befund."""
    monkeypatch.setattr(kalender_db, "_stand", lambda *_a, **_k: {"calendars": [], "rooms": []})
    t = _cf_tenant()
    kalender_db.in_tenant_mergen(t)
    assert [c["id"] for c in zimmer_map.raeume(t, "pzr")] == [EVA]


def test_fremder_mandant_bleibt_unangetastet(monkeypatch):
    monkeypatch.setattr(kalender_db, "_stand", _firestore_stand)
    t = {"clientId": "MEe4ZQHEzOPzLcexyhdT", "calendars": [{"id": "a", "name": "Doktor Michael Petsas"}]}
    kalender_db.in_tenant_mergen(t)
    assert t["calendars"] == [{"id": "a", "name": "Doktor Michael Petsas"}]
    assert "rooms" not in t
