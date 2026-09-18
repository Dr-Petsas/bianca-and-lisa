"""Anruf 53986f42 (Blessing, 17.09.2026) — Nachstellung Ende-zu-Ende ohne Modell.

Befund `docs/BEFUND-BIANCA-ALLE-ANRUFE-2026-09-17.md` (C1/C3): der Anrufer
("Hallo, Busch, guten Morgen!") kam ueber 21 Zuege nie zum Termin. Live:
`modus` fiel nach dem Buchstabieren weg, "guten Morgen" wurde als "morgen"
gelesen, "Und der Vorname?" kam fuenfmal wortgleich, "Ja." auf zwei Slots und
die vorab diktierte Rufnummer liefen ans freie Modell, das Erfolge erfand.

Hier laeuft dieselbe Zugfolge (plus die hypothetische Fortsetzung bis zum
Eintragen) gegen den Code — jede LLM-Anfrage ist ein Testbruch. Dazu die
Bausteine einzeln: Namens-Ernte, Rueckfragen auf die Namensfrage (C3), blankes
Ja auf ein Mehrfach-Angebot, Nummern-Diktat waehrend der Slot-Wahl, Praefix-
Rotation, Ziffernwoerter sind kein Inhalt, technischer Buchungsfehler ohne
Schleife (W-BUCHUNG-TECHNIK).
"""

import json

import pytest

from bianca import agent, flow, gehirn, hintergrund, session, telefon, verwalten
from kern import calendar as kal, gespraech, llm, stille
from kern.tenants import laden

SLOTS = {
    "ok": True,
    "slots": [
        {"iso": "2026-09-24T09:30", "date": "2026-09-24", "time": "09:30",
         "calendarId": "cal-bl", "doctorName": "Doktor Blessing"},
        {"iso": "2026-09-24T11:15", "date": "2026-09-24", "time": "11:15",
         "calendarId": "cal-bl", "doctorName": "Doktor Blessing"},
        {"iso": "2026-09-25T14:40", "date": "2026-09-25", "time": "14:40",
         "calendarId": "cal-bl", "doctorName": "Doktor Blessing"},
    ],
}

LIVE_ZUEGE = [
    "Hallo, Busch, guten Morgen!",
    "Ich bräuchte einen Termin bei der Frau Doktor Blessing.",
    "Busch, mein Name.",
    "Die Bitte.",
    "Nee, ich war schon bei Ihnen in der Praxisweise, Frau Doktor.",
    "B, U, S, C, H, Busch, Fertig, Nachname.",
    "Ja, mein Nachname, warte.",
    "Schon.",
    "um eine Nachsicht meiner Haut, ich habe da Bedenken, dass man etwas machen müsste, also ich weiss nicht weiter.",
    "Ich habe Symptome, mit dem ich veranlassen, dass ich einen Termin bräuchte bei Frau Doktor, der Hausarzt ist auch der Meinung.",
    "Da.",
    "Ja, bitte.",
    "Vormittag oder Nachmittag, eigentlich egal.",
    "Nein, den frühesten Termin, bitte.",
    "Ja.",
    "Ja, das würde passen.",
    "Yelto, J, E, L, B, O, tattig.",
    "Jelto ist der Vorname. Ich buchstabiere. J-E-L-T-O. Fertig.",
    "Null, sieben, eins, zwei, neun.",
    "Fünf, drei, eins, sechs.",
    "Ja.",
]
FORTSETZUNG = [
    "Den Donnerstag.",
    "Ja.",
    "Nein.",
    "Das war die ganze Nummer, fertig.",
    "Ja, richtig.",
    "Nein, danke.",
]


@pytest.fixture
def ohne_modell(monkeypatch):
    """LLM = Testbruch, Kalender gestubbt, Hintergrund stumm."""
    monkeypatch.setenv("INTENT_NACHZUG", "0")
    monkeypatch.setenv("WRITE_LIVE", "0")

    def _knall(*a, **k):
        raise AssertionError(f"LLM darf hier nicht laufen: {a[0][-1] if a and a[0] else ''}")

    monkeypatch.setattr(llm, "chat", _knall)
    monkeypatch.setattr(llm, "chat_stream", _knall)
    monkeypatch.setattr(agent.llm, "chat", _knall)
    monkeypatch.setattr(agent.llm, "chat_stream", _knall)
    monkeypatch.setattr(flow.hintergrund, "anstossen", lambda *a, **k: None)
    for name in ("vorrat_anstossen", "kartei_von_anrufer"):
        if hasattr(hintergrund, name):
            monkeypatch.setattr(hintergrund, name, lambda *a, **k: None)
    for fn in ("find_slots", "find_slots_behandler", "find_slots_raeume"):
        if hasattr(kal, fn):
            monkeypatch.setattr(kal, fn, lambda *a, **k: json.loads(json.dumps(SLOTS)))
    for fn in ("search_patients", "find_patient", "patient_suchen"):
        if hasattr(kal, fn):
            monkeypatch.setattr(kal, fn, lambda *a, **k: {"ok": True, "patients": []})
    yield


def _book_ok(*a, **k):
    iso = k.get("slot_iso") if k else (a[1] if len(a) > 1 else "")
    return {"ok": True, "booked": True, "verified": True, "slotIso": iso,
            "appointmentId": "apt-1", "patientId": "pat-1",
            "spoken": "Der Termin ist fest eingetragen."}


def _book_kaputt(*a, **k):
    return {"ok": False,
            "spoken": "Das hat gerade nicht geklappt. Die Praxis ruft Sie dazu zurück.",
            "regie": "Buchung fehlgeschlagen (500). Keinen Erfolg behaupten."}


def _lauf(sit: dict, zuege: list[str]) -> list[dict]:
    aus = []
    for satz in zuege:
        r = agent.user_turn(sit, satz)
        assert r is not None, satz
        aus.append({"a": satz, **r})
        if r.get("hangup"):
            break
    return aus


def _texte(aus: list[dict]) -> list[str]:
    return [(x.get("text") or "").strip() for x in aus]


def _keine_wortgleiche_schleife(texte: list[str], max_folge: int = 2) -> None:
    """Keine Ansage darf mehr als `max_folge`-mal in FOLGE wortgleich kommen."""
    folge = 1
    for a, b in zip(texte, texte[1:]):
        if a and a == b:
            folge += 1
            assert folge <= max_folge, f"wortgleiche Schleife: {a!r}"
        else:
            folge = 1


# --- 1) Ende-zu-Ende: die Live-Zuege + Fortsetzung bis zum Eintragen -------

def test_53986f42_laeuft_ohne_modell_bis_zur_buchung(ohne_modell, monkeypatch):
    calls: list[dict] = []

    def _book(*a, **k):
        calls.append(k or {"args": a[1:]})
        return _book_ok(*a, **k)

    monkeypatch.setattr(kal, "book_slot", _book)
    sit = session.neu(tenant=laden("blessing"))
    agent.start_reply(sit)
    aus = _lauf(sit, LIVE_ZUEGE + FORTSETZUNG)
    s = gehirn.sammler(sit)
    texte = _texte(aus)

    # Kein Zug fiel ans Modell (Fixture wirft sonst) und nichts blieb stumm —
    # ausser den BEWUSSTEN Warte-Zuegen (Denk-Cue "warte", Buchstabier-
    # Fragment: W-DATEN-FLOOR), die als `warte` markiert sind.
    stumm = [x["a"] for x, t in zip(aus, texte) if not t and not x.get("warte")]
    assert not stumm, stumm
    warte = [x["a"] for x in aus if x.get("warte")]
    assert "Ja, mein Nachname, warte." in warte, warte
    _keine_wortgleiche_schleife([t for t in texte if t])

    # Der Anrufer wurde erkannt, nichts Falsches wurde Name.
    assert s["nachname"] == "Busch"
    assert s["vorname"] == "Jelto"
    for falsch in ("Da", "Oder", "Schon", "Würde", "Was", "Yelto"):
        assert s["vorname"] != falsch and s["nachname"] != falsch
    assert s["warSchonMal"] is True
    assert s["modus"] == "buchen"

    # Nummer: erst vorab diktiert (9 Stellen Festnetz), Ziffer fuer Ziffer
    # bestaetigt, dann uebernommen.
    assert s["telefon"].replace(" ", "") == "071295316"
    assert s["telefonOk"] is True

    # Gebucht wurde GENAU einmal, mit dem gewaehlten Donnerstag-Slot, und
    # der Anruf endete mit dem Abschied.
    assert len(calls) == 1, calls
    assert s["slotIso"].startswith("2026-09-24")
    assert aus[-1].get("hangup"), aus[-1]
    assert any("eingetragen" in t.lower() for t in texte[-3:]), texte[-3:]


def test_53986f42_keine_fuenffache_vornamensfrage(ohne_modell, monkeypatch):
    """Live kam 'Meine Frage war: Und der Vorname?' fuenfmal wortgleich."""
    monkeypatch.setattr(kal, "book_slot", _book_ok)
    sit = session.neu(tenant=laden("blessing"))
    agent.start_reply(sit)
    aus = _lauf(sit, LIVE_ZUEGE[:18])
    vorname_zuege = [t for t in _texte(aus) if "vorname" in t.lower()]
    # Es darf gefragt werden — aber nie zweimal derselbe Satz.
    assert vorname_zuege, _texte(aus)
    assert len(vorname_zuege) == len(set(vorname_zuege)), vorname_zuege


# --- 2) W-BUCHUNG-TECHNIK: Fehlschlag => Notiz, Nummer, KEINE Schleife ------

def test_technischer_buchungsfehler_schreibt_notiz_und_schleift_nicht(ohne_modell, monkeypatch, tmp_path):
    monkeypatch.setattr(kal, "book_slot", _book_kaputt)
    notizen: list[dict] = []
    monkeypatch.setattr(verwalten, "_notiz_schreiben",
                        lambda sit, **k: notizen.append(k) or sit.__setitem__("praxisNotiz", k.get("dock_text", "")))
    sit = session.neu(tenant=laden("blessing"))
    agent.start_reply(sit)
    # Bis zum Ja auf das Nummern-Readback ("Ja, richtig.") — dort bucht die
    # Maschine und der Stub schlaegt fehl.
    aus = _lauf(sit, LIVE_ZUEGE + FORTSETZUNG[:5])
    s = gehirn.sammler(sit)
    # EIN Fehlschlag, echte Notiz mit dem bestaetigten Wunschtermin, Vorgang zu.
    assert any(n.get("anliegen") == "buchung_fehler" for n in notizen), notizen
    txt = " ".join(_texte(aus)).lower()
    assert "technisch nicht geklappt" in txt and "notiert" in txt, txt
    assert s["phase"] == "fertig"
    assert not sit.get("buchIntent")
    # Die Nummer war schon bestaetigt -> keine Nummernfrage mehr, Abschied.
    assert aus[-1].get("hangup"), aus[-1]
    assert "buchung fehlgeschlagen (500)" in str(notizen[-1].get("status", "")).lower()
    # Weitere Zuege duerfen NICHT erneut buchen (vorher: dieselbe Fehlermeldung
    # in Schleife, weil slotIso + buchIntent stehen blieben).
    n_vorher = len(notizen)
    aufrufe: list = []
    monkeypatch.setattr(kal, "book_slot", lambda *a, **k: aufrufe.append(1) or _book_kaputt())
    for satz in ("Ja, richtig.", "Hm.", "Nein, danke."):
        r = agent.user_turn(sit, satz)
        assert r is not None
        if r.get("hangup"):
            break
    assert not aufrufe, "book_slot lief nach dem technischen Fehlschlag erneut"
    assert len(notizen) <= n_vorher + 1  # hoechstens die Nummern-Nachreichung


def test_buchung_fehler_notiz_traegt_wunschtermin_und_grund():
    sit = {"tenant": laden("meddent"), "stimme": "Bianca"}
    s = gehirn.sammler(sit)
    s.update({"vorname": "Jelto", "nachname": "Busch", "grund": "Kontrolle",
              "grundWortlaut": "Nachsicht meiner Haut"})
    gesehen: list[dict] = []
    alt = verwalten._notiz_schreiben
    verwalten._notiz_schreiben = lambda sit, **k: gesehen.append(k)
    try:
        verwalten.buchung_fehler_notiz(sit, slot_iso="2026-09-24T09:30:00+02:00",
                                       grund_technisch="Buchung fehlgeschlagen (500)")
    finally:
        verwalten._notiz_schreiben = alt
    assert gesehen and gesehen[0]["anliegen"] == "buchung_fehler"
    dock = gesehen[0]["dock_text"]
    assert "Jelto Busch" in dock and "Nachsicht meiner Haut" in dock
    assert "manuell eintragen" in dock.lower() and "zurückrufen" in dock.lower()
    assert "500" in gesehen[0]["status"]


def test_netzfehler_prueft_statt_doppelt_einzutragen(monkeypatch):
    """Netzfehler: die Buchung KANN gelandet sein — Pruef-Notiz, kein
    'technisch gescheitert'."""
    sit = {"tenant": laden("meddent"), "stimme": "Bianca", "messages": []}
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "vorname": "Martin", "nachname": "Berger",
              "buchstabiert": True, "telefon": "015253904756", "telefonOk": True,
              "grund": "Kontrolle", "motivId": "kch-k", "warSchonMal": True,
              "slotIso": "2026-09-22T09:30:00+02:00", "phase": "bestaetigen",
              "arzt": {"typ": "egal"}})
    sit["offered"] = [{"iso": s["slotIso"], "spoken": "x"}]
    monkeypatch.setattr(flow.hintergrund, "anstossen", lambda *a, **k: None)
    monkeypatch.setattr(kal, "book_slot", lambda *a, **k: {
        "ok": False,
        "spoken": "Der Kalender antwortet gerade nicht.",
        "regie": "Netzfehler beim Buchen. Keinen anderen Slot anbieten, Rückruf zusagen."})
    pruef: list = []
    fehler: list = []
    monkeypatch.setattr(verwalten, "buchung_pruefen_notiz", lambda sit, **k: pruef.append(k))
    monkeypatch.setattr(verwalten, "buchung_fehler_notiz", lambda sit, **k: fehler.append(k))
    r = flow._buchen(sit)
    assert pruef and not fehler
    assert "doppelt" in r["text"].lower() and "notiert" in r["text"].lower()
    assert s["phase"] == "fertig" and not sit.get("buchIntent")


# --- 3) Namens-Ernte: was Name ist und was nie ------------------------------

def _sit_name(frage: str = "nachname", tid: str = "blessing", **extra) -> dict:
    sit = {"tenant": laden(tid), "stimme": "Bianca", "protokoll": [], "tools": [],
           "messages": [{"role": "system", "content": "x"}]}
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "frage": frage, "warSchonMal": False})
    s.update(extra)
    return sit


@pytest.mark.parametrize("satz, nachname", [
    ("Busch, mein Name.", "Busch"),
    ("Kromer, fertig.", "Kromer"),
    ("Meier, M-E-I-E-R, fertig.", "Meier"),
    ("Ich heiße Meier.", "Meier"),
])
def test_name_wird_geerntet(satz, nachname):
    sit = _sit_name()
    gehirn.einsammeln(sit, satz)
    assert gehirn.sammler(sit)["nachname"] == nachname


@pytest.mark.parametrize("satz", [
    "Da.", "Oder", "Schon.", "Würde", "Ja, bitte.", "Ja.",
    "Was soll ich aussprechen?", "Was meinen Sie?", "Wie bitte?",
    "Wozu brauchen Sie den?", "Soll ich buchstabieren?",
])
def test_kein_name_aus_fuellwort_oder_rueckfrage(satz):
    sit = _sit_name()
    gehirn.einsammeln(sit, satz)
    s = gehirn.sammler(sit)
    assert not s["nachname"] and not s["vorname"], (satz, s["nachname"], s["vorname"])


def test_guten_morgen_ist_kein_terminwunsch_fuer_morgen():
    sit = _sit_name(frage="wunsch")
    s = gehirn.sammler(sit)
    s["wunsch"] = None
    gehirn.einsammeln(sit, "Hallo, Busch, guten Morgen!")
    w = s.get("wunsch") or {}
    assert not w.get("date") and not w.get("minDaysAhead"), w


def test_korrektur_nicht_x_sondern_y_fertig():
    sit = _sit_name(nachname="Kromer")
    gehirn.einsammeln(sit, "Nicht Kromer, sondern Cramer, fertig.")
    assert gehirn.sammler(sit)["nachname"] == "Cramer"


def test_egal_und_fruehester_termin_sind_kein_zeitwunsch():
    sit = _sit_name(frage="wunsch")
    s = gehirn.sammler(sit)
    s["wunsch"] = None
    neu = gehirn.einsammeln(sit, "Vormittag oder Nachmittag, eigentlich egal.")
    assert "wunsch" in neu, neu
    w = s.get("wunsch") or {}
    assert not w.get("tageszeit") and not w.get("hourMin") and not w.get("hourMax"), w
    sit2 = _sit_name(frage="wunsch")
    s2 = gehirn.sammler(sit2)
    s2["wunsch"] = None
    neu2 = gehirn.einsammeln(sit2, "Nein, den frühesten Termin, bitte.")
    assert "wunsch" in neu2, neu2
    assert not (s2.get("wunsch") or {}).get("date")


# --- 4) C3: Rueckfragen auf die Namensfrage bleiben im Formular -----------

@pytest.fixture(autouse=True)
def _hintergrund_stumm(monkeypatch):
    monkeypatch.setattr(flow.hintergrund, "anstossen", lambda *a, **k: None)


def _flow_sit(frage: str, tid: str = "meddent", **extra) -> dict:
    sit = {"tenant": laden(tid), "stimme": "Bianca", "protokoll": [], "tools": [],
           "messages": [{"role": "system", "content": "x"}], "hirn": None}
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "frage": frage, "warSchonMal": False,
              "grund": "Kontrolle", "motivId": "x", "arzt": {"typ": "egal"},
              "wunsch": {"tageszeit": "vormittag"}})
    s.update(extra)
    return sit


@pytest.mark.parametrize("tid", ["meddent", "blessing"])
@pytest.mark.parametrize("satz, erwartet", [
    ("Was soll ich aussprechen?", "noch einmal"),
    ("Was meinen Sie?", "noch einmal"),
    ("Wie bitte?", "noch einmal"),
    ("Wozu brauchen Sie den?", "kartei"),
])
def test_namens_rueckfrage_wird_erklaert_und_frage_erneut_gestellt(tid, satz, erwartet):
    sit = _flow_sit("nachname", tid)
    r = flow.zug(sit, satz)
    assert r and r.get("text"), (tid, satz, r)
    t = r["text"].lower()
    assert erwartet in t, r["text"]
    assert "nachname" in t
    assert r["text"].count("?") == 1
    s = gehirn.sammler(sit)
    assert not s["nachname"]
    assert s["frage"] in {"nachname", "buchstabieren"}
    # Kein Fehlversuch — die Eskalation zaehlt Rueckfragen nicht.
    assert not (sit.get("frageLeer") or {}).get("nachname")


def test_namens_rueckfrage_wessen_nennt_die_person():
    sit = _flow_sit("nachname", fuerWen="sohn")
    r = flow.zug(sit, "Welchen Namen, meinen oder den vom Kind?")
    assert r and "ihren sohn" in r["text"].lower(), r
    assert "nachname" in r["text"].lower()
    sit2 = _flow_sit("nachname")
    r2 = flow.zug(sit2, "Welchen Namen, meinen?")
    assert r2 and "eigenen nachnamen" in r2["text"].lower(), r2


def test_namens_rueckfrage_auf_vorname():
    sit = _flow_sit("vorname", nachname="Busch")
    r = flow.zug(sit, "Was meinen Sie damit?")
    assert r and "vorname" in r["text"].lower(), r
    assert gehirn.sammler(sit)["frage"] == "vorname"
    assert gehirn.sammler(sit)["nachname"] == "Busch"


@pytest.mark.parametrize("satz", [
    "Ich heiße Meier.",          # Name mit Lead-in -> Ernte
    "M-E-I-E-R.",                # Buchstabier-Kette -> Ernte
    "Soll ich buchstabieren?",   # eigener Zweig (Buchstabier-Meta)
])
def test_namens_rueckfrage_gegenproben_gehoeren_der_ernte(satz):
    sit = _flow_sit("nachname")
    r = flow.zug(sit, satz)
    assert r and r.get("text")
    assert "noch einmal" not in r["text"].lower() and "kartei eintragen" not in r["text"].lower()


def test_namens_rueckfrage_nur_in_der_buchung():
    sit = _flow_sit("nachname")
    gehirn.sammler(sit)["modus"] = "absagen"
    assert flow._namens_rueckfrage_zug(sit, "Was soll ich aussprechen?") is None
    sit2 = _flow_sit("wunsch")
    assert flow._namens_rueckfrage_zug(sit2, "Was meinen Sie?") is None


# --- 5) Slot-Wahl: blankes Ja und Nummern-Diktat --------------------------

def _sit_angebot() -> dict:
    sit = _flow_sit("slotwahl", "blessing", nachname="Busch", vorname="Jelto",
                    buchstabiert=True, warSchonMal=True, phase="angebot")
    sit["offered"] = [{"iso": "2026-09-24T09:30", "spoken": "a"},
                      {"iso": "2026-09-25T14:40", "spoken": "b"}]
    return sit


def test_blankes_ja_auf_zwei_slots_fragt_welcher_und_nimmt_beim_zweiten_den_ersten():
    sit = _sit_angebot()
    assert flow._slot_ja_blank(sit, "Ja.") == ""
    assert flow._slot_ja_blank(sit, "Ja, gerne.") == sit["offered"][0]["iso"]
    # Kein blankes Ja:
    sit2 = _sit_angebot()
    assert flow._slot_ja_blank(sit2, "Ja, den zweiten.") is None
    assert flow._slot_ja_blank(sit2, "Nein.") is None
    assert flow._slot_ja_blank(sit2, "Ja, um halb zehn.") is None
    # Ein einzelnes Angebot: kein Fall fuer die Rueckfrage.
    sit3 = _sit_angebot()
    sit3["offered"] = sit3["offered"][:1]
    assert flow._slot_ja_blank(sit3, "Ja.") is None


def test_blankes_ja_im_fluss_stellt_die_welcher_frage():
    sit = _sit_angebot()
    r = flow.zug(sit, "Ja.")
    assert r and "welcher" in r["text"].lower(), r
    assert r["text"].count("?") == 1
    assert not gehirn.sammler(sit)["slotIso"]
    r2 = flow.zug(sit, "Den Donnerstag.")
    assert r2 and gehirn.sammler(sit)["slotIso"] == "2026-09-24T09:30", r2


def test_nummer_waehrend_slotwahl_wird_gemerkt_und_slotfrage_wiederholt():
    sit = _sit_angebot()
    s = gehirn.sammler(sit)
    r1 = flow.zug(sit, "Null, sieben, eins, zwei, neun.")
    assert r1 and "nummer" in r1["text"].lower() and "?" in r1["text"], r1
    assert s["telefonTeil"] == "07129"
    assert not s["slotIso"]
    r2 = flow.zug(sit, "Fünf, drei, eins, sechs.")
    assert r2 and "gemerkt" in r2["text"].lower(), r2
    assert s["telefonTeil"] == "071295316"
    assert not s["slotIso"]
    # Eine echte Wahl danach greift normal.
    r3 = flow.zug(sit, "Den zweiten.")
    assert r3 and s["slotIso"] == "2026-09-25T14:40", r3


@pytest.mark.parametrize("satz", [
    "Zwei.", "Den zweiten.", "Um halb zehn.", "Donnerstag um neun Uhr dreißig.",
])
def test_kurze_zahl_oder_zeitwort_ist_keine_nummer(satz):
    sit = _sit_angebot()
    assert flow._nummer_waehrend_slotwahl(sit, gehirn.sammler(sit), satz) == ""


def test_zahlwoerter_sind_kein_inhalt():
    assert not gespraech._inhaltsworte("null sieben eins zwei neun")
    assert not gespraech._inhaltsworte("ja das würde passen")
    assert "kontrolle" in gespraech._inhaltsworte("ich brauche eine kontrolle")


# --- 6) Rueckrufnummer: 9 Stellen Festnetz bestaetigt gilt ----------------

def test_plausibel_kurz_und_rueckruf_nummer_akzeptiert_bestaetigte_neun_stellen():
    assert telefon.plausibel_kurz("071295316")
    assert not telefon.plausibel("071295316")
    assert not telefon.plausibel_kurz("0712953")
    sit = {"tenant": laden("blessing"), "stimme": "Bianca"}
    s = gehirn.sammler(sit)
    s.update({"telefon": "071295316", "telefonOk": True})
    assert verwalten.rueckruf_nummer(sit).replace(" ", "") == "071295316"
    # Unbestaetigt bleibt die strenge Regel.
    s["telefonOk"] = False
    assert verwalten.rueckruf_nummer(sit) == ""


# --- 7) Praefix-Rotation: nie wortgleich -----------------------------------

def test_frage_praefix_rotiert_mit_sitzung():
    sit: dict = {}
    gesehen = {stille.frage_praefix("Und der Vorname?", sit) for _ in range(len(stille._PRAEFIXE))}
    assert len(gesehen) == len(stille._PRAEFIXE)
    # Ohne Sitzung: fester erster Vorsatz (Alt-Aufrufer).
    assert stille.frage_praefix("Und der Vorname?") == "Meine Frage war: Und der Vorname?"
