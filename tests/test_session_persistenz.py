import json
import threading

from bianca import session


def test_sip_sitzung_wird_trotz_laufzeit_event_vollstaendig_gesichert(
    tmp_path, monkeypatch
):
    """Runtime-Synchronisation darf nicht die gesamte JSON-Sicherung kosten."""
    monkeypatch.setattr(session, "_SESS_DIR", tmp_path)
    sit = {
        "id": "stallone-sip",
        "tenantId": "meddent",
        "tenant": {
            "clientId": "meddent",
            "_quelle": "cf:test",
            "begruessungText": "Guten Tag.",
        },
        "sammler": {
            "modus": "absagen",
            "nachname": "Stallone",
            "phase": "suchen",
        },
        "anrufer": {
            "vorname": "Michael",
            "nachname": "Petsas",
            "telefon": "+491776004600",
        },
        "_anruferReady": threading.Event(),
        "_satzJobs": [threading.Thread()],
    }

    session._sichern(sit)

    gespeichert = json.loads((tmp_path / "stallone-sip.json").read_text("utf-8"))
    assert gespeichert["sammler"]["nachname"] == "Stallone"
    assert gespeichert["anrufer"]["telefon"] == "+491776004600"
    assert gespeichert["tenant"]["_quelle"] == "cf:test"
    assert "_anruferReady" not in gespeichert
    assert "_satzJobs" not in gespeichert
