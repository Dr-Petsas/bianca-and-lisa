"""Sicherheitsnetze für den deaktivierten semantischen Task-Router."""

from bianca import agent
from kern import calendar, zuege


def test_toolpfad_behaelt_sicherheits_latches_im_sitzungskontext(monkeypatch):
    sit = {"tenant": {}, "booking": {}}

    def fake_book(tenant, ctx, *, slot_iso=""):
        ctx["namensunsicher"] = True
        return {"ok": False, "booked": False, "spoken": "Rückfrage nötig."}

    monkeypatch.setattr(calendar, "book_slot", fake_book)

    result = zuege.run_tool(
        sit, "book_slot", {"slot_iso": "2026-10-21T09:30:00+02:00"})

    assert result["ok"] is False
    assert sit["booking"]["namensunsicher"] is True


def test_buchungs_wache_reicht_unsicherheit_an_fluss_sync_weiter(
    monkeypatch,
):
    slot = "2026-10-21T09:30:00+02:00"
    sit = {
        "offered": [{"iso": slot, "spoken": "Mittwoch um neun Uhr dreißig"}],
        "sammler": {
            "phase": "bestaetigen",
            "frage": "bestaetigung",
            "slotIso": slot,
        },
    }

    monkeypatch.setattr(
        zuege,
        "run_tool",
        lambda *_a, **_k: {
            "ok": False,
            "booked": False,
            "slotIso": slot,
            "verificationFailed": True,
            "possiblyBooked": True,
            "writeAttempted": True,
            "manualCheckRequired": True,
            "spoken": "Die Buchung ist nicht eindeutig bestätigt.",
        },
    )

    _text, book = zuege.buchungs_wache(
        sit, "Alles klar, ich buche das für Sie.")

    assert book is not None
    assert book["verificationFailed"] is True
    assert book["possiblyBooked"] is True
    assert book["writeAttempted"] is True
    assert book["manualCheckRequired"] is True

    agent._fluss_sync(sit, ["book_slot"], book)

    assert sit["buchungUnklar"]["slotIso"] == slot
    assert sit["slotGesperrt"] == [slot]
    assert sit["sammler"]["phase"] == "fertig"
    assert sit["sammler"]["slotIso"] == ""


def test_llm_notauspfad_markiert_unklaren_write_und_sperrt_slot():
    slot = "2026-10-21T09:30:00+02:00"
    sit = {
        "sammler": {
            "phase": "bestaetigen",
            "frage": "bestaetigen",
            "slotIso": slot,
        },
        "buchIntent": True,
    }

    agent._fluss_sync(sit, ["book_slot"], {
        "booked": False,
        "slotIso": slot,
        "verificationFailed": True,
        "possiblyBooked": True,
        "writeAttempted": True,
    })

    assert sit["sammler"]["phase"] == "fertig"
    assert sit["sammler"]["slotIso"] == ""
    assert sit["buchungUnklar"]["slotIso"] == slot
    assert sit["slotGesperrt"] == [slot]
    assert "buchIntent" not in sit
