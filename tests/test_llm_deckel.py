"""P2 Satz-Deckel (29.08.2026): zwei Saetze plus Frage, sonst drei Saetze.

Reine Textarbeit — kein vLLM, kein Netz. Der Stream-Schnitt selbst sitzt
in chat_stream und wird hier ueber _deckel_text geprueft (gleiche Logik).
"""

import json

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


def test_neue_stream_saetze_erster_dann_rest():
    """P5: erster Block nach 25-Zeichen-Regel, danach jeder weitere Satz."""
    t = ("Das verstehe ich wirklich gut. Ihre Nummer habe ich. "
         "Wann passt es Ihnen? ")
    neu, n = llm._neue_stream_saetze(t, 0)
    assert neu == ["Das verstehe ich wirklich gut."]
    assert n == 1
    neu2, n2 = llm._neue_stream_saetze(t, n)
    assert neu2 == ["Ihre Nummer habe ich.", "Wann passt es Ihnen?"]
    assert n2 == 3


def test_neue_stream_saetze_unfertig_bleibt_leer():
    neu, n = llm._neue_stream_saetze("Das verstehe ich wirklich gut", 0)
    assert neu == [] and n == 0
    neu, n = llm._neue_stream_saetze("Das verstehe ich wirklich gut. Ihre Nummer", 1)
    assert neu == [] and n == 1


# --- W-TTS-NAHT (31.08.2026): Grenz-Wache + Mindestlaenge --------------------
# Vorbild phone_agent tts_chunks: ein Punkt hinter Abkuerzung/Ordnungszahl
# ist KEIN Satzende (sonst kappte der Deckel die Antwort mitten im Satz und
# der Vorab vertonte halbe Phrasen); Folge-Bloecke unter 20 Zeichen warten
# auf den naechsten Satz (keine Mini-Renders in der Fueller-Kette).


def test_strassenname_zaehlt_nicht_als_satzende():
    t = ("Die Praxis liegt in der Bahnhofstr. Fuenf in Duesseldorf. "
         "Kommen Sie einfach vorbei. Wir freuen uns auf Sie. Und noch was. ")
    out = llm._deckel_text(t)
    # "Bahnhofstr." darf nicht als Satzende zaehlen — sonst kappt der
    # Deckel die Antwort mitten in der Adresse.
    assert out.startswith("Die Praxis liegt in der Bahnhofstr. Fuenf in Duesseldorf.")
    assert "Und noch was" not in out


def test_ordnungszahl_zaehlt_nicht_als_satzende():
    saetze = llm._saetze_bis("Wir sind im 3. Stock. Der Aufzug ist rechts. ")
    assert saetze == ["Wir sind im 3. Stock.", "Der Aufzug ist rechts."]


def test_neue_stream_saetze_kurzer_folgesatz_wartet():
    t = "Das verstehe ich wirklich gut. Gut. Ich trage das gleich ein. "
    neu, n = llm._neue_stream_saetze(t, 0)
    assert neu == ["Das verstehe ich wirklich gut."] and n == 1
    # "Gut." (unter 20 Zeichen) wartet und kommt MIT dem Folgesatz.
    neu2, n2 = llm._neue_stream_saetze(t, n)
    assert neu2 == ["Gut. Ich trage das gleich ein."]
    assert n2 == 3


def test_neue_stream_saetze_kurzer_schlusssatz_bleibt_offen():
    t = "Das verstehe ich wirklich gut. Gut. "
    neu, n = llm._neue_stream_saetze(t, 1)
    # Haengt nur ein Kurz-Satz am Ende, bleibt er ungemeldet — er laeuft
    # spaeter im Rest-Render mit (nie doppelt, nie verloren).
    assert neu == [] and n == 1


def test_neue_stream_saetze_mehrsatz_block_zaehlt_alle():
    """Live 01.09.2026: kurzes „Ja, genau." + langer Satz als EIN Vorab-Block
    — der Zähler muss BEIDE Sätze zählen, sonst kommt Satz 2 nochmal."""
    t = ("Ja, genau. Ich bin die digitale Assistentin der Praxis und helfe "
         "Ihnen gerne bei Terminen oder Fragen. Darf ich Sie schon "
         "weiterhelfen, zum Beispiel bei der Terminvereinbarung? ")
    neu, n = llm._neue_stream_saetze(t, 0)
    assert neu == [
        "Ja, genau. Ich bin die digitale Assistentin der Praxis und helfe "
        "Ihnen gerne bei Terminen oder Fragen."
    ]
    assert n == 2  # nicht 1 — sonst Doppel-Vorab des Mittelsatzes
    neu2, n2 = llm._neue_stream_saetze(t, n)
    assert neu2 == [
        "Darf ich Sie schon weiterhelfen, zum Beispiel bei der Terminvereinbarung?"
    ]
    assert n2 == 3
    # Streaming-Simulation: nie denselben Satz zweimal als Vorab.
    n_saetze = 0
    teile = []
    for i in range(1, len(t) + 1):
        neu_i, n_neu = llm._neue_stream_saetze(t[:i], n_saetze)
        if neu_i:
            n_saetze = n_neu
            teile.extend(neu_i)
    assert teile == [
        "Ja, genau. Ich bin die digitale Assistentin der Praxis und helfe "
        "Ihnen gerne bei Terminen oder Fragen.",
        "Darf ich Sie schon weiterhelfen, zum Beispiel bei der Terminvereinbarung?",
    ]


def test_rest_nach_vorab_bei_doppel_mittelsatz():
    """Sicherheitsnetz: wenn der alte Bug den Mittelsatz doppelt im Vorab
    hatte, nur noch die fehlende Schlussfrage nachlegen — nie Full-Replay."""
    gesprochen = (
        "Ja, genau. Ich bin die digitale Assistentin der Praxis und helfe "
        "Ihnen gerne bei Terminen oder Fragen. Ich bin die digitale "
        "Assistentin der Praxis und helfe Ihnen gerne bei Terminen oder Fragen."
    )
    text = (
        "Ja, genau. Ich bin die digitale Assistentin der Praxis und helfe "
        "Ihnen gerne bei Terminen oder Fragen. Darf ich Sie schon "
        "weiterhelfen, zum Beispiel bei der Terminvereinbarung?"
    )
    rest = llm.rest_nach_vorab(gesprochen, text)
    assert rest == (
        "Darf ich Sie schon weiterhelfen, zum Beispiel bei der "
        "Terminvereinbarung?"
    )
    assert not text.startswith(gesprochen)  # exakter Prefix scheitert
    # Sauberer Prefix → Suffix wie bisher.
    g2 = text[: text.index("Darf")].strip()
    assert llm.rest_nach_vorab(g2, text).startswith("Darf ich")


def test_vorab_fifo_verwirft_doppelten_mittelsatz():
    """FIFO: schon gesendete Chunks/Sätze werden VOR dem TTS verworfen."""
    a = ("Ja, genau. Ich bin die digitale Assistentin der Praxis und helfe "
         "Ihnen gerne bei Terminen oder Fragen.")
    b = "Ich bin die digitale Assistentin der Praxis und helfe Ihnen gerne bei Terminen oder Fragen."
    c = "Darf ich Sie schon weiterhelfen, zum Beispiel bei der Terminvereinbarung?"
    fifo: list[str] = []
    assert llm.vorab_fifo_anhaengen(fifo, a) is True
    assert llm.vorab_fifo_anhaengen(fifo, b) is False  # Satz schon in a
    assert llm.vorab_fifo_anhaengen(fifo, a) is False   # Chunk-Duplikat
    assert llm.vorab_fifo_anhaengen(fifo, c) is True
    assert fifo == [a, c]
    text = f"{a} {c}"
    assert llm.rest_nach_vorab(fifo, text) == ""
    assert llm.rest_nach_vorab(fifo, text + " Noch etwas?") == "Noch etwas?"


def test_dienst_spielt_vorab_duplikat_nicht_und_rendert_nur_rest():
    """Live Thaler/MedDent 08.09.: ein P5-Mittelsatz lag im Vorab und noch
    einmal im finalen WAV. Die Dienst-Ebene muss die FIFO wirklich nutzen."""
    from kern import dienst as dienst_mod
    from kern.dienst import Dienst

    a = (
        "Ah, Herr Petsas. Das ist ein häufiger Grund. "
        "Ich helfe Ihnen gerne bei der Terminvereinbarung."
    )
    doppelt = (
        "Das ist ein häufiger Grund. "
        "Ich helfe Ihnen gerne bei der Terminvereinbarung."
    )
    frage = "Haben Sie schon einen Termin in unserer Praxis?"
    blockierend: list[str] = []
    rest_render: list[str] = []

    def turn(sit, text, melde=None, vorab=None):
        assert vorab is not None
        vorab(a)
        vorab(doppelt)
        return {"text": f"{a} {frage}"}

    d = Dienst(name="test", start_fn=lambda sit: {}, turn_fn=turn)

    def stimme(text, karte=None):
        blockierend.append(text)
        return f"/api/audio/v{len(blockierend)}.wav", 0.0

    def stimme_stream(text, karte=None):
        rest_render.append(text)
        return "/api/audio/rest.wav", 0.0

    d.stimme = stimme  # type: ignore[method-assign]
    d.stimme_stream = stimme_stream  # type: ignore[method-assign]
    mitschnitte: list[dict] = []
    echt_mitschnitt = dienst_mod.mitschnitt.zug
    dienst_mod.mitschnitt.zug = (  # type: ignore[method-assign]
        lambda sit, dienst, **kw: mitschnitte.append(kw)
    )
    try:
        zeilen = [
            json.loads(z)
            for z in d.zug_stream({}, art="turn", text_in="Ich brauche eine Füllung.")
        ]
    finally:
        dienst_mod.mitschnitt.zug = echt_mitschnitt  # type: ignore[method-assign]
    assert blockierend == [a]
    assert rest_render == [frage]
    assert [z["type"] for z in zeilen].count("filler") == 1
    assert next(z for z in zeilen if z["type"] == "filler")["inhalt"] is True
    reply = next(z for z in zeilen if z["type"] == "reply")
    assert reply["text"] == f"{a} {frage}"
    assert any(w["w"] == "vorab-duplikat" for w in reply["waechter"])
    assert mitschnitte[0]["vorab_urls"] == ["/api/audio/v1.wav"]
    assert mitschnitte[0]["audio_url"] == "/api/audio/rest.wav"


def test_dienst_entfernt_vorab_nur_nach_erfolgreichem_tts():
    """Schlägt das Vorab-TTS fehl, muss der finale Render den ganzen Text
    behalten — sonst erkauft Entdopplung einen stummen Satzverlust."""
    from kern.dienst import Dienst

    a = "Ich helfe Ihnen gerne bei der Terminvereinbarung."
    frage = "Wann passt es Ihnen am besten?"
    rest_render: list[str] = []

    def turn(sit, text, melde=None, vorab=None):
        assert vorab is not None
        vorab(a)
        return {"text": f"{a} {frage}"}

    d = Dienst(name="test", start_fn=lambda sit: {}, turn_fn=turn)
    d.stimme = lambda text, karte=None: ("", 0.0)  # type: ignore[method-assign]

    def stimme_stream(text, karte=None):
        rest_render.append(text)
        return "/api/audio/ganz.wav", 0.0

    d.stimme_stream = stimme_stream  # type: ignore[method-assign]
    zeilen = [
        json.loads(z)
        for z in d.zug_stream({}, art="turn", text_in="Hallo.")
    ]
    assert rest_render == [f"{a} {frage}"]
    assert not any(z["type"] == "filler" for z in zeilen)
