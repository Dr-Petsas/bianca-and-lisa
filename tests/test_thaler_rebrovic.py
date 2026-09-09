"""Thaler 08.09.2026 Schacklin Rebrovic — Live-Fehler nach der Buchung.

1. „Sehr gerne“ auf die Weiterleit-Frage zählte nicht als Ja.
2. Nach der Notiz für Frau Thaler kamen wieder Slots.
3. „Auf Wiederhören“ + „Wir haben doch schon einen Termin“ öffneten
   erneut das Angebot statt zu verabschieden.
"""

from __future__ import annotations

from bianca import agent, flow, gehirn, weiterleiten
from kern import gespraech
from kern.tenants import laden

EVA = "cal-eva"


def _sit_thaler() -> dict:
    t = {
        "clientId": "thaler-test",
        "locationId": "loc",
        "praxisName": "Zahnarztpraxis Eva Thaler",
        "defaultCalendarId": EVA,
        "calendars": [
            {"id": EVA, "name": "Dr. Eva Thaler"},
            {"id": "cal-prophy", "name": "Prophylaxe"},
        ],
        "visitMotives": [],
    }
    return {
        "tenant": t,
        "messages": [{"role": "system", "content": "x"}],
        "motivKatalog": [],
    }


def _sit_gebucht_thaler() -> dict:
    sit = _sit_thaler()
    sit["lastBook"] = {
        "booked": True,
        "appointmentId": "z1lItlCGCkr3yk9M6QLe",
        "slotIso": "2026-09-10T15:30:00+02:00",
        "spoken": "Donnerstag um fünfzehn Uhr dreißig bei Frau Thaler",
    }
    sit["booking"] = {"appointmentId": "z1lItlCGCkr3yk9M6QLe"}
    sit["offered"] = []
    sit["flussFrage"] = ""
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "phase": "gebucht",
        "frage": "",
        "vorname": "Schacklin",
        "nachname": "Rebrovic",
        "arzt": {"typ": "genannt", "calendarId": EVA,
                 "calendarName": "Dr. Eva Thaler"},
        "slotIso": "2026-09-10T15:30:00+02:00",
    })
    return sit


def _sit_bestaetigung_thaler() -> dict:
    sit = _sit_thaler()
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "phase": "bestaetigen",
        "frage": "bestaetigung",
        "grund": "Prophylaxe",
        "motivName": "PRO Professionelle Zahnreinigung",
        "vorname": "Nikolas",
        "nachname": "Helmich",
        "slotIso": "2026-09-21T16:00:00+02:00",
        "arzt": {
            "typ": "funktion",
            "calendarId": "cal-prophy",
            "calendarName": "Prophylaxe",
        },
    })
    sit["angebotKalender"] = {
        "calendarId": "cal-prophy",
        "calendarName": "Prophylaxe",
    }
    sit["offered"] = [{
        "iso": "2026-09-21T16:00:00+02:00",
        "spoken": "am Montag, den einundzwanzigsten September um sechzehn Uhr",
    }]
    return sit


def test_sehr_gerne_ist_ja():
    assert gehirn.ist_ja("Sehr gerne")
    assert gehirn.ist_ja("Sehr gern.")
    assert gehirn.ist_ja("Sehr gerne, bitte.")


def test_sehr_gerne_auf_anbieten_verbindet():
    """Live Rebrovic: Angebot „Soll ich Sie zu Frau Thaler weiterleiten?“
    — „Sehr gerne“ muss durchstellen (Platzhalter ohne Nummer)."""
    sit = _sit_thaler()
    sit["weiterleiten"] = {
        "frage": "anbieten",
        "ziel": {"calendarId": EVA, "calendarName": "Dr. Eva Thaler"},
    }
    z = weiterleiten.zug(sit, "Sehr gerne")
    assert z and weiterleiten.ANSAGE_PLATZHALTER in z["text"]


def test_sehr_gerne_auf_anbieten_meddent_transfer():
    sit = {"tenant": laden("meddent"), "messages": [{"role": "system", "content": "x"}]}
    sit["weiterleiten"] = {
        "frage": "anbieten",
        "ziel": {"calendarId": "zex5bmv5jfIHWVW6zHbg", "calendarName": "Dr. Petsas"},
    }
    events: list[str] = []
    z = weiterleiten.zug(sit, "Sehr gerne", events.append)
    assert z and z.get("transfer", {}).get("nummer") == "+4921130293035"
    assert z.get("hangup") and weiterleiten.JINGLE_EVENT in events


def test_eva_kahler_auf_arztfrage_verbindet_thaler():
    sit = _sit_thaler()
    sit["messages"].append({
        "role": "assistant",
        "content": "Zu welchem unserer Ärzte darf ich Sie verbinden?",
    })
    sit["weiterleiten"] = {"frage": "arzt"}
    z = weiterleiten.zug(sit, "Eva Kahler")
    assert z and weiterleiten.ANSAGE_PLATZHALTER in z["text"]


def test_mitarbeiter_thaler_kein_personalfrei():
    sit = _sit_thaler()
    z = flow.zug(sit, "zum Mitarbeiter durchstellen.")
    assert z
    assert "personalfrei" not in z["text"]
    assert "KI-geführt" not in z["text"]
    assert weiterleiten.WAHRHEIT in z["text"]


def test_gebucht_perfekt_danke_kein_slot():
    sit = _sit_gebucht_thaler()
    z = flow.zug(sit, "Perfekt, danke")
    assert z and "Wiederhören" in z["text"]
    assert "passt" not in z["text"].lower()
    assert gehirn.sammler(sit)["phase"] in {"gebucht", "fertig"}


def test_fertig_nach_notiz_kein_slot():
    sit = _sit_gebucht_thaler()
    gehirn.sammler(sit)["phase"] = "fertig"
    z = flow.zug(sit, "und dann noch eine Nachricht für Frau Thaler")
    assert z
    assert "passt" not in (z.get("text") or "").lower()
    assert "Donnerstag" not in (z.get("text") or "")
    assert "sonst noch" in (z.get("text") or "").lower()


def test_schon_termin_erinnert_nicht_slots():
    sit = _sit_gebucht_thaler()
    gehirn.sammler(sit)["phase"] = "fertig"
    z = flow.zug(sit, "Wir haben doch schon einen Termin")
    assert z and "genau" in z["text"].lower()
    assert "fünfzehn" in z["text"] or "Frau Thaler" in z["text"]
    assert "passt" not in z["text"].lower()


def test_auf_wiederhoeren_nach_buchung():
    sit = _sit_gebucht_thaler()
    z = flow.zug(sit, "Auf Wiederhören, Bianca")
    assert z and "Wiederhören" in z["text"]
    assert "passt" not in z["text"].lower()


def test_gebucht_nein_danke_kein_unklar_kein_slot():
    """Live Petsas 08.09. 08:33: nach der Buchung ‚Nein, danke.‘ →
    ‚Das habe ich nicht verstanden‘ statt Abschied."""
    sit = _sit_gebucht_thaler()
    z = flow.zug(sit, "Nein, danke.")
    assert z and "Wiederhören" in z["text"]
    assert "passt" not in z["text"].lower()
    assert not gespraech.wirkt_unklar("Nein, danke.")


def test_gebucht_verlegen_nach_vorne_sucht_slots():
    """Live Petsas 13:06: ‚Können wir den verlegen … nach vorne?‘ muss
    den frischen Termin verschieben — nicht Talk mit erfundenen Daten."""
    from bianca import verwalten
    sit = _sit_gebucht_thaler()
    s = gehirn.sammler(sit)
    s["motivName"] = "PRO Professionelle Zahnreinigung"
    s["motivId"] = "pzr-1"
    tag = s["slotIso"]
    fruher = tag.replace("T15:30", "T14:00")
    echt = verwalten.kal.find_slots_behandler
    verwalten.kal.find_slots_behandler = lambda tenant, ctx, **kw: {
        "ok": True, "slots": [fruher, tag],
    }
    try:
        z = flow.zug(sit, "Können wir den verlegen ein bisschen nach vorne?")
    finally:
        verwalten.kal.find_slots_behandler = echt
    assert z and "vierzehn" in (z.get("text") or "")
    assert s["modus"] == "verschieben"
    assert s["phase"] == "verschieb_angebot"
    assert sit.get("verschiebRichtung") == "frueher"
    isos = [o["iso"] for o in sit.get("offered") or []]
    assert fruher in isos
    assert "besprechen" not in (z.get("text") or "").lower()


def test_gebucht_ein_bisschen_frueher_ohne_verlegen():
    """Zweiter Zug desselben Anrufs: nur ‚früher‘, ohne das Verb."""
    from bianca import verwalten
    sit = _sit_gebucht_thaler()
    s = gehirn.sammler(sit)
    tag = s["slotIso"]
    fruher = tag.replace("T15:30", "T14:30")
    echt = verwalten.kal.find_slots_behandler
    verwalten.kal.find_slots_behandler = lambda tenant, ctx, **kw: {
        "ok": True, "slots": [fruher, tag],
    }
    try:
        z = flow.zug(sit, "ein bisschen früher, bitte")
    finally:
        verwalten.kal.find_slots_behandler = echt
    assert z
    assert s["modus"] == "verschieben"
    assert sit.get("verschiebRichtung") == "frueher"
    assert s["phase"] == "verschieb_angebot"


def test_terminabgleich_korrigiert_uhrzeit_ohne_neue_suche():
    """Live Helmich 09.09.: „Der Termin ist um 14 Uhr ... richtig?“ darf
    den gewaehlten 16-Uhr-Slot weder verwerfen noch als neuen Wunsch suchen."""
    sit = _sit_bestaetigung_thaler()
    z = flow.zug(sit, "Der Termin ist um 14 Uhr am 21.09. Richtig?")
    s = gehirn.sammler(sit)
    assert z and z.get("_wiederholungErlaubt")
    assert "Nein" in z["text"] and "sechzehn Uhr" in z["text"]
    assert "genau diesen Termin" in z["text"]
    assert s["slotIso"].startswith("2026-09-21T16:00")
    assert s["phase"] == "bestaetigen"
    assert not sit.get("lastBook")


def test_wiederhole_termindaten_bucht_nie_und_bleibt_hoerbar():
    """Live Helmich 09.09.: die zweite Wiederholbitte loeste book_slot aus.
    Ohne ausdrueckliches Ja bleibt Bianca beliebig oft vor dem Schreiben."""
    sit = _sit_bestaetigung_thaler()
    erster = flow.zug(sit, "Wiederhole den Termin.")
    assert erster and "einundzwanzigsten September" in erster["text"]
    zweiter = flow.zug(sit, "Wiederhole mir zuerst die Termindaten, bitte.")
    assert zweiter and "sechzehn Uhr" in zweiter["text"]
    assert gehirn.sammler(sit)["phase"] == "bestaetigen"
    assert not sit.get("lastBook")

    # Auch nach einem identischen vorherigen Readback darf der globale
    # Wiederholungs-Waechter die verlangten Termindaten nicht streichen.
    sit["messages"].append({
        "role": "assistant",
        "content": "Thaler Zahnmedizin. Wie kann ich Ihnen helfen?",
    })
    sit["messages"].append({"role": "assistant", "content": erster["text"]})
    aus = agent._maschinen_antwort(sit, zweiter, list(sit["messages"]))
    assert "einundzwanzigsten September" in aus["text"]
    assert "sechzehn Uhr" in aus["text"]


def test_zwei_unklare_bestaetigungen_buchen_nicht_automatisch():
    sit = _sit_bestaetigung_thaler()
    z1 = flow.zug(sit, "Vielleicht.")
    z2 = flow.zug(sit, "Ich bin nicht sicher.")
    assert z1 and z2
    assert "genau diesen Termin" in z2["text"]
    assert gehirn.sammler(sit)["phase"] == "bestaetigen"
    assert not sit.get("lastBook")


def test_ja_das_stimmt_bleibt_eine_eindeutige_buchungsbestaetigung():
    """Die Faktenfrage-Wache darf ein echtes „Ja, das stimmt“ nicht abfangen."""
    sit = _sit_bestaetigung_thaler()
    s = gehirn.sammler(sit)
    s["pzr"] = "nein"
    s["arztNotizFrage"] = "nein"
    echt_book = flow.kal.book_slot
    echt_note = flow.kal.note_appointment
    flow.kal.book_slot = lambda *a, **k: {
        "ok": True,
        "booked": True,
        "slotIso": s["slotIso"],
        "appointmentId": "apt-ok",
        "spoken": "Der Termin ist fest eingetragen.",
    }
    flow.kal.note_appointment = lambda *a, **k: {"ok": True}
    try:
        z = flow.zug(sit, "Ja, das stimmt.")
    finally:
        flow.kal.book_slot = echt_book
        flow.kal.note_appointment = echt_note
    assert z and (z.get("book") or {}).get("booked")
    assert "fest eingetragen" in z["text"]
