"""Kampagnen-Lisa ist von der Patienten-Lisa getrennt: Bewerbung, keine Termine."""

from __future__ import annotations

from lisa import bewerbung


def test_begruessung_ist_spontan_und_locker():
    t = bewerbung.begruessung()
    assert "Lisa von Pickadoc" in t
    assert "Personal für die Rezeption" in t
    assert "spontan" in t
    assert "störe" in t
    assert "Spreche ich mit" not in t
    assert "Guten Tag, hier ist Lisa" not in t


def test_begruessung_haengt_nicht_am_praxisnamen():
    assert bewerbung.begruessung(praxis_name="Praxis Dr. Meier") == bewerbung.GREETING


def test_prompt_ohne_kalender_und_ohne_steifen_pitch():
    p = bewerbung.system_prompt(auftrag="Bewerbung")
    assert "keinen Kalender" in p
    assert "book_slot" not in p
    assert "Telefonassistentin einer Zahnarztpraxis" not in p
    assert "Callcenter" in p or "locker" in p


def test_start_schweigt_bis_zur_meldung():
    sit = {"auftrag": "", "kampagne": {}, "patient": {}}
    out = bewerbung.start_reply(sit)
    assert sit["lisaArt"] == "bewerbung"
    assert sit["wartetAufMeldung"] is True
    assert sit["booking"] == {}
    assert out["text"] == ""
    assert sit["messages"][0]["role"] == "system"
    assert bewerbung.GREETING not in " ".join(m.get("content") or "" for m in sit["messages"])


def test_start_eine_stimme_pro_zug():
    sit = {}
    bewerbung.start_reply(sit)
    assert sit["ttsGanz"] is True


def test_erste_meldung_loest_begruessung_aus():
    sit = {}
    bewerbung.start_reply(sit)
    out = bewerbung.user_turn(sit, "Zahnarztpraxis Meier, guten Tag?")
    assert out["text"] == bewerbung.GREETING
    assert not out.get("hangup")
    assert sit["wartetAufMeldung"] is False
    assert sit["messages"][-2]["content"] == "Zahnarztpraxis Meier, guten Tag?"
    assert sit["messages"][-1]["content"] == bewerbung.GREETING


def test_stoeren_legt_auf():
    sit = {}
    bewerbung.start_reply(sit)
    bewerbung.user_turn(sit, "Ja, hallo?")
    out = bewerbung.user_turn(sit, "Äh, doch, sie stören.")
    assert out["hangup"] is True
    assert "störe ich nicht weiter" in out["text"]


def test_tschues_nach_abschied_legt_auf():
    sit = {}
    bewerbung.start_reply(sit)
    bewerbung.user_turn(sit, "Ja?")
    bewerbung.user_turn(sit, "Sie stören.")
    out = bewerbung.user_turn(sit, "Ja, tschüss.")
    assert out["hangup"] is True
    assert out["text"] == "Tschüss."


def test_stoeren_nicht_ist_kein_ende():
    assert not bewerbung._user_will_ende("Nee, Sie stören nicht, erzählen Sie.")


def test_leerer_zug_bleibt_still():
    sit = {}
    bewerbung.start_reply(sit)
    assert sit["wartetAufMeldung"] is True
    assert bewerbung.user_turn(sit, "   ")["text"] == ""
    assert sit["wartetAufMeldung"] is True


def test_stille_vor_meldung_ist_nur_hallo():
    sit = {}
    bewerbung.start_reply(sit)
    assert bewerbung.stille_zug(sit)["text"] == "Hallo?"


def test_hangup_schreibt_keine_terminnotiz():
    assert bewerbung.hangup({}) == {}
