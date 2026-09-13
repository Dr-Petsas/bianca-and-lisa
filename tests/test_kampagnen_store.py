"""Eigene Kampagnen-Seite: Liste parsen, Store, nächster offener Eintrag."""

from __future__ import annotations

from lisa import kampagnen_store as ks


def test_parse_semikolon_und_notiz():
    rows = ks.parse_liste("Praxis Dr. Meier;0211 123456;Dr. Meier selbst")
    assert len(rows) == 1
    assert rows[0]["name"] == "Praxis Dr. Meier"
    assert rows[0]["phone"] == "0211123456"
    assert rows[0]["notiz"] == "Dr. Meier selbst"


def test_parse_csv_kopf_und_komma():
    roh = "Praxis,Telefon,Notiz\nDr. Schulz,0176 1112233,Implantat\n# kommentar\n"
    rows = ks.parse_liste(roh)
    assert len(rows) == 1
    assert rows[0]["name"] == "Dr. Schulz"
    assert rows[0]["phone"] == "01761112233"


def test_parse_telefon_zuerst():
    rows = ks.parse_liste("0211-998877,Praxis am Rhein")
    assert rows[0]["name"] == "Praxis am Rhein"
    assert rows[0]["phone"] == "0211998877"


def test_parse_ohne_nummer_faellt_weg():
    assert ks.parse_liste("Nur ein Name ohne Telefon") == []


def test_parse_doppelte_nummer_einmal():
    roh = "A;02111234567\nB;0211 123 456 7;andere"
    rows = ks.parse_liste(roh)
    assert len(rows) == 1
    assert rows[0]["name"] == "A"


def test_store_anlegen_liste_markieren(tmp_path, monkeypatch):
    monkeypatch.setattr(ks, "_DIR", tmp_path)
    doc = ks.anlegen(
        name="KW36",
        auftrag="Pickadoc vorstellen",
        tenant="meddent",
        empfaenger_roh="Praxis A;0211111111\nPraxis B;0211222222;Hint",
    )
    assert doc["id"].startswith("k_")
    assert doc["auftrag"] == "Pickadoc vorstellen"
    assert [e["name"] for e in doc["empfaenger"]] == ["Praxis A", "Praxis B"]
    assert all(e["status"] == "offen" for e in doc["empfaenger"])

    uebersicht = ks.liste()
    assert uebersicht[0]["offen"] == 2
    assert uebersicht[0]["anzahl"] == 2

    nxt = ks.naechste_offen(doc)
    assert nxt["name"] == "Praxis A"
    marked = ks.markieren(doc["id"], nxt["id"], status="erreicht", session_id="s1")
    assert marked
    hit = next(e for e in marked["empfaenger"] if e["id"] == nxt["id"])
    assert hit["status"] == "erreicht" and hit["sessionId"] == "s1"
    assert ks.naechste_offen(marked)["name"] == "Praxis B"

    dazu = ks.empfaenger_dazu(doc["id"], roh="Praxis C;0211333333")
    assert len(dazu["empfaenger"]) == 3
    weg = ks.empfaenger_weg(doc["id"], dazu["empfaenger"][-1]["id"])
    assert len(weg["empfaenger"]) == 2
    assert ks.holen(doc["id"])["name"] == "KW36"


def test_default_auftrag_ist_pickadoc():
    assert "Pickadoc" in ks._DEFAULT_AUFTRAG
    assert "rezeption" in ks._DEFAULT_AUFTRAG.lower()


def test_markieren_ungueltiger_status(tmp_path, monkeypatch):
    monkeypatch.setattr(ks, "_DIR", tmp_path)
    doc = ks.anlegen(name="X", empfaenger_roh="A;0211111111")
    eid = doc["empfaenger"][0]["id"]
    assert ks.markieren(doc["id"], eid, status="boom") is None
