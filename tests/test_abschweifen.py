"""W-ABSCHWEIFEN: abwegige Bitten deterministisch erfuellen (13.09.2026).

Chef zum Live-Anruf 48673eca: "ausserdem bist du nicht auf den anrufer
eingegangen als der verlangte: zähl mal von 1 bis 4 oder buchstabiere meinen
namen Abdullah … das ist ja unser talk floor eigentlich … ein abschweifen …
das wurde nicht gut genug bearbeitet."

Laeuft ohne Netz, ohne Modell. Der teurere Fehler ist NICHT die verpasste
Spielerei, sondern eine gekaperte Datenerfassung: wenn der Anrufer SELBST
buchstabiert oder Ziffern diktiert, darf dieser Baustein nie zuschlagen.
Deshalb liegen die Gegenproben hier gleichwertig neben den Treffern.
"""

from __future__ import annotations

from bianca import gehirn
from kern import abschweifen
from kern.tenants import laden


def _sit() -> dict:
    return {"tenant": laden("meddent"), "messages": [{"role": "system", "content": "x"}]}


# --- Zaehlen ----------------------------------------------------------------

def test_von_bis_zaehlen():
    """Der Live-Satz: "zähl mal von 1 bis 4"."""
    assert abschweifen.antwort("Zähl mal von 1 bis 4.") == "Gerne: eins, zwei, drei, vier."


def test_zahlwoerter_und_nur_bis():
    assert abschweifen.antwort("Zähl mal von eins bis drei.") == "Gerne: eins, zwei, drei."
    # Ohne Untergrenze faengt jeder bei eins an.
    assert abschweifen.antwort("Kannst du bitte bis drei zählen?") == "Gerne: eins, zwei, drei."


def test_rueckwaerts_zaehlen():
    assert abschweifen.antwort("Zähl mal von drei bis eins.") == "Gerne: drei, zwei, eins."


def test_lange_reihe_wird_gedeckelt():
    """Niemand hoert am Telefon bis hundert zu — nach 20 Zahlen ist Schluss."""
    aus = abschweifen.antwort("Zähl mal von 1 bis 100.")
    assert aus.startswith("Gerne: eins, zwei,")
    assert aus.endswith("zwanzig und so weiter.")


# --- Ziffern nachsprechen ---------------------------------------------------

def test_ziffernfolge_nachsprechen():
    """Live landete "Wiederhol mal die Zahlen 1, 2, 3, 4." als RUECKRUF-NOTIZ."""
    assert abschweifen.antwort(
        "Wiederhol mal die Zahlen 1, 2, 3, 4.") == "Gerne: eins, zwei, drei, vier."


def test_ziffern_ohne_ziffern_bleibt_still():
    """"Wiederholen Sie die Ziffern meiner Nummer" traegt keine Ziffern — hier
    gibt es nichts zu spielen, der Satz gehoert dem normalen Gespraech."""
    assert abschweifen.antwort("Wiederholen Sie bitte die Ziffern meiner Nummer.") == ""


# --- Buchstabieren ----------------------------------------------------------

def test_namen_buchstabieren_mit_wort():
    """Der Live-Satz: "buchstabiere meinen Namen Abdullah"."""
    aus = abschweifen.antwort("Buchstabiere meinen Namen Abdullah.")
    assert aus == ("Gerne: A wie Anton, B wie Berta, D wie Dora, U wie Ulrich, "
                   "L wie Ludwig, L wie Ludwig, A wie Anton, H wie Heinrich.")


def test_ziel_steht_auch_vor_dem_verb():
    """"Kannst du Müller buchstabieren?" — das Ziel steht VOR dem Verb."""
    assert abschweifen.antwort("Kannst du Müller buchstabieren?").startswith(
        "Gerne: M wie Martha, Ü wie Übermut, L wie Ludwig")


def test_ohne_genanntes_wort_gilt_der_belegte_name():
    """"Kannst du meinen Namen buchstabieren?" — dann der Name aus dem Sammler."""
    assert abschweifen.antwort(
        "Kannst du meinen Namen buchstabieren?", name="Tzannis").startswith(
        "Gerne: T wie Theodor, Z wie Zacharias")
    # Ohne belegten Namen wird nie geraten.
    assert abschweifen.antwort("Kannst du meinen Namen buchstabieren?") == ""


# --- Gegenproben: die Datenerfassung darf nie gekapert werden ---------------

def test_anrufer_buchstabiert_selbst():
    """"Ich buchstabiere: Tzannis" ist eine ANTWORT, keine Bitte."""
    for satz in [
        "Ich buchstabiere: Tzannis.",
        "Ich buchstabiere Ihnen den Nachnamen.",
        "T-Z-A-N-N-I-S.",
        "A, B, D, U, L, L, A, H.",
        "Ich zähle die Tage bis zum Termin.",
    ]:
        assert abschweifen.antwort(satz, name="Tzannis") == "", satz


def test_normale_saetze_bleiben_unberuehrt():
    for satz in [
        "Ich hätte gern einen Termin.",
        "Meine Nummer ist 0177 1234567.",
        "Mein Nachname ist Thannes.",
        "Zahlt das die Kasse?",
        "Erzählen Sie mir von der Praxis.",
    ]:
        assert abschweifen.antwort(satz, name="Tzannis") == "", satz


def test_notaus(monkeypatch):
    monkeypatch.setenv("ABSCHWEIFEN", "0")
    assert abschweifen.antwort("Zähl mal von 1 bis 4.") == ""


# --- Einhaengung: Talk-Floor im Agenten ------------------------------------

def test_agent_erfuellt_die_bitte_und_haengt_die_frage_an():
    """Der Zug ist deterministisch (kein LLM) und die offene Pflichtfrage
    kommt hinterher — sonst verliert das Gespraech den Faden."""
    from bianca import agent
    from kern import llm

    def _knall(*a, **k):
        raise AssertionError("LLM darf beim Abschweifen nicht laufen")

    echt_chat, echt_stream = llm.chat, llm.chat_stream
    llm.chat = _knall
    llm.chat_stream = _knall
    try:
        sit = _sit()
        s = gehirn.sammler(sit)
        s["modus"] = "buchen"
        s["warSchonMal"] = True
        # Die wirklich offene Frage des Sammlers — wie live, wenn der Fluss
        # sie gerade gestellt hat.
        fid, frage = gehirn.naechste_frage(sit)
        s["frage"] = fid
        aus = agent.user_turn(sit, "Zähl mal von 1 bis 4.")
        assert "eins, zwei, drei, vier" in aus["text"]
        # Der Faden bleibt: die offene Frage steht im selben Zug.
        assert frage in aus["text"]
        # Nichts am Zustand angefasst.
        assert not s["nachname"] and not s["telefon"]
    finally:
        llm.chat = echt_chat
        llm.chat_stream = echt_stream


def test_agent_laesst_das_diktat_in_ruhe():
    """Waehrend Nummer/Buchstabieren gehoert JEDES Zeichen der Erfassung —
    dort darf die Spielerei nie zuschlagen (sonst frisst sie die Nummer)."""
    from bianca import agent

    sit = _sit()
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    s["warSchonMal"] = True
    s["frage"] = "telefon"
    agent.user_turn(sit, "Null eins sieben sieben, wiederholen Sie die Zahlen bitte.")
    spuren = [e.get("w") for e in (sit.get("_spur") or [])]
    assert "abschweifen" not in spuren
