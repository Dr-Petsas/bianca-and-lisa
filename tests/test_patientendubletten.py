"""Patientendubletten und gemeinsam genutzte Handynummern (26.09.2026)."""

from datetime import datetime, timedelta

from bianca import agent, flow, gehirn, session
from kern import agentprofil, anrufaudio, calendar, config, patients, standort
from kern.tenants import laden


class _Response:
    status_code = 200

    def __init__(self, rows):
        self._rows = rows

    def json(self):
        return self._rows


def _patient(pid: str, vor: str, nach: str, created: str, phone: str) -> dict:
    return {
        "id": pid,
        "firstName": vor,
        "lastName": nach,
        "createdAt": created,
        "mobilePhoneNumber": phone,
    }


def test_neubuchung_waehlt_neueste_gleichnamige_akte(monkeypatch):
    alt = _patient("alt", "Anna", "Müller", "2023-01-01T10:00:00Z", "+4915112345678")
    neu = _patient("neu", "Anna", "Müller", "2025-06-01T10:00:00Z", "+4915112345678")
    monkeypatch.setattr(
        patients,
        "search_patients",
        lambda tenant, query: {"ok": True, "patients": [alt, neu]},
    )
    karte = patients.patient_aufloesen(
        {"clientId": "c", "locationId": "l"},
        {"firstName": "Anna", "lastName": "Müller"},
    )
    assert karte["id"] == "neu"
    assert karte["duplicateCount"] == 2
    assert karte["duplicatePatientIds"] == ["alt", "neu"]
    assert karte["duplicateNewestCertain"] is True


def test_gleicher_name_mit_verschiedenen_geburtsdaten_ist_keine_dublette(
        monkeypatch):
    a = {
        **_patient("a", "Peter", "Müller", "2025-01-01T00:00:00Z", "+4915112345678"),
        "birthDate": "1970-02-03",
    }
    b = {
        **_patient("b", "Peter", "Müller", "2024-01-01T00:00:00Z", "+4915112345678"),
        "birthDate": "2002-04-05",
    }
    monkeypatch.setattr(
        patients,
        "search_patients",
        lambda tenant, query: {"ok": True, "patients": [a, b]},
    )
    unresolved = patients.patient_aufloesen(
        {"clientId": "c", "locationId": "l"},
        {"firstName": "Peter", "lastName": "Müller"},
    )
    assert not unresolved.get("id")
    assert not unresolved.get("duplicateCount")


def test_verwaltung_findet_vier_termine_ueber_alle_dubletten(monkeypatch):
    tenant = {"clientId": "c", "locationId": "l"}
    jetzt = datetime.now(calendar.TZ) + timedelta(days=10)
    rows = []
    for i, pid in enumerate(("alt", "alt", "neu", "neu")):
        start = (jetzt + timedelta(days=i)).isoformat()
        rows.append({
            "document": {
                "name": f"projects/p/databases/d/documents/a/apt-{i}",
                "fields": {
                    "start": start,
                    "status": "confirmed",
                    "patientStatus": "",
                    "patient": {
                        "id": pid,
                        "firstName": "Anna",
                        "lastName": "Müller",
                    },
                    "calendar": {"id": "cal", "name": "Doktor Beispiel"},
                    "visitMotive": {"id": "vm", "name": "Kontrolle"},
                },
            },
        })
    monkeypatch.setattr(config, "FIREBASE_CREDENTIALS", "test.json")
    monkeypatch.setattr(anrufaudio, "_access_token", lambda scope: "token")
    monkeypatch.setattr(standort, "_projekt", lambda: "projekt")
    monkeypatch.setattr(standort, "_decode", lambda value: value)
    monkeypatch.setattr(calendar.httpx, "post", lambda *a, **k: _Response(rows))

    result = calendar.find_patient_appointments(tenant, {
        "firstName": "Anna",
        "lastName": "Müller",
        "patientId": "neu",
        "duplicatePatientIds": ["alt", "neu"],
    })
    assert result["ok"] is True
    assert result["duplicateCount"] == 2
    assert len(result["appointments"]) == 4
    assert {a["patientId"] for a in result["appointments"]} == {"alt", "neu"}
    assert {a["id"] for a in result["appointments"]} == {
        "apt-0", "apt-1", "apt-2", "apt-3",
    }
    assert result["dispatch"]["request"] == {"patientRecords": 2}
    assert "patientId" not in str(result["dispatch"]["request"])


def test_gemeinsame_nummer_wird_nie_still_einer_person_zugeordnet(monkeypatch):
    a = _patient("a", "Anna", "Müller", "2025-01-01T00:00:00Z", "+4915112345678")
    b = _patient("b", "Peter", "Müller", "2024-01-01T00:00:00Z", "+4915112345678")
    monkeypatch.setattr(
        patients,
        "search_patients",
        lambda tenant, query: {"ok": True, "patients": [a, b]},
    )
    sit = {"tenant": {"clientId": "c", "locationId": "l"}}
    agentprofil._anrufer_mehrfach_aufloesen(
        sit, {"patientId": "a", "vorname": "Anna", "nachname": "Müller"},
        "4915112345678",
    )
    assert "anrufer" not in sit
    assert agentprofil.anrufer_auswahl_noetig(sit)
    frage = agentprofil.anrufer_auswahl_frage(sit)
    assert frage == (
        "Zu dieser Handynummer finde ich mehrere Personen. "
        "Spreche ich mit Anna Müller oder Peter Müller?"
    )
    assert agentprofil.anrufer_auswaehlen(sit, "Ja.") == "unclear"
    assert "anrufer" not in sit
    assert agentprofil.anrufer_auswaehlen(sit, "Anna Müller.") == "selected"
    assert sit["anrufer"]["patientId"] == "a"
    assert sit["anruferAuswahlBestaetigt"] is True


def test_gemeinsame_nummer_parkt_auftrag_und_setzt_ihn_nach_auswahl_fort():
    sit = session.neu(tenant_id="meddent")
    agent.start_reply(sit)
    sit["callerPhone"] = "+4915112345678"
    sit["anruferKandidaten"] = [
        {
            "id": "a", "patientId": "a", "firstName": "Anna",
            "lastName": "Müller", "phone": "+4915112345678",
        },
        {
            "id": "b", "patientId": "b", "firstName": "Peter",
            "lastName": "Müller", "phone": "+4915112345678",
        },
    ]
    frage = agent.user_turn(sit, "Ich möchte einen Termin buchen.")
    assert "Spreche ich mit Anna Müller oder Peter Müller" in frage["text"]
    assert sit["anruferAuswahlOffenerText"] == "Ich möchte einen Termin buchen."
    assert not gehirn.sammler(sit)["modus"]

    weiter = agent.user_turn(sit, "Anna Müller.")
    s = gehirn.sammler(sit)
    assert sit["anrufer"]["patientId"] == "a"
    assert s["patientId"] == "a"
    assert s["anruferCheck"] == "ja"
    assert s["modus"] == "buchen"
    assert "Spreche ich mit Anna Müller oder Peter Müller" not in weiter["text"]


def test_gleichnamige_nummerntreffer_sind_dubletten_ohne_x_oder_x_frage(monkeypatch):
    alt = _patient("alt", "Anna", "Müller", "2023-01-01T00:00:00Z", "+4915112345678")
    neu = _patient("neu", "Anna", "Müller", "2025-01-01T00:00:00Z", "+4915112345678")
    monkeypatch.setattr(
        patients,
        "search_patients",
        lambda tenant, query: {"ok": True, "patients": [alt, neu]},
    )
    sit = {"tenant": {"clientId": "c", "locationId": "l"}}
    agentprofil._anrufer_mehrfach_aufloesen(sit, {}, "4915112345678")
    assert sit["anrufer"]["patientId"] == "neu"
    assert [p["id"] for p in sit["patientenDubletten"]] == ["alt", "neu"]
    assert not agentprofil.anrufer_auswahl_noetig(sit)


def test_gleichnamige_familienmitglieder_werden_ueber_geburtsjahr_unterschieden(
        monkeypatch):
    a = {
        **_patient("a", "Peter", "Müller", "2025-01-01T00:00:00Z", "+4915112345678"),
        "birthDate": "1970-02-03",
    }
    b = {
        **_patient("b", "Peter", "Müller", "2024-01-01T00:00:00Z", "+4915112345678"),
        "birthDate": "2002-04-05",
    }
    monkeypatch.setattr(
        patients,
        "search_patients",
        lambda tenant, query: {"ok": True, "patients": [a, b]},
    )
    sit = {"tenant": {"clientId": "c", "locationId": "l"}}
    agentprofil._anrufer_mehrfach_aufloesen(sit, {}, "4915112345678")
    frage = agentprofil.anrufer_auswahl_frage(sit)
    assert "Peter Müller, geboren 1970" in frage
    assert "Peter Müller, geboren 2002" in frage
    assert agentprofil.anrufer_auswaehlen(
        sit, "Peter Müller, geboren 2002.") == "selected"
    assert sit["anrufer"]["patientId"] == "b"


def test_buchung_schreibt_dubletten_pruefnotiz(monkeypatch):
    sit = {
        "tenant": laden("meddent"),
        "messages": [{"role": "system", "content": "x"}],
        "stimme": "Bianca",
        "patientenDubletten": [
            {"id": "alt", "firstName": "Anna", "lastName": "Müller"},
            {"id": "neu", "firstName": "Anna", "lastName": "Müller"},
        ],
    }
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "phase": "bestaetigen",
        "frage": "bestaetigung",
        "warSchonMal": True,
        "grund": "Kontrolluntersuchung",
        "pzr": "nein",
        "bleaching": "nein",
        "motivId": "vm",
        "motivName": "KCH Kontrolluntersuchung",
        "wunsch": {},
        "vorname": "Anna",
        "nachname": "Müller",
        "buchstabiert": True,
        "nameVerified": True,
        "patientId": "neu",
        "telefon": "015112345678",
        "telefonOk": True,
        "telefonBekannt": "015112345678",
        "smsEmpfaenger": "patient",
        "slotIso": "2026-10-10T09:00:00+02:00",
        "arzt": {
            "typ": "genannt",
            "calendarId": "cal",
            "calendarName": "Doktor Beispiel",
        },
        "arztNotizFrage": "nein",
    })
    sit["offered"] = [{"iso": s["slotIso"], "spoken": "Samstag um neun"}]
    sit["angebotKalender"] = {
        "calendarId": "cal",
        "calendarName": "Doktor Beispiel",
    }
    notizen: list[str] = []

    def _book(tenant, ctx, slot_iso=""):
        assert ctx["patientId"] == "neu"
        assert ctx["patientDuplicateCount"] == 2
        return {
            "ok": True,
            "booked": True,
            "slotIso": slot_iso,
            "appointmentId": "apt",
            "patientId": "neu",
            "spoken": "Der Termin ist fest eingetragen.",
        }

    monkeypatch.setattr(flow.kal, "book_slot", _book)
    monkeypatch.setattr(
        flow.kal,
        "note_appointment",
        lambda tenant, ctx, sit2=None, *, note="": (
            notizen.append(note) or {"ok": True}
        ),
    )
    result = flow._buchen(sit)
    assert result.get("book", {}).get("booked") is True, result
    assert any(
        "2 Patientendubletten gefunden" in note
        and "bitte Akten prüfen und zusammenführen" in note
        for note in notizen
    )
    assert any(
        tool.get("name") == "note_appointment" and tool.get("ok") is True
        for tool in (sit.get("tools") or [])
    )


def test_einzelpatient_bleibt_ohne_dublettenfrage_und_notiz(monkeypatch):
    p = _patient("eins", "Anna", "Müller", "2025-01-01T00:00:00Z", "+4915112345678")
    monkeypatch.setattr(
        patients,
        "search_patients",
        lambda tenant, query: {"ok": True, "patients": [p]},
    )
    sit = {"tenant": {"clientId": "c", "locationId": "l"}}
    agentprofil._anrufer_mehrfach_aufloesen(sit, {}, "4915112345678")
    assert sit["anrufer"]["patientId"] == "eins"
    assert not agentprofil.anrufer_auswahl_noetig(sit)
    assert "patientenDubletten" not in sit
