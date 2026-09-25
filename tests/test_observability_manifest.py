import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from kern import mitschnitt, namenslink, observability_manifest
from tools.observability_report import auswerten


CORPUS = json.loads(
    (
        Path(__file__).parent
        / "fixtures"
        / "blessing_observability_v56.json"
    ).read_text(encoding="utf-8")
)

ERLAUBTE_KEYS = {
    "phase",
    "offsetMs",
    "httpStatus",
    "durationMs",
    "routeClass",
    "outcome",
    "errorClass",
    "source",
    "candidateCount",
}


@pytest.mark.parametrize("fall", CORPUS, ids=lambda f: f["case"])
def test_blessing_neun_faelle_bleiben_strikt_pii_frei(fall):
    assert len(CORPUS) == 9
    sit = {
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "tenant": {"tenant": "blessing"},
    }
    observability_manifest.emit(
        sit,
        fall["funnel"],
        fall["phase"],
        route_class=fall.get("routeClass", "none"),
        outcome=fall.get("outcome", "unknown"),
        source=fall.get("source", "none"),
        candidate_count=fall.get("candidateCount"),
    )
    export = observability_manifest.export(sit)
    event = export[fall["funnel"]][0]
    assert set(event) <= ERLAUBTE_KEYS
    assert event["phase"] == fall["phase"]
    assert event["outcome"] == fall["outcome"]


def test_dispatch_payload_und_freie_felder_koennen_nie_exportiert_werden():
    sit = {"startedAt": "2026-09-25T10:00:00+00:00"}
    dispatch = {
        "url": "https://example.invalid/x?token=sehr-geheim",
        "request": {
            "phone": "+491771234567",
            "patientId": "patient-42",
            "appointmentId": "appointment-99",
            "slotIso": "2026-10-13T09:45:00+02:00",
            "transcript": "Mein Name ist Mustermann",
        },
        "response": {"smsLink": "https://secret.invalid/sms"},
        "httpStatus": 200,
        "ms": 83.7,
    }
    observability_manifest.emit(
        sit,
        "reservation",
        "create",
        dispatch=dispatch,
        route_class="name_confirm",
        outcome="ok",
        source="+491771234567",
    )
    # Auch ein beschädigter In-Memory-Eintrag wird am Persistenzrand neu
    # allowgelistet.
    sit["observability"]["reservation"][0].update({
        "token": "sehr-geheim",
        "url": "https://secret.invalid",
        "patientName": "Max Mustermann",
        "appointmentId": "appointment-99",
        "slotIso": "2026-10-13T09:45:00+02:00",
        "smsLink": "https://secret.invalid/sms",
        "transcript": "voller Gesprächssatz",
    })
    roh = json.dumps(
        observability_manifest.export(sit),
        ensure_ascii=False,
        sort_keys=True,
    )
    for verboten in (
        "sehr-geheim",
        "+491771234567",
        "patient-42",
        "appointment-99",
        "2026-10-13",
        "Mustermann",
        "secret.invalid",
        "Gesprächssatz",
    ):
        assert verboten not in roh


def test_reservierung_done_bereinigt_token_url_hinweise_und_ids(monkeypatch):
    antworten = iter([
        (
            200,
            {
                "status": "ok",
                "token": "tok-sehr-geheim",
                "url": "https://secret.invalid/name",
                "sent": True,
            },
            {
                "url": "https://secret.invalid/create",
                "request": {"phone": "+491771234567"},
                "httpStatus": 200,
                "ms": 12,
            },
        ),
        (
            200,
            {
                "status": "done",
                "firstName": "Max",
                "lastName": "Mustermann",
            },
            {
                "url": "https://secret.invalid/status",
                "request": {"token": "tok-sehr-geheim"},
                "httpStatus": 200,
                "ms": 9,
            },
        ),
    ])
    monkeypatch.setattr(namenslink, "_cf_call", lambda *a, **k: next(antworten))
    sit = {
        "id": "session-secret",
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "tenant": {"clientId": "client-secret", "locationId": "location-secret"},
        "anrufer": {"telefon": "+491771234567"},
        "sammler": {
            "modus": "buchen",
            "appointmentId": "appointment-secret",
            "patientId": "patient-secret",
            "slotIso": "2026-10-13T09:45:00+02:00",
        },
    }
    assert namenslink.starten(sit) is not None
    assert sit["namenslink"]["token"] == "tok-sehr-geheim"
    data = namenslink.einziehen(sit)
    assert data["status"] == "done"
    assert sit["namenslink"] == {"done": True}
    assert sit["sammler"]["nameVerified"] is True
    phasen = [
        e["phase"] for e in
        observability_manifest.export(sit)["reservation"]
    ]
    assert phasen == ["create", "status", "done", "cleanup"]
    export = json.dumps(observability_manifest.export(sit), ensure_ascii=False)
    for geheim in (
        "tok-sehr-geheim",
        "secret.invalid",
        "+491771234567",
        "Mustermann",
        "appointment-secret",
        "patient-secret",
        "2026-10-13",
    ):
        assert geheim not in export


def test_reservierung_expired_bereinigt_lokalen_stand(monkeypatch):
    monkeypatch.setattr(
        namenslink,
        "_cf_call",
        lambda *a, **k: (
            200,
            {"status": "expired"},
            {"httpStatus": 200, "ms": 5},
        ),
    )
    sit = {
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "anrufer": {"telefon": "+491771234567"},
        "sammler": {"modus": "buchen"},
        "namenslink": {
            "token": "tok-alt",
            "url": "https://secret.invalid",
            "phone": "+491771234567",
            "appointmentId": "appointment-secret",
            "firstNameHint": "Max",
        },
    }
    data = namenslink.einziehen(sit)
    assert data["status"] == "expired"
    assert sit["namenslink"] == {"expired": True}
    phasen = [
        e["phase"] for e in
        observability_manifest.export(sit)["reservation"]
    ]
    assert phasen == ["status", "expired", "cleanup"]


def test_mitschnitt_persistiert_nur_den_sanitierten_unterbaum():
    sit = {"startedAt": datetime.now(timezone.utc).isoformat()}
    observability_manifest.emit(
        sit,
        "verwaltung",
        "read",
        route_class="calendar_day_read",
        outcome="found",
        source="patientId",
        candidate_count=1,
    )
    sit["observability"]["verwaltung"][0]["patientName"] = "Max Mustermann"
    manifest = {}
    mitschnitt._zusammenfassung(manifest, sit)
    obs = manifest["observability"]
    assert obs["schema"] == observability_manifest.SCHEMA
    assert "patientName" not in obs["verwaltung"][0]
    assert "Mustermann" not in json.dumps(obs, ensure_ascii=False)


def test_notaus_entfernt_bestehende_spur_am_persistenzrand(monkeypatch):
    sit = {"startedAt": datetime.now(timezone.utc).isoformat()}
    observability_manifest.emit(
        sit, "reservation", "create", route_class="name_confirm", outcome="ok"
    )
    monkeypatch.setenv("OBSERVABILITY_MANIFEST", "0")
    assert observability_manifest.export(sit) == {}
    manifest = {"observability": {"alt": "darf nicht bleiben"}}
    mitschnitt._zusammenfassung(manifest, sit)
    assert "observability" not in manifest


def test_report_aggregiert_ohne_sitzungsdetails_und_markiert_stale_pending():
    alt = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    manifests = [
        {
            "startedAt": alt,
            "observability": {
                "schema": observability_manifest.SCHEMA,
                "reservation": [{
                    "phase": "create",
                    "offsetMs": 1,
                    "routeClass": "name_confirm",
                    "outcome": "ok",
                    "errorClass": "none",
                }],
            },
        },
        {
            "startedAt": alt,
            "observability": {
                "schema": observability_manifest.SCHEMA,
                "verwaltung": [{
                    "phase": "write",
                    "offsetMs": 2,
                    "routeClass": "cancel_write",
                    "outcome": "write_ok",
                    "errorClass": "none",
                }],
            },
        },
    ]
    bericht = auswerten(manifests, orphan_after_minutes=120)
    assert bericht["callsScanned"] == 2
    assert bericht["callsWithObservability"] == 2
    assert bericht["stalePendingReservations"] == 1
    assert bericht["phases"]["verwaltung"]["write"] == 1
    assert set(bericht) == {
        "schema",
        "callsScanned",
        "callsWithObservability",
        "funnelCalls",
        "phases",
        "outcomes",
        "stalePendingReservations",
        "staleAfterMinutes",
    }
