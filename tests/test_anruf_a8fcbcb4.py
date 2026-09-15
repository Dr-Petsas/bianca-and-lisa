"""W-AKTE-HANDY (15.09.2026, Blessing-Anruf a8fcbcb4) — offline.

Live-Kette: In der Akte von Annemarie Mack stand nur eine FESTNETZnummer.
Die Anruferin nannte ihr Handy und bestaetigte es Ziffer fuer Ziffer —
die Plattform lehnte die Buchung trotzdem VIERMAL mit `needs_phone` ab,
weil niemand die Nummer in die Kartei schrieb. Dazwischen fragte Bianca
"Bestaetigungs-SMS an die alte Nummer oder die neue?" (an ein Festnetz),
und am Ende sagte das Modell "Dann ist alles fuer Sie eingetragen" —
im Kalender stand NICHTS.

Vier Wachen, jede mit ihrer Gegenprobe (eine fehlende Frage ist billiger
als eine falsch geschriebene Kartei oder ein verschluckter Satz):

1. `telefon.ist_handy` / `patients.ist_handy_de` — Festnetz ist kein Handy.
2. `gehirn.naechste_frage` bietet `telefon_alt` nur gegen ein echtes Handy an.
3. `kern.calendar.book_slot` traegt bei `needs_phone` die RUECKBESTAETIGTE
   Handynummer nach und bucht EINMAL neu (`BOOK_FIX_PHONE=0` = alt).
4. `fakten_wache` faengt "ist alles fuer Sie eingetragen" und
   "die Nummer ist gespeichert" ohne Schreib-Evidenz.
"""

from __future__ import annotations

import pytest

from bianca import flow, gehirn, telefon
from kern import calendar as kal
from kern import fakten_wache, patients
from kern.tenants import laden


# --- 1. Handy oder Festnetz -------------------------------------------------

@pytest.mark.parametrize("nummer", [
    "01776004600", "0177 600 46 00", "+491776004600", "015112345678",
    "01621234567",
])
def test_handy_erkannt(nummer: str):
    assert telefon.ist_handy(nummer)
    assert patients.ist_handy_de(nummer)


@pytest.mark.parametrize("nummer", [
    "02131234567",      # Festnetz Neuss (Akte im Live-Anruf)
    "+492131234567",
    "0211302040",       # Praxisnummer
    "0800123456",       # Servicenummer
    "",
    "0177",             # zu kurz
])
def test_festnetz_ist_kein_handy(nummer: str):
    assert not telefon.ist_handy(nummer)
    assert not patients.ist_handy_de(nummer)


def test_handy_ok_allein_reicht_nicht():
    """`handy_ok` prueft nur die Laenge — genau daran kam die Festnetznummer
    vorbei. Wo eine SMS ankommen MUSS, gilt `ist_handy_de`."""
    assert patients.handy_ok("02131234567")
    assert not patients.ist_handy_de("02131234567")


# --- 2. telefon_alt nur gegen ein echtes Handy ------------------------------

def _sit_nummernkonflikt(akte_nummer: str) -> dict:
    sit = {"tenant": laden("meddent"), "messages": [{"role": "system", "content": "x"}],
           "stimme": "Bianca"}
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": True, "patientId": "Uz5O",
              "vorname": "Annemarie", "nachname": "Mack", "buchstabiert": True,
              "arzt": {"typ": "genannt", "calendarId": "cal-1", "calendarName": "Dr. Blessing"},
              "grund": "Kontrolle", "grundWortlaut": "zur Kontrolle",
              "motivId": "kontrolle", "motivName": "KCH Kontrolluntersuchung",
              "versicherung": "gesetzlich", "telefon": "01776004600",
              "telefonOk": True, "aktePhone": akte_nummer,
              "slotIso": "2026-09-22T09:15", "phase": "bestaetigen"})
    return sit


def test_telefon_alt_nicht_gegen_festnetz_in_der_akte():
    sit = _sit_nummernkonflikt("02131234567")
    fid, _frage = gehirn.naechste_frage(sit)
    assert fid != "telefon_alt"


def test_telefon_alt_weiter_gegen_ein_handy_in_der_akte():
    """Gegenprobe: zwei Handys sind eine echte Wahl — die Frage bleibt."""
    sit = _sit_nummernkonflikt("01712223344")
    fid, frage = gehirn.naechste_frage(sit)
    assert fid == "telefon_alt" and frage


def test_buchen_traegt_gegen_festnetz_die_bestaetigte_nummer_nach(monkeypatch):
    """Ohne Wahlfrage muss die Nummer trotzdem in die Akte — sonst lehnt die
    Plattform mit needs_phone ab (und die SMS ginge ans Festnetz)."""
    sit = _sit_nummernkonflikt("02131234567")
    s = gehirn.sammler(sit)
    rufe: list[tuple[str, str]] = []
    monkeypatch.setattr(
        flow, "telefon_aktualisieren",
        lambda tenant, pid, phone: rufe.append((pid, phone)) or {
            "ok": True, "patientId": pid, "mobilePhoneNumber": "+491776004600",
            "previous": "02131234567"},
    )
    monkeypatch.setattr(flow.kal, "book_slot", lambda tenant, ctx, slot_iso="": {
        "ok": True, "booked": True, "slotIso": slot_iso, "appointmentId": "a1",
        "spoken": "Der Termin ist fest eingetragen."})
    monkeypatch.setattr(flow.kal, "note_appointment",
                        lambda tenant, ctx, sit=None, *, note="": {"ok": True})
    res = flow._buchen(sit)
    assert rufe == [("Uz5O", "01776004600")]
    assert s["telefonAlt"] == "neu" and s["aktePhone"] == "01776004600"
    assert "Die Bestätigung kommt gleich per SMS." in res["text"]


def test_ctx_traegt_nur_die_rueckbestaetigte_nummer_als_phoneconfirmed():
    sit = _sit_nummernkonflikt("02131234567")
    s = gehirn.sammler(sit)
    assert flow._ctx_bauen(sit).get("phoneConfirmed") == "01776004600"
    s["telefonOk"] = False  # bloss gehoert — kommt nie in die Kartei
    assert "phoneConfirmed" not in flow._ctx_bauen(sit)


# --- 3. needs_phone selbstheilend ------------------------------------------

def _book_umgebung(monkeypatch, *, rufe: list, needs_phone_mal: int = 1,
                   update_ok: bool = True):
    """masBookAppointment antwortet `needs_phone_mal` mal mit needs_phone,
    danach success; masUpdatePatientPhone nach `update_ok`."""
    monkeypatch.setattr(kal, "WRITE_LIVE", True)
    zaehler = {"book": 0}

    def _cf(route, body, timeout=None):
        rufe.append((route, dict(body)))
        if route == "masBookAppointment":
            zaehler["book"] += 1
            if zaehler["book"] <= needs_phone_mal:
                return 200, {"status": "needs_phone"}, {"route": route}
            return 200, {"status": "success", "appointmentId": "apt-neu"}, {"route": route}
        if route == "masUpdatePatientPhone":
            if update_ok:
                return 200, {"status": "success", "mobilePhoneNumber": "+491776004600",
                             "previous": "02131234567"}, {"route": route}
            return 500, {"status": "error", "message": "boom"}, {"route": route}
        raise AssertionError(f"unerwartete Route {route}")

    monkeypatch.setattr(kal, "_cf_call", _cf)
    monkeypatch.setattr(kal, "_buchung_verifizieren", lambda *a, **k: {
        "ok": True, "appointmentId": "apt-neu"})


def _ctx(**extra) -> dict:
    ctx = {"patientId": "Uz5O", "patientName": "Annemarie Mack",
           "firstName": "Annemarie", "lastName": "Mack",
           "calendarId": "cal-1", "visitMotiveId": "mot-1",
           "phone": "02131234567", "phoneConfirmed": "01776004600"}
    patients.patient_id_bindung_setzen(ctx, "Uz5O", "Annemarie", "Mack")
    ctx.update(extra)
    return ctx


def test_needs_phone_traegt_nummer_nach_und_bucht_einmal_neu(monkeypatch):
    rufe: list[tuple[str, dict]] = []
    _book_umgebung(monkeypatch, rufe=rufe)
    ctx = _ctx()
    res = kal.book_slot({"clientId": "c1", "locationId": "l1"}, ctx,
                        slot_iso="2026-09-22T09:15:00+02:00")
    assert res["ok"] and res["booked"] and res["appointmentId"] == "apt-neu"
    assert [r[0] for r in rufe] == [
        "masBookAppointment", "masUpdatePatientPhone", "masBookAppointment"]
    assert rufe[1][1]["mobilePhoneNumber"] == "+491776004600"
    assert rufe[1][1]["patientId"] == "Uz5O"
    # Der Fluss erfaehrt vom Nachtrag (Sammler zieht nach, keine "Akte
    # aktualisieren"-Notiz an einem gerade korrigierten Termin).
    assert ctx["aktePhoneNeu"] == "01776004600"
    assert ctx["aktePhoneAlt"] == "02131234567"


def test_needs_phone_ohne_bestaetigte_handynummer_schreibt_nichts(monkeypatch):
    """Eine bloss gehoerte oder eine Festnetznummer kommt NIE in die Kartei —
    dann bleibt es bei der ehrlichen Nachfrage."""
    for ctx in (_ctx(phoneConfirmed=""), _ctx(phoneConfirmed="02131234567")):
        rufe: list[tuple[str, dict]] = []
        _book_umgebung(monkeypatch, rufe=rufe)
        res = kal.book_slot({"clientId": "c1", "locationId": "l1"}, ctx,
                            slot_iso="2026-09-22T09:15:00+02:00")
        assert not res["ok"] and "Handynummer" in res["spoken"]
        assert [r[0] for r in rufe] == ["masBookAppointment"]


def test_needs_phone_update_kaputt_behauptet_keine_buchung(monkeypatch):
    rufe: list[tuple[str, dict]] = []
    _book_umgebung(monkeypatch, rufe=rufe, update_ok=False)
    res = kal.book_slot({"clientId": "c1", "locationId": "l1"}, _ctx(),
                        slot_iso="2026-09-22T09:15:00+02:00")
    assert not res["ok"] and "Handynummer" in res["spoken"]
    assert [r[0] for r in rufe] == ["masBookAppointment", "masUpdatePatientPhone"]


def test_needs_phone_bleibt_needs_phone_nur_ein_versuch(monkeypatch):
    """Sagt die Plattform auch NACH dem Nachtrag needs_phone, wird nicht
    endlos gewuerfelt (live viermal derselbe Fehlschlag)."""
    rufe: list[tuple[str, dict]] = []
    _book_umgebung(monkeypatch, rufe=rufe, needs_phone_mal=2)
    res = kal.book_slot({"clientId": "c1", "locationId": "l1"}, _ctx(),
                        slot_iso="2026-09-22T09:15:00+02:00")
    assert not res["ok"] and "Handynummer" in res["spoken"]
    assert [r[0] for r in rufe] == [
        "masBookAppointment", "masUpdatePatientPhone", "masBookAppointment"]


def test_notaus_book_fix_phone(monkeypatch):
    rufe: list[tuple[str, dict]] = []
    _book_umgebung(monkeypatch, rufe=rufe)
    monkeypatch.setattr(kal, "BOOK_FIX_PHONE", False)
    res = kal.book_slot({"clientId": "c1", "locationId": "l1"}, _ctx(),
                        slot_iso="2026-09-22T09:15:00+02:00")
    assert not res["ok"] and [r[0] for r in rufe] == ["masBookAppointment"]


def test_buchen_zieht_den_sammler_nach_dem_nachtrag_nach(monkeypatch):
    """book_slot hat selbst geheilt: der Sammler muss die neue Akten-Nummer
    uebernehmen, sonst haengt die Erfolgs-Ansage eine ueberfluessige
    'Bitte Akte aktualisieren'-Notiz an."""
    sit = _sit_nummernkonflikt("02131234567")
    s = gehirn.sammler(sit)
    s["telefonAlt"] = "akte"  # keine Wahlfrage offen, kein Vorab-Update
    monkeypatch.setattr(flow, "telefon_aktualisieren", lambda *a, **k: (
        _ for _ in ()).throw(AssertionError("kein Vorab-Update erwartet")))

    def _book(tenant, ctx, slot_iso=""):
        ctx["aktePhoneNeu"] = "01776004600"
        ctx["aktePhoneAlt"] = "02131234567"
        return {"ok": True, "booked": True, "slotIso": slot_iso,
                "appointmentId": "a1", "spoken": "Der Termin ist fest eingetragen."}

    notizen: list[str] = []
    monkeypatch.setattr(flow.kal, "book_slot", _book)
    monkeypatch.setattr(flow.kal, "note_appointment",
                        lambda tenant, ctx, sit=None, *, note="": notizen.append(note) or {"ok": True})
    flow._buchen(sit)
    assert s["aktePhone"] == "01776004600" and s["telefonAlt"] == "neu"
    assert sit["telefonUpdateAlt"] == "02131234567"
    assert not [n for n in notizen if "aktualisier" in n.lower() and "Alte Nummer" not in n]


# --- 4. Fakten-Wache: Phantom-Buchung und Phantom-Nummer -------------------

def _ledger(**marken) -> dict:
    sit: dict = {"tools": []}
    sit.update(marken)
    return sit


@pytest.mark.parametrize("satz", [
    "Dann ist alles für Sie eingetragen.",
    "Damit ist alles eingetragen.",
    "Somit ist für Sie alles eingetragen.",
    "Ihr Termin ist jetzt eingetragen.",
])
def test_phantom_buchung_faellt_durch(satz: str):
    assert fakten_wache.unbelegte_behauptung(_ledger(), satz) == "buchen"


def test_echte_buchung_darf_das_sagen():
    sit = _ledger(lastBook={"ok": True})
    assert fakten_wache.unbelegte_behauptung(
        sit, "Dann ist alles für Sie eingetragen.") == ""


@pytest.mark.parametrize("satz", [
    "Der Termin ist noch nicht eingetragen.",
    "Da ist noch nichts eingetragen — ich schaue nach.",
    "Soll ich das so eintragen?",
])
def test_ehrliche_saetze_bleiben(satz: str):
    assert fakten_wache.unbelegte_behauptung(_ledger(), satz) == ""


@pytest.mark.parametrize("satz", [
    "Ihre Handynummer ist gespeichert.",
    "Die Nummer habe ich in der Akte hinterlegt.",
    "Ihre Rufnummer wurde aktualisiert.",
    "Ich habe Ihre Nummer eingetragen.",
])
def test_phantom_nummer_faellt_durch(satz: str):
    assert fakten_wache.unbelegte_behauptung(_ledger(), satz) == "nummer"


def test_geschriebene_nummer_darf_das_sagen():
    sit = {"tools": [{"name": "update_phone", "ok": True}]}
    assert fakten_wache.unbelegte_behauptung(
        sit, "Ihre Handynummer ist gespeichert.") == ""
    assert fakten_wache.unbelegte_behauptung(
        _ledger(lastCreate={"ok": True}), "Ihre Nummer habe ich hinterlegt.") == ""


def test_nummer_aus_der_akte_ist_kein_phantom():
    """Gegenprobe: steht die Nummer schon in der Kartei und ist es genau die,
    die Bianca in der Hand hat, ist "hinterlegt" der Stand — kein Schreibwerk.
    Sonst haette die Wache Biancas eigene Frage nach der hinterlegten Nummer
    (W-ANRUFER-CHECK) mit "steht noch nicht in der Akte" ueberschrieben."""
    sit = _ledger()
    sit["sammler"] = {"aktePhone": "01776004600", "telefon": "+49 177 6004600"}
    assert fakten_wache.unbelegte_behauptung(
        sit, "Ihre Nummer ist bei uns hinterlegt.") == ""
    # Andere Nummer in der Akte -> die Aussage ist wieder unbelegt.
    sit["sammler"] = {"aktePhone": "02131234567", "telefon": "01776004600"}
    assert fakten_wache.unbelegte_behauptung(
        sit, "Ihre Nummer ist bei uns hinterlegt.") == "nummer"


@pytest.mark.parametrize("satz", [
    "Wie lautet Ihre Handynummer?",
    "Ich wiederhole die Nummer.",
    "An welche Nummer soll die Bestätigung gehen?",
    "In Ihrer Akte fehlt noch eine Handynummer.",
])
def test_nummern_saetze_ohne_behauptung_bleiben(satz: str):
    assert fakten_wache.unbelegte_behauptung(_ledger(), satz) == ""
