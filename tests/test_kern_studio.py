"""Dialogkern-Seite im Studio (``tests/baukasten/editor.py`` + ``kernprobe.py``).

Das isolierte Dock ist weg; getestet und eingestellt wird der Kern im
Teststudio — mandantenscharf, mit der Superuser-Maske fuer ``DialogPolicyV1``
und simulierten Werkzeugen. Diese Tests laufen ueber den FastAPI-Testklienten:
kein Server, kein LLM, kein Netz, kein Kalender-Schreiben.

Wichtigste Zusicherungen (in dieser Reihenfolge der Wichtigkeit):
  1. Die Maske kann die unveraenderlichen Sicherheitsgrenzen NICHT aufweichen
     (Telefon zuletzt, Ziffern-Rueckbestaetigung, Beweis vor Erfolg).
  2. Uebersteuern in der Maske aendert den Praxisstand nicht (nichts wird
     gespeichert) — das Studio ist eine Probe, keine Veroeffentlichung.
  3. Der Kern laeuft mandantenscharf und kommt aus Schleifen wieder heraus.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from bianca.controller import dialog_policy as dp  # noqa: E402
from tests.baukasten import editor, kernprobe  # noqa: E402


@pytest.fixture(autouse=True)
def _ohne_llm(monkeypatch):
    """Kein Netzversuch: der Kern faellt auf seine Regeln zurueck (deterministisch)."""
    monkeypatch.setattr(kernprobe, "_hirn_geprueft", True, raising=False)
    monkeypatch.setattr(kernprobe, "_hirn_fn", None, raising=False)


@pytest.fixture
def k():
    with TestClient(editor.app) as klient:
        yield klient


def _policy(k, tenant: str = "meddent", roh=None) -> dict:
    last = {"tenant": tenant}
    if roh is not None:
        last["policy"] = roh
    j = k.post("/api/kern/policy", json=last).json()
    assert j["ok"] is True, j
    return j


def _sid(k, tenant: str = "meddent", szenario: str = "normal", roh=None) -> str:
    last = {"tenant": tenant, "szenario": szenario}
    if roh is not None:
        last["policy"] = roh
    j = k.post("/api/kern/start", json=last).json()
    assert j["ok"] is True, j
    return j["kopf"]["sid"]


def _zug(k, sid: str, text: str) -> dict:
    j = k.post("/api/kern/zug", json={"sid": sid, "text": text}).json()
    assert j["ok"] is True, j
    return j["zug"]


# --------------------------------------------------------------------------- #
# 1. Sicherheitsgrenzen: was die Maske NIE anfassen darf.
# --------------------------------------------------------------------------- #
def test_telefon_ist_in_keiner_reihenfolge_waehlbar(k):
    """W-TELEFON-ZULETZT: die Nummer kommt zuletzt, nie per Maske vorgezogen."""
    j = k.get("/api/kern/maske").json()
    assert j["ok"] is True
    felder = [f for g in j["gruppen"] for f in g["felder"]]
    for f in felder:
        assert "telefon" not in (f.get("auswahl") or []), f
    assert all(f.get("pfad") and f.get("typ") for f in felder)
    assert j["invarianten"], "die Maske nennt die unveraenderlichen Grenzen"


def test_maske_kann_pflichtfelder_nicht_erfinden(k):
    """Unbekannte Slots fallen im Vertrag weg und werden ehrlich gemeldet."""
    roh = dict(_policy(k)["policy"])
    anliegen = {typ: dict(d) for typ, d in (roh.get("anliegen") or {}).items()}
    anliegen["buchen"]["pflicht"] = ["besuchsgrund", "telefon", "iban"]
    roh["anliegen"] = anliegen
    j = _policy(k, roh=roh)
    reihe = j["policy"]["anliegen"]["buchen"]["pflicht"]
    assert "telefon" not in reihe, "W-TELEFON-ZULETZT: nie vorziehbar"
    assert "iban" not in reihe
    assert j["warnungen"], "der Parser sagt, was er verworfen hat"


def test_auswahl_der_reihenfolge_ist_der_vertrag_nicht_die_maske(k):
    """Eine Quelle der Wahrheit: die Maske zeigt exakt die Vertrags-Slots."""
    j = k.get("/api/kern/maske").json()
    listen = [f for g in j["gruppen"] for f in g["felder"] if f.get("typ") == "liste"]
    buchen = [f for f in listen if f["pfad"] == ["anliegen", "buchen", "pflicht"]]
    assert buchen, "die Buchungs-Reihenfolge ist einstellbar"
    assert tuple(buchen[0]["auswahl"]) == dp.BUCHEN_SLOTS
    ident = [f for f in listen if f["pfad"][-1] == "identify"]
    assert ident and all(tuple(f["auswahl"]) == dp.IDENTIFY_SLOTS for f in ident)


# --------------------------------------------------------------------------- #
# 2. Uebersteuern ist eine Probe, keine Veroeffentlichung.
# --------------------------------------------------------------------------- #
def test_uebersteuern_laesst_den_praxisstand_unberuehrt(k):
    vorher = _policy(k)
    roh = dict(vorher["policy"])
    roh["rueckfrage"] = dict(roh.get("rueckfrage") or {}, max_rueckfragen=1)
    uebersteuert = _policy(k, roh=roh)
    assert uebersteuert["quelle"] == "uebersteuert"
    assert uebersteuert["policy"]["rueckfrage"]["max_rueckfragen"] == 1
    nachher = _policy(k)
    assert nachher["quelle"] == vorher["quelle"]
    assert nachher["policy"] == vorher["policy"]


def test_policy_ist_mandantenscharf(k):
    fach = {t: _policy(k, t)["fachId"] for t in ("meddent", "blessing", "ruether")}
    assert fach["meddent"] == "zahnmedizin"
    assert fach["blessing"] != fach["meddent"]
    assert fach["ruether"] != fach["meddent"]
    for t in ("meddent", "blessing", "ruether", "thaler"):
        j = _policy(k, t)
        assert j["quelle"] in ("vertrag", "legacy")
        assert isinstance(j["policy"], dict) and j["policy"]


# --------------------------------------------------------------------------- #
# 3. Gespraech gegen den reinen Kern.
# --------------------------------------------------------------------------- #
def test_start_spricht_und_fuehrt_das_szenario(k):
    j = k.post("/api/kern/start",
               json={"tenant": "meddent", "szenario": "slot_weg"}).json()
    assert j["ok"] is True
    assert j["kopf"]["szenario"] == "slot_weg"
    assert j["zug"]["antwort"], "die Begruessung wird gesprochen"


def test_buchungsfluss_sammelt_ohne_doppelte_frage(k):
    sid = _sid(k)
    gefragt: list[str] = []
    for satz in ("Ich haette gern einen Termin zur Kontrolle.",
                 "Nein, ich war noch nie bei Ihnen.",
                 "Bei Doktor Petsas bitte.",
                 "Naechste Woche Dienstag vormittags."):
        zug = _zug(k, sid, satz)
        assert zug["antwort"], f"stumm nach: {satz}"
        frage = (zug.get("zustand") or {}).get("frage") or ""
        if frage:
            gefragt.append(frage)
    assert len(gefragt) == len(set(gefragt)), gefragt
    assert (zug["zustand"]["zugNr"]) >= 4


def test_unklare_zuege_enden_in_der_uebergabe_statt_in_der_schleife(k):
    """Kein Endlos-Umformulieren: Neustart-Bitte, dann ehrlich abgeben."""
    roh = dict(_policy(k)["policy"])
    roh["rueckfrage"] = dict(roh.get("rueckfrage") or {}, max_rueckfragen=1)
    sid = _sid(k, roh=roh)
    antworten: list[str] = []
    uebergeben = False
    for _ in range(8):
        zug = _zug(k, sid, "haeh?")
        if zug.get("antwort"):
            antworten.append(zug["antwort"])
        if zug.get("uebergeben") or zug.get("hangup"):
            uebergeben = True
            break
    assert uebergeben, antworten
    assert len(set(antworten)) == len(antworten), antworten


def test_unbekannte_sitzung_wird_ehrlich_abgelehnt(k):
    j = k.post("/api/kern/zug", json={"sid": "gibtsnicht", "text": "hallo"}).json()
    assert j["ok"] is False and j.get("fehler")


def test_seite_und_mittel_werden_ausgeliefert(k):
    for pfad in ("/dialogkern", "/web/dialogkern.js", "/web/stil.css"):
        r = k.get(pfad)
        assert r.status_code == 200 and len(r.content) > 200, pfad
    assert b"kern-raster" in k.get("/web/stil.css").content
