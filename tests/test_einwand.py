"""W-EINWAND: Widerspruch gegen einen belegten Wert wird ZUERST korrigiert.

Chef 13.09.2026 (woertlich): "denk daran auch korrekturen einzubauen wenn eine
angabe nicht stimmt. telefon oder vorname oder was auch immer und der patient
da widerspricht, dass das dann zunaechst korrigiert wird und nicht uebergangen
wird […] dann wuerde bianca nie wieder einwaende einfach uebergehen."

Bis heute griff die Korrektur nur an der Readback-Frage ("Soll ich das so
eintragen?" -> Nein) und beim Namen. Mitten im Fragenfaden lief der Einwand
ins Leere: die Maschine stellte einfach ihre offene Frage weiter.

Die Gegenproben sind hier der teurere Fehler — ein falscher Treffer wirft
einen feststehenden Wert weg (genau die Katastrophe aus Anruf 1fbda5db).
Deshalb steht unten hinter jedem Positiv-Fall ein Negativ-Fall.
"""

from bianca import flow, gehirn
from kern import einwand
from kern.tenants import laden


def _sit(**felder) -> dict:
    sit = {"tenant": laden("meddent"),
           "messages": [{"role": "system", "content": "x"}]}
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen", "warSchonMal": True,
        "arzt": {"typ": "genannt", "calendarId": "zex5bmv5jfIHWVW6zHbg",
                 "calendarName": "Dr. Petsas"},
        "nachname": "Rateike", "buchstabiert": True,
        "vorname": "Stefan", "vornameQuelle": "gesagt",
        "grund": "Kontrolle", "motivId": "kontrolle", "motivName": "KCH Kontrolle",
        "telefon": "01776004600", "telefonOk": True,
        "versicherung": "gesetzlich", "versicherungOk": True,
        "versicherungAkte": "gesetzlich",
        "pzr": "nein", "bleaching": "nein", "rueckblick": "fertig",
        "frage": "wunsch",
    })
    s.update(felder)
    return sit


def _ohne_hintergrund(fn):
    """Kartei-/Slot-Vorrat nicht anstossen (kein Netz im Test)."""
    echt = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    try:
        return fn()
    finally:
        flow.hintergrund.anstossen = echt


# --- Erkennung -------------------------------------------------------------

def test_bestrittene_nummer_wird_erkannt():
    for satz in ("Nein, die Nummer stimmt nicht.",
                 "Die Handynummer ist falsch.",
                 "Meine Telefonnummer hat sich geändert.",
                 "Moment, die Nummer stimmt nicht mehr.",
                 "Das ist nicht meine Rufnummer."):
        assert einwand.feld(satz) == "nummer", satz


def test_bestrittene_versicherung_und_behandler_und_grund():
    assert einwand.feld("Nein, gesetzlich stimmt nicht mehr.") == "versicherung"
    assert einwand.feld("Ich bin nicht mehr privat versichert.") == "versicherung"
    assert einwand.feld("Ich war nicht bei dem Behandler.") == "arzt"
    assert einwand.feld("Der Besuchsgrund ist falsch.") == "grund"
    assert einwand.feld("Nein, mein Nachname ist falsch.") == "name"


def test_frage_des_anrufers_ist_kein_einwand():
    # "Stimmt meine Nummer nicht?" bestreitet nichts — das gehoert dem Gespraech.
    for satz in ("Stimmt meine Nummer nicht?",
                 "Haben Sie meine Nummer nicht?",
                 "Ist der Behandler nicht Doktor Petsas?"):
        assert einwand.feld(satz) == "", satz


def test_bitte_um_wiederholung_ist_kein_einwand():
    for satz in ("Wie war die Nummer nochmal.",
                 "Sagen Sie die Nummer noch einmal."):
        assert einwand.feld(satz) == "", satz


def test_marker_ohne_feldwort_und_feldwort_ohne_marker():
    # Nur Verneinung (der Slot lehnt sich selbst ab) bzw. nur Nennung.
    for satz in ("Nein, das passt mir nicht.",
                 "Nein, lieber nachmittags.",
                 "Meine Nummer ist null eins sieben sieben.",
                 "Ich war bei Doktor Petsas.",
                 "Ich bin gesetzlich versichert."):
        assert einwand.feld(satz) == "", satz


def test_marker_im_anderen_teilsatz_zaehlt_nicht():
    # "Nein" gehoert zum Grund, nicht zum Behandler — sonst haette ein
    # beliebiges Nein den feststehenden Kalender weggeworfen.
    assert einwand.feld("Nein, zur Kontrolle bei Doktor Petsas.") == ""
    assert einwand.feld("Nein danke, sonst nichts, die Nummer passt.") == ""


# --- Fix 4 (13.09.2026): Fehltreffer eng — ein falscher Einwand wirft einen
# feststehenden Wert weg. Hinter jedem Negativ-Fall steht der Positiv-Fall,
# der weiterhin greifen MUSS (sonst schluckt die Ausnahme echte Einwaende).

def test_zustandsangabe_keine_beschwerden_ist_kein_einwand():
    for satz in ("Ich habe keine Beschwerden.",
                 "Ich habe keine Schmerzen, nur zur Kontrolle.",
                 "Kein Problem, die Behandlung machen wir dann.",
                 "Keine Ahnung, welche Behandlung das war."):
        assert einwand.feld(satz) == "", satz
    # Gegenprobe: der Grund wird wirklich bestritten.
    assert einwand.feld("Nein, der Grund ist falsch, ich komme wegen Schmerzen.") == "grund"
    assert einwand.feld("Die Behandlung ist nicht richtig, ich will eine Zahnreinigung.") == "grund"


def test_keine_andere_nummer_ist_keine_aenderung():
    # "keine andere/neue Nummer" heisst: die hinterlegte BLEIBT.
    for satz in ("Ich habe keine andere Nummer.",
                 "Ich habe keine neue Nummer, nehmen Sie die.",
                 "Ich möchte keinen anderen Arzt.",
                 "Nein, keinen anderen Behandler, bei Doktor Petsas bleibt es."):
        assert einwand.feld(satz) == "", satz
    # Gegenprobe: "eine andere Nummer" ist eine echte Aenderung.
    assert einwand.feld("Ich habe jetzt eine andere Nummer.") == "nummer"
    assert einwand.feld("Ich hätte gern einen anderen Behandler.") == "arzt"


def test_bestaetigung_mit_vorangestelltem_nein_ist_kein_einwand():
    # STT verschluckt das Komma: "Nein die Nummer stimmt" bestaetigt.
    for satz in ("Nein die Nummer stimmt.",
                 "Nein der Name passt so.",
                 "Nein, die Nummer bleibt.",
                 "Nein privat ist richtig."):
        assert einwand.feld(satz) == "", satz
    # Gegenprobe: harte Verneinung im selben Teilsatz bleibt ein Einwand.
    assert einwand.feld("Nein die Nummer stimmt nicht.") == "nummer"
    assert einwand.feld("Die Nummer ist nicht richtig.") == "nummer"
    assert einwand.feld("Nein, privat ist nicht mehr korrekt.") == "versicherung"


def test_unwissen_des_anrufers_ist_kein_einwand():
    for satz in ("Ich weiß den Namen nicht.",
                 "Ich kenne den Namen vom Arzt nicht.",
                 "Ich habe den Namen nicht verstanden.",
                 "Ich habe die Nummer nicht mitbekommen.",
                 "Ich erinnere mich nicht an den Behandler."):
        assert einwand.feld(satz) == "", satz
    # Gegenprobe: BIANCA hat falsch verstanden — das ist ein Einwand.
    assert einwand.feld("Sie haben den Namen falsch verstanden.") == "name"
    assert einwand.feld("Sie haben die Nummer nicht richtig verstanden.") == "nummer"


def test_alter_und_neupatient_sind_keine_aenderung():
    for satz in ("Mein Sohn ist acht Jahre alt mit dem Namen Max.",
                 "Ich bin 70 Jahre alt, der Name ist Berger.",
                 "Ich bin eine neue Patientin mit dem Namen Berger.",
                 "Wir sind neue Patienten, der Behandler ist uns egal."):
        assert einwand.feld(satz) == "", satz
    # Gegenprobe: "veraltete Nummer" / "neuer Name" bleiben Aenderungen.
    # (Bewusst NICHT "meine alte Nummer": `alt` ist nur als ganzes Wort
    # Marker — "mein alter Zahnarzt" darf den Behandler nie wegwerfen.)
    assert einwand.feld("Die hinterlegte Nummer ist veraltet.") == "nummer"
    assert einwand.feld("Ich habe einen neuen Namen, ich habe geheiratet.") == "name"


def test_rueckblick_und_bewertung_sind_kein_einwand():
    for satz in ("Die Behandlung letztes Mal war nicht gut.",
                 "Damals war der Behandler nicht so nett.",
                 "Ich war früher nicht bei diesem Arzt.",
                 "Beim letzten Mal hat die Behandlung nicht gepasst."):
        assert einwand.feld(satz) == "", satz
    # Gegenprobe (Opus-Fall bleibt): der AKTUELLE Behandler wird bestritten.
    assert einwand.feld("Ich war nicht bei dem Behandler.") == "arzt"
    assert einwand.feld("Nein, bei dem Behandler war ich nicht.") == "arzt"


def test_arzt_gewinnt_vor_name_bei_heisst():
    # "Der Arzt heisst nicht Petsas" bestreitet den Behandler, nicht den
    # Patientennamen — deshalb steht `arzt` in _FELDER vor `name`.
    assert einwand.feld("Der Arzt heißt nicht Petsas.") == "arzt"
    assert einwand.feld("Nein, mein Behandler heißt nicht so.") == "arzt"
    # Ohne Arztwort bleibt es der Patientenname.
    assert einwand.feld("Ich heiße nicht Thomas.") == "name"


# --- Wirkung im Fluss ------------------------------------------------------

def test_bestrittene_nummer_mitten_im_faden_wird_sofort_korrigiert():
    """Die Nummer ist das EINE Feld, das die Korrektur mitten im Faden schon
    kannte (``_TEL_FALSCH_RE`` in ``einsammeln`` raeumt und sperrt sie, W-EINWAND
    haelt sich deshalb heraus). Der Vertrag gilt unveraendert weiter."""
    sit = _sit()
    r = _ohne_hintergrund(lambda: flow.zug(sit, "Moment, die Nummer stimmt nicht."))
    s = sit["sammler"]
    assert r is not None, "Einwand ging ans LLM statt in die Korrektur"
    text = r.get("text") or ""
    assert text.startswith("Entschuldigung"), text
    # NUR die Nummer ist weg …
    assert (s["telefon"], s["telefonOk"]) == ("", False)
    assert s["frage"] == "telefon"
    # … alles andere steht unveraendert (die Buchungskette laeuft weiter).
    assert s["nachname"] == "Rateike" and s["vorname"] == "Stefan"
    assert s["grund"] == "Kontrolle" and s["arzt"]
    assert s["versicherungOk"] is True


def test_bestrittener_behandler_raeumt_auch_den_slot_vorrat():
    sit = _sit(frage="wunsch")
    sit["slotVorrat"] = [{"iso": "2026-09-15T09:00:00"}]
    sit["offered"] = [{"iso": "2026-09-15T09:00:00"}]
    r = _ohne_hintergrund(lambda: flow.zug(sit, "Nein, bei dem Behandler war ich nicht."))
    s = sit["sammler"]
    assert r is not None and (r.get("text") or "").startswith("Entschuldigung")
    assert s["arzt"] is None and s["frage"] == "arzt"
    assert sit["slotVorrat"] == [] and sit["offered"] == []
    assert s["nachname"] == "Rateike" and s["telefon"] == "01776004600"


def test_bestrittene_versicherung_wird_neu_erhoben():
    sit = _sit(frage="wunsch")
    r = _ohne_hintergrund(lambda: flow.zug(sit, "Nein, gesetzlich stimmt nicht mehr."))
    s = sit["sammler"]
    assert r is not None
    assert "privat oder gesetzlich" in (r.get("text") or "")
    assert s["versicherungOk"] is False and s["frage"] == "versicherung"
    assert s["telefon"] == "01776004600"


def test_mitgelieferte_korrektur_laeuft_ueber_die_normale_ernte():
    # "nicht X, sondern Y": der neue Wert ist schon da — nichts raeumen, und
    # er wird wie jede Nummer Ziffer fuer Ziffer rueckbestaetigt.
    sit = _sit()
    _ohne_hintergrund(lambda: flow.zug(
        sit, "Die Nummer ist nicht richtig, meine Nummer ist 0170 1234567."))
    s = sit["sammler"]
    assert s["telefonOffen"].endswith("1234567"), s["telefonOffen"]
    spuren = [x.get("w") for x in (sit.get("_spur") or [])]
    assert "einwand" not in spuren, spuren


def test_kette_laeuft_nach_der_korrektur_weiter():
    """Chef: "es muss jedoch sichergestellt sein, dass der Job […] nicht
    unterbrochen wird, bzw. dass sie immer wieder zurueckfindet." Nach der
    Korrektur wird der neue Wert genommen und die Buchung geht dort weiter, wo
    sie stand — nicht zurueck auf Los."""
    sit = _sit(frage="wunsch")
    _ohne_hintergrund(lambda: flow.zug(sit, "Nein, gesetzlich stimmt nicht mehr."))
    s = sit["sammler"]
    assert s["frage"] == "versicherung"
    r = _ohne_hintergrund(lambda: flow.zug(sit, "Privat."))
    text = (r or {}).get("text") or ""
    assert (s["versicherung"], s["versicherungOk"]) == ("privat", True)
    # Der neue Wert wird ausgesprochen quittiert …
    assert "privat" in text.lower(), text
    # … und die Kette steht wieder auf ihrer offenen Frage (hier: Wunschzeit).
    assert s["frage"] == "wunsch" and "vormittags" in text, (s["frage"], text)
    # Weder Name noch Nummer werden erneut verlangt.
    assert s["nachname"] == "Rateike" and s["telefon"] == "01776004600"


def test_offene_eigene_frage_bleibt_beim_bestehenden_zweig():
    # Auf "Stimmt die Nummer so?" urteilt der Ja/Nein-Zweig — nicht W-EINWAND.
    sit = _sit(frage="telefon_check")
    _ohne_hintergrund(lambda: flow.zug(sit, "Nein, die Nummer stimmt nicht."))
    spuren = [x.get("w") for x in (sit.get("_spur") or [])]
    assert "einwand" not in spuren, spuren


def test_verwaltung_bleibt_unberuehrt():
    # Absage/Verschieben haben ihre eigene Namens-Korrektur (W-NAMESKORREKTUR).
    sit = _sit(modus="absagen", frage="nachname")
    r = flow._einwand_zug(sit, "Nein, die Nummer stimmt nicht.", set())
    assert r is None


def test_notaus_off(monkeypatch):
    monkeypatch.setenv("EINWAND", "0")
    sit = _sit()
    assert flow._einwand_zug(sit, "Die Nummer ist falsch.", set()) is None
    assert sit["sammler"]["telefon"] == "01776004600"


def test_shadow_meldet_aber_aendert_nichts(monkeypatch):
    monkeypatch.setenv("EINWAND", "shadow")
    sit = _sit()
    assert flow._einwand_zug(sit, "Die Nummer ist falsch.", set()) is None
    assert sit["sammler"]["telefon"] == "01776004600"
    spuren = [x.get("w") for x in (sit.get("_spur") or [])]
    assert "einwand-shadow" in spuren, spuren
