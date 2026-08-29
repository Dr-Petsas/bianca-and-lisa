"""P2 Satz-Deckel (29.08.2026): zwei Saetze plus Frage, sonst drei Saetze.

Reine Textarbeit — kein vLLM, kein Netz. Der Stream-Schnitt selbst sitzt
in chat_stream und wird hier ueber _deckel_text geprueft (gleiche Logik).
"""

from kern import llm


def test_zwei_saetze_plus_frage_schliesst():
    t = ("Das verstehe ich gut. Ihre Nummer habe ich. "
         "Wann passt es Ihnen am besten? Und sonst noch etwas, "
         "soll ich das auch gleich mitnehmen? ")
    out = llm._deckel_text(t)
    assert out == ("Das verstehe ich gut. Ihre Nummer habe ich. "
                   "Wann passt es Ihnen am besten?")
    assert "?" in out
    assert "sonst noch" not in out


def test_zwei_aussagen_plus_frage_reicht():
    t = ("Das mache ich gerne. Ich trage das gleich ein. "
         "Wann passt es Ihnen? Und noch eine Sache. ")
    out = llm._deckel_text(t)
    assert out == ("Das mache ich gerne. Ich trage das gleich ein. "
                   "Wann passt es Ihnen?")
    assert "noch eine Sache" not in out


def test_drei_aussagen_ohne_frage_kappen():
    t = ("Alles klar. Ich schaue das nach. Einen Moment bitte. "
         "Und dann buche ich das auch. ")
    out = llm._deckel_text(t)
    assert out == "Alles klar. Ich schaue das nach. Einen Moment bitte."
    assert "buche" not in out


def test_ein_satz_plus_frage_bleibt_offen():
    """Ein Satz plus Frage ist noch kein Deckel — der Zug darf so enden,
    aber wir schneiden nicht, solange der Stream laeuft (koennte noch
    ein zweiter Satz kommen)."""
    assert llm._deckel_text("Gern. Wann passt es Ihnen? ") == ""


def test_unfertiger_satz_zaehlt_nicht():
    assert llm._deckel_text("Alles klar. Ich schaue das nach") == ""
    assert llm._deckel_text("Alles klar. Ich schaue das nach.") == ""


def test_abkuerzung_und_uhrzeit_kein_schnitt():
    t = ("Dr. Petsas hat um 13:00 Uhr Zeit. Das passt gut. "
         "Soll ich den Termin so eintragen? Und sonst? ")
    out = llm._deckel_text(t)
    assert out.startswith("Dr. Petsas hat um 13:00 Uhr Zeit.")
    assert "Soll ich den Termin so eintragen?" in out
    assert "sonst" not in out
    # Trailing-space fehlt am Deckel-Ende — _saetze_bis bestaetigt den
    # letzten Satz darum nicht; der Inhalt zaehlt drei Satzzeichen.
    assert out.count(".") + out.count("?") == 4  # Dr. + 2 Saetze + Frage


def test_erster_satz_von_bleibt_25_zeichen():
    assert llm._erster_satz_von("Ja. ") == ""
    assert llm._erster_satz_von("Ja. Das mache ich sehr gerne. ") == \
        "Ja. Das mache ich sehr gerne."
