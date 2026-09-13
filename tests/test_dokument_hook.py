"""Fix 1 (13.09.2026, Feldtest-Analyse): der Dokument-Hook in `flow.zug`
ist mandanten- und kontextscharf.

Vorher lief `praxisregeln.unterlagen_antwort` fuer JEDEN Mandanten und bei
jeder Nennung von Rezept/Ueberweisung/Befund — MedDent und Thaler sprachen
Blessings festen Vorsprache-Text, „Ich bin vom Hausarzt ueberwiesen" und
„Termin zur Befundbesprechung" wurden mitten in der Buchung abgefangen, und
die offene Frage der Kette wurde geleert.

Die Gegenproben (Blessing bekommt den Text weiterhin) sind der teurere
Fehler und deshalb genauso breit abgedeckt.
"""

from bianca import flow
from kern import praxisregeln


BLESSING_PROMPT = f"""
# Besondere Features:
- {praxisregeln.DOKUMENT_MARKER}: Rezepte und Überweisungen nur persönlich.
"""


def _blessing() -> dict:
    return {"praxisName": "Hautarztpraxis Doktor Blessing",
            "dbPrompt": BLESSING_PROMPT}


def _meddent() -> dict:
    return {"praxisName": "Zahnärzte im Medical Center Düsseldorf",
            "fachtemplate": "zahnmedizin", "dbPrompt": ""}


def _sit(tenant: dict) -> dict:
    return {"tenant": tenant,
            "messages": [{"role": "system", "content": "x"}]}


# --- Mandanten-Schaerfe -------------------------------------------------------

def test_meddent_rezeptwunsch_bekommt_keinen_blessing_text():
    """Ohne DB-Marker gilt der Notiz-/Rueckruf-Weg — nie „nur persoenlich"."""
    for satz in ("Ich brauche ein Rezept.",
                 "Können Sie mir eine Überweisung zum Kieferorthopäden ausstellen?",
                 "Ich hätte gern ein neues Rezept für mein Schmerzmittel."):
        assert praxisregeln.unterlagen_antwort(_meddent(), satz) == "", satz


def test_blessing_rezeptwunsch_bekommt_weiter_den_vorsprache_text():
    for satz in ("Ich brauche ein Rezept.",
                 "Kann ich eine Überweisung zum Allergologen bekommen?",
                 "Ich möchte mein Rezept verlängern lassen.",
                 "Können Sie mir ein Rezept ausstellen?",
                 "Mein Rezept ist abgelaufen."):
        text = praxisregeln.unterlagen_antwort(_blessing(), satz)
        assert "persönlich in die Praxis" in text, satz


def test_dokument_anforderung_erkennt_wunsch_und_besitz():
    assert praxisregeln.dokument_anforderung("Ich brauche eine Überweisung.")
    assert praxisregeln.dokument_anforderung("Schicken Sie mir das Rezept zu?")
    assert not praxisregeln.dokument_anforderung(
        "Ich habe eine Überweisung vom Hausarzt.")
    assert not praxisregeln.dokument_anforderung(
        "Ich bin von Doktor Grüger überwiesen worden.")
    assert not praxisregeln.dokument_anforderung("Hallo, ich brauche einen Termin.")


# --- Kontext-Schaerfe: Ueberweisung HABEN ist ein Buchungsgrund ---------------

def test_ueberwiesener_anrufer_ist_kein_dokumentwunsch_bei_blessing():
    """Blessing: „Ich habe eine Ueberweisung vom Hausarzt und brauche einen
    Termin" ist eine Buchung — der Vorsprache-Text darf hier nie kommen."""
    for satz in ("Ich habe eine Überweisung vom Hausarzt und brauche einen Termin.",
                 "Ich bin vom Hausarzt zu Ihnen überwiesen worden.",
                 "Mein Hausarzt hat mir eine Überweisung mitgegeben, ich bräuchte einen Termin.",
                 "Ich komme mit einer Überweisung, wann haben Sie Zeit?"):
        assert praxisregeln.unterlagen_antwort(_blessing(), satz) == "", satz


def test_ueberwiesener_anrufer_bei_meddent_bleibt_in_der_buchung():
    sit = _sit(_meddent())
    s = flow.gehirn.sammler(sit)
    s.update({"modus": "buchen", "frage": "grund"})
    res = flow.zug(sit, "Ich bin von Doktor Grüger überwiesen worden.")
    text = (res or {}).get("text", "")
    assert "persönlich in die Praxis" not in text
    assert "gesicherten Dienstweg" not in text
    assert s["modus"] == "buchen"


# --- Kontext-Schaerfe: Befund/Roentgen als TERMIN ------------------------------

def test_befundbesprechung_und_roentgentermin_sind_termine():
    for satz in ("Ich brauche einen Termin zur Befundbesprechung.",
                 "Ich möchte einen Termin zum Röntgen.",
                 "Ich soll noch einmal geröntgt werden, wann kann ich kommen?",
                 "Ich hätte gern einen Röntgentermin.",
                 "Wir sollten die Befunde besprechen."):
        assert praxisregeln.unterlagen_antwort(_meddent(), satz) == "", satz


def test_zahnarzt_unterlagen_anforderung_bleibt_dienstweg():
    """Gegenprobe: echte Herausgabe-Wuensche bekommen weiter den Dienstweg."""
    for satz in ("Können Sie mir die Röntgenbilder zuschicken?",
                 "Ich brauche eine Kopie meiner Behandlungsunterlagen.",
                 "Ich möchte meine Röntgenaufnahmen mitnehmen."):
        text = praxisregeln.unterlagen_antwort(_meddent(), satz)
        assert "gesicherten Dienstweg" in text, satz


def test_roentgen_ohne_anforderung_faellt_durch():
    """Blosse Nennung ist kein Wunsch — z. B. Angst vor Strahlung."""
    assert praxisregeln.unterlagen_antwort(
        _meddent(), "Muss dabei geröntgt werden?") == ""
    assert praxisregeln.unterlagen_antwort(
        _meddent(), "Der Befund war beim letzten Mal unauffällig.") == ""


# --- Kette bleibt stehen -------------------------------------------------------

def test_blessing_dokumentwunsch_mitten_in_der_buchung_haelt_die_kette():
    """Laeuft eine Aufgabe mit offener Frage, gibt Bianca die Auskunft und
    stellt die offene Frage im SELBEN Zug erneut — `frage` wird nicht geleert."""
    sit = _sit(_blessing())
    sit["flussFrage"] = "Wie ist Ihr Nachname?"
    s = flow.gehirn.sammler(sit)
    s.update({"modus": "buchen", "frage": "nachname", "phase": "sammeln"})
    res = flow.zug(sit, "Ach, und ich brauche noch ein Rezept.")
    assert res and "persönlich in die Praxis" in res["text"]
    assert res["text"].rstrip().endswith("Wie ist Ihr Nachname?")
    assert s["frage"] == "nachname"
    assert s["modus"] == "buchen"


def test_blessing_dokumentwunsch_ohne_aufgabe_schliesst_wie_bisher():
    sit = _sit(_blessing())
    s = flow.gehirn.sammler(sit)
    res = flow.zug(sit, "Ich brauche ein Rezept.")
    assert res and "persönlich in die Praxis" in res["text"]
    assert s["frage"] == ""
