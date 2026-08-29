"""W-HALBSATZ (29.08.2026): unfertige Saetze halten, weiterhoeren, zusammenfuegen.

Live-Protokoll 29.08. 09:34: "Hallo, ich habe naechste Woche Dienstag ein" —
das Stille-Zugende schnitt in der Denkpause, Bianca antwortete auf den
halben Satz, der Anrufer musste dreimal ansetzen. Die Wache haelt unfertig
klingende Zuege (Komma-Ende, haengender Artikel/Konjunktion), das Dock hoert
weiter, der naechste Zug wird serverseitig angefuegt.
"""

import json
import os

import kern.dienst as dienst_mod
import kern.halbsatz as hs
from kern.dienst import Dienst


# --- Heuristik: klingt der Satz unfertig? -----------------------------------

def test_unfertig_erkennt_die_echten_fragmente():
    # Genau die Schnitte aus dem Live-Protokoll (09:34):
    assert hs.unfertig("Hallo, ich habe nächste Woche Dienstag ein")
    assert hs.unfertig("Ich sagte, ich habe nächste Woche Dienstag einen Termin, aber ich weiss nicht mehr,")
    assert hs.unfertig("Ich sagte, ich habe nächste Woche einen Termin, aber ich weiss nicht mehr,")
    # Weitere typische Denkpausen-Schnitte:
    assert hs.unfertig("Ich hätte gern einen Termin bei")
    assert hs.unfertig("Ich wollte fragen, ob")
    assert hs.unfertig("Am besten wäre so gegen")
    assert hs.unfertig("Mein Nachname ist übrigens der")


def test_fertige_saetze_bleiben_fertig():
    assert not hs.unfertig("Ich hätte gern einen Termin.")
    assert not hs.unfertig("Waren Sie schon einmal bei uns?")
    assert not hs.unfertig("Ja.")
    assert not hs.unfertig("Nein, danke.")
    assert not hs.unfertig("Martin Berger")  # Name ohne Punkt: fertig
    assert not hs.unfertig("Ja gerne")       # Kurzantwort ohne Punkt: fertig
    assert not hs.unfertig("Passt schon")
    assert not hs.unfertig("")


def test_ziffern_zuege_werden_nie_gehalten():
    # Nummern-Diktat hat seine eigene Teil-Logik (telefonTeil) — nie halten.
    sit: dict = {}
    assert not hs.halten(sit, "null eins sieben sieben und")
    assert not hs.halten(sit, "Die Nummer ist 0177,")
    assert "halbsatz" not in sit


# --- Halten, Zusammenfuegen, Deckel, Flush ----------------------------------

def test_halten_und_mergen_kette():
    sit: dict = {}
    assert hs.halten(sit, "Hallo, ich habe nächste Woche Dienstag ein")
    voll = hs.mergen(sit, "einen Termin, aber ich weiss nicht mehr, wann genau.")
    assert voll == ("Hallo, ich habe nächste Woche Dienstag ein einen Termin, "
                    "aber ich weiss nicht mehr, wann genau.")
    assert not hs.halten(sit, voll)  # fertig -> beantworten, Zaehler zurueck
    assert int(sit.get("halbsatzZahl") or 0) == 0


def test_halte_deckel_zwei_verlaengerungen():
    sit: dict = {}
    assert hs.halten(sit, "Ich habe")
    voll = hs.mergen(sit, "nächste Woche einen")
    assert hs.halten(sit, voll)
    voll2 = hs.mergen(sit, "und")
    # Deckel erreicht: auch ein weiter unfertiger Satz wird jetzt beantwortet.
    assert not hs.halten(sit, voll2)
    assert voll2 == "Ich habe nächste Woche einen und"


def test_abholen_flush():
    sit: dict = {}
    assert hs.halten(sit, "Ich wollte noch sagen, dass")
    assert hs.abholen(sit) == "Ich wollte noch sagen, dass"
    assert hs.abholen(sit) == ""
    assert int(sit.get("halbsatzZahl") or 0) == 0


def test_notaus_satz_hold():
    os.environ["SATZ_HOLD"] = "0"
    try:
        sit: dict = {}
        assert not hs.halten(sit, "Hallo, ich habe nächste Woche Dienstag ein")
        assert "halbsatz" not in sit
    finally:
        os.environ.pop("SATZ_HOLD", None)


# --- Dienst-Ebene: warte-Event + Zusammenfuegen im Zug-Strom -----------------

def _dienst() -> tuple[Dienst, list[str]]:
    d = Dienst(name="t", start_fn=lambda sit: {}, turn_fn=lambda sit, t, **k: {})
    gesehen: list[str] = []

    def antwort(sit, *, art, text_in, extra=None, melde=None, vorab=None):
        gesehen.append(text_in)
        return {"ok": True, "empty": False, "text": "Antwort.", "audioUrl": "",
                "textIn": text_in}

    d.json_antwort = antwort
    return d, gesehen


def _zeilen(d: Dienst, sit: dict, **kw) -> list[dict]:
    return [json.loads(z) for z in d.zug_stream(sit, **kw)]


def test_dienst_haelt_und_fuegt_zusammen():
    d, gesehen = _dienst()
    sit: dict = {}
    z1 = _zeilen(d, sit, art="turn", text_in="Hallo, ich habe nächste Woche Dienstag ein")
    assert [z["type"] for z in z1] == ["warte"]
    assert z1[0]["stilleMs"] >= 700  # Dock hoert mit laengerer Ruhe-Schwelle weiter
    assert gesehen == []             # kein Fluss, kein LLM, kein Ton
    z2 = _zeilen(d, sit, art="turn",
                 text_in="einen Termin, aber ich weiss nicht mehr, wann genau.")
    assert [z["type"] for z in z2][-1] == "reply"
    assert gesehen and gesehen[0].startswith(
        "Hallo, ich habe nächste Woche Dienstag ein einen Termin")


def test_dienst_flush_bei_leerem_nachzug():
    """Anrufer setzt den Satz NICHT fort (Stille-Blob, leeres Transkript):
    das gehaltene Fragment wird beantwortet — nie verschluckt."""
    d, gesehen = _dienst()
    sit: dict = {}
    _zeilen(d, sit, art="turn", text_in="Ich wollte fragen, ob")
    echt = dienst_mod.stt.transcribe
    dienst_mod.stt.transcribe = lambda *a, **k: ""
    try:
        z = _zeilen(d, sit, art="listen", stt_blob=b"x" * 4000)
    finally:
        dienst_mod.stt.transcribe = echt
    assert [x["type"] for x in z][-1] == "reply"
    assert gesehen == ["Ich wollte fragen, ob"]


def test_dienst_fertiger_satz_laeuft_unveraendert():
    d, gesehen = _dienst()
    sit: dict = {}
    z = _zeilen(d, sit, art="turn", text_in="Ich hätte gern einen Termin.")
    assert [x["type"] for x in z] == ["reply"]
    assert gesehen == ["Ich hätte gern einen Termin."]
