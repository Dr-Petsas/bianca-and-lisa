"""W-TASK-GRENZE (09.09.2026): duenne, typisierte Task-Grenze vor flow.zug.

Der Adapter muss transparent sein — gleiche Antwort und gleiche Werkzeug-
aufrufe wie der direkte flow.zug. Zusaetzlich ein Task-Ledger. Notaus
TASK_ADAPTERS=0. Offline, kein Netz.
"""

import copy

from bianca import flow, tasks
from kern import hirn
from kern.tenants import laden


def _sit() -> dict:
    sit = {
        "stimme": "Bianca",
        "tenant": laden("meddent"),
        "messages": [{"role": "system", "content": "x"}],
    }
    hirn.init(sit)
    return sit


def _deutung(handlung: str, gegenstand: str = "VORGANG", *, ersatz=None) -> dict:
    return {"kanal": "ok", "zug": "wechseln", "handlung": handlung,
            "gegenstand": gegenstand, "fuer": "selbst", "ersatz": ersatz,
            "spiegel": ""}


# --- Registry + Typisierung -------------------------------------------------

def test_registry_kennt_alle_typen():
    assert set(tasks.registry()) == set(tasks.TASK_TYPEN)
    assert set(tasks.TASK_TYPEN) == {
        "buchen", "absagen", "verschieben", "auskunft", "anmeldung", "rueckruf",
    }


def test_aktueller_typ_aus_modus_und_signalen():
    sit = _sit()
    sit["sammler"] = {"modus": "verschieben"}
    assert tasks.aktueller_typ(sit) == "verschieben"
    sit["sammler"] = {"modus": ""}
    sit["hirnAbgeben"] = {"offen": True}
    assert tasks.aktueller_typ(sit) == "rueckruf"


# --- Lifecycle-Einordnung ---------------------------------------------------

def test_lifecycle_done_bei_gebucht():
    sit = _sit()
    sit["sammler"] = {"modus": "buchen", "phase": "gebucht"}
    assert tasks.lifecycle(sit, {"text": "ok"}, geparkt_vorher=set()) == "done"


def test_lifecycle_active_bei_offener_frage():
    sit = _sit()
    sit["sammler"] = {"modus": "buchen", "phase": "sammeln"}
    assert tasks.lifecycle(sit, {"text": "?"}, geparkt_vorher=set()) == "active"


def test_lifecycle_transfer_ist_done():
    sit = _sit()
    fl = {"transfer": {"nummer": "+49211302"}}
    assert tasks.lifecycle(sit, fl, geparkt_vorher=set()) == "done"


def test_lifecycle_parked_wenn_anliegen_geparkt():
    sit = _sit()
    vor = tasks._geparkte_ids(sit)
    hirn.anwenden(sit, _deutung("ANLEGEN"))
    hirn.anwenden(sit, _deutung("AENDERN", ersatz=False))  # parkt die Buchung
    assert tasks.lifecycle(sit, {"text": "?"}, geparkt_vorher=vor) == "parked"


def test_lifecycle_none_ist_leer():
    sit = _sit()
    assert tasks.lifecycle(sit, None, geparkt_vorher=set()) == ""


# --- Transparenz: gleiche Antwort mit und ohne Adapter ----------------------

def test_adapter_ist_transparent(monkeypatch):
    monkeypatch.setenv("TASK_ADAPTERS", "1")
    monkeypatch.setattr(flow.hintergrund, "anstossen", lambda sit: None)
    basis = _sit()
    hirn.anwenden(basis, _deutung("ANLEGEN"))
    a, b = copy.deepcopy(basis), copy.deepcopy(basis)
    fl_direkt = flow.zug(a, "Ich möchte zur Kontrolle.")
    fl_adapter = tasks.zug(b, "Ich möchte zur Kontrolle.")
    assert fl_direkt == fl_adapter                 # gleiche Antwort
    assert b.get("taskLedger")                     # Ledger nur beim Adapter
    assert "taskLedger" not in a


def test_notaus_reicht_flow_unveraendert_durch(monkeypatch):
    monkeypatch.setenv("TASK_ADAPTERS", "0")
    monkeypatch.setattr(flow.hintergrund, "anstossen", lambda sit: None)
    basis = _sit()
    hirn.anwenden(basis, _deutung("ANLEGEN"))
    a, b = copy.deepcopy(basis), copy.deepcopy(basis)
    fl_direkt = flow.zug(a, "Ich möchte zur Kontrolle.")
    fl_aus = tasks.zug(b, "Ich möchte zur Kontrolle.")
    assert fl_direkt == fl_aus
    assert "taskLedger" not in b   # Notaus: kein Ledger, reines flow.zug


def test_ledger_faellt_bei_none_nicht_an(monkeypatch):
    monkeypatch.setenv("TASK_ADAPTERS", "1")
    monkeypatch.setattr(flow.hintergrund, "anstossen", lambda sit: None)
    sit = _sit()  # kein Modus -> reiner Smalltalk-Satz gibt None
    fl = tasks.zug(sit, "Schönes Wetter heute, nicht wahr?")
    assert fl is None
    assert not sit.get("taskLedger")
