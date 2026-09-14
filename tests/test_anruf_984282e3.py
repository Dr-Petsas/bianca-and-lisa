"""Anruf 984282e303cb414ab6c32125877473c2 (MedDent, 14.09.2026) — offline,
ohne LLM und ohne Netz.

Chef: "hier wurde durchgestellt, obwohl der patient sagt er wolle einen
termin". Kette live: Buchung laeuft, Maschine fragt "Wissen Sie noch, bei
welchem Behandler Sie zuletzt waren?" -> Anrufer: "Ja." -> die Maschine
erntete nichts (kein Ja-Zweig), der Zug fiel ans Modell -> das Modell bot
"Doktor Petsas, Patrikis oder Nikolaou" zum DURCHSTELLEN an -> Anrufer:
"Patrikis" -> weiterleiten.zug nahm die Modell-Rueckfrage als Beweis und
verband (Jingle, Transfer, Buchung weg).

Vier Wachen (W-VERBINDEN-BEWEIS / W-ARZT-JANEIN):
1. weiterleiten.zug Pfad (b) verbindet auf die LLM-Rueckfrage NUR, wenn die
   Maschine frei war (maschine_beschaeftigt).
2. angebot_saeubern streicht erfundene Verbinde-Angebote des Modells, wenn
   der Anrufer keinen Verbinde-Wunsch geaeussert hat und die Maschine
   arbeitet — am Zugende UND im P5-Strom.
3. "Ja"/"Nein" auf die Bestands-Behandlerfrage sind deterministisch: Ja ->
   Namen zur Wahl, Nein/zweites Ja -> Standard-Weg. Kein LLM.
4. Der Prompt nennt, wohin ueberhaupt durchgestellt werden kann — und dass
   der gesperrte Behandler (Nikolaou) nie zur Wahl steht.
"""

from bianca import agent, flow, gehirn, prompt, weiterleiten
from kern import behandler_sperre, llm
from kern.tenants import laden

PETSAS = "zex5bmv5jfIHWVW6zHbg"


def _s(v) -> str:
    return " ".join(str(v or "").split()).strip()


def _tenant() -> dict:
    t = dict(laden("meddent"))
    t["calendars"] = [dict(c) for c in (t.get("calendars") or [])]
    behandler_sperre.anwenden(t)
    return t


def _sit() -> dict:
    return {"tenant": _tenant(), "messages": [{"role": "system", "content": "x"}]}


def _buchung_arztfrage() -> dict:
    """Die Live-Lage: Bestandspatient, Buchung laeuft, Behandler-Frage offen."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": True, "frage": "arzt",
              "grund": "", "phase": ""})
    return sit


def _knall(*a, **k):
    raise AssertionError("LLM darf hier nicht laufen")


def _ohne_llm(fn):
    echt_chat, echt_stream = llm.chat, llm.chat_stream
    echt_anstossen = flow.hintergrund.anstossen
    llm.chat = _knall
    llm.chat_stream = _knall
    flow.hintergrund.anstossen = lambda sit: None
    try:
        return fn()
    finally:
        llm.chat = echt_chat
        llm.chat_stream = echt_stream
        flow.hintergrund.anstossen = echt_anstossen


# --- 1. Pfad (b): LLM-Rueckfrage ist kein Beweis, wenn die Maschine arbeitet --

def test_maschine_beschaeftigt_erkennt_die_lage():
    assert weiterleiten.maschine_beschaeftigt(_sit()) is False
    assert weiterleiten.maschine_beschaeftigt(_buchung_arztfrage()) is True
    # Offene Frage allein reicht (auch ohne Modus).
    sit = _sit()
    gehirn.sammler(sit)["frage"] = "telefon"
    assert weiterleiten.maschine_beschaeftigt(sit) is True
    # Ein aktives ERREICHEN-Anliegen ist das Geschaeft des Verbindens selbst.
    sit2 = _sit()
    sit2["hirn"] = {"anliegen": [{"id": "a1", "handlung": "ERREICHEN",
                                  "gegenstand": "PERSON", "status": "aktiv"}]}
    assert weiterleiten.maschine_beschaeftigt(sit2) is False


def test_name_auf_llm_rueckfrage_verbindet_nicht_mitten_in_der_buchung():
    """Live: 'Patrikis' nach der erfundenen Rueckfrage -> Transfer. Jetzt:
    die Maschine war beschaeftigt (frage=arzt), der Name ist KEINE
    Zielangabe — kein Jingle, kein transfer, kein hangup."""
    sit = _buchung_arztfrage()
    sit["messages"].append({"role": "assistant",
                            "content": "Zu welchem unserer Ärzte darf ich Sie verbinden?"})
    events: list[str] = []
    z = weiterleiten.zug(sit, "Patrikis", events.append)
    assert z is None or ("transfer" not in z and not z.get("hangup")), z
    assert weiterleiten.JINGLE_EVENT not in events


def test_name_auf_llm_rueckfrage_verbindet_weiter_wenn_maschine_frei():
    """Gegenprobe: der bewaehrte Rueckweg der Prompt-Leitplanke bleibt —
    ohne laufende Aufgabe zaehlt der Name nach der Rueckfrage wie bisher."""
    sit = _sit()
    sit["messages"].append({"role": "assistant",
                            "content": "Zu welchem unserer Ärzte darf ich Sie verbinden?"})
    events: list[str] = []
    z = weiterleiten.zug(sit, "Doktor Petsas, bitte.", events.append)
    assert z is not None
    assert weiterleiten.JINGLE_EVENT in events or weiterleiten.ANSAGE_PLATZHALTER in z["text"]


# --- 2. Erfundene Verbinde-Angebote des Modells fallen -----------------------

LIVE_ANGEBOT = ("Alles klar. Darf ich Sie zu Doktor Petsas, Doktor Patrikis "
                "oder Doktor Nikolaou durchstellen?")


def test_angebot_saeubern_streicht_erfundenes_angebot_in_der_buchung():
    sit = _buchung_arztfrage()
    text, gestrichen = weiterleiten.angebot_saeubern(sit, LIVE_ANGEBOT, "Ja.")
    assert gestrichen is True
    assert "durchstell" not in text.lower() and "Nikolaou" not in text
    assert text.startswith("Alles klar.")


def test_angebot_saeubern_laesst_echten_verbinde_wunsch_durch():
    """Der Anrufer WILL verbunden werden — dann darf das Modell die
    Rueckfrage stellen (Prompt-Leitplanke), auch mitten in einer Aufgabe."""
    sit = _buchung_arztfrage()
    frage = "Zu welchem unserer Ärzte darf ich Sie verbinden?"
    text, gestrichen = weiterleiten.angebot_saeubern(
        sit, frage, "Ich möchte bitte mit Doktor Petsas sprechen.")
    assert gestrichen is False and text == frage


def test_angebot_saeubern_laesst_maschine_frei_unangetastet():
    """Ohne laufende Aufgabe greift die Wache nicht — das freie Gespraech
    behaelt sein bisheriges Verhalten."""
    sit = _sit()
    text, gestrichen = weiterleiten.angebot_saeubern(sit, LIVE_ANGEBOT, "Ja.")
    assert gestrichen is False and text == LIVE_ANGEBOT


def test_angebot_saeubern_verschont_verneinung_und_sachtext():
    sit = _buchung_arztfrage()
    verneint = "Ich kann Sie leider nicht direkt verbinden. Wie ist Ihr Nachname?"
    text, gestrichen = weiterleiten.angebot_saeubern(sit, verneint, "Ja.")
    assert gestrichen is False and text == verneint
    sach = "Alles klar. Bei welchem Behandler waren Sie denn zuletzt?"
    text, gestrichen = weiterleiten.angebot_saeubern(sit, sach, "Ja.")
    assert gestrichen is False and text == sach


def test_agent_ende_zu_ende_modell_erfindet_angebot_kein_transfer():
    """Nachstellung des Live-Anrufs mit dem Modell als Taeter: die Maschine
    fragt den Behandler, der Anrufer antwortet unverwertbar (Zug faellt ans
    Modell), das Modell liefert WORTGLEICH das Live-Angebot samt Nikolaou.
    Erwartung: das Angebot erreicht den Mund nicht (auch nicht ueber P5),
    und "Patrikis" im Folgezug ist ein Behandler fuer die Buchung — kein
    Jingle, kein transfer."""
    gesprochen: list[str] = []

    def stream(msgs, tools=None, *, erster_satz=None, **k):
        if erster_satz:
            for satz in ("Alles klar.",
                         "Darf ich Sie zu Doktor Petsas, Doktor Patrikis "
                         "oder Doktor Nikolaou durchstellen?"):
                erster_satz(satz)
        return {"ok": True, "text": LIVE_ANGEBOT, "tool_calls": []}

    echt_chat, echt_stream = llm.chat, llm.chat_stream
    echt_anstossen = flow.hintergrund.anstossen
    llm.chat = lambda msgs, tools=None, **k: {"ok": True, "text": LIVE_ANGEBOT, "tool_calls": []}
    llm.chat_stream = stream
    flow.hintergrund.anstossen = lambda sit: None
    try:
        sit = _buchung_arztfrage()
        aus = agent.user_turn(
            sit, "Hm, gute Frage, das ist schon eine Weile her.",
            vorab=gesprochen.append)
        text = _s(aus.get("text"))
        assert "durchstell" not in text.lower() and "Nikolaou" not in text, text
        assert all("durchstell" not in g.lower() for g in gesprochen), gesprochen
        assert "transfer" not in aus and not aus.get("hangup")
        # Der Folgezug: der Name ist die Behandler-Antwort der Buchung.
        llm.chat = _knall
        llm.chat_stream = _knall
        events: list[str] = []
        aus2 = agent.user_turn(sit, "Patrikis", melde=events.append)
        assert "transfer" not in aus2 and not aus2.get("hangup"), aus2
        assert weiterleiten.JINGLE_EVENT not in events
        a = gehirn.sammler(sit).get("arzt") or {}
        assert "Patrikis" in _s(a.get("calendarName")), a
    finally:
        llm.chat = echt_chat
        llm.chat_stream = echt_stream
        flow.hintergrund.anstossen = echt_anstossen


def test_verbinden_wache_im_agent_markiert_spur():
    sit = _buchung_arztfrage()
    aus = agent._verbinden_wache_anwenden(sit, LIVE_ANGEBOT, "Ja.")
    assert "durchstell" not in aus.lower()
    spuren = [e for e in (sit.get("_spur") or []) if "verbinden" in str(e.get("w")).lower()]
    assert spuren, sit.get("_spur")


# --- 3. Ja/Nein auf die Bestands-Behandlerfrage sind deterministisch --------

def test_ja_auf_arztfrage_fragt_namen_zur_wahl_ohne_llm():
    def lauf():
        sit = _buchung_arztfrage()
        z = flow.zug(sit, "Ja.")
        assert z is not None, "fiel ans LLM"
        text = _s(z.get("text"))
        assert "Doktor Petsas" in text and "Doktor Patrikis" in text, text
        assert "Nikolaou" not in text, text
        assert "transfer" not in z and not z.get("hangup")
        s = gehirn.sammler(sit)
        assert s.get("arztJa") is True and s["frage"] == "arzt"
        return sit
    _ohne_llm(lauf)


def test_nach_ja_setzt_der_name_den_behandler_und_die_kette_laeuft():
    def lauf():
        sit = _buchung_arztfrage()
        flow.zug(sit, "Ja.")
        events: list[str] = []
        z = flow.zug(sit, "Patrikis", events.append)
        assert z is not None, "fiel ans LLM"
        s = gehirn.sammler(sit)
        a = s.get("arzt") or {}
        assert "Patrikis" in _s(a.get("calendarName")), a
        assert s["frage"] != "arzt", s["frage"]
        assert "transfer" not in z and not z.get("hangup")
        assert weiterleiten.JINGLE_EVENT not in events
    _ohne_llm(lauf)


def test_nein_auf_arztfrage_geht_den_standard_weg():
    def lauf():
        sit = _buchung_arztfrage()
        z = flow.zug(sit, "Nein.")
        assert z is not None, "fiel ans LLM"
        s = gehirn.sammler(sit)
        assert (s.get("arzt") or {}).get("typ") == "unbekannt", s.get("arzt")
        assert s["frage"] != "arzt", s["frage"]
        assert "Kein Problem" in _s(z.get("text")), z.get("text")
    _ohne_llm(lauf)


def test_zweites_ja_ohne_namen_gilt_wie_weiss_nicht():
    def lauf():
        sit = _buchung_arztfrage()
        flow.zug(sit, "Ja.")
        z = flow.zug(sit, "Ja, genau.")
        assert z is not None, "fiel ans LLM"
        s = gehirn.sammler(sit)
        assert (s.get("arzt") or {}).get("typ") == "unbekannt", s.get("arzt")
        assert s["frage"] != "arzt", s["frage"]
    _ohne_llm(lauf)


def test_widerspruch_mit_inhalt_ist_kein_blosses_nein():
    """Gegenprobe zu W-EINWAND: "Nein, bei dem Behandler war ich nicht" ist
    ein Widerspruch, kein Ja/Nein auf die Frage — der Ja/Nein-Zweig haelt
    sich heraus, der Behandler wird NICHT still auf 'unbekannt' gesetzt."""
    assert gehirn._arzt_janein_kurz("Ja.") is True
    assert gehirn._arzt_janein_kurz("Nein, leider nicht.") is True
    assert gehirn._arzt_janein_kurz("Nein, bei dem Behandler war ich nicht.") is False
    assert gehirn._arzt_janein_kurz(
        "Ja, ich glaube das war der mit dem Bart im zweiten Stock") is False


def test_neupatient_arztwahl_unveraendert():
    """Die Neupatienten-Wahl nennt die Namen selbst — dort bleibt 'Ja' ohne
    Namen wie bisher (kein arztJa), die Wahl-Frage wird erneut gestellt
    oder eskaliert wie gehabt."""
    def lauf():
        sit = _sit()
        s = gehirn.sammler(sit)
        s.update({"modus": "buchen", "warSchonMal": False, "frage": "arzt"})
        flow.zug(sit, "Ja.")
        assert not s.get("arztJa")
    _ohne_llm(lauf)


def test_arzt_nachfrage_nennt_nie_den_gesperrten_behandler():
    sit = _buchung_arztfrage()
    frage = gehirn.arzt_nachfrage(sit)
    assert "Doktor Petsas" in frage and "Doktor Patrikis" in frage
    assert "Nikolaou" not in frage
    # Auch mit dem UNGEFILTERTEN Mandanten (persistierte Alt-Sitzung).
    sit2 = {"tenant": laden("meddent")}
    assert "Nikolaou" not in gehirn.arzt_nachfrage(sit2)


# --- 4. Prompt: wohin ueberhaupt, und wer nie ------------------------------

def test_verbinden_zeile_meddent_nennt_ziele_und_sperre():
    zeile = weiterleiten.verbinden_zeile(_tenant())
    assert "Doktor Petsas" in zeile and "Doktor Patrikis" in zeile
    assert "Nikolaou" in zeile and "nie" in zeile
    # Der gesperrte Name steht NICHT bei den Zielen.
    ziele = zeile.split("Telefonisch weder")[0]
    assert "Nikolaou" not in ziele, ziele


def test_verbinden_zeile_ohne_whitelist_sagt_kein_durchstellen(monkeypatch):
    monkeypatch.delenv("VERBINDEN_ERLAUBT", raising=False)
    t = {"calendars": [{"id": "a", "name": "Doktor Eva Thaler"}]}
    zeile = weiterleiten.verbinden_zeile(t)
    assert "NICHT durchgestellt" in zeile
    assert "Thaler" not in zeile


def test_system_prompt_traegt_die_verbinden_zeile():
    zeile = weiterleiten.verbinden_zeile(_tenant())
    p = prompt.system_prompt(praxis="Zahnärzte im Medical Center",
                             behandler="Doktor Petsas", verbinden_zeile=zeile)
    assert zeile in p
    assert "bietest NIE von dir aus an" in p
