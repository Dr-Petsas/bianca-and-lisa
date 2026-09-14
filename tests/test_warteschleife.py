"""W-WARTESCHLEIFE (14.09.2026, Thaler 9311a9e2 / e2badc4c) — offline.

Die Praxis-Telefonanlage holt den Anrufer in ihre Warteschleife zurueck;
Bianca HOERT deren Ansagen ("Einen kleinen Augenblick noch bitte, wir sind
gleich persoenlich fuer Sie da", "online finden Sie uns ... unter www.…")
und behandelte sie live als Anrufer-Saetze: das Modell bedankte sich fuer
den "Hinweis", die Buchungsmaschine startete auf eine Ansage, der Anruf lief
minutenlang gegen die Schleife.

Die Wache ist deterministisch (0 ms, kein Modell). Der teurere Fehler waere
ein ECHTER Anrufersatz, der als Ansage geschluckt wird — deshalb sind die
Gegenproben hier der groessere Teil.
"""

import pytest

from bianca import agent, flow, gehirn
from kern import gedaechtnis, llm, mitschnitt, warteschleife
from kern.tenants import laden

# Live-Wortlaute (Parakeet-Transkripte aus den Mitschnitten, inkl. Verhoerer).
ANSAGE_WEB = ("Übrigens, online finden Sie uns rund um die Uhr, ganz ohne "
              "Wartezeiten, unter www.zahnarztpraxis-mainburg.de, dort haben Sie "
              "auch jederzeit die Möglichkeit, einen Termin zu vereinbaren.")
ANSAGE_WEB_VERHOERT = ("Übrigens, online finden Sie uns rund um die Uhr, ganz ohne "
                       "Wartezeiten, unter www.zahnarztpraxis-meinburg.de. Dort haben "
                       "Sie auch jederzeit die Möglichkeit, einen Termin zu vereinbaren.")
ANSAGE_MOMENT = ("Einen kleinen Augenblick noch bitte, wir sind gleich persönlich "
                 "für Sie da.")
# e2badc4c Zug 4: Anrufer-Sprache UND Ansage in einem Zug.
GEMISCHT = ("Ja, ich wurde angerufen, von wem? Keine Ahnung. " + ANSAGE_WEB)

WEITERE_ANSAGEN = [
    "Alle Leitungen sind derzeit besetzt. Bitte bleiben Sie in der Leitung.",
    "Ihr Anruf ist uns wichtig, der nächste freie Mitarbeiter ist gleich für Sie da.",
    "Sie werden gleich verbunden.",
    "Wir bitten um einen Moment Geduld.",
    "Vielen Dank für Ihren Anruf. Unsere Sprechzeiten sind Montag bis Freitag von acht bis achtzehn Uhr.",
    "Bitte hinterlassen Sie eine Nachricht nach dem Signalton.",
    "Besuchen Sie auch unsere Homepage.",
]

# Saetze echter Anrufer, die NIE als Ansage gelten duerfen.
ANRUFER = [
    "Einen Moment bitte, ich hole eben meinen Kalender.",
    "Einen kleinen Augenblick noch, ich schaue nach.",
    "Kann ich auch außerhalb der Sprechzeiten kommen?",
    "Ich habe Sie im Internet gefunden.",
    "Ich habe online schon mal einen Termin vereinbart.",
    "Ich rufe an, weil alle Leitungen besetzt waren.",
    "Wir sind gleich da, wir stehen schon vor der Tür.",
    "Ich möchte einen Termin vereinbaren, gerne ohne lange Wartezeit.",
    "Ja, ich habe eine Überweisung.",
    "Nein, die Nummer stimmt so.",
    "Meine Nummer ist null eins sieben sieben.",
    "Danke, das war's, auf Wiederhören.",
    "Haben Sie eine Webseite, wo ich das nachlesen kann?",
    "Mein Anruf ist mir wichtig, ich habe starke Schmerzen.",
    "Ich bleibe dran.",
]


def _s(v) -> str:
    return " ".join(str(v or "").split()).strip()


def _tenant() -> dict:
    t = dict(laden("meddent"))
    t["calendars"] = [dict(c) for c in (t.get("calendars") or [])]
    return t


def _sit(*, gesprochen: bool = True) -> dict:
    msgs = [{"role": "system", "content": "x"},
            {"role": "assistant", "content": "Guten Tag, hier ist Bianca. Was kann ich für Sie tun?"}]
    if gesprochen:
        msgs.append({"role": "user", "content": "Ich hätte gern einen Termin."})
        msgs.append({"role": "assistant", "content": "Gerne. Waren Sie schon einmal bei uns?"})
    sit = {"tenant": _tenant(), "messages": msgs, "stimme": "Bianca"}
    if gesprochen:
        s = gehirn.sammler(sit)
        s.update({"modus": "buchen", "frage": "schonmal", "phase": ""})
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
        llm.chat, llm.chat_stream = echt_chat, echt_stream
        flow.hintergrund.anstossen = echt_anstossen


# ---- Erkennung ---------------------------------------------------------------

@pytest.mark.parametrize("satz", [ANSAGE_WEB, ANSAGE_WEB_VERHOERT, ANSAGE_MOMENT] + WEITERE_ANSAGEN)
def test_ansagen_der_anlage_werden_erkannt(satz):
    assert warteschleife.ist_ansage(satz), satz


@pytest.mark.parametrize("satz", ANRUFER)
def test_anrufer_saetze_sind_keine_ansage(satz):
    """Gegenprobe — der teurere Fehler: ein Mensch, der geschluckt wird."""
    assert not warteschleife.ist_ansage(satz), satz
    assert warteschleife.zerlegen(satz) == ("", "")


def test_zerlegen_trennt_anrufer_rest_von_der_ansage():
    """e2badc4c Zug 4: der Anfang ist Anrufer-Sprache, der Rest Ansage."""
    ansage, rest = warteschleife.zerlegen(GEMISCHT)
    assert rest == "Ja, ich wurde angerufen, von wem? Keine Ahnung."
    assert "online finden Sie uns" in ansage


def test_zerlegen_unbekannter_ansagesatz_neben_bekanntem_gehoert_zur_ansage():
    """'Herzlich willkommen bei …' kennt kein Muster — ohne Sprecher-Marker
    neben einer erkannten Ansage ist es trotzdem Anlage, kein Anrufer."""
    text = "Herzlich willkommen bei der Zahnarztpraxis Thaler. " + ANSAGE_MOMENT
    ansage, rest = warteschleife.zerlegen(text)
    assert rest == ""
    assert ansage.startswith("Herzlich willkommen")


def test_zerlegen_ohne_ansage_liefert_leer():
    assert warteschleife.zerlegen("Ich hätte gern einen Termin zur Kontrolle.") == ("", "")


# ---- Bewertung / Schwellen ---------------------------------------------------

def test_bewerten_anrufer_hat_gesprochen_zweite_ansage_legt_auf():
    sit = _sit(gesprochen=True)
    a1 = warteschleife.bewerten(sit, ANSAGE_MOMENT)
    assert a1["aktion"] == "warte"
    assert not warteschleife.aufgelegt(sit)
    a2 = warteschleife.bewerten(sit, ANSAGE_WEB)
    assert a2["aktion"] == "auflegen"
    assert warteschleife.aufgelegt(sit)
    assert warteschleife.stand(sit)["n"] == 2


def test_bewerten_ohne_anrufer_sprache_erst_dritte_ansage_legt_auf():
    """Eine Begruessungsansage VOR dem Durchstellen darf einen echten Anruf
    nie beenden — ohne gesprochenen Anrufer braucht es drei reine Ansagen."""
    sit = _sit(gesprochen=False)
    assert warteschleife.bewerten(sit, ANSAGE_MOMENT)["aktion"] == "warte"
    assert warteschleife.bewerten(sit, ANSAGE_MOMENT)["aktion"] == "warte"
    assert warteschleife.bewerten(sit, ANSAGE_WEB)["aktion"] == "auflegen"


def test_bewerten_gemischter_zug_legt_nie_auf():
    """Solange im Zug ein Mensch spricht, wird nur der Rest weitergegeben —
    auch wenn die Ansagen-Zahl die Schwelle laengst ueberschritten hat."""
    sit = _sit(gesprochen=True)
    warteschleife.bewerten(sit, ANSAGE_MOMENT)
    warteschleife.bewerten(sit, ANSAGE_MOMENT)  # n=2 (aufgelegt-Flag gesetzt)
    a = warteschleife.bewerten(sit, GEMISCHT)
    assert a["aktion"] == "rest"
    assert a["text"] == "Ja, ich wurde angerufen, von wem? Keine Ahnung."


def test_bewerten_ohne_ansage_ist_weiter_und_zaehlt_nicht():
    sit = _sit()
    assert warteschleife.bewerten(sit, "Ich hätte gern einen Termin.") == {"aktion": "weiter"}
    assert "warteschleife" not in sit


def test_notaus_schaltet_alles_ab(monkeypatch):
    monkeypatch.setenv("WARTESCHLEIFE", "0")
    sit = _sit()
    assert warteschleife.bewerten(sit, ANSAGE_MOMENT) == {"aktion": "weiter"}


# ---- Agent Ende-zu-Ende (ohne LLM) ------------------------------------------

def test_agent_reine_ansage_bleibt_still_und_beruehrt_nichts():
    """Reine Ansage: kein Ton, kein Modell, nichts im Verlauf, Stille-Zaehler
    und Maschinenzustand unveraendert."""
    def lauf():
        sit = _sit(gesprochen=True)
        sit["stupse"] = 1
        vorher_msgs = list(sit["messages"])
        vorher_s = dict(gehirn.sammler(sit))
        aus = agent.user_turn(sit, ANSAGE_MOMENT)
        assert aus.get("warte") is True
        assert aus.get("text") == ""
        assert not aus.get("hangup")
        assert sit["messages"] == vorher_msgs
        assert dict(gehirn.sammler(sit)) == vorher_s
        assert sit["stupse"] == 1  # stille.reset lief NICHT
        assert any(e.get("w") == "warteschleife" for e in (sit.get("_spur") or []))
        return sit
    _ohne_llm(lauf)


def test_agent_zweite_ansage_legt_auf_und_report_nennt_die_schleife():
    def lauf():
        sit = _sit(gesprochen=True)
        agent.user_turn(sit, ANSAGE_MOMENT)
        aus = agent.user_turn(sit, ANSAGE_WEB)
        assert aus.get("hangup") is True
        assert aus.get("text") == ""
        assert warteschleife.aufgelegt(sit)
        # Kein Ansagetext im LLM-Verlauf.
        assert all("online finden Sie uns" not in _s(m.get("content"))
                   for m in sit["messages"])
        zf = gedaechtnis.zusammenfassung(sit)
        assert "Warteschleife" in zf and "aufgelegt" in zf
        manifest: dict = {}
        mitschnitt._zusammenfassung(manifest, sit)
        assert manifest["warteschleife"]["aufgelegt"] is True
        assert manifest["warteschleife"]["n"] == 2
    _ohne_llm(lauf)


def _mit_stummem_llm(fn, text: str = "Alles klar."):
    """Der Zug darf ans Modell fallen — es antwortet neutral und ohne Werkzeug."""
    antwort = {"ok": True, "text": text, "tool_calls": []}
    echt_chat, echt_stream = llm.chat, llm.chat_stream
    echt_anstossen = flow.hintergrund.anstossen
    llm.chat = lambda msgs, tools=None, **k: dict(antwort)
    llm.chat_stream = lambda msgs, tools=None, **k: dict(antwort)
    flow.hintergrund.anstossen = lambda sit: None
    try:
        return fn()
    finally:
        llm.chat, llm.chat_stream = echt_chat, echt_stream
        flow.hintergrund.anstossen = echt_anstossen


def test_agent_gemischter_zug_verarbeitet_nur_die_anrufer_sprache():
    """e2badc4c Zug 4 nachgestellt: die Maschine wartet auf 'schon einmal bei
    uns?' — verarbeitet wird der Anrufer-Teil (der darf ans Modell fallen),
    die Ansage landet nie im Verlauf, nichts legt auf."""
    def lauf():
        sit = _sit(gesprochen=True)
        aus = agent.user_turn(sit, GEMISCHT)
        assert not aus.get("hangup")
        assert not aus.get("warte")
        user = [m for m in sit["messages"] if m.get("role") == "user"]
        assert user[-1]["content"] == "Ja, ich wurde angerufen, von wem? Keine Ahnung."
        assert all("www." not in _s(m.get("content")) for m in sit["messages"])
        assert warteschleife.stand(sit)["n"] == 1
        assert not warteschleife.aufgelegt(sit)
    _mit_stummem_llm(lauf)


def test_agent_echter_anrufersatz_laeuft_unveraendert():
    """Gegenprobe im Agent: 'Einen Moment bitte, ich hole eben meinen
    Kalender.' ist ein Mensch — kein warte, kein hangup, Zaehler leer. Der
    Satz beantwortet die offene Frage nicht und darf ans Modell fallen."""
    def lauf():
        sit = _sit(gesprochen=True)
        aus = agent.user_turn(sit, "Einen Moment bitte, ich hole eben meinen Kalender.")
        assert not aus.get("hangup")
        assert not aus.get("warte")
        assert "warteschleife" not in sit
        user = [m for m in sit["messages"] if m.get("role") == "user"]
        assert user[-1]["content"] == "Einen Moment bitte, ich hole eben meinen Kalender."
    _mit_stummem_llm(lauf, "Gerne, ich warte.")
