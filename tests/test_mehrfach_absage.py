"""W-MEHRFACH-ABSAGE (15.09.2026): "beide/alle/den ersten und den zweiten"
sagen mehrere vorgelesene Termine gemeinsam ab — EINE Rueckbestaetigung, dann
nacheinander ueber cancel-by-id, Teilfehler ehrlich, schleifenfreier Abschluss.

Der wichtigere Teil sind die Gegenproben: nie "beide abgesagt", wenn nur ein
Werkzeug erfolgreich war; "Nein" laesst alles bestehen; ein einzelnes "den
ersten" bleibt der bewaehrte Einzelweg.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bianca import flow, gehirn, verwalten  # noqa: E402
from kern.tenants import laden  # noqa: E402


def _sit() -> dict:
    return {"tenant": laden("meddent"), "messages": [{"role": "system", "content": "x"}]}


ZWEI = {
    "ok": True,
    "patient": {"id": "pat-1", "firstName": "Martin", "lastName": "Berger"},
    "appointments": [
        {
            "id": "apt-1", "iso": "2026-09-03T10:00", "date": "2026-09-03",
            "calendarId": "cal-1", "doctorName": "Dr. Petsas",
            "motivId": "vm-1", "motivName": "Kontrolluntersuchung",
            "spoken": "am Donnerstag, den dritten September um zehn Uhr",
        },
        {
            "id": "apt-2", "iso": "2026-09-10T14:00", "date": "2026-09-10",
            "calendarId": "cal-1", "doctorName": "Dr. Petsas",
            "motivId": "vm-1", "motivName": "Kontrolluntersuchung",
            "spoken": "am Donnerstag, den zehnten September um vierzehn Uhr",
        },
    ],
}

VIER = [
    {
        "id": f"apt-{i}",
        "iso": f"2026-10-{i:02d}T{8 + i:02d}:00",
        "date": f"2026-10-{i:02d}",
        "calendarId": "cal-1",
        "doctorName": "Dr. Petsas",
        "motivId": "vm-1",
        "motivName": "Kontrolluntersuchung",
        "spoken": f"am {i}. Oktober um {8 + i} Uhr",
    }
    for i in range(1, 5)
]


def _bis_wahl(sit, monkeypatch, cancel):
    """Fluss bis zur Termin-Wahl mit zwei gefundenen Terminen treiben."""
    monkeypatch.setattr(verwalten.kal, "find_patient_appointments",
                        lambda t, c: {k: (list(v) if isinstance(v, list) else v)
                                      for k, v in ZWEI.items()})
    monkeypatch.setattr(verwalten.kal, "cancel_by_id", cancel)
    monkeypatch.setattr(verwalten.hintergrund, "anstossen", lambda sit: None)
    z1 = flow.zug(sit, "Guten Tag, ich möchte meine Termine absagen.")
    if gehirn.sammler(sit)["frage"] == "wann":
        z1 = flow.zug(sit, "Den Zeitpunkt weiß ich nicht mehr.")
    if gehirn.sammler(sit)["frage"] == "arzt":
        z1 = flow.zug(sit, "Den Behandler weiß ich auch nicht mehr.")
    assert z1 and "nachname" in z1["text"].lower()
    z2 = flow.zug(sit, "Berger.")
    if gehirn.sammler(sit)["frage"] == "buchstabieren":
        assert "buchstabe" in z2["text"].lower()
        z2 = flow.zug(sit, "B E R G E R")
    if gehirn.sammler(sit)["frage"] == "nachname_check":
        assert "ist das richtig" in z2["text"].lower()
        z2 = flow.zug(sit, "Ja.")
    assert z2 and "mehrere termine" in z2["text"].lower()
    assert gehirn.sammler(sit)["phase"] == "wahl"
    return z2


def test_mehrfach_auswahl_erkennung():
    zwei = ZWEI["appointments"]
    assert len(verwalten._mehrfach_auswahl("beide", zwei)) == 2
    assert len(verwalten._mehrfach_auswahl("alle absagen", zwei)) == 2
    assert len(verwalten._mehrfach_auswahl("den ersten und den zweiten", zwei)) == 2
    # Einzelwahl ist KEIN Mehrfach-Wunsch.
    assert verwalten._mehrfach_auswahl("den ersten", zwei) == []
    assert verwalten._mehrfach_auswahl("den zweiten bitte", zwei) == []
    # Nur ein Termin: nie Mehrfach.
    assert verwalten._mehrfach_auswahl("beide", zwei[:1]) == []
    # Bei vier Terminen ist "beide" mehrdeutig und darf nie still die ersten
    # beiden löschen. "Alle" bleibt dagegen ausdrücklich und eindeutig.
    assert verwalten._mehrfach_auswahl("beide", VIER) == []
    assert [a["id"] for a in verwalten._mehrfach_auswahl("alle", VIER)] == [
        "apt-1", "apt-2", "apt-3", "apt-4",
    ]


def test_beide_absagen_sammelbestaetigung_und_beide_weg(monkeypatch):
    aufrufe = []

    def _cancel(t, c, aid):
        aufrufe.append(aid)
        return {"ok": True, "cancelled": True, "appointmentId": aid,
                "spoken": "Der Termin ist abgesagt."}

    sit = _sit()
    _bis_wahl(sit, monkeypatch, _cancel)

    # "Beide." -> EINE gemeinsame Rueckbestaetigung, noch nichts abgesagt.
    z = flow.zug(sit, "Beide bitte.")
    assert z and "wirklich" in z["text"].lower()
    assert "Martin Berger" in z["text"]
    assert gehirn.sammler(sit)["phase"] == "mehrfach_bestaetigen"
    assert aufrufe == [], "vor dem Ja darf nichts abgesagt sein"

    # "Ja." -> beide nacheinander abgesagt.
    z = flow.zug(sit, "Ja, bitte.")
    assert aufrufe == ["apt-1", "apt-2"]
    low = z["text"].lower()
    assert "abgesagt" in low
    assert "sonst noch" in low
    assert "neuen termin" not in low
    assert gehirn.sammler(sit)["frage"] == "sonst_noch"


def test_beide_absagen_teilfehler_ehrlich(monkeypatch, tmp_path):
    """Nur der erste klappt — nie 'beide abgesagt' behaupten."""
    def _cancel(t, c, aid):
        if aid == "apt-1":
            return {"ok": True, "cancelled": True, "appointmentId": aid}
        return {"ok": False, "spoken": "Das hat nicht geklappt."}

    sit = _sit()
    monkeypatch.setattr(verwalten, "DATA_DIR", tmp_path)
    _bis_wahl(sit, monkeypatch, _cancel)
    flow.zug(sit, "Beide.")
    z = flow.zug(sit, "Ja.")
    low = z["text"].lower()
    assert "abgesagt sind" in low  # der erfolgreiche Teil
    assert "nicht geklappt" in low  # der Fehler ehrlich benannt
    assert "rückrufnotiz" in low
    assert (tmp_path / "praxis_notizen.jsonl").exists()
    assert any(t.get("name") == "praxis_notiz" and t.get("ok")
               for t in sit.get("tools") or [])


def test_teilfehler_mit_notiz_schreibfehler_bleibt_ehrlich(monkeypatch):
    class _NichtSchreibbar:
        def mkdir(self, **kwargs):
            raise OSError("Datenträger nicht verfügbar")

    def _cancel(t, c, aid):
        if aid == "apt-1":
            return {"ok": True, "cancelled": True, "appointmentId": aid}
        return {"ok": False, "spoken": "Das hat nicht geklappt."}

    sit = _sit()
    monkeypatch.setattr(verwalten, "DATA_DIR", _NichtSchreibbar())
    _bis_wahl(sit, monkeypatch, _cancel)
    flow.zug(sit, "Beide.")
    z = flow.zug(sit, "Ja.")

    low = z["text"].lower()
    assert "nicht speichern" in low
    assert "rückrufnotiz hinterlassen" not in low
    assert any(t.get("name") == "praxis_notiz" and not t.get("ok")
               for t in sit.get("tools") or [])


def test_beide_absagen_nein_behaelt_termine(monkeypatch):
    aufrufe = []

    def _cancel(t, c, aid):
        aufrufe.append(aid)
        return {"ok": True, "cancelled": True, "appointmentId": aid}

    sit = _sit()
    _bis_wahl(sit, monkeypatch, _cancel)
    flow.zug(sit, "Beide.")
    z = flow.zug(sit, "Nein, doch nicht.")
    assert aufrufe == [], "Nein sagt nichts ab"
    assert "bestehen" in z["text"].lower()
    assert gehirn.sammler(sit)["phase"] == "wahl"


def test_einzelwahl_bleibt_einzelweg(monkeypatch):
    """'den ersten' darf nie den Mehrfach-Weg zuenden."""
    def _cancel(t, c, aid):
        return {"ok": True, "cancelled": True, "appointmentId": aid}

    sit = _sit()
    _bis_wahl(sit, monkeypatch, _cancel)
    z = flow.zug(sit, "Den ersten bitte.")
    # Einzelbestaetigung (kein Mehrfach): "wirklich absagen … ?"
    assert gehirn.sammler(sit)["phase"] == "absage_bestaetigen"
    assert "absagen" in z["text"].lower()


def test_vier_termine_werden_alle_vorgelesen_und_vierter_ist_waehlbar(monkeypatch):
    aufrufe = []
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "absagen", "phase": "wahl", "frage": "terminwahl"})
    sit["gefunden"] = list(VIER)
    monkeypatch.setattr(
        verwalten.kal,
        "cancel_by_id",
        lambda _t, _c, aid: (
            aufrufe.append(aid)
            or {"ok": True, "cancelled": True, "appointmentId": aid}
        ),
    )

    liste = verwalten._liste_sprechbar(VIER)
    for termin in VIER:
        assert termin["spoken"] in liste
    assert "Viertens" in liste

    antwort = verwalten.zug(sit, "Den vierten Termin bitte.", set())
    assert antwort and "wirklich absagen" in antwort["text"].lower()
    assert sit["verwaltenTermin"] == "apt-4"
    assert s["phase"] == "absage_bestaetigen"
    assert aufrufe == [], "die Auswahl allein darf noch nichts absagen"

    verwalten.zug(sit, "Ja, bitte.", set())
    assert aufrufe == ["apt-4"], "nur der ausdrücklich gewählte Termin darf weg"


def test_vierter_termin_wird_gezielt_verschoben(monkeypatch):
    aufrufe = []
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "verschieben", "phase": "wahl", "frage": "terminwahl"})
    sit["gefunden"] = list(VIER)

    antwort = verwalten.zug(sit, "Den vierten.", set())
    assert antwort and "wann passt" in antwort["text"].lower()
    assert sit["verwaltenTermin"] == "apt-4"
    assert s["phase"] == "verschieb_wunsch"

    s.update({
        "slotIso": "2026-11-20T15:00",
        "phase": "verschieb_bestaetigen",
        "frage": "verschieb_ok",
    })

    def _move(_tenant, ctx, slot_iso):
        aufrufe.append((ctx.get("appointmentId"), slot_iso))
        return {"ok": True, "moved": True, "appointmentId": ctx.get("appointmentId")}

    monkeypatch.setattr(verwalten.kal, "move_appointment", _move)
    verwalten.zug(sit, "Ja, das passt.", set())
    assert aufrufe == [("apt-4", "2026-11-20T15:00")]


def test_beide_bei_vier_termine_fuehrt_nicht_zu_einem_write(monkeypatch):
    aufrufe = []
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "absagen", "phase": "wahl", "frage": "terminwahl"})
    sit["gefunden"] = list(VIER)
    monkeypatch.setattr(
        verwalten.kal,
        "cancel_by_id",
        lambda _t, _c, aid: aufrufe.append(aid) or {"ok": True},
    )

    antwort = verwalten.zug(sit, "Beide bitte.", set())
    assert antwort and "da will ich nichts falsches erwischen" in antwort["text"].lower()
    assert "vierten" in antwort["text"].lower()
    assert s["phase"] == "wahl"
    assert aufrufe == []


def test_folgeanliegen_erbt_keine_alte_terminauswahl(monkeypatch):
    """Nach einer erledigten Absage startet Verschieben mit einem sauberen
    Verwaltungszustand und kann einen anderen Termin gezielt binden."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "absagen", "phase": "fertig", "frage": "sonst_noch"})
    sit.update({
        "gefunden": list(VIER),
        "gefundenKey": "alt",
        "verwaltenTermin": "apt-2",
        "mehrfachAbsage": [{"id": "apt-1"}, {"id": "apt-2"}],
        "offered": [{"iso": "2026-10-30T09:00"}],
        "verschiebRichtung": "später",
        "verwAbschlussOffen": True,
    })

    verwalten._verw_reset(sit)
    assert sit["gefunden"] == []
    assert sit["gefundenKey"] == ""
    assert sit["verwaltenTermin"] == ""
    assert sit["mehrfachAbsage"] == []
    assert sit["offered"] == []
    assert sit["verschiebRichtung"] == ""
    assert "verwAbschlussOffen" not in sit

    # Das zweite Anliegen bekommt seine eigene, aktuelle Trefferliste. Nach
    # der vorherigen Absage sind nur noch drei Termine vorhanden.
    aktuell = [VIER[0], VIER[2], VIER[3]]
    s.update({"modus": "verschieben", "phase": "wahl", "frage": "terminwahl"})
    sit["gefunden"] = aktuell
    antwort = verwalten.zug(sit, "Den dritten davon.", set())
    assert antwort and "wann passt" in antwort["text"].lower()
    assert sit["verwaltenTermin"] == "apt-4"

    aufrufe = []
    s.update({
        "slotIso": "2026-11-24T15:00",
        "phase": "verschieb_bestaetigen",
        "frage": "verschieb_ok",
    })
    monkeypatch.setattr(
        verwalten.kal,
        "move_appointment",
        lambda _t, ctx, slot_iso: (
            aufrufe.append((ctx.get("appointmentId"), slot_iso))
            or {"ok": True, "moved": True}
        ),
    )
    verwalten.zug(sit, "Ja.", set())
    assert aufrufe == [("apt-4", "2026-11-24T15:00")]


def test_mehrfach_absage_ueber_verschiedene_patienten_wird_gesperrt():
    sit = _sit()
    s = gehirn.sammler(sit)
    s["modus"] = "absagen"
    termine = [
        {
            **ZWEI["appointments"][0],
            "patientId": "pat-1",
            "patientName": "Martin Berger",
        },
        {
            **ZWEI["appointments"][1],
            "patientId": "pat-2",
            "patientName": "Petra Müller",
        },
    ]

    antwort = verwalten._mehrfach_absage_start(sit, termine)
    assert antwort and "verschiedenen patienten" in antwort["text"].lower()
    assert s["frage"] == "buchstabieren"
    assert "buchstabe für buchstabe" in antwort["text"].lower()
    assert not sit.get("mehrfachAbsage")
