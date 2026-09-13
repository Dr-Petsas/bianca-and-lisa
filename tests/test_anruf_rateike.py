"""Anruf 1fbda5db (13.09.2026) — die Befunde des Chefs, wortgleich.

Sein Text: "obwohl ich nach dem buchstabieren fertig sage und bianca den namen
rateike erkennt, nennt sie mich spaeter rateike fertig […] die frage nach der
zhanreinigung kommt doppelt […] dann sagt bianca dass sie einen termin zur
Kontrolluntersuchung buchen wird, ich weiss nicht ob sie im kalender auf
kieferorthopaedie gemappt haette […] als ich gesagt habe dass ich nicht rateike
fertig heisse sondern rateike frgt sie erneut nach dem vornamen!!!!!!!!"

Im Session-Hirn stand hinterher: nachname="Sdasrateikefertig" (buchstabiert=
True!), pzr="gefragt" (das "ja" war verloren), motivName="KCH
Kontrolluntersuchung".
"""

from bianca import besuchsgrund, buchstaben, flow, gehirn


def _sit(**felder):
    sit = {"tenant": {"praxisName": "Testpraxis"}}
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", **felder})
    return sit


# --- "fertig" gehoert nie zum Namen (W-DIKTAT-FERTIG) --------------------

def test_buchstabiert_mit_fertig_am_ende():
    # Live: "R-A-T-E-I-K-E, fertig." wurde zu "Rateikefertig".
    got = buchstaben.deute("R, A, T, E, I, K, E, fertig.")
    assert got and got["name"] == "Rateike"


def test_fuellwoerter_werden_nicht_zu_buchstaben():
    # Live: "aufstabiert es das R-A-T-E-I-K-E" -> "Sdasrateike".
    got = buchstaben.deute("Rateike, aufstabiert es das R-A-T-E-I-K-E.")
    assert got and got["name"] == "Rateike"


def test_gesprochener_name_schlaegt_streubuchstaben():
    got = buchstaben.deute("es R A T E I K E")
    assert got and got["name"].lower().endswith("rateike")


# --- Der Einwand gegen den Namen (W-NAME-EINWAND-2) ---------------------

def test_einwand_mit_mehrwortigem_falschnamen():
    sit = _sit(nachname="Rateike fertig", vorname="Stefan", buchstabiert=True)
    s = sit["sammler"]
    neu = gehirn.einsammeln(
        sit, "Ich heiße nicht Rateike fertig, sondern Rateike.")
    assert "name" in neu or s["nachname"] == "Rateike"
    assert s["nachname"] == "Rateike"
    # Der Vorname war NIE beanstandet — er muss stehen bleiben.
    assert s["vorname"] == "Stefan"


def test_namenskorrektur_an_der_bestaetigung_laesst_den_vornamen_stehen():
    # Chef: "der wurde doch gar nicht beanstandet und steht schon fest!!!!"
    sit = _sit(nachname="Rateike fertig", vorname="Stefan", buchstabiert=True,
               telefon="01776004600", telefonOk=True, frage="aenderung",
               phase="", grund="Kontrolle",
               arzt={"typ": "genannt", "calendarId": "c1",
                     "calendarName": "Doktor Michael Petsas"})
    s = sit["sammler"]
    zug = flow._aenderung_zug(sit, "Ich heiße nicht Rateike fertig, sondern Rateike.")
    assert s["nachname"] == "Rateike"
    assert s["vorname"] == "Stefan", zug
    # Und die Vornamen-Frage darf nicht erneut kommen.
    fid, frage = gehirn.naechste_frage(sit)
    assert fid != "vorname", frage


# --- Die Zahnreinigung genau einmal (W-FRAGE-GATE + W-JA-NACHGESTELLT) ---

def test_zusage_zur_zahnreinigung_wird_aufgenommen(monkeypatch):
    from kern import motive
    monkeypatch.setattr(motive, "fuehrt_pzr", lambda sit: True)
    sit = _sit(frage="pzr", pzr="gefragt", grund="Kontrolle")
    gehirn.einsammeln(
        sit, "Hast du doch schon befragt, haben wir doch schon gesagt, ja.")
    assert sit["sammler"]["pzr"] == "ja"


# --- Schiefe Zaehne sind Kieferorthopaedie, auch verhoert ----------------

_KATALOG = [
    {"id": "kfo", "name": "KFO Besprechung", "duration": 30},
    {"id": "kontrolle", "name": "KCH Kontrolluntersuchung", "duration": 30},
    {"id": "pzr", "name": "PZR Zahnreinigung", "duration": 60},
    {"id": "ze", "name": "ZE Besprechung", "duration": 30},
]


def test_schiefe_zaehne_mappen_auf_kfo():
    kern, vm = besuchsgrund.deute(
        {}, "Ich habe schiefe Zähne, ich möchte die gerade haben.",
        katalog=_KATALOG)
    assert (vm or {}).get("name") == "KFO Besprechung", kern


def test_schiefe_zehen_sind_in_der_zahnarztpraxis_auch_zaehne():
    # Live-Wortlaut aus dem STT — der Termin lief auf Kontrolle.
    kern, vm = besuchsgrund.deute(
        {}, "Ich habe schiefe Zehen, ich möchte die gerade haben.",
        katalog=_KATALOG)
    assert (vm or {}).get("name") == "KFO Besprechung", kern


def test_zehen_bleiben_beim_hautarzt_zehen():
    # Gegenprobe: ohne Zahn-Katalog wird nichts umgedeutet.
    derma = [{"id": "a", "name": "Hautkrebsvorsorge"},
             {"id": "b", "name": "Sprechstunde"}]
    kern, vm = besuchsgrund.deute(
        {}, "Ich habe etwas an den Zehen.", katalog=derma)
    assert kern == "" and vm is None
