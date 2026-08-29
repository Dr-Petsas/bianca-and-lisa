"""Katalog-Wachen des Baukasten-Tests: jede Variante muss von Biancas
Deutern verstanden werden, BEVOR sie als Audio in einen Testanruf geht."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bianca import besuchsgrund, telefon  # noqa: E402
from kern import slots, tenants  # noqa: E402
from tests.baukasten import saetze  # noqa: E402


def test_telefon_varianten_parsen_auf_testnummer():
    for satz in saetze.TELEFON + saetze.READBACK_NEIN:
        assert telefon.aus_satz(satz) == saetze.TESTNUMMER, satz


def test_gruende_mappen_aufs_erwartete_motiv():
    tenant = tenants.laden("meddent")
    for gid, (varianten, erwartet) in saetze.GRUENDE.items():
        assert len(varianten) == 10, f"{gid}: {len(varianten)} statt 10 Varianten"
        for satz in varianten:
            _, vm = besuchsgrund.deute(tenant, satz)
            assert vm, f"{gid}: kein Motiv fuer {satz!r}"
            assert erwartet.lower() in vm["name"].lower(), \
                f"{gid}: {satz!r} -> {vm['name']!r}, erwartet {erwartet!r}"


def test_wunsch_saetze_werden_als_slotwunsch_verstanden():
    for tag in ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"):
        for nr in range(len(saetze.WUNSCH_MUSTER)):
            satz = saetze.wunsch_satz(tag, nr)
            wunsch = slots.parse_slot_wish(satz)
            assert wunsch, f"kein Slot-Wunsch: {satz!r}"


def test_buchstabier_alphabet_traegt_alle_nachnamen():
    for name in saetze.NACHNAMEN:
        for stil in range(3):
            satz = saetze.buchstabier_satz(name, stil)
            assert satz and name.lower()[0] in satz.lower()
    # Umlaute und Eszett nicht vergessen:
    assert "Ü wie Übermut" in saetze.buchstabier_satz("Müller", 0)


def test_zehn_varianten_je_kernbaustein():
    kern = [
        saetze.EROEFFNUNG_MACHEN, saetze.EROEFFNUNG_ABSAGEN,
        saetze.EROEFFNUNG_VERSCHIEBEN, saetze.EROEFFNUNG_ERFAHREN,
        saetze.SCHONMAL_JA, saetze.SCHONMAL_NEIN, saetze.ARZT_MUSTER,
        saetze.ARZT_EGAL, saetze.WUNSCH_MUSTER, saetze.SLOT_FRUEHER,
        saetze.SLOT_SPAETER, saetze.SLOT_ANNAHME, saetze.NAME_MUSTER,
        saetze.TELEFON, saetze.READBACK_JA, saetze.BESTAETIGUNG_JA,
        saetze.ABSCHIED, saetze.VERSICHERUNG_PRIVAT_MUSTER,
        saetze.VERSICHERUNG_GESETZLICH_MUSTER,
    ]
    for liste in kern:
        assert len(liste) == 10, f"{liste[0]!r}...: {len(liste)} statt 10"
    for gid, varianten in saetze.ANLIEGEN.items():
        assert len(varianten) == 10, f"Anliegen {gid}: {len(varianten)} statt 10"
    for thema in ("wehgetan", "verschoben2x", "rechnung_teuer", "pzr_schlecht",
                  "fussball", "trump", "iran", "kosten_hoch", "hartz4",
                  "ratenzahlung", "taxi"):
        assert len(saetze.ABSCHWEIFER[thema]) == 10, thema


def test_versicherung_saetze_bauen():
    for nr in range(10):
        p = saetze.versicherung_satz(True, nr)
        g = saetze.versicherung_satz(False, nr)
        assert "{" not in p and "{" not in g
        assert p != g


def test_schonmal_saetze_ernten_keinen_namen():
    """Live 29.08.2026: "ich bin gerade erst hergezogen" wurde als Name
    "Gerade Hergezogen" verbucht — kein Schonmal-Satz darf Namen setzen."""
    from bianca import gehirn
    tenant = tenants.laden("meddent")
    for satz in saetze.SCHONMAL_JA + saetze.SCHONMAL_NEIN:
        sit = {"tenant": tenant, "messages": [{"role": "system", "content": "x"}]}
        s = gehirn.sammler(sit)
        s["modus"] = "buchen"
        s["frage"] = "schonmal"
        gehirn.einsammeln(sit, satz)
        assert not s["vorname"] and not s["nachname"], \
            f"{satz!r} -> Name {s['vorname']!r} {s['nachname']!r}"


if __name__ == "__main__":
    fehler = 0
    for name in sorted(n for n in dir() if n.startswith("test_")):
        try:
            globals()[name]()
            print(f"gruen: {name}")
        except AssertionError as e:
            fehler += 1
            print(f"ROT:   {name} — {e}")
    sys.exit(1 if fehler else 0)
