"""W-NAMEN-0810: Buchstabiertafel und Namensernte (Blessing 08./09.10.2026).

Live-Anrufe 2d1201f6 und 755c98f3, Sätze wortgleich aus den Manifesten:
- „Ursula“/„Elizabeth“ als Tafelwort mitten in der Kette fehlten, aus
  Kukielka wurde „Kkilka“;
- „M-I-R-Z-A-Mirsa.“ wurde zu „Mirzamirsa“;
- „Fünfzehnte Zehnte.“ (eine Datumsangabe) wurde zum Nachnamen „Zehnte“;
- ein kurzes „Set.“ auf die Rücklese ersetzte den buchstabierten Namen.
Die Gegenproben halten bewährte Ketten und echte Vornamen fest.
"""

from __future__ import annotations

import pytest

from bianca import buchstaben, flow, gehirn, verwalten
from kern import hirn
from kern.tenants import laden


def _buchen(frage: str = "buchstabieren") -> dict:
    sit = {
        "id": f"namen-0810-{frage}",
        "stimme": "Bianca",
        "tenant": laden("blessing"),
        "messages": [{"role": "system", "content": "test"}],
        "booking": {},
        "tools": [],
        "zuege": [],
    }
    hirn.init(sit)
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "phase": "",
        "frage": frage,
        "warSchonMal": True,
        "arzt": {
            "typ": "genannt",
            "calendarId": "blessing-cal",
            "calendarName": "Doktor Charlotte Blessing",
        },
        "grund": "Kontrolle",
    })
    return sit


def _absage(monkeypatch) -> dict:
    monkeypatch.setattr(
        verwalten.kal, "find_appointments_by_date",
        lambda tenant, day: {"ok": True, "appointments": [], "dispatch": {}},
    )
    sit = {"tenant": laden("blessing"),
           "messages": [{"role": "system", "content": "x"}]}
    s = gehirn.sammler(sit)
    s.update({"modus": "absagen", "frage": "buchstabieren"})
    sit["verwAktiv"] = True
    return sit


KUKIELKA_Z4 = ("Kukielka, Konrad, Ursula, Konrad, Ida, Elizabeth, Ludwig, "
               "Konrad, Adam, Kielka, Elizabeth.")
KUKIELKA_Z7 = ("Konrad, Ursula, Konrad, Ida, Elisabeth, Ludwig, Konrad, Adam, "
               "Kukjelka,")


@pytest.mark.parametrize("gesagt", [KUKIELKA_Z4, KUKIELKA_Z7])
def test_ursula_und_elisabeth_zaehlen_mitten_in_der_kette(gesagt):
    assert buchstaben.deute(gesagt)["name"] == "Kukielka"


def test_nachgesprochener_name_haengt_nichts_an():
    assert buchstaben.deute("M-I-R-Z-A-Mirsa.")["name"] == "Mirza"


@pytest.mark.parametrize("gesagt,name", [
    ("Feldkamp, also F-E-LD-Kamp", "Feldkamp"),
    ("F-E-L-D-Kamp", "Feldkamp"),
    ("M-E-I-E-R, Meier", "Meier"),
    ("Rateike, R-A-T-E-I-K-E, fertig.", "Rateike"),
])
def test_bewaehrte_ketten_bleiben(gesagt, name):
    assert buchstaben.deute(gesagt)["name"] == name


@pytest.mark.parametrize("gesagt", [
    "Ursula", "Elisabeth", "Mein Vorname ist Ursula",
    "Ursula Elisabeth Schmidt", "Elisabeth, Evi, Elisabeth",
])
def test_vornamen_allein_sind_keine_buchstaben(gesagt):
    assert buchstaben.deute(gesagt) is None
    assert buchstaben.teil(gesagt) == ""


def test_tafelwort_mit_wie_bleibt_buchstabe():
    assert buchstaben.teil("U wie Ursula") == "u"
    assert buchstaben.teil("Anna") == "a"


def test_ordinalzahlen_sind_kein_name():
    assert gehirn._name_tokens("Fünfzehnte Zehnte.") == []
    assert gehirn._nachgesprochen("Fünfzehnte Zehnte.") == ""
    assert gehirn._name_tokens("Mein Name ist Zehner.") == ["Zehner"]


def test_live_datum_auf_buchstabierfrage_wird_kein_nachname(monkeypatch):
    sit = _absage(monkeypatch)
    flow.zug(sit, "Fünfzehnte Zehnte.", set())
    assert gehirn.sammler(sit).get("nachname", "") == ""


def test_live_kukielka_kette_im_absagefluss(monkeypatch):
    sit = _absage(monkeypatch)
    aus = flow.zug(sit, KUKIELKA_Z4, set())
    s = gehirn.sammler(sit)
    assert s["nachname"] == "Kukielka"
    assert s["frage"] == "nachname_check"
    assert "Kukielka" in aus["text"]


def _readback(name: str) -> dict:
    sit = _buchen(frage="nachname_check")
    s = sit["sammler"]
    s["nachname"] = name
    s["buchstabiert"] = True
    s["nachnameCheck"] = "offen"
    return sit


def test_kurzwort_auf_ruecklese_ersetzt_den_namen_nicht():
    sit = _readback("Mirza")
    modus, aus = flow._nachname_check_vorbereiten(sit, "Set.")
    s = sit["sammler"]
    assert modus == "beantwortet"
    assert s["nachname"] == "Mirza"
    assert s["nachnameCheck"] == "offen"
    assert "Ja oder Nein" in aus["text"]


def test_kurzer_echter_name_mit_nein_korrigiert_weiter():
    sit = _readback("Mirza")
    aus = flow.zug(sit, "Nein, Ott.")
    s = sit["sammler"]
    assert s["nachname"] == "Ott"
    assert "Ott" in aus["text"]


def test_laengerer_name_allein_korrigiert_weiter():
    sit = _readback("Pusch")
    aus = flow.zug(sit, "Busch.")
    assert sit["sammler"]["nachname"] == "Busch"
    assert "Busch" in aus["text"]
