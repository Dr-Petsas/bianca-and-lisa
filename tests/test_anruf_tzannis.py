"""Live-Anruf e5c25e25 (13.09.2026, Sohn-Termin) — die vier Befunde des Chefs.

Wortlaut: "dieses gespräch ist auch komplett in die Hose gegangen. da gab es
eine 100prozentige wiederholung […] der Nachname wurde nicht richtig erkannt
und sie springt trotzdem vor der klärung zum vornamen weiter […] der einwand
des anrufers wird überhört!! […] es ist von einem SOHN die rede, wieso sagt
Bianca dann dass es sich um den Termin bei FRAU tzannis handelt […] 'der
frühere' wurde nicht in seinem relativen bezug verstanden."

Die Wiederholung selbst haengt an der Satzkarte und steht in
tests/test_unterbrechung.py (dort liegen die echten Barge-Zahlen). Hier:
Einwand, Geschlecht aus der Rolle und die relative Slotwahl — offline, ohne
LLM, ohne Netz.
"""

from __future__ import annotations

from bianca import flow, gehirn
from kern.tenants import laden


def _sit() -> dict:
    return {"tenant": laden("meddent"), "messages": [{"role": "system", "content": "x"}]}


def _buchung(**felder) -> tuple[dict, dict]:
    sit = _sit()
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    s["warSchonMal"] = True
    s.update(felder)
    return sit, s


# --- Befund 2: der Einwand gegen den verhoerten Nachnamen ------------------

def test_einwand_gegen_verhoerten_nachnamen_wird_quittiert():
    """Live kam auf "Thomas." der Widerspruch — und Bianca sagte nur "Danke."

    Der Anrufer muss HOEREN, dass seine Korrektur angekommen ist; sonst
    wiederholt er sie (live dreimal) und legt am Ende auf."""
    sit, s = _buchung(nachname="Thomas", frage="vorname")
    neu = gehirn.einsammeln(sit, "Nein, nein, nein, nein, nicht Thomas, Thannes ist mein Nachname.")
    assert s["nachname"] == "Thannes"
    quittung = flow._quittung(s, neu)
    assert "Thomas" in quittung and "Thannes" in quittung
    assert "Entschuldigung" in quittung


def test_korrigierter_nachname_wird_sofort_geklaert():
    """"sie springt trotzdem vor der klärung zum vornamen weiter": nach dem
    zweiten Verhoerer in Folge wird der Nachname SOFORT buchstabiert — nicht
    erst nach Grund und Wunschzeit (live sechs Zuege spaeter)."""
    sit, s = _buchung(nachname="Thomas", frage="vorname",
                      arzt={"typ": "genannt", "calendarName": "Dr. Petsas"})
    gehirn.einsammeln(sit, "Nicht Thomas, Thannes ist mein Nachname.")
    frage, text = gehirn.naechste_frage(sit)
    assert frage == "buchstabieren", f"stattdessen: {frage} / {text}"
    assert "Thannes" in text


def test_erste_nennung_ist_keine_korrektur():
    """Gegenprobe — der teurere Fehler waere, jede normale Namensaufnahme als
    Korrektur zu quittieren ("ich hatte gehört …") und zusaetzlich
    buchstabieren zu lassen."""
    sit, s = _buchung(frage="buchstabieren",
                      arzt={"typ": "genannt", "calendarName": "Dr. Petsas"})
    neu = gehirn.einsammeln(sit, "Mein Nachname ist Thannes.")
    assert s["nachname"] == "Thannes"
    assert "hatte" not in flow._quittung(s, neu)
    assert gehirn.naechste_frage(sit)[0] == "vorname", "keine Buchstabier-Schleife"


def test_ausdrueckliche_zuweisung_ist_keine_buchstabierkette():
    """`buchstaben.teil("Mein Nachname ist Thannes.")` liefert das Fragment
    "h" — damit verschwand die Angabe ungehoert und Bianca antwortete "Den
    Anfang habe ich. Bitte mit den restlichen Buchstaben weiter"."""
    sit, s = _buchung(frage="buchstabieren", buchstabenTeil="th")
    gehirn.einsammeln(sit, "Mein Nachname ist Thannes.")
    assert s["nachname"] == "Thannes"
    assert s["buchstabenTeil"] == "", "die alte Kette gehoerte zum verhoerten Namen"


def test_buchstabierter_nachname_beendet_die_klaerung():
    """Nach der Buchstabierung ist die Klaerung durch — keine Endlosfrage."""
    sit, s = _buchung(nachname="Thomas", frage="vorname",
                      arzt={"typ": "genannt", "calendarName": "Dr. Petsas"})
    gehirn.einsammeln(sit, "Nicht Thomas, Thannes ist mein Nachname.")
    frage, _ = gehirn.naechste_frage(sit)
    assert frage == "buchstabieren"
    s["frage"] = frage  # das macht live der Fluss, wenn er die Frage stellt
    gehirn.einsammeln(sit, "T-Z-A-N-N-I-S.")
    assert s["nachname"] == "Tzannis"
    assert s["buchstabiert"]
    assert gehirn.naechste_frage(sit)[0] == "vorname"


# --- Befund 3: Sohn-Termin, aber "Frau Tzannis" ----------------------------

def test_sohn_ueberstimmt_die_vornamen_schaetzung():
    """"das geschlecht wurde mehrfach genannt": Rolle Sohn ist maennlich —
    egal was der Vornamen-Waechter zu "Levy" meint (Chef-Default bei
    unklarem Vornamen ist WEIBLICH, live wurde daraus "Frau Tzannis")."""
    sit, s = _buchung(fuerWen="sohn", vorname="Levy", nachname="Tzannis")
    gehirn.geschlecht_aus_rolle(s)
    assert s["geschlecht"] == "m"
    assert s["geschlechtQuelle"] == "rolle"
    assert gehirn.anrede(s) == "Herr Tzannis"


def test_tochter_ist_weiblich_auch_bei_maennlichem_vornamen():
    sit, s = _buchung(fuerWen="tochter", vorname="Andrea", nachname="Tzannis")
    gehirn.geschlecht_aus_rolle(s)
    assert s["geschlecht"] == "f"
    assert gehirn.anrede(s) == "Frau Tzannis"


def test_kartei_geschlecht_bleibt_staerker_als_die_rolle():
    """Die Akte ist die Wahrheit: "mein Sohn Andrea" (Akte: weiblich) darf
    nicht gegen die Kartei umgeschrieben werden."""
    sit, s = _buchung(fuerWen="sohn", vorname="Andrea", nachname="Tzannis",
                      geschlecht="f", geschlechtQuelle="akte")
    gehirn.geschlecht_aus_rolle(s)
    assert s["geschlecht"] == "f"


def test_geschlechtsneutrale_rolle_raet_nicht():
    """"mein Kind" / "die Person" sagt nichts ueber das Geschlecht — dann
    bleibt der Vornamen-Waechter zustaendig."""
    sit, s = _buchung(fuerWen="kind", vorname="Levy", nachname="Tzannis")
    gehirn.geschlecht_aus_rolle(s)
    assert not s["geschlecht"]


def test_rolle_setzt_geschlecht_beim_einsammeln():
    """Die Rolle kommt im Gespraech, nicht als Testfeld: "der Termin ist fuer
    meinen Sohn" muss im selben Zug das Geschlecht festlegen."""
    sit, s = _buchung(frage="vorname", nachname="Tzannis")
    gehirn.einsammeln(sit, "Der Termin ist für meinen Sohn.")
    assert s["fuerWen"] == "sohn"
    gehirn.einsammeln(sit, "Levy.")
    assert s["vorname"] == "Levy"
    assert s["geschlecht"] == "m", "Rolle Sohn schlaegt die Vornamen-Schaetzung"


# --- Befund 4: "der frühere" / "der späteste" ------------------------------

def _angebot() -> list[dict]:
    # Wie live: zwei Slots, der frühere zuerst genannt.
    return [
        {"iso": "2026-09-15T10:30:00", "calendarId": "k1"},
        {"iso": "2026-09-16T10:30:00", "calendarId": "k1"},
    ]


def test_der_fruehere_waehlt_den_ersten_slot():
    assert flow._slot_wahl("Der frühere.", _angebot()) == "2026-09-15T10:30:00"


def test_der_frueheste_und_eher_waehlen_ebenfalls_vorne():
    for satz in ("Den frühesten bitte.", "Lieber eher.", "Den ersten Termin."):
        assert flow._slot_wahl(satz, _angebot()) == "2026-09-15T10:30:00", satz


def test_der_spaetere_waehlt_den_letzten_slot():
    for satz in ("Der spätere.", "Den spätesten bitte.", "Lieber später."):
        assert flow._slot_wahl(satz, _angebot()) == "2026-09-16T10:30:00", satz


def test_spaeter_mit_eigenem_zeitwunsch_bleibt_kein_slotgriff():
    """"Geht es später, gegen vierzehn Uhr?" ist ein neuer Wunsch, keine Wahl
    aus der Liste — sonst wuerde der 16. bestaetigt, obwohl beide Angebote um
    zehn Uhr dreissig liegen."""
    assert not flow._slot_wahl("Geht es später, gegen vierzehn Uhr?", _angebot())


def test_relative_wahl_auch_bei_einem_angebot():
    einer = [{"iso": "2026-09-15T10:30:00", "calendarId": "k1"}]
    assert flow._slot_wahl("Der frühere.", einer) == "2026-09-15T10:30:00"
