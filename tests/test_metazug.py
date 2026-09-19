"""W-META-LIVE: Meta-Bitten am Telefon (19.09.2026).

Drei Bitten, die im Dialogkern fertig waren und am Telefon ins Modell fielen:
wiederholen, abbrechen, auslassen. Laeuft ohne Netz, ohne Modell.

Die Gegenproben sind hier der teurere Teil. Ein verpasstes "Wie bitte?" kostet
einen Zug; ein falsch erkannter Abbruch wirft eine halb erfasste Buchung weg,
und ein gekapertes Diktat frisst die Rufnummer. Deshalb steht hinter jedem
Treffer der Fall, in dem NICHTS passieren darf.
"""

from __future__ import annotations

from bianca import gehirn, metazug
from kern.tenants import laden


def _sit() -> dict:
    return {"tenant": laden("meddent"), "messages": [{"role": "system", "content": "x"}]}


def _msgs(*saetze: str) -> list[dict]:
    return [{"role": "assistant", "content": s} for s in saetze]


def _buchung_laeuft(sit: dict, frage: str = "nachname") -> dict:
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    s["warSchonMal"] = True
    s["grund"] = "Kontrolle"
    s["frage"] = frage
    return s


# --- Wiederholen ------------------------------------------------------------

def test_wiederholen_spricht_die_letzte_ansage_erneut():
    sit = _sit()
    _buchung_laeuft(sit)
    aus = metazug.zug(sit, "Wie bitte?", _msgs("Wie lautet Ihr Nachname?"))
    assert aus is not None
    assert "Wie lautet Ihr Nachname?" in aus["text"]
    # Nicht wortgleich: eine Einleitung macht aus der Platte eine Antwort.
    assert aus["text"] != "Wie lautet Ihr Nachname?"
    # Ausdrueckliche Bitte — der Entdoppler darf den Inhalt nicht streichen.
    assert aus["_wiederholungErlaubt"] is True


def test_wiederholen_wechselt_die_einleitung():
    """Dreimal dieselbe Einleitung klingt selbst wieder wie eine Schleife."""
    sit = _sit()
    _buchung_laeuft(sit)
    msgs = _msgs("Wie lautet Ihr Nachname?")
    erste = metazug.zug(sit, "Wie bitte?", msgs)["text"]
    zweite = metazug.zug(sit, "Können Sie das nochmal sagen?", msgs)["text"]
    assert erste != zweite


def test_wiederholen_ueberspringt_presence():
    """"Sind Sie noch dran?" noch einmal zu sagen beantwortet keine Bitte."""
    sit = _sit()
    _buchung_laeuft(sit)
    aus = metazug.zug(
        sit, "Wie bitte?",
        _msgs("Wie lautet Ihr Nachname?", "Sind Sie noch dran?"),
    )
    assert "Wie lautet Ihr Nachname?" in aus["text"]
    assert "noch dran" not in aus["text"]


def test_wiederholen_deckel_wird_ehrlich():
    """Nach drei Bitten ist nicht der Satz das Problem, sondern die Leitung."""
    sit = _sit()
    _buchung_laeuft(sit)
    msgs = _msgs("Wie lautet Ihr Nachname?")
    for _ in range(metazug.DECKEL):
        metazug.zug(sit, "Wie bitte?", msgs)
    aus = metazug.zug(sit, "Wie bitte?", msgs, offene="Wie lautet Ihr Nachname?")
    assert "direkt" in aus["text"]
    # Der Faden bleibt: die offene Frage haengt hinterher.
    assert "Nachname" in aus["text"]


def test_inhaltlicher_zug_nullt_die_serie():
    sit = _sit()
    _buchung_laeuft(sit)
    msgs = _msgs("Wie lautet Ihr Nachname?")
    metazug.zug(sit, "Wie bitte?", msgs)
    assert metazug.zug(sit, "Meier.", msgs) is None
    assert not sit.get("metaWiederhol")


def test_eigene_wiederholung_ist_keine_bitte():
    """"Ich sage es nochmal: Meier" wiederholt der ANRUFER — nicht Bianca."""
    sit = _sit()
    _buchung_laeuft(sit)
    assert metazug.zug(sit, "Ich sage es nochmal, Meier.", _msgs("Wie lautet Ihr Nachname?")) is None


# --- Abbrechen --------------------------------------------------------------

def test_abbrechen_raeumt_das_anliegen_und_fragt_ab():
    sit = _sit()
    s = _buchung_laeuft(sit, frage="wunsch")
    s["motivId"] = "m1"
    sit["offered"] = [{"iso": "2026-09-21T09:00:00"}]
    aus = metazug.zug(sit, "Vergessen Sie's.", _msgs("Wann passt es Ihnen?"))
    assert aus is not None
    assert "lassen wir das" in aus["text"]
    s2 = gehirn.sammler(sit)
    assert not s2["modus"] and not s2["grund"] and not s2["motivId"]
    assert "offered" not in sit
    # Die Abschluss-Frage ist REGISTRIERT — sonst faellt "Nein." ans Modell
    # und niemand legt auf (die Schleife vom 15.09.2026).
    assert s2["frage"] == "sonst_noch"
    assert sit.get("abgebenSonstNoch") is True


def test_abbrechen_behaelt_die_identitaet():
    """Wer eben seinen Namen buchstabiert hat, tut das nach "vergessen Sie's"
    nicht noch einmal."""
    sit = _sit()
    s = _buchung_laeuft(sit, frage="wunsch")
    s["nachname"] = "Meier"
    s["vorname"] = "Peter"
    s["buchstabiert"] = True
    s["telefon"] = "01771234567"
    metazug.zug(sit, "Hat sich erledigt.", _msgs("Wann passt es Ihnen?"))
    s2 = gehirn.sammler(sit)
    assert s2["nachname"] == "Meier" and s2["vorname"] == "Peter"
    assert s2["telefon"] == "01771234567"


def test_abbrechen_schreibt_keine_rueckrufnotiz():
    """Ein Abbruch ist ein Zuruecknehmen — niemand hat um Rueckruf gebeten."""
    sit = _sit()
    _buchung_laeuft(sit, frage="wunsch")
    metazug.zug(sit, "Vergessen Sie's.", _msgs("Wann passt es Ihnen?"))
    assert not sit.get("praxisNotiz")
    assert not sit.get("tools")


def test_abbrechen_nach_gebuchtem_termin_ist_ehrlich():
    """Es gibt kein Werkzeug, das eine Buchung ungeschehen macht."""
    sit = _sit()
    s = _buchung_laeuft(sit, frage="")
    s["phase"] = "gebucht"
    sit["tools"] = [{"name": "book_slot", "ok": True}]
    aus = metazug.zug(sit, "Vergessen Sie's.", _msgs("Der Termin ist eingetragen."))
    assert "schon eingetragen" in aus["text"]
    assert "absagen" in aus["text"]
    # Der Zustand bleibt stehen: "ja, absagen" geht den normalen Weg.
    assert gehirn.sammler(sit)["phase"] == "gebucht"


def test_abbrechen_ohne_laufendes_anliegen():
    sit = _sit()
    aus = metazug.zug(sit, "Vergessen Sie's.", _msgs("Was kann ich für Sie tun?"))
    assert aus is not None
    assert "Kein Problem" in aus["text"]


def test_weiche_formel_vor_der_slotwahl_ist_kein_abbruch():
    """Auf ein Slot-Angebot heisst "das moechte ich doch nicht" DIESEN Termin
    nicht — dort entscheidet die deterministische Ja/Nein-Frage."""
    sit = _sit()
    _buchung_laeuft(sit, frage="slotwahl")
    assert metazug.streng(sit) is True
    assert metazug.zug(sit, "Das möchte ich doch nicht.", _msgs("Welcher passt Ihnen?")) is None


def test_harte_formel_wirkt_auch_vor_der_slotwahl():
    sit = _sit()
    _buchung_laeuft(sit, frage="slotwahl")
    aus = metazug.zug(sit, "Vergessen Sie's.", _msgs("Welcher passt Ihnen?"))
    assert aus is not None and "lassen wir das" in aus["text"]


# --- Auslassen --------------------------------------------------------------

def test_auslassen_bleibt_bei_der_pflichtfrage():
    """Am Telefon ist jedes Buchungsfeld Pflicht: ehrlich sagen, warum."""
    sit = _sit()
    _buchung_laeuft(sit, frage="nachname")
    aus = metazug.zug(sit, "Muss das sein?", _msgs("Wie lautet Ihr Nachname?"),
                      offene="Wie lautet Ihr Nachname?")
    assert aus is not None
    assert "Akte" in aus["text"]
    assert "Nachname" in aus["text"]
    # Nichts geraten, nichts geleert.
    assert gehirn.sammler(sit)["frage"] == "nachname"


def test_auslassen_nennt_den_grund_der_rufnummer():
    sit = _sit()
    _buchung_laeuft(sit, frage="telefon")
    aus = metazug.zug(sit, "Das möchte ich nicht sagen.",
                      _msgs("Wie lautet Ihre Rufnummer?"),
                      offene="Wie lautet Ihre Rufnummer?")
    assert "erreichen" in aus["text"]


def test_auslassen_ohne_offene_frage_gehoert_dem_gespraech():
    sit = _sit()
    assert metazug.zug(sit, "Muss das sein?", _msgs("Was kann ich für Sie tun?")) is None


def test_sachfrage_ist_kein_auslassen():
    """"Ist das nötig für die Behandlung?" ist eine Frage, keine Weigerung."""
    sit = _sit()
    _buchung_laeuft(sit, frage="nachname")
    assert metazug.zug(
        sit, "Ist das nötig für die Behandlung?",
        _msgs("Wie lautet Ihr Nachname?"), offene="Wie lautet Ihr Nachname?",
    ) is None


# --- Wer den Zug behaelt ----------------------------------------------------

def test_nur_die_begruessung_ist_keine_vorlage():
    """"Wie bitte?" direkt nach dem Hallo: ein zweites Hallo waere falsch.

    Die Regreeting-Wache streicht eine wiederholte Begruessung — der Zug bliebe
    stumm. Also gehoert der Satz dem normalen Weg (kurze Frage nach dem
    Anliegen).
    """
    sit = _sit()
    gruss = "Hallo, hier ist Bianca. Wie kann ich helfen?"
    sit["begruessungText"] = gruss
    assert metazug.zug(sit, "Wie bitte?", _msgs(gruss)) is None


def test_ruecklese_behaelt_der_fluss():
    """Auf einer Ruecklese eskaliert der Fluss selbst (Schreibweise frisch)."""
    sit = _sit()
    _buchung_laeuft(sit, frage="nachname_check")
    assert metazug.zug(sit, "Wie bitte?", _msgs("Ist das richtig?")) is None


# --- Notaus + Diktat --------------------------------------------------------

def test_notaus(monkeypatch):
    monkeypatch.setenv("META_LIVE", "0")
    sit = _sit()
    _buchung_laeuft(sit)
    assert metazug.zug(sit, "Wie bitte?", _msgs("Wie lautet Ihr Nachname?")) is None


def test_agent_laesst_das_diktat_in_ruhe():
    """"Nochmal die Sieben" ist eine Korrektur, keine Bitte um Wiederholung —
    im Diktat darf der Baustein nie zuschlagen (sonst frisst er die Nummer)."""
    from bianca import agent

    sit = _sit()
    s = _buchung_laeuft(sit, frage="telefon")
    s["telefonTeil"] = "0177"
    agent.user_turn(sit, "Nochmal die Sieben.")
    spuren = [e.get("w") for e in (sit.get("_spur") or [])]
    assert "meta-live" not in spuren


def test_agent_wiederholt_ohne_modell():
    """Der Zug ist deterministisch — das Modell darf nicht laufen."""
    from bianca import agent
    from kern import llm

    def _knall(*a, **k):
        raise AssertionError("LLM darf bei einer Meta-Bitte nicht laufen")

    echt_chat, echt_stream = llm.chat, llm.chat_stream
    llm.chat = _knall
    llm.chat_stream = _knall
    try:
        sit = _sit()
        s = _buchung_laeuft(sit, frage="")
        fid, frage = gehirn.naechste_frage(sit)
        s["frage"] = fid
        sit["messages"].append({"role": "assistant", "content": frage})
        aus = agent.user_turn(sit, "Wie bitte?")
        assert frage.split("?")[0][:18] in aus["text"]
        spuren = [e.get("w") for e in (sit.get("_spur") or [])]
        assert "meta-live" in spuren
    finally:
        llm.chat = echt_chat
        llm.chat_stream = echt_stream
