"""Hirn: Verstehen ruft das Modell bei Inhalt, nicht bei nacktem Ja."""

from __future__ import annotations

from bianca.controller import hirn, policy, verstehen
from bianca.controller.gateway_sim import Szenario
from bianca.controller.orchestrator import TestGespraech
from bianca.controller.typen import Intent, Quelle, SemanticEvent, SlotValue, Verstand


def test_formular_ja_geht_nicht_ans_hirn():
    gerufen: list[str] = []

    def llm(text: str, **_k) -> SemanticEvent:
        gerufen.append(text)
        return SemanticEvent(intent=Intent.UNKLAR)

    ev = verstehen.deuten("ja", erwartet_janein=True, llm=llm)
    assert gerufen == []
    assert ev.bestaetigung is True


def test_inhalt_geht_ans_hirn_auch_wenn_nein_erkannt_wurde():
    def llm(text: str, **_k) -> SemanticEvent:
        return SemanticEvent(
            intent=Intent.KORREKTUR,
            slots={
                "besuchsgrund": SlotValue(
                    wert="Schwangerschaftsvorsorge", quelle=Quelle.GESAGT,
                )
            },
            bestaetigung=False,
            korrektur_feld="besuchsgrund",
            roh=text,
        )

    ev = verstehen.deuten(
        "nein zur schwangerschaftsvorsorge",
        erwartet_janein=True,
        llm=llm,
    )
    assert ev.intent == Intent.KORREKTUR
    assert ev.korrektur_feld == "besuchsgrund"
    assert ev.slots["besuchsgrund"].wert == "Schwangerschaftsvorsorge"
    assert ev.bestaetigung is False


def test_hirn_wirft_bekannten_korrekturwert_weg():
    ev = hirn.event_aus_json(
        '{"intent":"korrektur","bestaetigung":false,'
        '"korrektur_feld":"besuchsgrund",'
        '"slots":{"besuchsgrund":"Hautscreening"}}',
        anrufer="den grund",
    )
    ev = hirn.ohne_alte_wiederholung(ev, {"slots": {"besuchsgrund": "Hautscreening"}})
    assert ev is not None
    assert ev.intent == Intent.KORREKTUR
    assert ev.korrektur_feld == "besuchsgrund"
    assert "besuchsgrund" not in ev.slots


def test_hirn_alias_zeit_wird_nicht_verworfen():
    ev = hirn.event_aus_json(
        '{"intent":"buchen","slots":{"zeit":"naechsten Monat","grund":"Vorsorge"}}'
    )
    assert ev is not None
    assert "monat" in ev.slots["wunschzeit"].wert.lower()
    assert ev.slots["besuchsgrund"].wert == "Vorsorge"


def test_hirn_buchen_wird_bei_zwei_verwaltung_gerettet():
    """LLM sagt nur buchen — zwei Verben duerfen die Haelfte nicht verlieren."""
    def llm(_t: str, **_k) -> SemanticEvent:
        return SemanticEvent(
            intent=Intent.BUCHEN,
            roh=_t,
            llm='{"intent":"buchen","slots":{}}',
        )

    ev = verstehen.deuten(
        "hallo ich will meinen termin verschieben und den von meinem mann absagen",
        llm=llm,
    )
    assert ev.deutung == "hirn"
    assert ev.intent == Intent.VERSCHIEBEN
    assert ev.slots["zweit_anliegen"].wert == "absagen"
    assert ev.slots["zweit_fuer_wen"].wert == "mann"
    assert ev.llm.startswith("{")


def test_hirn_unklar_wird_nicht_von_nlu_geflickt():
    def llm(_t: str, **_k) -> SemanticEvent:
        return SemanticEvent(intent=Intent.UNKLAR, roh=_t, llm='{"intent":"unklar"}')

    ev = verstehen.deuten("ich möchte den Termin auf meine schwester Julia übertragen", llm=llm)
    assert ev.deutung == "hirn"
    assert ev.intent == Intent.UNKLAR
    assert ev.slots == {}
    assert ev.llm.startswith("{")


def test_hirn_event_nicht_von_nlu_ueberschrieben():
    def llm(_t: str, **_k) -> SemanticEvent:
        return SemanticEvent(
            intent=Intent.BUCHEN,
            slots={"wunschzeit": SlotValue(wert="nächsten Monat", quelle=Quelle.GESAGT)},
            roh=_t,
        )

    ev = verstehen.deuten("irgendwannnaechsten monat", llm=llm)
    assert ev.deutung == "hirn"
    assert "monat" in ev.slots["wunschzeit"].wert.lower()
    assert "montag" not in ev.slots["wunschzeit"].wert.lower()


def test_naechster_monat_keine_september_slots():
    from bianca.controller.gateway_sim import _slot_texte
    from bianca.controller import wuensche
    assert "monat" in wuensche.wunschzeit("irgendwannnaechsten monat").lower()
    assert wuensche.wochentag("naechsten Monat") == ""
    slots = _slot_texte(3, "naechsten Monat")
    assert slots
    assert all(".10." in s for s in slots)
    assert not any(".09." in s for s in slots)
    gem = wuensche.wunsch_mischen("naechsten Monat", "Mittwoch")
    assert "monat" in gem.lower() and "mittwoch" in gem.lower()
    mid = _slot_texte(3, gem)
    assert all(".10." in s and "mittwoch" in s.lower() for s in mid)


def test_hirn_json_ohne_vllm():
    ev = hirn.event_aus_json(
        '{"intent":"korrektur","bestaetigung":false,'
        '"korrektur_feld":"besuchsgrund",'
        '"slots":{"besuchsgrund":"Schwangerschaftsvorsorge"}}',
        anrufer="nein zur schwangerschaftsvorsorge",
    )
    assert ev is not None
    assert ev.intent == Intent.KORREKTUR
    assert ev.slots["besuchsgrund"].wert == "Schwangerschaftsvorsorge"


def _hirn_stub(text: str, **_k) -> SemanticEvent | Verstand:
    """Stand-in fuer vLLM in der Maschine — Produktiv-Dock spricht echt."""
    t = text.lower()
    if "sms" in t or "bestätig" in t or "bestaetig" in t:
        return Verstand(
            verstanden="Sie möchte eine Bestätigung per SMS.",
            genannt={"kanal": "SMS"},
            hint="dokument" if "sms" in t else "bestaetigen",
            janein=True if "sms" not in t else None,
            roh=text,
            llm='{"verstanden":"Sie möchte eine Bestätigung per SMS.","genannt":{"kanal":"SMS"}}',
        )
    if "tochter" in t and ("wissen" in t or "erfahr" in t or "wann" in t):
        return Verstand(
            verstanden="Der Anrufer möchte den genauen Termin für seine Tochter erfahren.",
            genannt={"wer": "Tochter"},
            roh=text,
            llm='{"verstanden":"Der Anrufer möchte den genauen Termin für seine Tochter erfahren.","genannt":{"wer":"Tochter"}}',
        )
    if "es geht um" in t and "tochter" in t:
        return Verstand(
            verstanden="Der Anrufer möchte, dass die Buchung nicht für sich selbst, sondern für seine Tochter getätigt wird.",
            genannt={"beziehung": "Tochter"},
            roh=text,
            llm='{"verstanden":"Buchung für die Tochter.","genannt":{"beziehung":"Tochter"}}',
        )
    if "vergess" in t:
        return SemanticEvent(intent=Intent.AUSKUNFT, roh=text, llm='{"intent":"auskunft"}')
    if ("termine" in t or "3 termin" in t) and "absag" not in t:
        return SemanticEvent(
            intent=Intent.AUSKUNFT,
            roh=text,
            llm='{"intent":"auskunft","slots":{}}',
        )
    if "alle" in t or "umgezogen" in t or "umzug" in t:
        slots = {}
        if "umgez" in t or "umzug" in t:
            slots["besuchsgrund"] = SlotValue(wert="Umzug", quelle=Quelle.GESAGT)
        if "suche" in t:
            slots["suche_weiter"] = SlotValue(wert="true", quelle=Quelle.GESAGT)
        if "alle" in t:
            slots["terminwahl"] = SlotValue(wert="alle", quelle=Quelle.GESAGT)
        return SemanticEvent(
            intent=Intent.ABSAGEN,
            slots=slots,
            roh=text,
            llm='{"intent":"absagen","slots":{"besuchsgrund":"Umzug"}}',
        )
    if "schwanger" in t:
        return SemanticEvent(
            intent=Intent.KORREKTUR,
            slots={
                "besuchsgrund": SlotValue(
                    wert="Schwangerschaftsvorsorge", quelle=Quelle.GESAGT,
                )
            },
            bestaetigung=False,
            korrektur_feld="besuchsgrund",
            roh=text,
        )
    if "grund" in t:
        return SemanticEvent(
            intent=Intent.KORREKTUR,
            korrektur_feld="besuchsgrund",
            roh=text,
        )
    if "uebertrag" in t or "schwester" in t:
        return SemanticEvent(
            intent=Intent.ABSAGEN,
            bestaetigung=True,
            slots={
                "uebertragen": SlotValue(wert="ja", quelle=Quelle.GESAGT),
                "fuer_wen": SlotValue(wert="schwester", quelle=Quelle.GESAGT),
                "vorname": SlotValue(wert="Julia", quelle=Quelle.GESAGT),
            },
            roh=text,
        )
    if "anderen" in t:
        return SemanticEvent(
            intent=Intent.ABSAGEN,
            bestaetigung=False,
            slots={"suche_weiter": SlotValue(wert="ja", quelle=Quelle.GESAGT)},
            roh=text,
        )
    if "zahnreinigung" in t:
        return SemanticEvent(
            intent=Intent.ABSAGEN,
            slots={
                "wunschzeit": SlotValue(wert="Freitag", quelle=Quelle.GESAGT),
                "besuchsgrund": SlotValue(wert="Zahnreinigung", quelle=Quelle.GESAGT),
                "suche_weiter": SlotValue(wert="ja", quelle=Quelle.GESAGT),
            },
            roh=text,
        )
    if "finden" in t or "daten" in t:
        return SemanticEvent(
            intent=Intent.ABSAGEN,
            slots={"suche_weiter": SlotValue(wert="ja", quelle=Quelle.GESAGT)},
            roh=text,
        )
    if "monat" in t or "irgendwann" in t:
        return SemanticEvent(
            intent=Intent.BUCHEN,
            slots={"wunschzeit": SlotValue(wert="naechsten Monat", quelle=Quelle.GESAGT)},
            roh=text,
        )
    if "mittwoch" in t:
        return SemanticEvent(
            intent=Intent.BUCHEN,
            slots={"wunschzeit": SlotValue(wert="Mittwoch", quelle=Quelle.GESAGT)},
            roh=text,
        )
    if "freitad" in t or "freitag" in t:
        return SemanticEvent(
            intent=Intent.BUCHEN,
            slots={"wunschzeit": SlotValue(wert="Freitag", quelle=Quelle.GESAGT)},
            roh=text,
        )
    raise RuntimeError("offline")


def _glueck(**kw) -> TestGespraech:
    return TestGespraech(policy.default(), Szenario(
        anrufer_anrede="Frau",
        anrufer_nachname="Meier",
        anrufer_telefon="01701234567",
        anrufer_versicherung="gesetzlich",
        letzter_arzt="Doktor Blessing",
        letzter_grund="Hautscreening",
        letzter_wann="4 Monaten",
        **kw,
    ), llm=_hirn_stub)


def test_nein_zum_grund_keine_aenderungsschleife():
    g = _glueck()
    g.eingabe("hallo ich hätte einen termin")
    g.eingabe("ja")
    g.eingabe("freitags")
    a = g.eingabe("ja")
    assert "eintragen" in a.antwort.lower() or "fasse" in a.antwort.lower()
    a = g.eingabe("nein zur schwangerschaftsvorsorge")
    t = a.antwort.lower()
    assert "was möchten sie ändern" not in t
    assert "schwanger" in t or "grund" in t or "freitag" in t or "anbieten" in t or "passen" in t
    a = g.eingabe("den grund")
    assert "was möchten sie ändern" not in a.antwort.lower()
    a = g.eingabe("den grund")
    assert "was möchten sie ändern" not in a.antwort.lower()


def test_zeitwunsch_wechsel_keine_praxisnotiz():
    g = _glueck()
    g.eingabe("hallo ich hätte einen termin")
    g.eingabe("ja")
    for satz in (
        "freitags", "montags", "mittwochs", "nachmittag",
        "mittwoch nachmittag", "doch den montags termin",
    ):
        a = g.eingabe(satz)
        t = a.antwort.lower()
        assert "notiz fuer die praxis" not in t
        assert "notiz für die praxis" not in t
        assert "rückruf" not in t and "rueckruf" not in t


def test_naechster_monat_wird_gesucht_nicht_diese_woche():
    g = _glueck()
    g.eingabe("hallo ich hätte gern einen termin zur vorsorge")
    g.eingabe("ja")
    a = g.eingabe("irgendwannnaechsten monat")
    t = a.antwort.lower()
    assert ".10." in t or "oktober" in t or "01.10" in t
    assert "22.09" not in t
    a = g.eingabe("naechsten monat bitte")
    assert "22.09" not in a.antwort
    a = g.eingabe("der mittwochs")
    assert "24.09" not in a.antwort
    assert "mittwoch" in a.antwort.lower()


def test_absage_hirn_filtert_und_uebertraegt():
    g = TestGespraech(policy.default(), Szenario(
        anrufer_anrede="Frau",
        anrufer_nachname="Meier",
        anrufer_telefon="01701234567",
        termine=3,
    ), llm=_hirn_stub)
    g.eingabe("hallo einen termin bitte absagen")
    a = g.eingabe("ja")
    assert "gefunden" in a.antwort.lower() or "13:00" in a.antwort
    a = g.eingabe("nein")
    t = a.antwort.lower()
    assert "terminwahl" not in t
    assert "sicher verstanden" not in t
    assert "bitte" not in t or "terminwahl" not in t
    a = g.eingabe("ich habe ncoh einen anderen")
    t = a.antwort.lower()
    assert "terminwahl" not in t
    assert "sicher verstanden" not in t
    a = g.eingabe(
        "freitag habe ich einen termin zur zahnreinigung "
        "aber keinen plan um wieviel uhr"
    )
    t = a.antwort.lower()
    assert "eintragen" not in t
    assert "sicher verstanden" not in t
    a = g.eingabe("weiss ich nicht koennen Sie den nicht finden sie haben doch meine daten")
    assert "sicher verstanden" not in a.antwort.lower()
    a = g.eingabe("ich moechte den Termin auf meine schwester Julia uebertragen")
    t = a.antwort.lower()
    assert "sicher verstanden" not in t
    assert "neuen termin" not in t
    assert "julia" in t or "schwester" in t or "übertrag" in t or "uebertrag" in t


def test_leere_suche_fragt_neu_keine_notiz():
    g = _glueck(freie_slots=0)
    g.eingabe("hallo ich hätte einen termin")
    g.eingabe("ja")
    a = g.eingabe("freitags")
    t = a.antwort.lower()
    assert "notiz fuer die praxis" not in t
    assert "notiz für die praxis" not in t
    assert "wann" in t or "passt" in t or "frei" in t


def test_hirn_umzug_wird_absagegrund_und_alle():
    """Live-JSON: Umzug als Besuchsgrund + suche_weiter darf Alle-Absage nicht fressen."""
    def llm(_t: str, **_k) -> SemanticEvent:
        return SemanticEvent(
            intent=Intent.ABSAGEN,
            slots={
                "besuchsgrund": SlotValue(wert="Umzug", quelle=Quelle.GESAGT),
                "suche_weiter": SlotValue(wert="true", quelle=Quelle.GESAGT),
            },
            roh=_t,
            llm='{"intent":"absagen","slots":{"besuchsgrund":"Umzug","suche_weiter":true}}',
        )

    ev = verstehen.deuten(
        "ich möchte alle termine absagen ich bin umgezogen",
        llm=llm,
    )
    assert ev.intent == Intent.ABSAGEN
    assert ev.slots["terminwahl"].wert == "alle"
    assert ev.slots["absage_grund"].wert == "umzug"
    assert "besuchsgrund" not in ev.slots
    assert not ev.slots.get("suche_weiter") or not ev.slots["suche_weiter"].wert


def test_glueck_drei_termine_alle_absagen_mit_bezug():
    """Vorbezug + Fakten: Anzahl bestaetigen, alle drei wegen Umzug absagen."""
    g = _glueck(termine=3)
    a = g.eingabe("hallo ich habe vergessewann mein termin ist")
    assert "meier" in a.antwort.lower()
    a = g.eingabe("ja")
    assert "2026-10-02" in a.antwort
    a = g.eingabe("ich habe 3 termine?")
    t = a.antwort.lower()
    assert "drei" in t or "3" in t
    assert "welchen meinen sie" not in t
    assert "ihr nächster termin" not in t and "ihr naechster termin" not in t
    a = g.eingabe("ich möchte alle termine absagen ich bin umgezogen")
    t = a.antwort.lower()
    assert "umgezogen" in t
    assert "alle" in t and "drei" in t
    assert "welchen meinen sie" not in t
    assert "soll ich" in t
    a = g.eingabe("ja")
    t = a.antwort.lower()
    assert "abgesagt" in t
    assert "alle" in t or "drei" in t


def test_freier_vorlauf_ohne_intent_wird_sms():
    ev = hirn.event_aus_json(
        '{"verstanden":"Sie will eine SMS-Bestätigung der Absage.",'
        '"janein":null,"genannt":{"kanal":"SMS"}}',
        anrufer="kriege ich eine bestätigung?",
        lage={"letzter_write": "absagen"},
    )
    assert ev is not None
    assert ev.verstanden
    assert ev.slots["sms"].wert == "ja"
    assert ev.intent != Intent.DOKUMENT


def test_glueck_sms_nach_absage_kein_rezept():
    g = _glueck(termine=3)
    g.eingabe("hallo ich möchte meinen termin annulieren")
    g.eingabe("ja")
    g.eingabe("alle")
    a = g.eingabe("ja")
    assert "abgesagt" in a.antwort.lower()
    a = g.eingabe("kriege ich eine bestätigung?")
    t = a.antwort.lower()
    assert "sms" in t
    assert "rezept" not in t
    assert "überweisung" not in t and "ueberweisung" not in t
    assert "nicht sicher verstanden" not in t
    a = g.eingabe("ich will eine bestätigungs sms")
    t = a.antwort.lower()
    assert "sms" in t
    assert "rezept" not in t


def test_verstanden_wird_nicht_gesprochen_absage_und_mann():
    """LLM-Metasatz bleibt intern; Maschine sagt Plan + Fakten."""
    g = _glueck(termine=3)
    a = g.eingabe(
        "hallo ich will meinen termin absagen und den von meinem Mann verscheiben"
    )
    t = a.antwort.lower()
    assert "der anrufer möchte" not in t
    assert "stornieren" not in t
    assert "meier" in t
    assert "zuerst" in t
    assert "mann" in t
    assert "absag" in t or " ab" in t
    a = g.eingabe("ja")
    assert "2026-10-02" in a.antwort
    a = g.eingabe("welcher ist denn von meinem mann")
    t = a.antwort.lower()
    assert "möchte wissen" not in t
    assert "anruferin" not in t
    assert "stornieren" not in t
    assert "mann" in t
    assert "keinen eigenen" in t or "akte" in t
    assert "welchen von ihren" in t or "welchen meinen sie" in t


def test_verstanden_tochter_termin_ist_auskunft():
    ev = hirn.event_aus_json(
        '{"verstanden":"Der Anrufer möchte den genauen Termin für seine Tochter erfahren.",'
        '"janein":null,"genannt":{"wer":"Tochter"}}',
        anrufer="ich will wissenwann der termin meiner tochter ist",
    )
    assert ev is not None
    assert ev.intent == Intent.AUSKUNFT
    assert ev.slots["fuer_wen"].wert == "tochter"
    assert ev.slots["auskunft_art"].wert == "bestand"


def test_glueck_tochter_termin_kein_neubuchen():
    g = _glueck(termine=2)
    a = g.eingabe("ich will wissenwann der termin meiner tochter ist")
    t = a.antwort.lower()
    assert "der anrufer möchte" not in t
    assert "buche wieder" not in t
    assert "käme" not in t and "kaeme" not in t
    assert "tochter" in t or "meier" in t
    a = g.eingabe("ja")
    t = a.antwort.lower()
    assert "buche wieder" not in t
    assert "käme es" not in t and "kaeme es" not in t
    assert "passen" not in t
    assert "10:30" in a.antwort or "patrikis" in t or "tochter" in t
