"""W-TOOL-UI (02.09.2026): CF-Dispatch landet in der Unterhaltung."""

from __future__ import annotations

import kern.calendar as kal
from kern.sitzung import _tools_des_zugs, merke_tool


def test_cf_call_liefert_dispatch_mit_url_body_response(monkeypatch):
    monkeypatch.setattr(kal, "CF_BASE", "https://example.test")
    monkeypatch.setattr(
        kal, "_cf_post",
        lambda route, body, timeout=None: (200, {
            "status": "success",
            "data": {
                "free_time_slots": [
                    "2026-08-28T10:30:00+02:00",
                    "2026-08-28T11:00:00+02:00",
                ],
                "doctor_name": "Dr. Michael Petsas",
                "visit_motive_name": "akute Schmerzen / Notfall",
            },
        }),
    )
    status, data, dispatch = kal._cf_call("getFreeTimeSlots", {
        "clientId": "c1",
        "locationId": "l1",
        "source": "phone_agent",
    })
    assert status == 200 and data["status"] == "success"
    assert dispatch["method"] == "POST"
    assert dispatch["url"] == "https://example.test/getFreeTimeSlots"
    assert dispatch["request"]["clientId"] == "c1"
    assert dispatch["httpStatus"] == 200
    assert isinstance(dispatch["ms"], int) and dispatch["ms"] >= 0
    assert dispatch["response"]["data"]["doctor_name"] == "Dr. Michael Petsas"
    keys = {u["key"] for u in dispatch["updates"]}
    assert "free_time_slots" in keys and "doctor_name" in keys


def test_find_slots_haengt_dispatch_an(monkeypatch):
    monkeypatch.setattr(kal, "CF_BASE", "https://example.test")
    monkeypatch.setattr(
        kal, "_cf_post",
        lambda route, body, timeout=None: (200, {
            "status": "success",
            "data": {"free_time_slots": ["2026-09-01T09:00:00+02:00"], "doctor_name": "Dr. X"},
        }),
    )
    found = kal.find_slots(
        {"clientId": "c1", "locationId": "l1"},
        {"calendarId": "cal1", "visitMotiveId": "vm1", "visitMotiveName": "Kontrolle"},
        source="pickadoc-bianca",
    )
    assert found["ok"] is True
    d = found["dispatch"]
    assert d["route"] == "getFreeTimeSlots"
    assert d["request"]["calendarId"] == "cal1"
    assert "2026-09-01T09:00:00+02:00" in found["slots"]


def test_merke_tool_buendelt_dispatch_fuer_zug():
    sit = {"tools": [], "booking": {}}
    result = {
        "ok": True,
        "spoken": "Frei …",
        "dispatch": {
            "route": "getFreeTimeSlots",
            "url": "https://example.test/getFreeTimeSlots",
            "method": "POST",
            "request": {"clientId": "c1"},
            "httpStatus": 200,
            "ms": 1900,
            "response": {"status": "success"},
            "updates": [{"key": "doctor_name", "from": "", "to": "Dr. X"}],
        },
    }
    merke_tool(sit, "getFreeTimeSlots", result, args={"wish": "morgen"})
    assert len(sit["tools"]) == 1
    ein = sit["tools"][0]
    assert ein["name"] == "getFreeTimeSlots"
    assert ein["cf"] == "getFreeTimeSlots"
    assert ein["ms"] == 1900
    assert ein["args"]["wish"] == "morgen"
    assert ein["dispatch"]["url"].endswith("/getFreeTimeSlots")
    assert ein["dispatch"]["request"]["clientId"] == "c1"
    zug = _tools_des_zugs(sit)
    assert len(zug) == 1 and zug[0]["ms"] == 1900
    assert _tools_des_zugs(sit) == []


def test_angebot_zeigt_hintergrund_vorrat_als_tool():
    """Hintergrund hat getFreeTimeSlots schon geladen — Angebots-Zug muss die
    Tool-Karte trotzdem tragen (W-VORRAT-UI, live 02.09. Tzannis)."""
    from bianca import flow, gehirn
    from kern.tenants import laden

    sit = {
        "tenant": laden("meddent"),
        "slotVorrat": [
            "2026-09-02T10:15:00+02:00",
            "2026-09-02T12:45:00+02:00",
        ],
        "vorratDispatch": {
            "route": "getFreeTimeSlots",
            "url": "https://example.test/getFreeTimeSlots",
            "method": "POST",
            "request": {"clientId": "c1", "calendarId": "cal1"},
            "httpStatus": 200,
            "ms": 420,
            "response": {"status": "success"},
            "updates": [],
        },
        "vorratGemerkt": False,
        "tools": [],
    }
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "warSchonMal": True,
        "arzt": {"typ": "genannt", "calendarId": "cal1", "calendarName": "Dr. Petsas"},
        "motivId": "vm1", "motivName": "Kontrolle",
        "grund": "Kontrolle", "wunsch": {"date": "2026-09-02"},
        "vorname": "Kiriakos", "nachname": "Tzannis", "bekannt": True,
        "buchstabiert": True, "telefonOk": True, "telefon": "015253904756",
    })
    # Kein CF-Nachladen — Vorrat deckt den Wunsch ab.
    ang = flow._angebot(sit)
    assert ang and "frei" in (ang.get("text") or "").lower()
    tools = sit.get("tools") or []
    assert any(t.get("name") == "getFreeTimeSlots" for t in tools), tools
    ein = next(t for t in tools if t["name"] == "getFreeTimeSlots")
    assert ein.get("dispatch", {}).get("url", "").endswith("/getFreeTimeSlots")
    assert sit.get("vorratGemerkt") is True
    # Zweiter Angebots-Zug ohne neuen Vorrat: keine Doppel-Karte.
    n_vorher = len(tools)
    flow._angebot(sit)
    assert len(sit["tools"]) == n_vorher


def test_response_kappen_lange_slot_liste():
    slots = [f"2026-09-01T{h:02d}:00:00+02:00" for h in range(8, 20)] * 5
    assert len(slots) > kal._SLOT_CAP
    gekappt = kal._response_kappen({
        "status": "success",
        "data": {"free_time_slots": slots, "doctor_name": "Dr. X"},
    })
    assert len(gekappt["data"]["free_time_slots"]) == kal._SLOT_CAP
    assert gekappt["data"]["free_time_slots_total"] == len(slots)
