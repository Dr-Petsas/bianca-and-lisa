"""W-SACHNAME (05.10.2026): Fachwörter und Verneinungen sind keine Namen.

Live heute: „Danke, Frau Doktorkontrolle.“, „Danke, Frau E-mail.“ und
„Ich habe den Nachnamen Russland aufgenommen“ auf „das ist immer noch kein
Russland hier“."""

from __future__ import annotations

import pytest

from bianca import flow, gehirn, session
from kern.tenants import laden


@pytest.mark.parametrize("wort", ["Doktorkontrolle", "E-mail", "E-Mail", "Mail", "SMS",
                                  "Hautkontrolle", "Kontrolltermin"])
def test_sachwoerter_sind_keine_namens_token(wort):
    assert gehirn._name_tokens(wort) == []


@pytest.mark.parametrize("name", ["Ismail", "Mollner", "Kalchreuter", "Termeer", "Praxl", "Kontny"])
def test_echte_namen_bleiben(name):
    assert gehirn._name_tokens(name) == [name]


def test_verneintes_wort_ist_kein_name():
    assert "Russland" not in gehirn._name_tokens(
        gehirn.ohne_verneinte_woerter("Also, das ist immer noch kein Russland hier."))
    # „nicht mehr“ / „nicht so“ verschlucken nichts
    assert "Meier" in gehirn.ohne_verneinte_woerter("nicht mehr Meier")


def _readback_sit() -> dict:
    sit = session.neu(tenant=laden("blessing"))
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "nachname": "Mollner", "buchstabiert": True,
              "nachnameCheck": "offen", "frage": "nachname_check"})
    return sit


def test_kein_russland_im_readback_erntet_keinen_nachnamen():
    sit = _readback_sit()
    flow._nachname_check_vorbereiten(sit, "Also, das ist immer noch kein Russland hier.")
    assert gehirn.sammler(sit).get("nachname") != "Russland"


def test_frau_doktorkontrolle_wird_kein_nachname():
    sit = session.neu(tenant=laden("blessing"))
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "frage": "nachname"})
    gehirn._name_aufnehmen(
        s, "Frau Doktor, meine immer kommt die Kontrolle, die Frau Doktorkontrolle immer.",
        erzwungen=True)
    assert "kontrolle" not in (s.get("nachname") or "").casefold()


def test_schreib_eine_email_ist_kein_name():
    s = gehirn.sammler(session.neu(tenant=laden("blessing")))
    s["frage"] = "schonmal"
    gehirn._name_aufnehmen(s, "Schreib so kurz eine E-Mail bitte.", erzwungen=False)
    assert "mail" not in f"{s.get('vorname')} {s.get('nachname')}".casefold()


def test_nicht_x_sondern_y_bleibt_korrektur():
    s = gehirn.sammler(session.neu(tenant=laden("meddent")))
    s.update({"frage": "nachname", "nachname": "Müller"})
    gehirn._name_aufnehmen(s, "Nicht Müller, sondern Möller.", erzwungen=True)
    assert s["nachname"] == "Möller"
