"""Schattenlauf-Anzeige der zweiten Spalte in ``/anrufe`` (DIALOG_CONTROLLER).

Die rechte Spalte zeigte lange nur "fragt X" und ob die Frage vom Live-Pfad
abweicht. Der heutige Kern kann mehr: die Loop-Aufsicht
(``bianca/controller/aufsicht.py``) fasst EINMAL zusammen und gibt danach
ehrlich ab, statt dieselbe Frage endlos umzuformulieren — und welche Praxis-
Policy dabei galt, ist ebenfalls Teil der Aussage.

Geprueft wird deshalb, dass ``tools/kern_replay.py`` genau diese Felder ins
Manifest schreibt (die Anzeige liest nur daraus) und dass es dabei NICHTS am
Live-Mitschnitt aendert. Alles offline: kein Netz, kein Werkzeug, keine Datei.
"""
from __future__ import annotations

import copy

from tools import kern_replay as kr


def _manifest(zuege: list[dict], tenant: str = "meddent") -> dict:
    return {
        "id": "testsid",
        "tenantId": tenant,
        "startedAt": "2026-09-19T08:00:00Z",
        "endedAt": "2026-09-19T08:05:00Z",
        "zuege": zuege,
    }


def _wunsch_dann_unklar(n: int) -> list[dict]:
    """Live fragt n+1 mal dieselbe Ja/Nein-Frage, der Anrufer versteht nichts."""
    z = [{
        "art": "turn",
        "textIn": "Ich haette gern einen Termin zur Kontrolle.",
        "text": "Waren Sie schon einmal bei uns?",
        "frage": "schonmal",
    }]
    for _ in range(n):
        z.append({
            "art": "turn", "textIn": "haeh?",
            "text": "Waren Sie schon einmal bei uns?", "frage": "schonmal",
        })
    return z


# --------------------------------------------------------------------------- #
# Kopfzeile: Schema-Version und Praxis-Policy.
# --------------------------------------------------------------------------- #
def test_kopfzeile_traegt_version_und_policy():
    m = _manifest(_wunsch_dann_unklar(2))
    kr.replay_manifest(m)
    s = m["kernReplaySummary"]
    # Die Anzeige unterscheidet an ``v`` alte von neuen Schattenlaeufen.
    assert s["v"] == 2
    p = s["policy"]
    assert p["quelle"] in ("vertrag", "legacy")
    assert p["max_rueckfragen"] >= 1
    assert isinstance(p["zusammenfassung_bei_stocken"], bool)
    assert "buchen" in p["eigene_tasks"]
    assert p["fach_id"] == "zahnmedizin"


def test_policy_kommt_aus_dem_mandanten_nicht_aus_dem_code():
    """Zwei Faecher, zwei Policys — die Spalte darf nicht praxis-blind sein."""
    a = _manifest(_wunsch_dann_unklar(1), tenant="meddent")
    b = _manifest(_wunsch_dann_unklar(1), tenant="blessing")
    kr.replay_manifest(a)
    kr.replay_manifest(b)
    assert a["kernReplaySummary"]["policy"]["fach_id"] == "zahnmedizin"
    assert b["kernReplaySummary"]["policy"]["fach_id"] != "zahnmedizin"


# --------------------------------------------------------------------------- #
# Loop-Aufsicht: EIN Rueckblick, dann ehrliche Abgabe.
# --------------------------------------------------------------------------- #
def test_aufsicht_stufen_stehen_je_zug_im_manifest():
    m = _manifest(_wunsch_dann_unklar(9))
    agg = kr.replay_manifest(m)
    arten = [
        (z.get("kernReplay") or {}).get("aufsicht", {}).get("art")
        for z in m["zuege"]
    ]
    assert "rueckblick" in arten, arten
    assert "uebergabe" in arten, arten
    # Reihenfolge: erst zusammenfassen, dann abgeben — nie umgekehrt.
    assert arten.index("rueckblick") < arten.index("uebergabe")
    assert agg["aufsicht_rueckblick"] == 1
    assert agg["aufsicht_uebergabe"] == 1
    s = m["kernReplaySummary"]
    assert s["aufsicht_rueckblick"] == 1 and s["aufsicht_uebergabe"] == 1


def test_zaehler_erst_ab_der_zweiten_wiederholung():
    """``zahl == 1`` ist der Normalfall — als Zaehler waere das nur Rauschen."""
    m = _manifest(_wunsch_dann_unklar(9))
    kr.replay_manifest(m)
    zahlen = [
        (z.get("kernReplay") or {}).get("stock", {}).get("zahl")
        for z in m["zuege"]
    ]
    assert all(n is None or n >= 2 for n in zahlen), zahlen
    assert any(n == 2 for n in zahlen), zahlen
    for z in m["zuege"]:
        st = (z.get("kernReplay") or {}).get("stock")
        if st:
            assert st["budget"] >= 1


def test_uebergebene_zuege_werden_als_solche_gemeldet():
    """Was der Kern nicht fuehrt, gehoert ehrlich dem bisherigen Pfad."""
    m = _manifest([{
        "art": "turn",
        "textIn": "Ich habe eine Frage zu meiner Rechnung.",
        "text": "Rechnungen bespricht die Praxis persoenlich.",
        "frage": "",
    }])
    agg = kr.replay_manifest(m)
    kern = [z.get("kernReplay") or {} for z in m["zuege"]]
    assert agg["kern_uebergeben"] == sum(1 for k in kern if k.get("uebergeben"))


# --------------------------------------------------------------------------- #
# Live-Befunde: was der Kern vermieden haette (und was nicht).
# --------------------------------------------------------------------------- #
def test_vermiedene_schleife_nur_wenn_der_kern_wirklich_anders_handelt():
    m = _manifest(_wunsch_dann_unklar(9))
    agg = kr.replay_manifest(m)
    assert agg["schleifen"] >= 3
    assert 0 < agg["gerettet"] <= agg["schleifen"]
    for z in m["zuege"]:
        sig = z.get("liveSignal") or {}
        ger = sig.get("gerettet")
        if not ger:
            continue
        assert ger["grund"] in ("aufsicht", "andere_frage")
        if ger["grund"] == "andere_frage":
            # Nur dann "vermieden", wenn der Kern etwas ANDERES fragte.
            assert kr._kanon(ger["kern"]) != kr._kanon(z.get("frage") or "")


def test_gleiche_frage_ohne_eingriff_gilt_nicht_als_vermieden():
    """Ehrlichkeit: haette der Kern dasselbe gefragt, ist nichts gewonnen."""
    m = _manifest(_wunsch_dann_unklar(9))
    kr.replay_manifest(m)
    for z in m["zuege"]:
        kern = z.get("kernReplay") or {}
        sig = z.get("liveSignal") or {}
        if not sig.get("schleife") or kern.get("aufsicht"):
            continue
        kf = (kern.get("in") or {}).get("frage_id") or ""
        if kf and kr._kanon(kf) == kr._kanon(z.get("frage") or ""):
            assert "gerettet" not in sig


# --------------------------------------------------------------------------- #
# Der Live-Mitschnitt bleibt unberuehrt (die Spalte ist NUR Anzeige).
# --------------------------------------------------------------------------- #
def test_replay_aendert_keinen_live_wert():
    zuege = _wunsch_dann_unklar(4)
    zuege[0]["tools"] = [{"name": "masSearchPatients", "ok": True}]
    m = _manifest(zuege)
    vorher = copy.deepcopy(m)
    kr.replay_manifest(m)
    for alt, neu in zip(vorher["zuege"], m["zuege"]):
        for feld in ("textIn", "text", "frage", "art", "tools"):
            assert alt.get(feld) == neu.get(feld)
    # Zusatzfelder kommen additiv dazu, nichts wird ersetzt.
    assert set(vorher["zuege"][1]) <= set(m["zuege"][1])


def test_ohne_anrufer_zug_kein_schattenlauf():
    m = _manifest([{"art": "turn", "text": "Guten Tag, hier ist Bianca.", "frage": ""}])
    agg = kr.replay_manifest(m)
    assert agg["anrufer_zuege"] == 0
    assert "kernReplaySummary" not in m
    assert all("kernReplay" not in z for z in m["zuege"])
