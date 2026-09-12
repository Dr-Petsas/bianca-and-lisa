"""W-ANSTAND: Beschimpfung/Fluchen — freundlich deeskalieren, nie kontern.

Laeuft ohne Netz. Der Konter ist deterministisch (bianca/anstand.py) und
greift NUR, wenn kein Fluss den Satz bedient hat — ein Anliegen im selben
Satz gewinnt immer den Fach-Weg.
"""

from bianca import anstand, flow, gehirn, weiterleiten
from kern.tenants import laden


def _sit() -> dict:
    return {"tenant": laden("meddent"), "messages": [{"role": "system", "content": "x"}]}


# --- Auch derbe Beleidigungen bleiben freundlich -----------------------------

def test_fick_dich_bekommt_selber():
    for satz in [
        "Ach, fick dich!",
        "Fick dich doch.",
        "Verpiss dich.",
        "Leck mich am Arsch.",
        "Sie Arschloch!",
        "Du Wichser.",
    ]:
        z = anstand.zug(_sit(), satz)
        assert z and z["text"] == anstand.ANTWORT_SELBER, satz
        assert "selber" not in z["text"].lower()


# --- Beschimpfungen -> 4-5 Alternativen, rotierend ----------------------------

def test_beschimpfung_bekommt_netten_konter():
    for satz in [
        "Sie blöde Kuh!",
        "Du dumme Maschine.",
        "Halt die Klappe!",
        "Halt's Maul.",
        "So eine Scheiß-KI.",
        "Bist du blöd?",
        "Du nervst.",
        "Sie Idiotin!",
    ]:
        z = anstand.zug(_sit(), satz)
        assert z and z["text"] in anstand.ANTWORTEN, satz


def test_konter_rotiert_pro_sitzung():
    sit = _sit()
    gesehen = []
    for _ in range(len(anstand.ANTWORTEN)):
        z = anstand.zug(sit, "Sie blöde Kuh!")
        assert z is not None
        gesehen.append(z["text"])
    # Alle Varianten kamen dran, keine doppelt hintereinander.
    assert gesehen == list(anstand.ANTWORTEN)


def test_kurzer_fluch_wird_gekontert_langer_frust_nicht():
    # Kurzer purer Fluch: Konter.
    assert anstand.zug(_sit(), "So ein Scheiß!") is not None
    # Frust ueber die eigene Lage mit Inhalt: gehoert dem Gespraech, kein Konter.
    assert anstand.zug(_sit(), "Verdammte Scheiße, ich habe den Termin heute Morgen komplett verpennt.") is None


def test_harmlose_saetze_bleiben_unberuehrt():
    for satz in [
        "Der Termin passt mir nicht.",
        "Ich habe eine Spastik im Rücken.",  # \bspasti?\b darf NICHT greifen
        "Mein Zahn ist abgebrochen.",
        "Können Sie mich zurückrufen lassen?",
        "Die Klappe vom Briefkasten klemmt.",
        "Seht, seht!",  # W-MEDDENT: STT-Müll, kein Konter
        "Niedjungel",
    ]:
        assert anstand.zug(_sit(), satz) is None, satz


# --- Vorfahrt: Anliegen im selben Satz gewinnt den Fach-Weg -------------------

def test_anliegen_mit_schimpfwort_gewinnt_fachweg():
    """'Verbinden Sie mich ..., Sie bloede Kuh!' -> Weiterleitung, kein Konter
    (agent fragt anstand erst, wenn flow.zug None geliefert hat)."""
    sit = _sit()
    z = flow.zug(sit, "Verbinden Sie mich mit Doktor Petsas, Sie blöde Kuh!")
    assert z is not None
    assert z.get("transfer") or weiterleiten.ANSAGE_PLATZHALTER in z["text"]


def test_agent_kontert_pure_beschimpfung_ohne_llm():
    """Pure Beschimpfung: kein Fluss greift, anstand kontert — das LLM
    darf dabei NIE angerufen werden (0 ms, GPU bleibt frei)."""
    from bianca import agent
    from kern import llm

    def _knall(*a, **k):
        raise AssertionError("LLM darf beim Anstand-Konter nicht laufen")

    echt_chat, echt_stream = llm.chat, llm.chat_stream
    llm.chat = _knall
    llm.chat_stream = _knall
    try:
        sit = _sit()
        aus = agent.user_turn(sit, "Ach, fick dich!")
        assert aus["text"] in anstand.ANTWORTEN
        assert "selber" not in aus["text"].lower()
    finally:
        llm.chat = echt_chat
        llm.chat_stream = echt_stream
