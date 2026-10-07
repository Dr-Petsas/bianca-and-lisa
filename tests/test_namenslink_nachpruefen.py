"""W-NAMENSLINK-NACHPRUEFEN (07.10.2026, Anruf dad02eaf): ``agentNameConfirm
action=create`` lief in den Client-Timeout (httpStatus 0), die Cloud Function
hatte Termin, Link und SMS aber erzeugt. Bianca sagte, es habe nicht geklappt,
und brach die Reservierung ab. Jetzt fragt sie bei httpStatus 0 einmal
``action=status`` mit demselben Token nach; nur ``open``/``done`` zählt.

Offline, kein Netz.
"""

import pytest

from bianca import gehirn
from kern import namenslink
from tests.test_bianca_bausteine import _sit


@pytest.fixture(autouse=True)
def _an(monkeypatch):
    monkeypatch.setenv("NAMENS_LINK", "1")
    monkeypatch.delenv("NAMENSLINK_NACHPRUEFEN", raising=False)


def _handy_sit():
    sit = _sit()
    sit["id"] = "sitzung-nachpruefen"
    sit["anrufer"] = {"telefon": "+491776004600"}
    gehirn.sammler(sit).update({
        "slotIso": "2026-10-08T09:00:00+02:00",
        "calendarId": "cal-1",
        "motivId": "motiv-1",
    })
    return sit


def _cf(monkeypatch, *, create, status):
    calls = []

    def cf(route, body, timeout=None):
        calls.append((body.get("action"), timeout))
        if body["action"] == "create":
            return create
        if body["action"] == "status":
            return status
        if body["action"] == "abort":
            return 200, {"status": "cancelled"}, {}
        return 200, {"status": "ok"}, {}

    monkeypatch.setattr(namenslink, "_cf_call", cf)
    return calls


_TIMEOUT = (0, None, {"httpStatus": 0})


@pytest.mark.parametrize("remote", ["open", "done"])
def test_timeout_aber_sms_raus_gilt_als_erfolg(monkeypatch, remote):
    calls = _cf(monkeypatch, create=_TIMEOUT, status=(200, {"status": remote}, {}))
    sit = _handy_sit()
    aus = namenslink.starten(sit, parallel=True, appointment_id="apt-1",
                             patient_id="pat-1")
    assert aus is not None
    assert [a for a, _ in calls] == ["create", "status"]
    assert calls[1][1] == 3.0
    stand = sit["namenslink"]
    assert stand["sent"] is True and stand["bound"] is True
    assert stand["token"] == namenslink.reservierungs_token(sit)
    assert "createFailed" not in stand
    assert namenslink.offen(sit)


def test_timeout_ohne_termin_ist_nicht_gebunden(monkeypatch):
    _cf(monkeypatch, create=_TIMEOUT, status=(200, {"status": "open"}, {}))
    sit = _handy_sit()
    assert namenslink.starten(sit, parallel=True) is not None
    assert sit["namenslink"]["bound"] is False


@pytest.mark.parametrize("status", [
    (200, {"status": "pending_sms"}, {}),
    (200, {"status": "create_failed"}, {}),
    (404, {"status": "not_found"}, {}),
    (0, None, {}),
])
def test_status_ohne_versandbeleg_bleibt_fail_closed(monkeypatch, status):
    calls = _cf(monkeypatch, create=_TIMEOUT, status=status)
    sit = _handy_sit()
    assert namenslink.starten(sit, parallel=True, appointment_id="apt-1",
                              patient_id="pat-1") is None
    assert [a for a, _ in calls] == ["create", "status", "abort"]
    assert sit["namenslink"]["createFailed"] is True


def test_echte_ablehnung_fragt_nicht_nach(monkeypatch):
    calls = _cf(monkeypatch, create=(502, {"status": "error", "sent": False}, {}),
                status=(200, {"status": "open"}, {}))
    sit = _handy_sit()
    assert namenslink.starten(sit, parallel=True, appointment_id="apt-1",
                              patient_id="pat-1") is None
    assert [a for a, _ in calls] == ["create", "abort"]


def test_erfolg_ohne_timeout_kein_zusatzaufruf(monkeypatch):
    sit = _handy_sit()
    tok = namenslink.reservierungs_token(sit)
    calls = _cf(monkeypatch, create=(200, {"status": "ok", "token": tok,
                                           "sent": True, "bound": True}, {}),
                status=(200, {"status": "open"}, {}))
    assert namenslink.starten(sit, parallel=True, appointment_id="apt-1") is not None
    assert [a for a, _ in calls] == ["create"]


def test_notaus(monkeypatch):
    monkeypatch.setenv("NAMENSLINK_NACHPRUEFEN", "0")
    calls = _cf(monkeypatch, create=_TIMEOUT, status=(200, {"status": "open"}, {}))
    sit = _handy_sit()
    assert namenslink.starten(sit, parallel=True, appointment_id="apt-1",
                              patient_id="pat-1") is None
    assert [a for a, _ in calls] == ["create", "abort"]
