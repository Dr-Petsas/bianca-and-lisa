"""Wortgleiche Live-Saetze am reinen Kern: Auskunft, Rezeption ≠ Rezept, Hallo.

Fruehere Quelle war das eigene Dock (``bianca/controller/dock.py``, Port 8199).
Das ist raus — getestet wird derselbe reine Kern ueber ``TestGespraech``, bedient
wird er im Studio (``/dialogkern`` auf 8097).
"""

from __future__ import annotations

from bianca.controller import nlu_test, policy, renderer, verstehen, varianten
from bianca.controller.gateway_sim import Szenario
from bianca.controller.orchestrator import TestGespraech
from bianca.controller.typen import Intent, SpeakSpec, SprechAkt


def test_nlu_auskunft_ist_ein_wort():
    ev = nlu_test.deuten("Auskunft")
    assert ev.intent == Intent.AUSKUNFT
    assert ev.slots["auskunft_art"].wert == "unklar"


def test_nlu_rezeption_ist_keine_rezept():
    assert nlu_test.deuten("rezeptiom").intent == Intent.ANMELDUNG
    assert nlu_test.deuten("rezeption").intent == Intent.ANMELDUNG
    assert nlu_test.deuten("mitarbeiter").intent == Intent.ANMELDUNG
    assert nlu_test.deuten("Mitarbeiterin").intent == Intent.ANMELDUNG
    assert nlu_test.deuten("mit der Arzthelferin sprechen").intent == Intent.ANMELDUNG
    assert nlu_test.deuten("Verbinde mich mit dem Personal").intent == Intent.ANMELDUNG
    assert nlu_test.deuten("Kann ich mit jemandem sprechen").intent == Intent.ANMELDUNG
    assert nlu_test.deuten("Chef").intent == Intent.ANMELDUNG
    assert nlu_test.deuten("Ich brauche ein Rezept").intent == Intent.DOKUMENT
    assert nlu_test.deuten("hallo").intent == Intent.SMALLTALK
    assert nlu_test.deuten("arzt sorechen").intent == Intent.VERBINDEN
    assert nlu_test.deuten("arzt sprechen").intent == Intent.VERBINDEN
    assert nlu_test.deuten("mit dem Arzt sprechen").intent == Intent.VERBINDEN
    assert "behandler" not in nlu_test.deuten("arzt sprechen").slots


def test_live_verlauf_kein_legacy_kein_stumm():
    """Der getippte Verlauf vom 19.09. — kein UEBERGEBEN, kein leerer Satz."""
    g = TestGespraech(policy.default())
    g.start()
    zuege = [
        ("Auskunft", "bestehend"),
        ("rezeptiom", "anmeldung"),
        ("rezeption", "Rückruf"),
        ("hallo", "kann ich"),
        ("mitarbeiter", "Rückruf"),
    ]
    for text, muss in zuege:
        a = g.eingabe(text)
        assert a.antwort, (text, a.as_dict())
        assert not a.uebergeben, (text, a.grund)
        assert muss.lower() in a.antwort.lower(), (text, a.antwort)


def test_echtes_rezept_bleibt_dokument():
    g = TestGespraech(policy.default())
    a = g.eingabe("Ich brauche ein Rezept")
    assert "Rezept" in a.antwort
    assert "persönlich" in a.antwort or "persoenlich" in a.antwort
    assert a.naechste == "fragen"


def test_renderer_anmeldung_und_hallo():
    an = renderer.rendern(SpeakSpec(akt=SprechAkt.INFO, detail="anmeldung"))
    ha = renderer.rendern(SpeakSpec(akt=SprechAkt.INFO, detail="hallo"))
    assert "menschlich" in an.lower() and "worum" in an.lower()
    assert ha.startswith("Hallo")


def test_arzt_sprechen_und_rueckruf_kein_legacy():
    """Wortgleicher Dock-Verlauf 19.09.: kein UEBERGEBEN an Legacy."""
    g = TestGespraech(policy.default())
    g.start()
    a = g.eingabe("arzt sorechen")
    assert not a.uebergeben, a.as_dict()
    assert a.antwort and "durchstellen" in a.antwort.lower() or "anliegen" in a.antwort.lower()
    a = g.eingabe("rückruf")
    assert "Nachname" in a.antwort and not a.uebergeben
    a = g.eingabe("meier")
    assert any(w in a.antwort.lower() for w in ("handy", "mobil", "nummer")) and not a.uebergeben
    a = g.eingabe("91231239")
    assert not a.uebergeben, a.as_dict()
    assert "91231239" in a.antwort
    a = g.eingabe("ja")
    assert not a.uebergeben, a.as_dict()
    assert "Notiz" in a.antwort or "meldet" in a.antwort.lower()


def test_anmeldung_ist_ausfuehrlich():
    text = renderer.rendern(SpeakSpec(akt=SprechAkt.INFO, detail="anmeldung"))
    assert "Worum geht es" in text
    assert "belastet" in text
    assert "entlaste" in text.lower() or "entlastet" in text.lower() or "Anmeldung" in text


def test_termin_startet_mit_schonmal():
    g = TestGespraech(policy.default())
    g.start()
    a = g.eingabe("Ich hätte gern einen Termin")
    assert not a.uebergeben
    assert "schon" in a.antwort.lower()
    a = g.eingabe("nein")
    assert "Behandler" in a.antwort


def test_notfall_danach_kein_leerer_zug():
    g = TestGespraech(policy.default())
    g.start()
    a = g.eingabe("notfall")
    assert a.hangup and a.antwort
    a = g.eingabe("Ich hätte gern einen Termin")
    assert a.antwort, a.as_dict()
    assert "schon" in a.antwort.lower()


def test_zweites_anmeldung_ja_startet_rueckruf():
    g = TestGespraech(policy.default())
    g.start()
    g.eingabe("Mitarbeiter")
    a = g.eingabe("Ich will mit einer Mitarbeiterin sprechen")
    assert "Rückruf" in a.antwort or "Rueckruf" in a.antwort
    a = g.eingabe("ja")
    assert "Nachname" in a.antwort and not a.uebergeben


def test_arzt_sprechen_ohne_transfer_nimmt_anliegen():
    g = TestGespraech(policy.default())
    a = g.eingabe("ich will mit dem arzt sprechen")
    assert "durchstellen" in a.antwort.lower()
    assert "worum" in a.antwort.lower()
    a = g.eingabe("rückruf")
    assert "Nachname" in a.antwort


def test_nlu_verbinden_absageb_egal_schon_gesagt():
    assert nlu_test.deuten("verbinden").intent == Intent.VERBINDEN
    assert nlu_test.deuten("mit arzt verbinden").intent == Intent.VERBINDEN
    assert nlu_test.deuten("nein ich wollte den termin absageb").intent == Intent.ABSAGEN
    ev = nlu_test.deuten("rgal", offene_frage="behandler")
    assert ev.slots["behandler"].wert == "egal"
    ev = nlu_test.deuten("zu keinem", offene_frage="behandler")
    assert ev.slots["behandler"].wert == "egal"
    ev = nlu_test.deuten("habe ich doch eben gesagt", offene_frage="nachname")
    assert "nachname" not in ev.slots


def test_session_hirn_fragt_schonmal_nur_einmal():
    g = TestGespraech(policy.default())
    g.start()
    a = g.eingabe("termin")
    assert "schon" in a.antwort.lower()
    g.eingabe("rezeption")
    a = g.eingabe("termin")
    assert "schon" not in a.antwort.lower(), a.antwort
    assert "Behandler" in a.antwort or "Worum" in a.antwort


def test_session_hirn_name_bleibt_ueber_themenwechsel():
    g = TestGespraech(policy.default())
    g.start()
    g.eingabe("rückruf")
    a = g.eingabe("haus")
    assert "Handy" in a.antwort
    g.eingabe("017755445566")
    a = g.eingabe("ja")
    assert "Notiz" in a.antwort or "meldet" in a.antwort.lower()
    a = g.eingabe("termin absagen")
    assert "Nachname" not in a.antwort, a.antwort
    assert "gefunden" in a.antwort.lower() or "Termin" in a.antwort
    a = g.eingabe("habe ich doch eben gesagt")
    assert "Nachname" not in a.antwort, a.antwort


def test_drittperson_sohn_kein_schonmal_nein():
    ev = nlu_test.deuten(
        "nicht für mich , für meinen sohn",
        offene_frage="schonmal",
        erwartet_janein=True,
    )
    assert ev.slots["fuer_wen"].wert == "sohn"
    assert "schonmal" not in ev.slots
    assert ev.bestaetigung is None


def test_drittperson_fuenfjaehriger_sohn():
    ev = nlu_test.deuten("ich möchte ieinen termin für meinen 5 jährigen Sohn")
    assert ev.intent == Intent.BUCHEN
    assert ev.slots["fuer_wen"].wert == "sohn"


def test_dock_termin_fuer_sohn():
    g = TestGespraech(policy.default())
    g.start()
    a = g.eingabe("hallo ich möchte einen termin")
    assert "schon" in a.antwort.lower()
    a = g.eingabe("nicht für mich , für meinen sohn")
    assert "sohn" in a.antwort.lower(), a.antwort
    assert "schon" in a.antwort.lower()
    a = g.eingabe("nein")
    assert "Behandler" in a.antwort
    assert "sohn" in a.antwort.lower()
    a = g.eingabe("zu dr. petsas")
    assert "Worum" in a.antwort
    a = g.eingabe("schmerzen")
    assert "Wann" in a.antwort
    g.eingabe("mitarbeiter")
    g.eingabe("kannich mit dr. petsas verbunden werden")
    a = g.eingabe("ich möchte ieinen termin für meinen 5 jährigen Sohn")
    assert "schon einmal" not in a.antwort.lower(), a.antwort
    assert "Wann" in a.antwort or "Nachname" in a.antwort or "versichert" in a.antwort.lower()


def test_absage_sagt_abgesagt_nicht_eingetragen():
    text = renderer.rendern(SpeakSpec(
        akt=SprechAkt.ERFOLG,
        detail="absagen",
        fakten=(("gefunden_iso", "2026-10-02 13:00"),),
    ))
    assert "abgesagt" in text
    assert "eingetragen" not in text
    assert "SMS" not in text


def test_anliegen_semantik_chefsaetze():
    ev = nlu_test.deuten("Termin vereinbaren.")
    assert ev.intent == Intent.BUCHEN
    ev = nlu_test.deuten("Ich würde gerne die Einsicht in Behandlungsunterlagen bekommen.")
    assert ev.intent == Intent.DOKUMENT
    assert ev.slots["dokumentart"].wert == "unterlagen"
    ev = nlu_test.deuten("Hallo, es geht um eine Terminverschiebung")
    assert ev.intent == Intent.VERSCHIEBEN
    ev = nlu_test.deuten("Hallo, haut ab! Ich habe Fragen zu einer Hyposensibilisierung.")
    assert ev.intent == Intent.PRAXISINFO
    ev = nlu_test.deuten("Terminauskunft")
    assert ev.intent == Intent.AUSKUNFT
    assert ev.slots["auskunft_art"].wert == "unklar"
    ev = nlu_test.deuten("habe ich einen Termin")
    assert ev.slots["auskunft_art"].wert == "bestand"
    ev = nlu_test.deuten("Ich habe einen Termin, ich möchte einen Termin absagen.")
    assert ev.intent == Intent.ABSAGEN


def test_terminauskunft_wird_hinterfragt():
    g = TestGespraech(policy.default())
    a = g.eingabe("Terminauskunft")
    assert "bestehend" in a.antwort.lower() or "neuen" in a.antwort.lower()
    assert "Nachname" not in a.antwort
    a = g.eingabe("einen neuen")
    assert "schon" in a.antwort.lower()


def test_unterlagen_nicht_rezept():
    g = TestGespraech(policy.default())
    a = g.eingabe("Ich würde gerne die Einsicht in Behandlungsunterlagen bekommen.")
    assert "unterlagen" in a.antwort.lower() or "akte" in a.antwort.lower()
    assert "Rezept" not in a.antwort


def test_hyposens_keine_buchung():
    g = TestGespraech(policy.default())
    a = g.eingabe("Hallo, haut ab! Ich habe Fragen zu einer Hyposensibilisierung.")
    assert "hyposens" in a.antwort.lower() or "ärztin" in a.antwort.lower() or "aerztin" in a.antwort.lower()
    assert "schon einmal" not in a.antwort.lower()


def test_anrufer_check_dann_neuer_termin_nicht_bestand():
    g = TestGespraech(policy.default(), Szenario(
        anrufer_anrede="Frau",
        anrufer_nachname="Meier",
    ))
    a = g.eingabe("Terminauskunft")
    assert "meier" in a.antwort.lower()
    a = g.eingabe("einen neuen")
    assert "Behandler" in a.antwort or "schon" in a.antwort.lower()
    assert "13:00" not in a.antwort


def test_anrufer_check_und_vortermin():
    g = TestGespraech(policy.default(), Szenario(
        anrufer_anrede="Frau",
        anrufer_nachname="Meier",
        letzter_arzt="Doktor Blessing",
        letzter_grund="Hautscreening",
    ))
    a = g.eingabe("Termin vereinbaren")
    assert "meier" in a.antwort.lower()
    assert any(w in a.antwort.lower() for w in ("erkannt", "richtige", "stimmt", "passt", "kontrolle", "bin ich"))
    a = g.eingabe("ja")
    assert "blessing" in a.antwort.lower()
    assert "hautscreening" in a.antwort.lower()


def test_zehn_varianten_pro_fall():
    for key in ("anmeldung", "anrufer_check", "auskunft_klar", "schonmal", "unklar",
                "bezug", "angebot_persoenlich", "arzt_notiz"):
        saetze = {varianten.waehle(
            key, i, anrede="Frau", name="Meier", arzt="Doktor Blessing",
            grund="Hautscreening", wann="4 Monaten", slot="morgen 9 Uhr",
        ) for i in range(10)}
        assert len(saetze) == 10, key


def test_nlu_notfall_nicht_akute_haut():
    assert nlu_test.deuten("Notfall").intent == Intent.NOTFALL
    assert nlu_test.deuten("Zahn vorne rausgefallen").intent == Intent.NOTFALL
    ev = nlu_test.deuten("akute Hautbeschwerden")
    assert ev.intent != Intent.NOTFALL
    assert ev.intent == Intent.BUCHEN
    ev = nlu_test.deuten("Befunde per email")
    assert ev.intent == Intent.DOKUMENT
    ev = nlu_test.deuten("rötgen bilder")
    assert ev.intent == Intent.DOKUMENT
    ev = nlu_test.deuten("behnadlungsunterlagen")
    assert ev.intent == Intent.DOKUMENT


def test_unterlagen_keine_auskunftsschleife():
    g = TestGespraech(policy.default())
    a = g.eingabe("auskunft")
    assert "bestehend" in a.antwort.lower() or "neuen" in a.antwort.lower()
    a = g.eingabe("nein zu meinen befunden")
    assert "bestehend" not in a.antwort.lower() or "befund" in a.antwort.lower() or "unterlagen" in a.antwort.lower()
    a = g.eingabe("befunde per email")
    assert "bestehend" not in a.antwort.lower()
    assert "unterlagen" in a.antwort.lower() or "mail" in a.antwort.lower() or "rückruf" in a.antwort.lower()
    a = g.eingabe("rötgen bilder")
    assert "bestehend" not in a.antwort.lower()
    a = g.eingabe("behnadlungsunterlagen")
    assert "bestehend" not in a.antwort.lower()


def test_erkannte_person_kein_erneutes_abfragen_und_persoenliches_angebot():
    g = TestGespraech(policy.default(), Szenario(
        anrufer_anrede="Frau",
        anrufer_nachname="Meier",
        anrufer_telefon="01701234567",
        anrufer_versicherung="gesetzlich",
        letzter_arzt="Doktor Blessing",
        letzter_grund="Hautscreening",
        letzter_wann="4 Monaten",
    ))
    a = g.eingabe("Termin vereinbaren")
    assert "meier" in a.antwort.lower()
    a = g.eingabe("ja")
    assert "blessing" in a.antwort.lower()
    assert "hautscreening" in a.antwort.lower()
    assert "4 monaten" in a.antwort.lower()
    assert "Nachname" not in a.antwort
    assert "versichert" not in a.antwort.lower()
    a = g.eingabe("morgen")
    assert "meier" in a.antwort.lower()
    assert "frei" in a.antwort.lower() or "passt" in a.antwort.lower()
    a = g.eingabe("ja")
    assert "eintragen" in a.antwort.lower() or "fasse" in a.antwort.lower()
    a = g.eingabe("ja")
    assert "nachricht" in a.antwort.lower() or "notiz" in a.antwort.lower()
    a = g.eingabe("nein")
    assert "eingetragen" in a.antwort.lower()
    assert "sms" in a.antwort.lower()


def test_zwei_drittpersonen_und_danke_holt_naechste():
    g = TestGespraech(policy.default())
    a = g.eingabe("Termin für meinen Nachbarn und meinen Sohn")
    assert "nachbar" in a.antwort.lower() or "sohn" in a.antwort.lower()
    a = g.eingabe("danke")
    assert not a.hangup, a.as_dict()
    assert a.antwort


def test_absage_nein_legt_nicht_auf():
    g = TestGespraech(policy.default())
    g.eingabe("Termin absagen")
    a = g.eingabe("Meier")
    assert "gefunden" in a.antwort.lower() or "termin" in a.antwort.lower()
    a = g.eingabe("nein")
    assert not a.hangup, a.as_dict()
    assert "wiederhören" not in a.antwort.lower()
    assert "wiederhoeren" not in a.antwort.lower()


def test_glueck_terminauskunft_zu_meinem_termin():
    g = TestGespraech(policy.default(), Szenario(
        anrufer_anrede="Frau",
        anrufer_nachname="Meier",
        letzter_arzt="Doktor Blessing",
        letzter_grund="Hautscreening",
        letzter_wann="4 Monaten",
    ))
    a = g.eingabe("terminauskunft")
    assert "meier" in a.antwort.lower()
    a = g.eingabe("ja")
    assert "bestehend" in a.antwort.lower() or "neuen" in a.antwort.lower()
    a = g.eingabe("zu meinem termin")
    assert "13:00" in a.antwort or "gefunden" in a.antwort.lower()
    assert "passen" not in a.antwort.lower()


def test_verschieben_keiner_donnerstags():
    g = TestGespraech(policy.default(), Szenario(
        anrufer_anrede="Frau", anrufer_nachname="Meier",
    ))
    g.eingabe("terminauskunft")
    g.eingabe("ja")
    g.eingabe("zu meinem termin")
    g.eingabe("kann ich den verschieben")
    g.eingabe("ja ahaben wir doch schon geklärt gehabt")
    a = g.eingabe("keiner bitte donnerstags")
    assert "donnerstag" in a.antwort.lower(), a.as_dict()
    assert "sicher verstanden" not in a.antwort.lower()
    a = g.eingabe("ich kann nur donnerstags")
    assert "donnerstag" in a.antwort.lower()
    assert "sicher verstanden" not in a.antwort.lower()


def test_anmeldung_tippfehler_und_ki_ablehnung():
    assert nlu_test.deuten("Anmledung").intent == Intent.ANMELDUNG
    assert nlu_test.deuten("Mitarbeter").intent == Intent.ANMELDUNG
    assert nlu_test.deuten("ich möchte nicht mit der ki reden").intent == Intent.ANMELDUNG
    assert nlu_test.deuten("ich möchte mit einem Menschen reden").intent == Intent.ANMELDUNG
    g = TestGespraech(policy.default())
    a = g.eingabe("rezeption")
    assert "digitale" in a.antwort.lower() or "anmeldung" in a.antwort.lower()
    a = g.eingabe("Mitarbeter")
    assert "rückruf" in a.antwort.lower() or "rueckruf" in a.antwort.lower()
    a = g.eingabe("ich möchte nicht mit der ki reden")
    assert "rückruf" in a.antwort.lower() or "rueckruf" in a.antwort.lower() or "nachname" in a.antwort.lower()


def test_i6_absage_ohne_namen_sucht_nicht():
    g = TestGespraech(policy.default())
    a = g.eingabe("Termin absagen")
    assert "Nachname" in a.antwort
    assert not a.tool
    a = g.eingabe("ja")
    assert "Nachname" in a.antwort
    assert not a.tool, a.as_dict()


def test_nlu_temin_dienstags_nachmittags():
    ev = nlu_test.deuten("hallo ich hätte gerne einen temin dienstags nachmittags")
    assert ev.intent == Intent.BUCHEN
    w = ev.slots["wunschzeit"].wert.lower()
    assert "dienstag" in w
    assert "nachmittag" in w


def test_sim_dienstag_nachmittag_kein_montag():
    from bianca.controller.gateway_sim import _slot_texte
    slots = _slot_texte(3, "Dienstag nachmittag")
    assert slots
    assert all("dienstag" in s.lower() for s in slots)
    assert not any("montag" in s.lower() for s in slots)
    assert all(("14:" in s) or ("15:" in s) for s in slots)
    leer = _slot_texte(3, "")
    assert leer[0].startswith("Montag")


def test_nlu_verschieben_und_neu_fuer_mann():
    ev = nlu_test.deuten(
        "ich möchte ienen termin verschieben und einen neuen für meinen mann machen"
    )
    assert ev.intent == Intent.VERSCHIEBEN
    assert "fuer_wen" not in ev.slots
    assert ev.slots["zweit_anliegen"].wert == "buchen"
    assert ev.slots["zweit_fuer_wen"].wert == "mann"


def test_nlu_alle_absagen_umzug_kein_besuchsgrund():
    ev = verstehen.deuten("ich möchte alle termine absagen ich bin umgezogen")
    assert ev.intent == Intent.ABSAGEN
    assert ev.slots["terminwahl"].wert == "alle"
    assert ev.slots["absage_grund"].wert == "umzug"
    assert "besuchsgrund" not in ev.slots


def test_renderer_spricht_verstanden_nicht():
    spec = SpeakSpec(
        akt=SprechAkt.FRAGE,
        frage_id="anrufer_check",
        fakten=(
            ("gehoert_verstanden",
             "Der Anrufer möchte den eigenen Termin stornieren "
             "und den Termin des Ehemanns verschieben."),
            ("anrede", "Frau"),
            ("name", "Meier"),
        ),
    )
    t = renderer.rendern(spec)
    assert "stornieren" not in t.lower()
    assert "ehemann" not in t.lower()
    assert "meier" in t.lower()


def test_renderer_vorbezug_dann_faktenfrage():
    spec = SpeakSpec(
        akt=SprechAkt.FRAGE,
        frage_id="mehrfach_ok",
        fakten=(
            ("anzahl", "3"),
            ("absage_grund", "umzug"),
            ("gehoert_terminwahl", "alle"),
        ),
    )
    t = renderer.rendern(spec)
    assert t.startswith("Sie möchten alle drei Termine absagen, weil Sie umgezogen sind.")
    assert t.endswith("Soll ich das wirklich tun?")


def test_nlu_verschieben_und_mann_absagen():
    ev = nlu_test.deuten(
        "hallo ich will meinen termin verschieben und den von meinem mann absagen"
    )
    assert ev.intent == Intent.VERSCHIEBEN
    assert "fuer_wen" not in ev.slots
    assert ev.slots["zweit_anliegen"].wert == "absagen"
    assert ev.slots["zweit_fuer_wen"].wert == "mann"


def test_glueck_verschieben_und_mann_absagen_kein_neubuchen():
    """Wortgleich Glueck: eigenes Verschieben zuerst, nie 'Ich buche wieder'."""
    g = TestGespraech(policy.default(), Szenario(
        anrufer_anrede="Frau",
        anrufer_nachname="Meier",
        anrufer_telefon="01701234567",
        anrufer_versicherung="gesetzlich",
        letzter_arzt="Doktor Blessing",
        letzter_grund="Hautscreening",
        letzter_wann="4 Monaten",
        termine=3,
    ))
    a = g.eingabe(
        "hallo ich will meinen termin verschieben und den von meinem mann absagen"
    )
    t = a.antwort.lower()
    assert "meier" in t
    assert "zuerst" in t
    assert "mann" in t
    assert "absag" in t or ("sagen" in t and " ab" in t)
    assert "buche wieder" not in t
    assert a.llm
    a = g.eingabe("ja")
    t = a.antwort.lower()
    assert "buche wieder" not in t
    assert "käme es" not in t and "kaeme es" not in t
    assert "sms" not in t
    assert "termin" in t


def test_verschieben_erst_dann_mann_keine_namensschleife():
    """Wortgleicher Verlauf: eigener Termin zuerst, ok wählt Slot, kein Nachnamen-Loop."""
    g = TestGespraech(policy.default())
    a = g.eingabe(
        "ich möchte ienen termin verschieben und einen neuen für meinen mann machen"
    )
    t = a.antwort.lower()
    assert "zuerst" in t or "erst" in t
    assert "ihren mann" in t
    assert "ihr mann mit nachnamen" not in t
    a = g.eingabe("meier")
    assert "13:00" in a.antwort or "gefunden" in a.antwort.lower()
    assert "ihr mann mit nachnamen" not in a.antwort.lower()
    a = g.eingabe("ja")
    assert "montag" in a.antwort.lower() or "dienstag" in a.antwort.lower()
    a = g.eingabe("ok")
    t = a.antwort.lower()
    assert "ihr mann mit nachnamen" not in t
    assert "wie heißt ihr mann" not in t
    assert "eintragen" in t or "termin" in t or "verschob" in t
    a = g.eingabe("ja")
    t = a.antwort.lower()
    assert "erledigt" in t or "verschob" in t or "mann" in t
    a = g.eingabe("meier")
    a = g.eingabe("meier")
    assert "wie heißt ihr mann mit nachnamen" not in a.antwort.lower()
    a = g.eingabe("fick dich")
    assert "selber" in a.antwort.lower()
    assert "wie heißt ihr mann mit nachnamen" not in a.antwort.lower()


def test_glueck_haelt_dienstag_nachmittag():
    """Wortgleicher Glueck-Verlauf: Zeitwunsch bleibt, kein Montag, keine zweite Wann-Frage."""
    g = TestGespraech(policy.default(), Szenario(
        anrufer_anrede="Frau",
        anrufer_nachname="Meier",
        anrufer_telefon="01701234567",
        anrufer_versicherung="gesetzlich",
        letzter_arzt="Doktor Blessing",
        letzter_grund="Hautscreening",
        letzter_wann="4 Monaten",
    ))
    a = g.eingabe("hallo ich hätte gerne einen temin dienstags nachmittags")
    assert "meier" in a.antwort.lower()
    a = g.eingabe("ja")
    t = a.antwort.lower()
    assert "blessing" in t
    assert "dienstag" in t, a.as_dict()
    assert "montag" not in t
    assert "käme es" not in t and "würde es" not in t
    a = g.eingabe("nein dienstags")
    assert "dienstag" in a.antwort.lower(), a.as_dict()
    assert "montag" not in a.antwort.lower()
    a = g.eingabe("dienstags!!!!!!")
    assert "dienstag" in a.antwort.lower(), a.as_dict()
    assert "montag" not in a.antwort.lower()
