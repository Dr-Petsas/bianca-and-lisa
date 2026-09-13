"""W-FACH-WACHE (13.09.2026): beim Hautarzt spricht Bianca nie Zahnmedizin.

Chef (Punkt 8, 13.09.2026): "bei blessing darf auf gar keinen Fall ein
zahnmedizinischer Einfluss oder gesprächsverlauf entstehen keine
zahnmedizinischen Themen erlaubt".

Die Maschine ist katalog-gegated (tests/test_zahn_katalog.py). Hier geht es
um den LLM-Ausgang: das Modell darf einem Anrufer der Hautarztpraxis keinen
Zahn-Satz sagen — auch nicht im P5-Streaming. Gegenproben sind der teurere
Teil: MedDent (Zahn) bleibt unberuehrt, Derma-Vokabular (Prophylaxe,
Fuellung=Filler) wird nie gestrichen, ohne bekanntes Fach bleibt die Wache aus.
Alles offline: kein LLM, kein Netz.
"""

from __future__ import annotations

import pytest

from bianca import agent as bianca_agent
from bianca import flow, gehirn
from kern import fach_wache, hirn
from kern.tenants import laden

KAT_BLESSING = [
    {"id": "haut", "name": "Hautkrebs-Screening", "duration": 10, "allowOnlineBooking": True},
    {"id": "akne", "name": "Akne / Rosacea / Ekzeme", "duration": 10, "allowOnlineBooking": True},
    {"id": "kontr", "name": "Kontrolle", "duration": 15, "allowOnlineBooking": True},
    {"id": "botox", "name": "Beratung Behandlung Botox / Filler", "duration": 10,
     "allowOnlineBooking": True},
]


def _blessing_sit(**extra) -> dict:
    sit = {
        "id": "fach-1",
        "tenant": {
            "clientId": "UUJnPzoYPa4yYyzcaGlm",
            "praxisName": "Hautarztpraxis Doktor Blessing",
            "fachgebiet": "dermatologie",
            "visitMotives": list(KAT_BLESSING),
            "calendars": [{"id": "cal-b", "name": "Doktor Charlotte Blessing"}],
            "booking": {"calendars": [{"id": "cal-b", "name": "Doktor Charlotte Blessing"}]},
            "wissen": {},
        },
        "motivKatalog": list(KAT_BLESSING),
        "messages": [{
            "role": "assistant",
            "content": "Hautarztpraxis Doktor Blessing, Sie sprechen mit Bianca. Wie kann ich helfen?",
        }],
        "sammler": {},
    }
    sit.update(extra)
    gehirn.sammler(sit)
    hirn.init(sit)
    return sit


def _meddent_sit() -> dict:
    t = laden("meddent")
    sit = {
        "id": "fach-2",
        "tenant": t,
        "motivKatalog": list(t.get("visitMotives") or []),
        "messages": [{"role": "assistant", "content": "Guten Tag."}],
        "sammler": {},
    }
    gehirn.sammler(sit)
    hirn.init(sit)
    return sit


@pytest.fixture(autouse=True)
def _kein_hintergrund(monkeypatch):
    monkeypatch.setattr(flow.hintergrund, "anstossen", lambda _sit: None)
    monkeypatch.delenv("FACH_WACHE", raising=False)


# --- Aktivierung -------------------------------------------------------------

def test_blessing_ist_scharf_meddent_nicht():
    assert fach_wache.aktiv(_blessing_sit()) is True
    assert fach_wache.aktiv(_meddent_sit()) is False


def test_ohne_bekanntes_fach_bleibt_die_wache_aus():
    """Leerer Katalog + kein fachgebiet = 'allgemein' — MedDent darf in der
    ersten Sekunde vor dem Katalog-Lauf nicht verstummen."""
    sit = {"tenant": {"praxisName": "Irgendwer", "visitMotives": []}, "motivKatalog": []}
    assert fach_wache.aktiv(sit) is False
    assert fach_wache.saeubern(sit, "Eine Zahnreinigung geht.")[0] == "Eine Zahnreinigung geht."
    assert fach_wache.aktiv(None) is False


def test_fachgebiet_reicht_auch_ohne_katalog():
    """Blessing traegt fachgebiet=dermatologie in der lokalen Datei — die
    Wache ist damit ab dem ERSTEN Zug scharf, auch wenn der Katalog noch
    laedt."""
    sit = {"tenant": {"fachgebiet": "dermatologie", "visitMotives": []}, "motivKatalog": []}
    assert fach_wache.aktiv(sit) is True


# --- Streichen ---------------------------------------------------------------

def test_zahn_satz_faellt_rest_bleibt():
    sit = _blessing_sit()
    neu, treffer = fach_wache.saeubern(
        sit, "Gerne. Eine Zahnreinigung kann ich Ihnen gleich mit anbieten. Wann passt es Ihnen?")
    assert neu == "Gerne. Wann passt es Ihnen?"
    assert treffer and treffer[0].lower() == "zahnreinigung"


@pytest.mark.parametrize("text", [
    "Bei Zahnschmerzen sollten Sie zeitnah zum Zahnarzt gehen.",
    "Die PZR kostet etwa 120 Euro.",
    "Ein Bleaching dauert eine Stunde länger.",
    "Ihre Krone muss der Zahnarzt prüfen.",
    "Für das Implantat brauchen wir eine Besprechung.",
    "Der Weisheitszahn kann gezogen werden.",
    "Ihre Zähne werden professionell gereinigt.",
    "Karies behandeln wir mit einer Wurzelbehandlung.",
])
def test_nur_zahn_wird_ehrlicher_fachsatz(text):
    sit = _blessing_sit()
    neu, treffer = fach_wache.saeubern(sit, text)
    assert treffer
    assert neu == "Das gehört nicht zu unserer Praxis — wir sind eine Hautarztpraxis."
    assert not fach_wache.zahn_treffer(neu)


@pytest.mark.parametrize("text", [
    "Die Hautkrebs-Prophylaxe ist einmal im Jahr sinnvoll.",
    "Filler dienen der Füllung von Falten.",
    "Wir sehen uns die Brücke Ihrer Nase an.",
    "Bringen Sie die Überweisung bitte mit.",
    "Zur Hautkontrolle passt Dienstag um zehn.",
    "Eine Kontrolle bei Doktor Blessing — wann passt es Ihnen?",
    "Der Mundwinkel ist entzündet, das schaut sich die Ärztin an.",
])
def test_derma_saetze_bleiben_unberuehrt(text):
    sit = _blessing_sit()
    assert fach_wache.saeubern(sit, text) == (text, [])


def test_zahnpraxis_bleibt_komplett_unberuehrt():
    sit = _meddent_sit()
    text = "Die Zahnreinigung buche ich mit ein. Ihre Krone schaut Doktor Petsas an."
    assert fach_wache.saeubern(sit, text) == (text, [])


def test_abkuerzung_wird_nicht_zerschnitten():
    """Satz-Split ueber sprech.tts_saetze: 'Dr.' ist kein Satzende."""
    sit = _blessing_sit()
    neu, _ = fach_wache.saeubern(
        sit, "Dr. Blessing ist heute da. Zahnstein entfernen wir nicht.")
    assert neu == "Dr. Blessing ist heute da."


# --- Agent-Einhaengung -------------------------------------------------------

def test_agent_wache_streicht_und_spurt():
    sit = _blessing_sit()
    aus = bianca_agent._fach_wache_anwenden(
        sit, "Alles klar. Die Zahnreinigung machen wir mit. Wann passt es?")
    assert aus == "Alles klar. Wann passt es?"
    assert any(e.get("w") == "fach-wache" for e in sit.get("_spur") or []), sit.get("_spur")


def test_shadow_aendert_nichts(monkeypatch):
    monkeypatch.setenv("FACH_WACHE", "shadow")
    sit = _blessing_sit()
    text = "Die Zahnreinigung machen wir mit."
    assert bianca_agent._fach_wache_anwenden(sit, text) == text


def test_notaus_haelt_die_wache_an(monkeypatch):
    monkeypatch.setenv("FACH_WACHE", "off")
    sit = _blessing_sit()
    text = "Die Zahnreinigung machen wir mit."
    assert bianca_agent._fach_wache_anwenden(sit, text) == text


def test_llm_zug_beim_hautarzt_ohne_zahn(monkeypatch):
    """Ende-zu-Ende ueber user_turn: das Modell antwortet zahnaerztlich auf
    'Zahnschmerzen' beim Hautarzt — der Anrufer hoert es nie."""
    monkeypatch.setattr(
        bianca_agent.llm, "chat",
        lambda *_a, **_k: {
            "ok": True,
            "text": ("Das tut mir leid. Bei Zahnschmerzen sollten Sie zum Zahnarzt gehen. "
                     "Eine Zahnreinigung könnten wir auch anbieten."),
            "tool_calls": [],
        },
    )
    monkeypatch.setattr(bianca_agent.intent, "enabled", lambda: False)
    monkeypatch.setattr(bianca_agent.tasks, "zug", lambda *_a, **_k: None)
    monkeypatch.setattr(bianca_agent.task_router, "braucht_auswahl", lambda _sit: False)
    monkeypatch.setattr(bianca_agent.llm, "chat_stream", bianca_agent.llm.chat)

    sit = _blessing_sit()
    aus = bianca_agent.user_turn(sit, "Ich habe seit gestern starke Zahnschmerzen.")
    text = aus["text"]
    assert text.strip(), "kein stummer Zug"
    assert not fach_wache.zahn_treffer(text), text
    # Der Verlauf traegt ebenfalls die gesaeuberte Fassung — sonst plaudert
    # das Modell im naechsten Zug auf dem Zahn-Satz weiter.
    letzte = [m for m in sit["messages"] if m.get("role") == "assistant"][-1]["content"]
    assert not fach_wache.zahn_treffer(letzte), letzte


# --- EINGANGS-Seite (Live-Probe 14.09.2026) -----------------------------------

def test_zahnanliegen_beim_hautarzt_startet_keine_buchung():
    """Live-Probe 14.09.2026 00:50 (Blessing): "Ich habe furchtbare
    Zahnschmerzen und brauche schnell einen Termin" -> Bianca fragte "Waren
    Sie schon einmal bei uns?" — der ZAHN-Buchungsfluss lief beim HAUTARZT an.
    Jetzt: ehrlicher Verweis, kein Fluss, kein Zahn-Wort, kein Modell."""
    sit = _blessing_sit()
    aus = bianca_agent.user_turn(
        sit, "Ich habe furchtbare Zahnschmerzen und brauche schnell einen Termin.")
    text = aus["text"]
    assert "Hautarztpraxis" in text, text
    assert not fach_wache.zahn_treffer(text), text
    assert not aus.get("book")
    s = gehirn.sammler(sit)
    assert s.get("modus") in ("", None), s.get("modus")
    assert not s.get("frage"), s.get("frage")
    assert any(e.get("w") == "fach-wache-eingang" for e in sit.get("_spur") or []), sit.get("_spur")


@pytest.mark.parametrize("satz", [
    "Ich brauche eine professionelle Zahnreinigung.",
    "Ich möchte einen Termin beim Zahnarzt.",
    "Ich habe Karies und brauche eine Wurzelbehandlung.",
    "Mein Weisheitszahn tut weh.",
])
def test_fremdes_anliegen_erkannt(satz):
    assert fach_wache.fremdes_anliegen(_blessing_sit(), satz)


@pytest.mark.parametrize("satz", [
    # Kontaktallergie ist Hautarzt-Alltag — "Zahnpasta" ist kein Zahn-Anliegen.
    "Ich habe eine Allergie gegen meine Zahnpasta bekommen.",
    # Ueberweisung VOM Zahnarzt: der Anrufer gehoert hierher.
    "Mein Zahnarzt hat mich wegen einem Ausschlag zu Ihnen überwiesen.",
    "Ich habe einen akuten Ausschlag am Arm.",
    "Ich möchte einen Termin zur Hautkrebsvorsorge.",
    "Ich brauche ein Rezept für meine Salbe.",
])
def test_fremdes_anliegen_gegenproben(satz):
    """Der teurere Fehler: ein echter Hautarzt-Patient wird weggeschickt."""
    assert fach_wache.fremdes_anliegen(_blessing_sit(), satz) == ""


def test_fremdes_anliegen_nie_bei_zahnpraxis_und_ohne_fach():
    assert fach_wache.fremdes_anliegen(_meddent_sit(), "Ich habe Zahnschmerzen.") == ""
    sit = _blessing_sit()
    sit["tenant"].pop("fachgebiet", None)
    sit["tenant"]["visitMotives"] = []
    sit["motivKatalog"] = []
    assert fach_wache.fremdes_anliegen(sit, "Ich habe Zahnschmerzen.") == ""


def test_fremdes_anliegen_laesst_laufende_aufgabe_stehen():
    """Mitten in einer echten Haut-Buchung faellt ein Zahn-Satz: Verweis PLUS
    die offene Pflichtfrage — der Faden reisst nicht."""
    sit = _blessing_sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": False, "frage": "grund"})
    sit["flussFrage"] = "Worum geht es denn bei dem Termin?"
    aus = bianca_agent.user_turn(sit, "Ach, und Zahnschmerzen habe ich auch noch.")
    assert "Hautarztpraxis" in aus["text"], aus["text"]
    assert "Worum geht es" in aus["text"], aus["text"]
    assert gehirn.sammler(sit)["modus"] == "buchen"


def test_fremdes_anliegen_shadow_und_off(monkeypatch):
    monkeypatch.setenv("FACH_WACHE", "shadow")
    assert fach_wache.fremdes_anliegen(_blessing_sit(), "Ich habe Zahnschmerzen.") == ""
    monkeypatch.setenv("FACH_WACHE", "off")
    assert fach_wache.fremdes_anliegen(_blessing_sit(), "Ich habe Zahnschmerzen.") == ""


def test_llm_zug_bei_meddent_behaelt_zahn(monkeypatch):
    """Gegenprobe: in der Zahnpraxis ist Zahn-Vokabular der Job."""
    monkeypatch.setattr(
        bianca_agent.llm, "chat",
        lambda *_a, **_k: {
            "ok": True,
            "text": "Gerne, die Zahnreinigung nehme ich mit auf.",
            "tool_calls": [],
        },
    )
    monkeypatch.setattr(bianca_agent.intent, "enabled", lambda: False)
    monkeypatch.setattr(bianca_agent.tasks, "zug", lambda *_a, **_k: None)
    monkeypatch.setattr(bianca_agent.task_router, "braucht_auswahl", lambda _sit: False)
    monkeypatch.setattr(bianca_agent.llm, "chat_stream", bianca_agent.llm.chat)

    sit = _meddent_sit()
    aus = bianca_agent.user_turn(sit, "Ich hätte gern eine Zahnreinigung.")
    assert "Zahnreinigung" in aus["text"]


# --- Punkt 6: 116 117 nur mit Blessing-Notfallregel ---------------------------

from kern import praxisregeln  # noqa: E402


def test_zahnpraxis_nennt_nie_den_bereitschaftsdienst():
    sit = _meddent_sit()
    text = ("Das tut mir leid. Wenden Sie sich bitte an den ärztlichen "
            "Bereitschaftsdienst unter 116 117. Möchten Sie einen Akut-Termin?")
    neu = bianca_agent._notdienst_wache_anwenden(sit, text)
    assert "116" not in neu
    assert neu == "Das tut mir leid. Möchten Sie einen Akut-Termin?"
    assert any(e.get("w") == "notdienst-wache" for e in sit["_spur"])


@pytest.mark.parametrize("text", [
    "Rufen Sie die 116117 an.",
    "Der Bereitschaftsdienst hat die Nummer 116 117.",
    "Wählen Sie 1 1 6 1 1 7.",
])
def test_nur_notdienst_wird_ehrlicher_satz(text):
    sit = _meddent_sit()
    neu = bianca_agent._notdienst_wache_anwenden(sit, text)
    assert "116" not in neu and "1 1 6" not in neu
    assert neu == "Bei akuten Beschwerden helfen wir Ihnen hier in der Praxis weiter."


def test_blessing_mit_db_marker_darf_116117_sagen():
    """Die Blessing-Notfallregel kommt per DB-Marker — dort ist der Verweis
    gewollt (Chef 09.09.2026) und bleibt stehen."""
    sit = _blessing_sit()
    sit["tenant"]["dbPrompt"] = f"{praxisregeln.NOTFALL_MARKER}: Sprechzeiten Mo-Fr 8-17 Uhr."
    text = "Wenden Sie sich bitte an den Bereitschaftsdienst unter 116 117."
    assert bianca_agent._notdienst_wache_anwenden(sit, text) == text


def test_feste_notfallantwort_nur_mit_marker():
    """Die deterministische Notfall-Antwort (mit 116 117) faellt in
    Zahnpraxen nie — sie haengt am DB-Marker."""
    med = laden("meddent")
    assert praxisregeln.notfall_antwort(med, "Ich habe starke Schmerzen und Blutung") == ""
    assert praxisregeln.notdienst_erlaubt(med) is False


def test_andere_zahlen_bleiben():
    sit = _meddent_sit()
    text = "Die Praxis hat die Nummer 0211 1161170 und öffnet um 11 Uhr 6."
    assert bianca_agent._notdienst_wache_anwenden(sit, text) == text
