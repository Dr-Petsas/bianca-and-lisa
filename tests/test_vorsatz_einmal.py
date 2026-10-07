"""W-VORSATZ-EINMAL (07.10.2026): „mehrere Termine“ nur beim ersten Mal.

Live 06.10.2026 (5af9635e, 4eb8de09, e5066c5e): beim zweiten Durchlauf
blieb nur „Zu dieser Zeit sehe ich mehrere Termine.“ stehen — ohne Frage.
"""

from bianca import gehirn, verwalten
from kern.tenants import laden


def _sit() -> dict:
    sit = {"id": "vorsatz", "tenant": laden("blessing"), "messages": [],
           "booking": {}, "tools": [], "zuege": []}
    s = gehirn.sammler(sit)
    s["modus"] = "absagen"
    sit["verwHinweis"] = {"date": "2026-10-08", "hour": 10, "minuteOfDay": 600}
    return sit


def _zwei_patienten(monkeypatch) -> None:
    termine = [
        {"id": "a1", "patientId": "p1", "patientName": "Anna Albers",
         "calendarId": "k1", "start": "2026-10-08T10:00:00+02:00"},
        {"id": "a2", "patientId": "p2", "patientName": "Bernd Beck",
         "calendarId": "k1", "start": "2026-10-08T10:00:00+02:00"},
    ]
    monkeypatch.setattr(verwalten, "_detail_kandidaten",
                        lambda sit, melde: {"appointments": termine, "source": "tag"})


def test_mehrere_termine_vorsatz_nur_beim_ersten_mal(monkeypatch):
    _zwei_patienten(monkeypatch)
    sit = _sit()

    _, erst = verwalten._detail_dispatch(sit, None)
    _, zweit = verwalten._detail_dispatch(sit, None)

    assert erst["text"].startswith("Zu dieser Zeit sehe ich mehrere Termine.")
    assert "?" in erst["text"]
    assert "mehrere Termine" not in zweit["text"]
    assert "?" in zweit["text"]
    assert gehirn.sammler(sit)["frage"] in {"nachname", "name", "buchstabieren"}


def test_nach_reset_kommt_der_vorsatz_wieder(monkeypatch):
    _zwei_patienten(monkeypatch)
    sit = _sit()
    verwalten._detail_dispatch(sit, None)
    verwalten._verw_reset(sit)
    gehirn.sammler(sit)["modus"] = "absagen"
    sit["verwHinweis"] = {"date": "2026-10-08", "hour": 10, "minuteOfDay": 600}

    _, wieder = verwalten._detail_dispatch(sit, None)

    assert wieder["text"].startswith("Zu dieser Zeit sehe ich mehrere Termine.")


def test_notaus_spricht_den_vorsatz_immer(monkeypatch):
    monkeypatch.setenv("VORSATZ_EINMAL", "0")
    _zwei_patienten(monkeypatch)
    sit = _sit()
    verwalten._detail_dispatch(sit, None)

    _, zweit = verwalten._detail_dispatch(sit, None)

    assert zweit["text"].startswith("Zu dieser Zeit sehe ich mehrere Termine.")
