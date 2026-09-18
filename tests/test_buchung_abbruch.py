"""W-BUCHUNG-ABBRUCH (17.09.2026) — der Anrufer will den Termin doch NICHT.

Befund `docs/BEFUND-BIANCA-ALLE-ANRUFE-2026-09-17.md` A4: 23 Readbacks ohne
Buchung. Live-Saetze wortgleich: "Ich mache den Termin online aus. Danke."
(05a5dd55), "Nein." / "Oh ne." (31b8842d), "Nein, danke." (4dfc81be) und
mitten im Slot-Angebot "Ich moechte das Telefon beenden, Termin nicht buchen."
(66913eb8). Vorher fragte Bianca bis zu dreimal "Was darf ich aendern?" oder
las das Angebot erneut vor.

Offline, ohne LLM, ohne Netz. Die Gegenproben (Fragen, "online geht nicht",
Besitz-Formen, Nebenfragen der Buchung) sind der wichtigere Teil: ein
falscher Treffer wirft eine halb fertige Buchung weg.
"""

import pytest

from bianca import flow, gehirn
from kern import abbruch
from kern.tenants import laden

KATALOG = [
    {"id": "kch-k", "name": "KCH Kontrolluntersuchung", "calendarIds": [],
     "allowOnlineBooking": True, "duration": 15},
]
SLOT = "2026-09-22T09:30:00+02:00"


# --- Erkenner ---------------------------------------------------------------

@pytest.mark.parametrize("satz, art", [
    # Live-Saetze
    ("Ich mache den Termin online aus. Danke.", "online"),
    ("Ich möchte das Telefon beenden, Termin nicht buchen.", "beenden"),
    ("Dann lege ich mal auf.", "beenden"),
    ("Ich lege jetzt auf.", "beenden"),
    # online
    ("Ich buche das lieber online.", "online"),
    ("Dann mache ich das über die Webseite.", "online"),
    ("Ist gut, dann online.", "online"),
    ("Habe ich schon online gemacht.", "online"),
    # spaeter
    ("Ich melde mich dann nochmal.", "spaeter"),
    ("Ich überlege es mir noch.", "spaeter"),
    ("Ich rufe später nochmal an.", "spaeter"),
    ("Das muss ich erst mit meiner Frau besprechen.", "spaeter"),
    # kein Termin
    ("Ich möchte doch keinen Termin.", "kein_termin"),
    ("Dann brauche ich keinen Termin.", "kein_termin"),
    ("Lassen Sie es, danke.", "kein_termin"),
    ("Hat sich erledigt.", "kein_termin"),
    ("Kein Interesse.", "kein_termin"),
    ("Bitte nicht eintragen.", "kein_termin"),
    ("Tragen Sie bitte nichts ein.", "kein_termin"),
    ("Ich will den Termin nicht mehr.", "kein_termin"),
    ("Lieber keinen Termin.", "kein_termin"),
    ("Nein, lieber gar keinen Termin.", "kein_termin"),
])
def test_abbruch_erkannt(satz, art):
    assert abbruch.erkannt(satz) == art


@pytest.mark.parametrize("satz", [
    # Fragen wollen eine Antwort, keinen Abbruch
    "Kann ich das auch online machen?",
    "Geht das auch online",
    "Wie lange dauert der Termin?",
    # online ging NICHT — deshalb ruft der Anrufer an
    "Online hat es nicht geklappt.",
    "Ich habe es online versucht, das ging nicht.",
    # Besitz / Verfuegbarkeit, kein Wunsch
    "Ich habe noch keinen Termin.",
    "Ich hatte bisher keinen Termin bei Ihnen.",
    "Es gibt also keinen Termin diese Woche.",
    "Haben Sie keinen Termin am Freitag?",
    # Teil-Nein / Behandler-Praeferenz
    "Ich brauche keinen Termin bei Doktor Nikolaou, der andere Arzt ist auch okay.",
    "Nein, keinen Termin für die Zahnreinigung.",
    # Korrektur, kein Abbruch
    "Ach, doch nicht Dienstag, lieber Mittwoch.",
    "Nein, der Name stimmt nicht.",
    # Bestandstermin = eigenes Anliegen
    "Ich möchte meinen Termin absagen.",
    "Können Sie den Termin verschieben?",
    # nicht auflegen
    "Bitte nicht gleich auflegen, ich suche den Kalender.",
    # ganz normale Antworten
    "Ja, gerne.",
    "Dienstag um halb zehn passt.",
    "Zur Kontrolle.",
])
def test_kein_abbruch(satz):
    assert abbruch.erkannt(satz) == ""
    assert abbruch.erkannt(satz, auf_bestaetigung=True) == ""


@pytest.mark.parametrize("satz", [
    "Nein, danke.", "Nein danke, nicht nötig.", "Danke, nein.",
    "Doch nicht.", "Nein, doch nicht.", "Lieber nicht.", "Dann lieber nicht.",
    "Gar keinen.",
])
def test_hoefliche_ablehnung_nur_auf_bestaetigung(satz):
    assert abbruch.erkannt(satz, auf_bestaetigung=True) == "kein_termin"
    # Ohne Bestaetigungsfrage (mitten in der Datenaufnahme) NICHT.
    assert abbruch.erkannt(satz) == ""


def test_nebenfrage_weiche_ablehnung_ist_kein_abbruch():
    # "Zahnreinigung mitbuchen?" / "SMS an diese Nummer?" — Nein heisst Nein
    # zur NEBENFRAGE, nicht zum Termin.
    for satz in ["Nein, danke.", "Kein Interesse.", "Lieber nicht.",
                 "Nein, das brauche ich nicht.", "Ich überlege es mir noch.",
                 "Hat sich erledigt.", "Nein, keinen Termin für die Zahnreinigung."]:
        assert abbruch.erkannt(satz, nebenfrage=True) == "", satz
        assert abbruch.erkannt(satz, auf_bestaetigung=True, nebenfrage=True) == "", satz


def test_nebenfrage_harter_termin_bezug_bricht_ab():
    assert abbruch.erkannt("Nein, dann doch keinen Termin.", nebenfrage=True) == "kein_termin"
    assert abbruch.erkannt("Ich möchte das Telefon beenden.", nebenfrage=True) == "beenden"
    assert abbruch.erkannt("Den Termin mache ich lieber online.", nebenfrage=True) == "online"
    assert abbruch.erkannt("Bitte nichts eintragen, ich will den Termin nicht.",
                           nebenfrage=True) == "kein_termin"


def test_ist_ablehnung_nur_reine_verneinung():
    for satz in ["Nein.", "Oh ne.", "Nee.", "Nö.", "Nein, danke.", "Nein, nichts."]:
        assert abbruch.ist_ablehnung(satz), satz
    for satz in ["Nein, der Name.", "Nein, die Nummer stimmt nicht.", "Der Zeitpunkt.",
                 "Nein, für meinen Sohn.", "Ja."]:
        assert not abbruch.ist_ablehnung(satz), satz


def test_doch_buchen_und_ende_wort():
    assert abbruch.doch_buchen("Doch, tragen Sie es ein.")
    assert abbruch.doch_buchen("Ach, ich möchte den Termin doch.")
    assert not abbruch.doch_buchen("Doch nicht.")
    assert not abbruch.doch_buchen("Nein.")
    assert abbruch.ist_ende_wort("Ich mache das online. Danke.")
    assert abbruch.ist_ende_wort("Tschüss!")
    assert not abbruch.ist_ende_wort("Ich melde mich dann.")


def test_notaus(monkeypatch):
    monkeypatch.setenv("BUCHUNG_ABBRUCH", "0")
    assert abbruch.erkannt("Ich möchte das Telefon beenden.") == ""
    assert abbruch.erkannt("Nein, danke.", auf_bestaetigung=True) == ""
    assert not abbruch.ist_ablehnung("Nein.")


# --- Fluss ------------------------------------------------------------------

def _sit() -> dict:
    return {"tenant": laden("meddent"),
            "messages": [{"role": "system", "content": "x"}],
            "motivKatalog": list(KATALOG)}


def _bis_bestaetigen(sit: dict) -> dict:
    """Readback-Stand: Slot liegt, 'Soll ich das so eintragen?' ist offen."""
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen", "warSchonMal": True,
        "vorname": "Martin", "nachname": "Berger", "buchstabiert": True,
        "telefon": "015253904756", "telefonOk": True,
        "arzt": {"typ": "name", "calendarId": "zex5bmv5jfIHWVW6zHbg",
                 "calendarName": "Doktor Michael Petsas"},
        "grund": "Kontrolluntersuchung", "motivId": "kch-k",
        "motivName": "KCH Kontrolluntersuchung", "wunsch": {},
        "slotIso": SLOT, "phase": "bestaetigen", "frage": "bestaetigung",
    })
    sit["offered"] = [{"iso": SLOT, "spoken": "Dienstag um halb zehn"}]
    sit["angebotKalender"] = {"calendarId": "zex5bmv5jfIHWVW6zHbg",
                              "calendarName": "Doktor Michael Petsas"}
    return s


@pytest.fixture(autouse=True)
def _ohne_hintergrund(monkeypatch):
    monkeypatch.setattr(flow.hintergrund, "anstossen", lambda sit: None)


def _abgebrochen(sit: dict, s: dict, art: str) -> None:
    ab = sit.get("buchungAbgebrochen") or {}
    assert ab.get("aktiv") is True and ab.get("art") == art, ab
    assert s["phase"] == "fertig" and s["frage"] in {"", "sonst_noch"}
    assert not s["slotIso"] and not sit.get("offered")


def test_31b8842d_nein_nein_beendet_die_buchung():
    """Live: 'Nein.' auf das Readback, 'Oh ne.' auf 'Was darf ich aendern?' —
    Bianca fragte dreimal dasselbe. Jetzt: Ausgang in der Aenderungsfrage,
    beim zweiten Nein ist Schluss — EIN Satz, EINE Abschlussfrage."""
    sit = _sit()
    s = _bis_bestaetigen(sit)
    z1 = flow.zug(sit, "Nein.")
    assert z1 and "ändern" in z1["text"].lower(), z1
    assert "keinen termin" in z1["text"].lower(), z1  # der Ausgang wird genannt
    assert s["frage"] == "aenderung" and s["slotIso"] == SLOT
    z2 = flow.zug(sit, "Oh ne.")
    assert z2, z2
    assert "trage ich nichts ein" in z2["text"].lower(), z2
    assert "ändern" not in z2["text"].lower()
    assert z2["text"].count("?") == 1 and "sonst noch" in z2["text"].lower(), z2
    assert not z2.get("hangup")
    _abgebrochen(sit, s, "kein_termin")
    assert s["frage"] == "sonst_noch"
    # Abschlussfrage verneint -> auflegen, kein Angebot mehr.
    z3 = flow.zug(sit, "Nein, danke.")
    assert z3 and z3.get("hangup"), z3
    assert "termin" not in z3["text"].lower()


def test_4dfc81be_nein_danke_auf_readback_ist_ende():
    sit = _sit()
    s = _bis_bestaetigen(sit)
    z = flow.zug(sit, "Nein, danke.")
    assert z and "trage ich nichts ein" in z["text"].lower(), z
    assert "ändern" not in z["text"].lower()
    # "danke" ist ein Ende-Wort: kein "Sonst noch etwas?", Abschied + auflegen.
    assert z.get("hangup") and "wiederhören" in z["text"].lower(), z
    _abgebrochen(sit, s, "kein_termin")


def test_05a5dd55_online_mit_danke_legt_auf():
    sit = _sit()
    s = _bis_bestaetigen(sit)
    z = flow.zug(sit, "Ich mache den Termin online aus. Danke.")
    assert z and "online" in z["text"].lower() and "nichts ein" in z["text"].lower(), z
    assert z.get("hangup"), z
    _abgebrochen(sit, s, "online")


def test_66913eb8_telefon_beenden_im_slot_angebot():
    """Mitten im Angebot: 'Ich moechte das Telefon beenden, Termin nicht
    buchen.' — live kam 'Ganz kurz bitte. Im Angebot sind: ...'."""
    sit = _sit()
    s = _bis_bestaetigen(sit)
    s["phase"] = "angebot"
    s["frage"] = "slotwahl"
    s["slotIso"] = ""
    sit["offered"] = [{"iso": SLOT, "spoken": "Dienstag um halb zehn"},
                      {"iso": "2026-09-23T11:00:00+02:00", "spoken": "Mittwoch um elf"}]
    z = flow.zug(sit, "Ich möchte das Telefon beenden, Termin nicht buchen.")
    assert z and z.get("hangup"), z
    assert "angebot" not in z["text"].lower() and "mittwoch" not in z["text"].lower()
    _abgebrochen(sit, s, "beenden")


def test_nein_der_name_bleibt_korrektur():
    """W-SCHLEIFE bleibt: 'Nein.' -> 'Der Name.' ist eine Korrektur, kein Abbruch."""
    sit = _sit()
    s = _bis_bestaetigen(sit)
    flow.zug(sit, "Nein.")
    z = flow.zug(sit, "Der Name.")
    assert z and not (sit.get("buchungAbgebrochen") or {}).get("aktiv"), z
    assert s["phase"] != "fertig" and s["slotIso"] == SLOT
    assert not s["nachname"]


def test_nebenfrage_pzr_nein_danke_bricht_nicht_ab(monkeypatch):
    """'Zahnreinigung mitbuchen?' -> 'Nein, danke.' meint die PZR — der Zug
    gehoert dem PZR-Zweig, die Buchung laeuft weiter."""
    sit = _sit()
    s = _bis_bestaetigen(sit)
    s["frage"] = "pzr"
    s["pzr"] = "gefragt"
    monkeypatch.setattr(flow, "_pzr_zug", lambda sit, t, melde=None: {"text": "PZR-ZWEIG"})
    for satz in ["Nein, danke.", "Kein Interesse.", "Lieber nicht."]:
        s["frage"] = "pzr"
        z = flow.zug(sit, satz)
        assert z and z["text"] == "PZR-ZWEIG", (satz, z)
        assert not (sit.get("buchungAbgebrochen") or {}).get("aktiv")
        assert s["slotIso"] == SLOT


def test_nebenfrage_mit_hartem_termin_bezug_bricht_ab():
    sit = _sit()
    s = _bis_bestaetigen(sit)
    s["frage"] = "pzr"
    s["pzr"] = "gefragt"
    z = flow.zug(sit, "Nein — dann doch lieber gar keinen Termin.")
    assert z and "trage ich nichts ein" in z["text"].lower(), z
    _abgebrochen(sit, s, "kein_termin")


def test_kein_abbruch_waehrend_diktat():
    """Mitten in der Nummern-Aufnahme urteilt der Diktat-Sammler, nicht der
    Abbruch-Erkenner (ein Fragment darf nie eine halbe Buchung wegwerfen)."""
    sit = _sit()
    s = _bis_bestaetigen(sit)
    s.update({"phase": "", "frage": "telefon", "telefon": "", "telefonOk": False,
              "telefonTeil": "0177"})
    flow.zug(sit, "Kein Interesse.")
    assert not (sit.get("buchungAbgebrochen") or {}).get("aktiv")


def test_doch_buchen_holt_denselben_termin_zurueck():
    sit = _sit()
    s = _bis_bestaetigen(sit)
    flow.zug(sit, "Nein, doch nicht.")
    _abgebrochen(sit, s, "kein_termin")
    z = flow.zug(sit, "Ach, doch — tragen Sie es bitte ein.")
    assert z and "soll ich das so eintragen" in z["text"].lower(), z
    assert s["slotIso"] == SLOT and s["phase"] == "bestaetigen"
    assert not (sit.get("buchungAbgebrochen") or {}).get("aktiv")


def test_nach_abbruch_kein_angebot_mehr_und_status_fuer_das_modell():
    sit = _sit()
    s = _bis_bestaetigen(sit)
    flow.zug(sit, "Ich überlege es mir noch.")
    _abgebrochen(sit, s, "spaeter")
    # Talk-Satz danach: kein Angebot, kein Readback — Talk-Schicht (None) mit
    # klarer Ansage an das Modell.
    z = flow.zug(sit, "Wo kann ich denn parken bei Ihnen?")
    assert z is None
    zeile = flow.status_zeile(sit)
    assert "ABGEBROCHEN" in zeile and "keinen Termin" in zeile
    assert s["phase"] == "fertig" and not s["slotIso"]


def test_abschied_nach_abbruch_legt_auf():
    sit = _sit()
    s = _bis_bestaetigen(sit)
    flow.zug(sit, "Ich melde mich dann nochmal.")
    _abgebrochen(sit, s, "spaeter")
    z = flow.zug(sit, "Danke, tschüss.")
    assert z and z.get("hangup"), z


def test_blessing_schliesst_nach_abbruch_kurz():
    """W-BLESSING-KNAPP: 'Sonst noch?' nur nach Erfolg — nach dem Abbruch
    Abschied + auflegen."""
    sit = _sit()
    sit["tenant"] = laden("blessing")
    s = _bis_bestaetigen(sit)
    z = flow.zug(sit, "Nein, doch nicht.")
    assert z and z.get("hangup"), z
    assert "sonst noch" not in z["text"].lower()
    _abgebrochen(sit, s, "kein_termin")
