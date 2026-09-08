"""Unbekannte Anrufer: Name und Nummer über lange Sprechpausen retten."""

from bianca import agent, buchstaben, flow, gehirn
from kern import hirn, task_router
from kern.tenants import laden


def _sit() -> dict:
    sit = {
        "id": "daten-pausen",
        "stimme": "Bianca",
        "tenant": laden("meddent"),
        "messages": [],
        "booking": {},
        "tools": [],
    }
    hirn.init(sit)
    gehirn.sammler(sit)
    return sit


def _bereit(sit: dict, *, frage: str) -> dict:
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "warSchonMal": False,
        "arzt": {
            "typ": "genannt",
            "calendarId": "cal-1",
            "calendarName": "Dr. Petsas",
        },
        "grund": "Kontrolluntersuchung",
        "motivId": "motiv-1",
        "motivName": "Kontrolluntersuchung",
        "wunsch": {},
        "vorname": "Theo",
        "nachname": "Zanis",
        "buchstabiert": False,
        "telefon": "",
        "telefonOffen": "",
        "telefonTeil": "",
        "telefonOk": False,
        "frage": frage,
    })
    return s


def test_einzelne_buchstabenfragmente_werden_eindeutig_erkannt():
    assert buchstaben.teil("T wie Theodor") == "t"
    assert buchstaben.teil("Z") == "z"
    assert buchstaben.teil("Anton") == "a"
    assert buchstaben.teil("Doppel L") == "ll"
    assert buchstaben.teil("Spend wie Zacharias.") == "z"
    assert buchstaben.teil("AVI Anton") == "a"
    assert buchstaben.teil("Ivi Ida") == "i"
    assert buchstaben.teil("SW Samuel fertig.") == "s"
    assert buchstaben.teil("TV Theodor") == "t"
    assert buchstaben.teil("Zwesacharias?") == "z"
    assert buchstaben.teil("NV Nordpol") == "n"
    assert buchstaben.teil("Envy Nordpol") == "n"
    assert buchstaben.teil("E wie Ida.") == "i"
    assert buchstaben.teil("Es wie Samuel fertig.") == "s"
    assert buchstaben.teil("N'Winopol") == "n"
    assert buchstaben.teil("Ich heiße Müller") == ""


def test_ein_eindeutiger_vorname_wird_nicht_zum_nachnamen():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "frage": "name"})
    gehirn.einsammeln(sit, "Haila")
    assert s["vorname"] == "Haila"
    assert not s["nachname"]
    assert s["geschlecht"] == "f"


def test_lange_pausen_zwischen_buchstaben_bauen_einen_namen():
    sit = _sit()
    s = _bereit(sit, frage="buchstabieren")
    teile = [
        "T wie Theodor",
        "Z wie Zacharias",
        "A wie Anton",
        "N wie Nordpol",
        "N wie Nordpol",
        "I wie Ida",
    ]
    for text in teile:
        s["frage"] = "buchstabieren"
        neu = gehirn.einsammeln(sit, text)
        assert "buchstabenTeil" in neu
        assert not s["buchstabiert"]
    # Der zuerst verstandene Name war sogar kürzer. Trotzdem wird nicht
    # vorzeitig nach dessen Länge abgeschlossen.
    assert s["nachname"] == "Zanis"
    s["frage"] = "buchstabieren"
    neu = gehirn.einsammeln(sit, "S wie Samuel, fertig.")
    assert "nachname" in neu
    assert s["nachname"] == "Tzannis"
    assert s["buchstabiert"] is True
    assert not s["buchstabenTeil"]


def test_gemischte_live_kette_verliert_keine_buchstaben_an_tafelwort():
    """Live 08.09.: „P A P A wie Anton G R“ wurde nur als A gespeichert."""
    sit = _sit()
    s = _bereit(sit, frage="buchstabieren")
    s["nachname"] = "Papagrigorius"
    gehirn.einsammeln(sit, "P A P A wie Anton G R")
    assert s["buchstabenTeil"] == "papagr"
    gehirn.einsammeln(sit, "I, G, O, R, I, O, U, S")
    assert s["buchstabenTeil"] == "papagrigorious"
    neu = gehirn.einsammeln(sit, "Fertig")
    assert "nachname" in neu
    assert s["nachname"] == "Papagrigorious"
    assert s["buchstabiert"] is True


def test_echte_whisper_serien_ergeben_trotz_verhörern_tzannis():
    serien = (
        (
            "T wie Theodor.", "Spend wie Zacharias.", "AVI Anton",
            "N wie Nordpol.", "Wie Nordpol?", "Ivi Ida",
            "SW Samuel fertig.",
        ),
        (
            "TV Theodor", "Zwas wie Zacharias?", "Abi Anton",
            "N'Winopol", "Wie Nordpol?", "Evie Ida",
            "Swiss Samuel fertig.",
        ),
        (
            "T wie Theodor", "Zwiesacher Rias", "AVI Anton",
            "N wie Nordpol", "Envy Nordpol", "IWI-IDA",
            "Zwiesammeel fertig.",
        ),
    )
    for serie in serien:
        sit = _sit()
        s = _bereit(sit, frage="buchstabieren")
        for text in serie:
            s["frage"] = "buchstabieren"
            gehirn.einsammeln(sit, text)
        assert s["nachname"] == "Tzannis", (serie, s["nachname"])
        assert s["buchstabiert"] is True


def test_buchstabier_unvermögen_fällt_auf_langsames_nachsprechen_zurück():
    sit = _sit()
    s = _bereit(sit, frage="buchstabieren")
    neu = gehirn.einsammeln(sit, "Ich kann leider nicht buchstabieren.")
    assert "buchstabierHilfe" in neu
    fid, frage = gehirn.naechste_frage(sit)
    assert fid == "buchstabieren"
    assert "langsam am Stück" in frage
    s["frage"] = fid
    neu2 = gehirn.einsammeln(sit, "Mattavatta")
    assert "nachname" in neu2
    assert s["nachname"] == "Mattavatta"
    assert s["buchstabiert"] is True


def test_einzelziffern_mit_turnpausen_werden_nicht_abgeschnitten():
    sit = _sit()
    s = _bereit(sit, frage="telefon")
    for wort in (
        "null", "eins", "sieben", "sieben", "sechs",
        "null", "null", "vier", "sechs", "null",
    ):
        s["frage"] = "telefon"
        gehirn.einsammeln(sit, wort)
    assert s["telefonTeil"] == "0177600460"
    assert not s["telefonOffen"]
    s["frage"] = "telefon"
    gehirn.einsammeln(sit, "null")
    assert s["telefonOffen"] == "01776004600"
    assert not s["telefonTeil"]


def test_nummerngruppen_über_mehrere_turns_bleiben_in_reihenfolge():
    sit = _sit()
    s = _bereit(sit, frage="telefon")
    for gruppe in ("null eins sieben sieben", "sechs null null", "vier sechs"):
        s["frage"] = "telefon"
        gehirn.einsammeln(sit, gruppe)
        assert not s["telefonOffen"]
    s["frage"] = "telefon"
    gehirn.einsammeln(sit, "null null")
    assert s["telefonOffen"] == "01776004600"
    assert not s["telefonTeil"]


def test_kürzere_fragmentnummer_wird_nur_mit_fertig_abgeschlossen():
    sit = _sit()
    s = _bereit(sit, frage="telefon")
    for gruppe in ("null drei null", "eins zwei drei", "vier fünf", "sechs sieben"):
        s["frage"] = "telefon"
        gehirn.einsammeln(sit, gruppe)
    assert s["telefonTeil"] == "0301234567"
    assert not s["telefonOffen"]
    s["frage"] = "telefon"
    gehirn.einsammeln(sit, "fertig")
    assert s["telefonOffen"] == "0301234567"
    assert not s["telefonTeil"]


def test_teilantworten_bleiben_im_diktatmodus():
    sit = _sit()
    s = _bereit(sit, frage="buchstabieren")
    gehirn.einsammeln(sit, "T wie Theodor")
    fid, frage = gehirn.naechste_frage(sit)
    assert fid == "buchstabieren"
    assert "restlichen Buchstaben" in frage
    assert gehirn.stille_ms({"frage": fid}) == 1500

    sit = _sit()
    s = _bereit(sit, frage="telefon")
    s["buchstabiert"] = True
    s["frage"] = "telefon"
    gehirn.einsammeln(sit, "null eins sieben sieben")
    fid2, frage2 = gehirn.naechste_frage(sit)
    assert fid2 == "telefon"
    assert "restlichen Ziffern" in frage2
    assert gehirn.stille_ms({"frage": fid2}) == 1500


def test_fragmente_sind_stille_wartezuege_statt_zwischenansagen():
    sit = _sit()
    s = _bereit(sit, frage="buchstabieren")
    s["nachname"] = "Papagrigorius"
    z1 = flow.zug(sit, "P A P A wie Anton G R")
    assert z1 and z1.get("warte") is True
    assert z1.get("text") == ""
    assert s["buchstabenTeil"] == "papagr"

    s["buchstabiert"] = True
    s["frage"] = "telefon"
    z2 = flow.zug(sit, "null")
    assert z2 and z2.get("warte") is True
    assert z2.get("text") == ""
    assert s["telefonTeil"] == "0"


def test_agent_ruft_bei_nummernfragment_keine_talk_schicht():
    sit = _sit()
    sit["messages"] = [
        {"role": "system", "content": "test"},
        {"role": "assistant", "content": "Wie lautet Ihre Handynummer?"},
    ]
    s = _bereit(sit, frage="telefon")
    s["buchstabiert"] = True
    def niemals_llm(*_a, **_k):
        raise AssertionError("Ein Diktatfragment darf nie an die Talk-Schicht")

    echt_anstossen = flow.hintergrund.anstossen
    echt_chat = agent.llm.chat
    echt_stream = agent.llm.chat_stream
    flow.hintergrund.anstossen = lambda _sit: None
    agent.llm.chat = niemals_llm
    agent.llm.chat_stream = niemals_llm
    try:
        out = agent.user_turn(sit, "Null")
        assert out.get("warte") is True
        assert out.get("text") == ""
        assert s["telefonTeil"] == "0"
    finally:
        flow.hintergrund.anstossen = echt_anstossen
        agent.llm.chat = echt_chat
        agent.llm.chat_stream = echt_stream


def test_nachname_wird_nicht_nach_vor_und_nachname_erneut_gefragt():
    sit = _sit()
    s = _bereit(sit, frage="")
    s.update({"vorname": "", "nachname": "", "buchstabiert": False})
    fid, frage = gehirn.naechste_frage(sit)
    assert fid == "buchstabieren"
    assert "Nachname" in frage
    assert "Vor- und Nachname" not in frage

    s["frage"] = fid
    neu = gehirn.einsammeln(sit, "Papagrigorius")
    assert "nachname" in neu
    assert s["buchstabiert"] is True
    fid2, frage2 = gehirn.naechste_frage(sit)
    assert fid2 == "vorname"
    assert "Vorname" in frage2

    s["frage"] = fid2
    gehirn.einsammeln(sit, "Efthimios")
    fid3, frage3 = gehirn.naechste_frage(sit)
    assert fid3 == "telefon"
    assert "Nachname" not in frage3


def test_voller_neupatientenfluss_über_fragmentierte_daten():
    sit = _sit()
    echt = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda _sit: None
    try:
        assert task_router.anwenden(
            sit,
            {"operation": "buchen", "reason": "Kontrolltermin"},
            original="Ich möchte zur Kontrolle.",
        )
        z1 = flow.zug(sit, "Ich möchte zur Kontrolle.")
        assert z1 and "schon einmal" in z1["text"]
        z2 = flow.zug(sit, "Nein.")
        assert z2 and "Zahnreinigung" in z2["text"]
        z3 = flow.zug(sit, "Nein, danke.")
        assert z3 and "Behandler" in z3["text"]
        z4 = flow.zug(sit, "Bei Doktor Petsas.")
        assert z4 and "Wann passt" in z4["text"]
        z5 = flow.zug(sit, "Vormittags bitte.")
        assert z5 and "Nachname" in z5["text"]
        assert "Vor- und Nachname" not in z5["text"]

        for text in (
            "T wie Theodor",
            "Z wie Zacharias",
            "A wie Anton",
            "N wie Nordpol",
            "N wie Nordpol",
            "I wie Ida",
        ):
            z = flow.zug(sit, text)
            assert z and z.get("warte") is True and not z["text"]
        z7 = flow.zug(sit, "S wie Samuel, fertig.")
        assert z7 and "Vorname" in z7["text"]
        z7b = flow.zug(sit, "Theo")
        assert z7b and "Handynummer" in z7b["text"]

        for text in (
            "null eins sieben sieben",
            "sechs null null",
            "vier sechs",
        ):
            z = flow.zug(sit, text)
            assert z and z.get("warte") is True and not z["text"]
        z8 = flow.zug(sit, "null null")
        assert z8 and "wiederhole" in z8["text"].lower()
        z9 = flow.zug(sit, "Ja, stimmt.")
        assert z9 and ("privat" in z9["text"].lower() or "gesetzlich" in z9["text"].lower())

        s = gehirn.sammler(sit)
        assert s["vorname"] == "Theo"
        assert s["nachname"] == "Tzannis"
        assert s["telefon"] == "01776004600"
        assert s["telefonOk"] is True
    finally:
        flow.hintergrund.anstossen = echt
