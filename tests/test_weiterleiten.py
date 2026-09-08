"""Weiterleitungs-Platzhalter (Kirri/Zaluma): Erkennung, Ablauf, Jingle-Event.

Laeuft ohne Netz: die Akten-Recherche (letzter_behandler) wird gestummt,
der Mandant kommt aus tenants/meddent.json (lokale Datei).
"""

from bianca import flow, gehirn, weiterleiten
from kern.tenants import laden


def _sit() -> dict:
    return {"tenant": laden("meddent"), "messages": [{"role": "system", "content": "x"}]}


# --- (a) Erkennung ----------------------------------------------------------

def test_erkennung_verbinden_saetze():
    for satz in [
        "Verbinden Sie mich mit einem Mitarbeiter",
        "Kann ich mit einem Menschen sprechen?",
        "Stellen Sie mich durch",
        "Ich möchte jemanden vom Empfang",
        "Gibt es da kein Personal?",
        "Kann ich mit Doktor Petsas sprechen?",
        "Können Sie mich bitte weiterleiten?",
        "Ich will mit einem echten Menschen reden.",
        "Ich möchte mich direkt zu Doktor Petsas verbinden lassen.",
        "Kann ich mit der Buchhaltung sprechen?",
        "Verbinden Sie mich mit der Patientenannahme.",
    ]:
        assert weiterleiten.erkannt(satz), satz


def test_live_saetze_29_08_verbunden_formen():
    """Live 29.08.2026 08:44: 'Könnte ich bitte mit Doktor Petzers verbunden?'
    und 'Ich möchte verbunden.' rutschten an der Erkennung vorbei — das LLM
    erfand eine Ablehnung ('Hier spricht man nicht mit den Ärzten am
    Telefon'). Um 07:15 halluzinierte es sogar ein Fake-Verbinden ohne
    Jingle. Diese Formen MUESSEN deterministisch erkannt werden."""
    for satz in [
        "Könnte ich bitte mit Doktor Petzers verbunden?",
        "Ich möchte verbunden.",
        "denn ich möchte verbunden werden.",
        "Ich würde gerne verbunden werden.",
        "Ich will bitte verbunden werden.",
    ]:
        assert weiterleiten.erkannt(satz), satz


def test_live_saetze_31_08_imperativ_und_verhoerte_namen():
    """Live 31.08.2026 14:11: 'Verbinde mich mit Dr. Petzos jetzt.' fiel
    durch ALLE Erkennungs-Formen (nackter Imperativ ohne 'Sie', 'verbinde'
    stand nicht in _SPRECH_VERB_RE) — das LLM fragte zum x-ten Mal 'Zu
    welchem unserer Ärzte darf ich Sie verbinden?', der Anrufer legte auf.
    Der ganze Zug muss deterministisch bis zum Jingle laufen, auch mit
    verhörtem Namen (Petzos/Petzl -> Petsas)."""
    for satz in [
        "Verbinde mich mit Dr. Petzos jetzt.",
        "Verbinde mich bitte mit Doktor Petsas.",
        "Verbinde uns mit der Praxis.",
    ]:
        assert weiterleiten.erkannt(satz), satz
    for satz in [
        "Verbinde mich mit Dr. Petzos jetzt.",
        "Ich möchte bitte mit Dr. Petzl sprechen.",
    ]:
        sit = _sit()
        events: list[str] = []
        z = flow.zug(sit, satz, events.append)
        assert z and z.get("transfer", {}).get("nummer") == "+4921130293035", satz
        assert z.get("hangup") and weiterleiten.JINGLE_EVENT in events, satz
        s = gehirn.sammler(sit)
        assert (s["arzt"] or {}).get("calendarName") == "Dr. Petsas", satz


def test_herr_dr_patrikis_sprechen_ohne_mit_verbindet():
    """Live Schnorbus 08.09.: ‚Ich würde gerne Herr Dr. Patrikis sprechen.‘
    ohne ‚mit‘ — muss direkt durchstellen, nicht nach dem Arzt fragen."""
    sit = _sit()
    events: list[str] = []
    z = flow.zug(sit, "Ich würde gerne Herr Dr. Patrikis sprechen.", events.append)
    assert z and z.get("transfer", {}).get("nummer") == "+4921130293034"
    assert z.get("hangup") and weiterleiten.JINGLE_EVENT in events


def test_ja_bitte_verbinden_nach_namensnennung():
    """Live Schnorbus: Name fiel, Maschine fragte nochmal, dann
    ‚Ja bitte verbinden‘ — LLM sagte ‚ich verbinde Sie‘ ohne Transfer."""
    sit = _sit()
    sit["messages"].append({"role": "user", "content": "Herr Dr. Patrikis"})
    sit["weiterleiten"] = {"frage": "arzt", "leer": 1}
    events: list[str] = []
    z = weiterleiten.zug(sit, "Ja bitte verbinden.", events.append)
    assert z and z.get("transfer", {}).get("nummer") == "+4921130293034"
    assert z.get("hangup") and weiterleiten.JINGLE_EVENT in events
    assert weiterleiten.erkannt("Ja bitte verbinden.")
    assert weiterleiten.erkannt("Ja, können Sie mich verbinden?")


def test_kosten_verbunden_ist_kein_weiterleitungswunsch():
    """Preis-/Sachfragen mit 'verbunden' bleiben beim LLM (keine Doktor-Wörter,
    kein 'ich möchte verbunden')."""
    for satz in [
        "Ist das mit Kosten verbunden?",
        "Ist die Behandlung mit Schmerzen verbunden?",
        "Ich möchte wissen, ob das mit Kosten verbunden ist.",
    ]:
        assert not weiterleiten.erkannt(satz), satz
        assert weiterleiten.zug(_sit(), satz) is None, satz


# --- (e) Buchungssaetze loesen den Zweig NICHT aus ---------------------------

def test_buchungssaetze_loesen_nicht_aus():
    for satz in [
        "Ich hätte gern einen Termin",
        "Ich möchte meinen Termin verschieben.",
        "Ich war bei Doktor Patrikis",
        "Eine Kontrolle bitte.",
        "Wann ist mein Termin nochmal?",
        "Ich brauche einen Termin zur ZE Besprechung.",
    ]:
        assert not weiterleiten.erkannt(satz), satz
    # Voller Fluss: normale Buchung landet weiter in der 'schonmal'-Frage.
    echt_anstossen = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    try:
        sit = _sit()
        z = flow.zug(sit, "Ich hätte gern einen Termin")
        assert z and "schon" in z["text"].lower()
        assert not (sit.get("weiterleiten") or {})
    finally:
        flow.hintergrund.anstossen = echt_anstossen


# --- (b) Namentlich genannter Arzt: DIREKT verbinden, ohne Ansage ------------

def test_namentlich_genannt_verbindet_direkt_ohne_personalfrei():
    """'Kann ich bitte mit Doktor Patrikis sprechen?' (Chef 27.08., zweite
    Fassung): KEINE Personalfrei-Ansage, KEINE Rueckfrage. Mit eingerichteter
    Weiterleitung (meddent.json): Jingle + transfer, kein Platzhalter."""
    sit = _sit()
    events: list[str] = []
    z = flow.zug(sit, "Kann ich bitte mit Doktor Patrikis sprechen?", events.append)
    assert z and z.get("transfer") == {
        "nummer": "+4921130293034", "name": "Dr. Patrikis",
    }
    assert z.get("hangup") and weiterleiten.JINGLE_EVENT in events
    assert weiterleiten.WAHRHEIT not in (z.get("text") or "")
    assert not (sit.get("weiterleiten") or {})  # Anliegen bedient
    s = gehirn.sammler(sit)
    assert (s["arzt"] or {}).get("calendarName") == "Dr. Patrikis"


def test_petzers_hoerfehler_verbindet_zu_petsas():
    """Der Chef-Satz vom 29.08. wortgleich: STT-Hörfehler 'Petzers' läuft
    über die Klang-Faltung in arzt.deute auf Doktor Petsas — echte
    Weiterleitung (meddent Forwardings)."""
    sit = _sit()
    events: list[str] = []
    z = flow.zug(sit, "Könnte ich bitte mit Doktor Petzers verbunden?", events.append)
    assert z and z.get("transfer", {}).get("nummer") == "+4921130293035"
    assert z.get("hangup") and weiterleiten.JINGLE_EVENT in events
    s = gehirn.sammler(sit)
    assert (s["arzt"] or {}).get("calendarName") == "Dr. Petsas"


def test_verbunden_ohne_namen_fragt_nach_arzt():
    """'Ich möchte verbunden.' (Chef-Satz 29.08.): kein Name, kein
    Mitarbeiter-Wort -> nur die Arzt-Frage, danach verbindet der Name."""
    sit = _sit()
    z = flow.zug(sit, "Ich möchte verbunden.")
    assert z and weiterleiten.WAHRHEIT not in z["text"]
    assert "zu welchem unserer" in z["text"].lower()
    events: list[str] = []
    z2 = flow.zug(sit, "Mit Doktor Petsas.", events.append)
    assert z2 and z2.get("transfer", {}).get("nummer") == "+4921130293035"
    assert z2.get("hangup") and weiterleiten.JINGLE_EVENT in events


def test_herr_petsas_ohne_doktor_titel_verbindet():
    """Name + Sprechverb ohne Doktor-Titel: 'Kann ich Herrn Petsas
    sprechen?' zaehlt als Weiterleitungs-Wunsch (Namens-Weg)."""
    sit = _sit()
    events: list[str] = []
    z = flow.zug(sit, "Kann ich Herrn Petsas sprechen?", events.append)
    assert z and z.get("transfer", {}).get("nummer") == "+4921130293035"
    assert z.get("hangup") and weiterleiten.JINGLE_EVENT in events
    s = gehirn.sammler(sit)
    assert (s["arzt"] or {}).get("calendarId") == "zex5bmv5jfIHWVW6zHbg"


def test_arzt_ans_telefon_verbindet():
    sit = _sit()
    events: list[str] = []
    z = flow.zug(sit, "Holen Sie mir bitte Doktor Nikolaou ans Telefon.", events.append)
    # Nikolaou hat keine Forwarding-Nummer → ehrlicher Platzhalter
    assert z and weiterleiten.ANSAGE_PLATZHALTER in z["text"]
    assert weiterleiten.JINGLE_EVENT not in events


def test_chef_ans_telefon_bekommt_wahrheit_und_angebot():
    sit = _sit()
    z = flow.zug(sit, "Holen Sie mir mal den Chef ans Telefon.")
    assert z and weiterleiten.WAHRHEIT in z["text"]


def test_llm_rueckfrage_name_allein_verbindet():
    """Prompt-Leitplanke WEITERLEITEN: hat das LLM 'Zu welchem unserer Ärzte
    darf ich Sie verbinden?' gefragt (Maschine war nicht bewaffnet), zaehlt
    der blosse Behandler-Name im naechsten Zug als Zielangabe."""
    sit = _sit()
    sit["messages"].append({"role": "assistant",
                            "content": "Zu welchem unserer Ärzte darf ich Sie verbinden?"})
    events: list[str] = []
    z = weiterleiten.zug(sit, "Doktor Nikolaou, bitte.", events.append)
    assert z and weiterleiten.ANSAGE_PLATZHALTER in z["text"]
    assert not z.get("hangup") and weiterleiten.JINGLE_EVENT not in events


def test_name_allein_ohne_rueckfrage_verbindet_nicht():
    """Ohne Verb und ohne Verbinde-Rueckfrage bleibt der blosse Name bei den
    anderen Fluessen ('Bei Doktor Petsas' = Buchungs-Antwort)."""
    sit = _sit()
    sit["messages"].append({"role": "assistant",
                            "content": "Wissen Sie noch, bei welchem Behandler Sie zuletzt waren?"})
    assert weiterleiten.zug(sit, "Bei Doktor Petsas.") is None


def test_verbinden_lassen_mit_namen_verbindet_direkt():
    sit = _sit()
    events: list[str] = []
    z = flow.zug(sit, "Ich möchte mich direkt zu Doktor Petsas verbinden lassen.", events.append)
    assert z and z.get("transfer", {}).get("nummer") == "+4921130293035"
    assert z.get("hangup") and weiterleiten.JINGLE_EVENT in events
    assert weiterleiten.WAHRHEIT not in (z.get("text") or "")
    s = gehirn.sammler(sit)
    assert (s["arzt"] or {}).get("calendarId") == "zex5bmv5jfIHWVW6zHbg"


# --- (b2) Mitarbeiter-/Abteilungs-Anfrage: Wahrheit + Arzt-Angebot ------------

def test_mitarbeiter_mit_bekanntem_arzt_wahrheit_und_angebot():
    sit = _sit()
    s = gehirn.sammler(sit)
    s["arzt"] = {"typ": "genannt", "calendarId": "zex5bmv5jfIHWVW6zHbg", "calendarName": "Dr. Petsas"}
    z = flow.zug(sit, "Verbinden Sie mich bitte mit einem Mitarbeiter.")
    assert z, "Weiterleitungs-Zweig muss deterministisch antworten"
    t = z["text"]
    assert weiterleiten.WAHRHEIT in t
    assert "zu Doktor Petsas" in t and "weiterleiten" in t
    assert "bei wem" not in t.lower()  # NICHT nach dem Behandler fragen


def test_buchhaltung_bekommt_wahrheit_und_arztfrage():
    """Abteilungs-Wunsch (Buchhaltung/Rezeption/Patientenannahme) ohne
    bekannten Arzt: Wahrheit + Angebot, zu einem Arzt zu verbinden."""
    sit = _sit()
    z = flow.zug(sit, "Kann ich mit der Buchhaltung sprechen?")
    assert z and weiterleiten.WAHRHEIT in z["text"]
    assert "Ärzte" in z["text"] and "durchstellen" in z["text"]
    # Arzt genannt -> direkt verbinden, keine weitere Rueckfrage.
    events: list[str] = []
    z2 = flow.zug(sit, "Dann zu Doktor Patrikis, bitte.", events.append)
    assert z2 and z2.get("transfer", {}).get("nummer") == "+4921130293034"
    assert z2.get("hangup") and weiterleiten.JINGLE_EVENT in events


def test_akte_liefert_letzten_behandler():
    """Kein Arzt im Gespraech, aber Patientenakte da: letzter_behandler
    liefert das Ziel — KEINE Rueckfrage (Chef: doppelte Fragen verboten)."""
    echt = weiterleiten.arztmod.letzter_behandler
    weiterleiten.arztmod.letzter_behandler = lambda t, pid: {
        "ok": True, "calendarId": "GVyoyXqCYof1QrGaNNnG",
        "calendarName": "Dr. Nikolaou", "doctorName": "Dr. Nikolaou", "war": True,
    }
    try:
        sit = _sit()
        s = gehirn.sammler(sit)
        s["patientId"] = "pat-1"
        z = flow.zug(sit, "Gibt es da kein Personal?")
        assert z and "zu Doktor Nikolaou" in z["text"]
        assert weiterleiten.WAHRHEIT in z["text"]  # Mitarbeiter-Frage -> Wahrheit
        assert "bei wem" not in z["text"].lower()
    finally:
        weiterleiten.arztmod.letzter_behandler = echt


# --- (c) Verbinde-Wunsch ohne Namen und ohne Mitarbeiter-Wort ------------------

def test_weiterleiten_ohne_namen_fragt_nur_nach_arzt():
    """'Können Sie mich bitte weiterleiten?': kein Mitarbeiter-Wort ->
    KEINE Personalfrei-Ansage, nur die Arzt-Frage."""
    sit = _sit()
    z = flow.zug(sit, "Können Sie mich bitte weiterleiten?")
    assert z and weiterleiten.WAHRHEIT not in z["text"]
    assert "zu welchem unserer" in z["text"].lower() and "Ärzte" in z["text"]
    # Antwort mit Behandler-Namen (Fuzzy ueber arzt.deute) -> direkt verbinden.
    events: list[str] = []
    z2 = flow.zug(sit, "Bei Doktor Patrikis.", events.append)
    assert z2 and z2.get("transfer", {}).get("nummer") == "+4921130293034"
    assert z2.get("hangup") and weiterleiten.JINGLE_EVENT in events


def test_infofrage_verbindet_nicht():
    """Live 29.08.2026: 'Nein, gibt es auch Doktor Patrikis ist bei euch?'
    (Auskunftsfrage auf die Arzt-Rueckfrage) wurde als Zielangabe gedeutet —
    Bianca 'verband' mitten in der Frage. Info-Fragen gehen ans LLM, eine
    echte Zielangabe danach verbindet weiter."""
    sit = _sit()
    sit["weiterleiten"] = {"frage": "arzt"}
    assert weiterleiten.zug(sit, "Nein, gibt es auch Doktor Patrikis ist bei euch?") is None
    assert weiterleiten.zug(sit, "Welche Ärzte haben Sie denn?") is None
    events: list[str] = []
    z = weiterleiten.zug(sit, "Dann zu Doktor Patrikis, bitte.", events.append)
    assert z and z.get("transfer", {}).get("nummer") == "+4921130293034"
    assert z.get("hangup") and weiterleiten.JINGLE_EVENT in events


def test_infofrage_beim_angebot_verbindet_nicht():
    sit = _sit()
    sit["weiterleiten"] = {"frage": "anbieten",
                           "ziel": {"calendarId": "zex5bmv5jfIHWVW6zHbg",
                                    "calendarName": "Dr. Petsas"}}
    assert weiterleiten.zug(sit, "Gibt es auch Doktor Patrikis bei Ihnen?") is None
    events: list[str] = []
    z = weiterleiten.zug(sit, "Ja, gerne.", events.append)
    assert z and z.get("transfer", {}).get("nummer") == "+4921130293035"
    assert z.get("hangup") and weiterleiten.JINGLE_EVENT in events


def test_mensch_ohne_arzt_fragt_nach_arzt():
    sit = _sit()
    z = flow.zug(sit, "Kann ich mit einem Menschen sprechen?")
    assert z and weiterleiten.WAHRHEIT in z["text"]
    assert "Zu wem darf ich Sie durchstellen?" in z["text"]


# --- (d) Ja -> mit Einrichtung: Jingle + transfer ------------------------------

def test_ja_mit_einrichtung_echte_weiterleitung():
    sit = _sit()
    s = gehirn.sammler(sit)
    s["arzt"] = {"typ": "genannt", "calendarId": "zex5bmv5jfIHWVW6zHbg", "calendarName": "Dr. Petsas"}
    events: list[str] = []
    z1 = flow.zug(sit, "Stellen Sie mich durch.", events.append)
    assert z1 and "weiterleiten" in z1["text"]
    # Kein Mitarbeiter-Wort im Satz -> keine Personalfrei-Ansage.
    assert weiterleiten.WAHRHEIT not in z1["text"]
    z2 = flow.zug(sit, "Ja, bitte.", events.append)
    assert z2 and z2.get("transfer", {}).get("nummer") == "+4921130293035"
    assert z2.get("hangup") and weiterleiten.JINGLE_EVENT in events
    assert not (sit.get("weiterleiten") or {})


def test_nein_bricht_sauber_ab():
    sit = _sit()
    s = gehirn.sammler(sit)
    s["arzt"] = {"typ": "genannt", "calendarId": "zex5bmv5jfIHWVW6zHbg", "calendarName": "Dr. Petsas"}
    flow.zug(sit, "Ich möchte jemanden vom Empfang.")
    z = flow.zug(sit, "Nein, lassen Sie mal.")
    assert z and "sonst noch" in z["text"].lower()
    assert not (sit.get("weiterleiten") or {})


# --- (f) W-VERBINDEN-ECHT: eingerichtete Client-Weiterleitung -----------------

_WL_KONFIG = [
    {"name": "Dr. Petsas", "nummer": "+49211111111", "hinweis": ""},
    {"name": "Praxishandy", "nummer": "+49222222222",
     "hinweis": "Weiterleitung zu Doktor Nikolaou bei dringenden Faellen"},
]


def _sit_mit_weiterleitung() -> dict:
    sit = _sit()
    sit["tenant"] = dict(sit["tenant"])
    sit["tenant"]["weiterleitungen"] = [dict(e) for e in _WL_KONFIG]
    return sit


def test_weiterleitungs_ziel_matcht_behandler_ueber_name_und_hinweis():
    t = {"weiterleitungen": [dict(e) for e in _WL_KONFIG]}
    z1 = weiterleiten.weiterleitungs_ziel(t, {"calendarName": "Dr. Petsas"})
    assert z1 == {"name": "Dr. Petsas", "nummer": "+49211111111"}
    # Nikolaou steht nur im HINWEIS des Praxishandys — zaehlt trotzdem.
    z2 = weiterleiten.weiterleitungs_ziel(t, {"calendarName": "Dr. Nikolaou"})
    assert z2 == {"name": "Praxishandy", "nummer": "+49222222222"}
    # Kein Treffer bei MEHREREN Eintraegen: nichts raten.
    assert weiterleiten.weiterleitungs_ziel(t, {"calendarName": "Dr. Patrikis"}) == {}


def test_weiterleitungs_ziel_einzelner_eintrag_gilt_fuer_alle():
    t = {"weiterleitungen": [{"name": "Praxis", "nummer": "+49333", "hinweis": ""}]}
    assert weiterleiten.weiterleitungs_ziel(t, {"calendarName": "Dr. Patrikis"}) == {
        "name": "Praxis", "nummer": "+49333"}
    assert weiterleiten.weiterleitungs_ziel(t, {"calendarName": ""}) == {
        "name": "Praxis", "nummer": "+49333"}


def test_weiterleitungs_ziel_ohne_konfig_leer():
    assert weiterleiten.weiterleitungs_ziel({}, {"calendarName": "Dr. Petsas"}) == {}
    assert weiterleiten.weiterleitungs_ziel({"weiterleitungen": []}, {}) == {}
    # Eintraege ohne Nummer zaehlen nicht.
    t = {"weiterleitungen": [{"name": "Dr. Petsas", "nummer": ""}]}
    assert weiterleiten.weiterleitungs_ziel(t, {"calendarName": "Dr. Petsas"}) == {}


def test_echte_weiterleitung_traegt_transfer_und_bleibt_stumm():
    """W-VERBINDEN-ECHT (31.08.2026): hat der Client eine Weiterleitung
    eingerichtet, kommt KEIN Kirri-Zettel — die Antwort traegt transfer
    ({nummer, name}), Ansage + Jingle laufen als Filler, danach waehlt der
    Asterisk-Dialplan wirklich raus."""
    sit = _sit_mit_weiterleitung()
    events: list[str] = []
    z = flow.zug(sit, "Kann ich bitte mit Doktor Petsas sprechen?", events.append)
    assert z is not None
    assert z.get("transfer") == {"nummer": "+49211111111", "name": "Dr. Petsas"}
    assert z.get("hangup") is True
    assert z["text"] == ""  # nach dem Jingle klingelt es — kein Zettel
    assert weiterleiten.JINGLE_EVENT in events
    sag = [e for e in events if e.startswith("sag:")]
    assert sag and "Verbindung" in sag[0]
    assert sit["weiterleitungZiel"] == {"name": "Dr. Petsas", "nummer": "+49211111111"}


def test_ohne_passendes_ziel_bleibt_platzhalter():
    """Mehrere Eintraege, keiner passt zum gewuenschten Behandler:
    NICHT raten — der Platzhalter-Weg (ehrliche Ansage) bleibt."""
    sit = _sit_mit_weiterleitung()
    events: list[str] = []
    z = flow.zug(sit, "Kann ich bitte mit Doktor Patrikis sprechen?", events.append)
    assert z is not None and weiterleiten.ANSAGE_PLATZHALTER in z["text"]
    assert "transfer" not in z
    assert not z.get("hangup")


def test_agent_reicht_transfer_durch_ohne_llm():
    """Live erlebt 31.08.2026 (erste Probe): das Transfer-Reply traegt
    text="" — agent.user_turn wertete das als 'Maschine schweigt' und das
    LLM uebernahm ('Zu welchem unserer Ärzte...'), die Weiterleitung fiel
    weg. Ein Reply mit transfer/hangup ZAEHLT als Maschinen-Zug und das
    transfer-Feld erreicht den Dienst. (Ohne pytest-Fixture gestubbt —
    lauf_bianca ruft Testfunktionen argumentlos auf.)"""
    from bianca import agent
    from kern import llm

    def _knall(*a, **k):
        raise AssertionError("LLM darf beim Transfer-Reply nicht uebernehmen")

    echt_chat, echt_stream = llm.chat, llm.chat_stream
    llm.chat = _knall
    llm.chat_stream = _knall
    try:
        sit = _sit_mit_weiterleitung()
        aus = agent.user_turn(sit, "Ich möchte bitte mit Doktor Petsas sprechen.")
        assert aus.get("transfer") == {"nummer": "+49211111111", "name": "Dr. Petsas"}
        assert aus.get("hangup") is True
        assert aus["text"] == ""
    finally:
        llm.chat = echt_chat
        llm.chat_stream = echt_stream


def test_dienst_json_antwort_reicht_transfer_bis_bruecke():
    """Live 06.09.2026: agent hatte transfer, json_antwort liess es fallen —
    Bruecke sah nur hangup → Jingle, CURL leer, Auflegen ohne Dial."""
    from kern.dienst import Dienst

    sit = _sit_mit_weiterleitung()
    d = Dienst(name="test", start_fn=lambda s: {},
               turn_fn=lambda s, t, **k: {
                   "text": "",
                   "hangup": True,
                   "transfer": {"nummer": "+4921130293035", "name": "Dr. Petsas"},
               })
    # stimme stubben — leerer Text braucht kein TTS
    d.stimme = lambda text, karte=None: ("", 0.0)  # type: ignore
    d.stimme_stream = lambda text, karte=None: ("", 0.0)  # type: ignore
    aus = d.json_antwort(sit, art="listen", text_in="Mit Doktor Petsas verbinden.")
    assert aus.get("hangup") is True
    assert aus.get("transfer") == {
        "nummer": "+4921130293035", "name": "Dr. Petsas",
    }


def test_meddent_mit_weiterleitung_verbindet_echt():
    """meddent.json traegt die Portal-Forwardings (Petsas/Patrikis) — echte
    Weiterleitung mit transfer, nicht nur Platzhalter (Live 06.09.2026)."""
    sit = _sit()
    events: list[str] = []
    z = flow.zug(sit, "Kann ich bitte mit Doktor Petsas sprechen?", events.append)
    assert z is not None and z.get("transfer") == {
        "nummer": "+4921130293035", "name": "Dr. Petsas",
    }
    assert z.get("hangup") is True
    assert weiterleiten.JINGLE_EVENT in events


def test_live_leitung_check_petsas_ist_kein_transfer():
    """Live 08.09.2026 01:44: 'Hallo, Petsas mein Name. Bin ich mit der
    Praxis Dr. Petsas verbunden?' hat Jingle + echte Weiterleitung
    ausgelöst — Name Petsas plus Verb 'verbunden' auf dem Namens-Weg.
    Das ist eine Leitungs-Statusfrage, kein Durchstellen."""
    satz = "Hallo, Petsas mein Name. Bin ich mit der Praxis Dr. Petsas verbunden?"
    assert not weiterleiten.erkannt(satz)
    assert not weiterleiten.erkannt("Bin ich mit der Praxis Dr. Petsas verbunden?")
    assert not weiterleiten.erkannt("Spreche ich mit der Praxis?")
    assert not weiterleiten.erkannt("Habe ich die richtige Praxis erreicht?")
    # Echte Verbinde-Wünsche bleiben Transfer.
    assert weiterleiten.erkannt("Könnte ich bitte mit Doktor Petsas verbunden?")
    assert weiterleiten.erkannt("Verbinde uns mit der Praxis.")
    sit = _sit()
    events: list[str] = []
    z = flow.zug(sit, satz, events.append)
    assert z and not z.get("transfer") and not z.get("hangup"), z
    assert weiterleiten.JINGLE_EVENT not in events
    assert "richtig verbunden" in (z.get("text") or "").lower()


def test_implantatbesprechung_ist_kein_weiterleiten():
    """'Implantatbesprechung' darf weder Intent-ERREICHEN noch
    weiterleiten.erkannt triggern (sprech\\w*-Bug, Live 06.09.2026)."""
    from kern import intent
    assert not weiterleiten.erkannt("Ich brauche eine Implantatbesprechung.")
    assert not weiterleiten.erkannt("Ich brauche einen Termin zur ZE Besprechung.")
    d = intent._fallback(_sit(), "Ich brauche eine Implantatbesprechung.")
    assert d["handlung"] != "ERREICHEN"
    d2 = intent._eindeutig("Ich brauche eine Implantatbesprechung.")
    assert d2 is None or d2.get("handlung") != "ERREICHEN"


def test_schiene_abholen_ist_kein_weiterleiten():
    """Pourianmehr 08.09.: Abholung + 'mit dem Arzt sprechen' = Buchung."""
    from kern import intent
    satz = ("Ich möchte meine Zahnschienen abholen und darüber "
            "möchte ich mit einem Arzt sprechen.")
    assert not weiterleiten.erkannt(satz)
    assert not weiterleiten.erkannt("Ich möchte meine Zahnschienen abholen.")
    d = intent._fallback(_sit(), satz)
    assert d["handlung"] == "ANLEGEN"
    d2 = intent._eindeutig(satz)
    assert d2 and d2["handlung"] == "ANLEGEN"
    sit = _sit()
    sit["weiterleiten"] = {"frage": "arzt"}
    sit["hirnVerbinden"] = {"person": "Arzt"}
    z = weiterleiten.zug(sit, satz)
    assert z is None
    assert sit.get("weiterleiten") == {}
    assert "hirnVerbinden" not in sit

# --- Jingle-Infrastruktur ----------------------------------------------------

def test_jingle_datei_liegt_im_repo():
    from kern.config import BIANCA_WEB_DIR
    p = BIANCA_WEB_DIR / "verbinden.mp3"
    assert p.is_file() and p.stat().st_size > 10_000


def test_dienst_festes_audio():
    from kern.dienst import Dienst
    d = Dienst(name="test", start_fn=lambda sit: {}, turn_fn=lambda sit, t, **k: {})
    blob = b"\xff\xfb\x90\x00daten"
    url = d.audio_fest_legen("verbinden", blob)
    assert url == "/api/audio/verbinden.mp3"
    assert d.audio_fest_url("verbinden") == url
    assert d.audio_holen("verbinden.mp3") == blob


def test_ansage_ueberlebt_sprech_filter():
    """Platzhalter-Ansage und Wahrheit duerfen der Sprech-Filter nicht zerlegen.
    (Chef 03.09.2026: der alte Kirri-Spassatz ist Geschichte — die Ansage ist
    jetzt eine ehrliche Rueckruf-Zusage.)"""
    from kern import sprech
    raus = sprech.sanitize(weiterleiten.ANSAGE_PLATZHALTER)
    assert "Verbindung" in raus and "möglich" in raus
    assert "Kirri" not in raus and "Lappen" not in raus
    wahr = sprech.sanitize(weiterleiten.WAHRHEIT)
    assert "Empfang" in wahr and "niemand" in wahr
    assert "personalfrei" not in wahr and "KI-geführt" not in wahr
