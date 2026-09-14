"""W-QWEN-KORREKTOR (13.09.2026): Qwen als asynchrones Zweit-Ohr.

Chef: "das gespraech laeuft ueber parakeet die ganze zeit weiter ... qwens
transkript liegt vor und hat jetzt vorrang und llm versteht im vergleich zum
aktuellen parakeet turn und vorherigen qwen turn das richtige."

Alle Faelle offline (kein Netz, kein Modell). Die Verhoerer sind die echten
Thaler-Clips vom 11.09.2026 (Parakeet live vs. Qwen nachgehoert).
"""

from __future__ import annotations

import json
import os
import struct

import pytest

import kern.dienst as dienst_mod
import kern.mitschnitt as mit
from kern import qwen_korrektor as qk
from kern.dienst import Dienst


@pytest.fixture(autouse=True)
def _an(monkeypatch):
    monkeypatch.delenv("QWEN_KORREKTOR", raising=False)
    monkeypatch.setattr(qk, "_vokabular", lambda sit: {"petsas", "patrikis"})


def _sit(**extra) -> dict:
    sit = {"id": "ab12cd34ef56ab12", "stimme": "Bianca", "tenantId": "thaler",
           "messages": [{"role": "system", "content": "sys"}], "tenant": {}}
    sit.update(extra)
    return sit


def _qwen(sit, zug, parakeet, qwen, *, auth=True, spaet=True, s=1.0):
    return qk.nachtrag(sit, zug, {"text": qwen, "parakeet": parakeet,
                                  "authoritative": auth, "spaet": spaet, "s": s,
                                  "reason": "" if auth else "not_authoritative"})


# ------------------------------------------------------------- Nachtrag

def test_nachtrag_merkt_ergebnis_und_lernt_zwei_zu_eins_verhoerer():
    """'Brent Campbellt' (2 Woerter) -> 'Röntgenbild' (1 Wort) wird als EIN Paar
    gelernt; Qwens Inhaltswort wird Hotword fuer Parakeets Folge-Zuege."""
    sit = _sit()
    e = _qwen(sit, 1, "Brent Campbellt.", "Röntgenbild.", s=4.8)
    assert e and e["zug"] == 1 and e["auth"] and e["spaet"]
    assert sit["qwenSpaet"][0]["qwen"] == "Röntgenbild."
    assert sit["qwenWoerter"] == {"brent campbellt": "Röntgenbild"}
    assert qk.hotwords(sit) == ["Röntgenbild"]
    assert e["gelernt"] == ["brent campbellt->Röntgenbild"]


def test_nachtrag_lernt_drei_zu_eins_und_ein_zu_eins():
    sit = _sit()
    _qwen(sit, 1, "Ich brauche mein Rentenbild für den Zahnarzt.",
          "Ich brauche mein Röntgenbild für den Zahnarzt.")
    _qwen(sit, 2, "Brennt ein Builder faxen.", "Röntgenbilder faxen.")
    assert sit["qwenWoerter"] == {"rentenbild": "Röntgenbild",
                                  "brennt ein builder": "Röntgenbilder"}
    assert qk.hotwords(sit) == ["Röntgenbild", "Röntgenbilder"]


def test_nachtrag_lernt_nichts_ohne_autoritaet_oder_bei_ziffernabweichung():
    sit = _sit()
    _qwen(sit, 1, "Brent Campbellt.", "Röntgenbild.", auth=False)
    assert "qwenWoerter" not in sit and qk.hotwords(sit) == []
    # Ziffern gehoeren dem Readback-Waechter: weicht die Folge ab, wird der
    # Zug NICHT als Lernquelle genommen.
    _qwen(sit, 2, "Meine Nummer ist 0177 123, Rentenbild.",
          "Meine Nummer ist 0177 128, Röntgenbild.")
    assert "qwenWoerter" not in sit


def test_nachtrag_lernt_keine_mandanten_und_strukturwoerter():
    sit = _sit()
    # Parakeet traegt den Behandler (Hotword aus der DB) -> vertrauen, nichts lernen.
    _qwen(sit, 1, "Termin bei Petsas bitte.", "Termin bei Betsas bitte.")
    assert "qwenWoerter" not in sit
    # Strukturwoerter/Zahlwoerter werden nie gelernt.
    _qwen(sit, 2, "Ich möchte einen Termin.", "Ich hätte gern einen Termin.")
    assert "qwenWoerter" not in sit


def test_nachtrag_deckelt_sitzung():
    sit = _sit()
    n = max(qk._MAX_SPAET, qk._MAX_WOERTER) + 4

    def _suffix(i: int) -> str:
        return chr(ord("a") + i % 26) * (1 + i // 26)

    for i in range(n):
        s = _suffix(i)
        _qwen(sit, i + 1, f"Rentenbild{s} bitte.", f"Röntgenbild{s} bitte.")
    assert len(sit["qwenSpaet"]) == qk._MAX_SPAET
    assert 0 < len(sit["qwenWoerter"]) <= qk._MAX_WOERTER
    # Quell-Zug-Tabelle bleibt deckungsgleich mit dem Woerterbuch.
    assert set(sit["qwenWoerterZug"]) == set(sit["qwenWoerter"])
    # Der juengste Eintrag ueberlebt den Deckel, der aelteste faellt.
    assert f"rentenbild{_suffix(n - 1)}" in sit["qwenWoerter"]
    assert "rentenbilda" not in sit["qwenWoerter"]


# -------------------------------------------------------------- Anwenden

def test_widerspruch_zieht_qwens_fassung_vor_und_schreibt_verlauf_um():
    """Der Chef-Fall: Parakeet 'Brent Campbellt' -> Bianca versteht nichts ->
    Anrufer: 'Nein, Röntgenbild!' -> Qwens Text zum vorigen Zug gilt."""
    sit = _sit()
    sit["messages"] += [{"role": "user", "content": "Brent Campbellt."},
                        {"role": "assistant", "content": "Das habe ich nicht verstanden."}]
    qk.naechster_zug(sit)  # Zug 1 (der verhoerte)
    _qwen(sit, 1, "Brent Campbellt.", "Röntgenbild.")
    qk.naechster_zug(sit)  # Zug 2
    text, detail = qk.anwenden(sit, "Nein, Röntgenbild!")
    assert text == "Nein, Röntgenbild!"
    assert detail["vorzug"] and detail["grund"] == "widerspruch" and detail["zug"] == 1
    assert detail["verlauf"] is True
    assert sit["messages"][1]["content"] == "Röntgenbild."
    assert sit["qwenSpaet"][0]["verwendet"] is True
    h = qk.prompt_hinweis(sit)
    assert "Röntgenbild." in h and "Brent Campbellt." in h
    assert qk.prompt_hinweis(sit) == ""  # einmalig


def test_wiederholung_des_verhoerers_wird_qwens_text():
    """Anrufer sagt denselben Satz noch einmal — Parakeet hoert ihn wieder
    falsch, Qwens Fassung IST der neue Zug."""
    sit = _sit()
    qk.naechster_zug(sit)
    _qwen(sit, 1, "Brent Campbellt.", "Röntgenbild.")
    qk.naechster_zug(sit)
    text, detail = qk.anwenden(sit, "Brent Campbell.")
    assert text == "Röntgenbild."
    assert detail["grund"] == "wiederholung" and detail["textVorher"] == "Brent Campbell."


def test_woerterbuch_ersetzt_gelernten_verhoerer_im_folgezug():
    sit = _sit()
    qk.naechster_zug(sit)
    _qwen(sit, 1, "Ich bräuchte mein Rückenbild bitte.", "Ich bräuchte mein Röntgenbild bitte.")
    assert sit["qwenWoerter"] == {"rückenbild": "Röntgenbild"}
    qk.naechster_zug(sit)
    qk.naechster_zug(sit)
    qk.naechster_zug(sit)  # weit spaeter, kein Vorzug mehr — Woerterbuch bleibt
    text, detail = qk.anwenden(sit, "Rückenbild, für den Zahnarzt.")
    assert text == "Röntgenbild, für den Zahnarzt."
    assert detail["woerterbuch"] == ["Rückenbild->Röntgenbild"]
    assert not detail.get("vorzug")


def test_woerterbuch_laesst_mandantenwoerter_und_ziffern_in_ruhe():
    sit = _sit(qwenWoerter={"petsas": "Betsas", "0177": "0178"})
    text, detail = qk.anwenden(sit, "Bei Petsas, Nummer 0177.")
    assert text == "Bei Petsas, Nummer 0177." and detail == {}


def test_unbezogener_folgezug_laesst_alles_stehen():
    sit = _sit()
    sit["messages"] += [{"role": "user", "content": "Brent Campbellt."}]
    qk.naechster_zug(sit)
    _qwen(sit, 1, "Brent Campbellt.", "Röntgenbild.")
    qk.naechster_zug(sit)
    text, detail = qk.anwenden(sit, "Ja, morgen um zehn Uhr passt.")
    assert text == "Ja, morgen um zehn Uhr passt." and detail == {}
    assert sit["messages"][1]["content"] == "Brent Campbellt."  # Verlauf unangetastet
    assert not sit["qwenSpaet"][0].get("verwendet")
    assert qk.prompt_hinweis(sit) == ""


def test_kein_vorzug_wenn_qwen_und_parakeet_fast_gleich_oder_ziffern_abweichen():
    sit = _sit()
    qk.naechster_zug(sit)
    _qwen(sit, 1, "Ich hätte gern einen Termin.", "Ich hätte gerne einen Termin.")
    qk.naechster_zug(sit)
    _, detail = qk.anwenden(sit, "Nein, ich hätte gern einen Termin.")
    assert not detail.get("vorzug")
    sit2 = _sit()
    qk.naechster_zug(sit2)
    _qwen(sit2, 1, "Meine Nummer 0177 123 Rentenbild.", "Meine Nummer 0177 128 Röntgenbild.")
    qk.naechster_zug(sit2)
    _, detail = qk.anwenden(sit2, "Nein, Röntgenbild.")
    assert not detail.get("vorzug")


def test_vorzug_nur_fuer_den_vorigen_oder_vorvorigen_zug():
    sit = _sit()
    qk.naechster_zug(sit)
    _qwen(sit, 1, "Brent Campbellt.", "Röntgenbild.")
    for _ in range(4):
        qk.naechster_zug(sit)
    _, detail = qk.anwenden(sit, "Nein, Röntgenbild!")
    assert not detail.get("vorzug")


def test_qwen_aus_dem_eigenen_zug_hebelt_das_live_ohr_nicht_aus():
    """Kommt Qwens Ergebnis zum SELBEN Zug noch VOR dem Korrektor an (schnelle
    Qwen-Antwort, aber vom Live-Ohr abgelehnt oder knapp zu spaet), bleibt der
    Live-Text dieses Zugs stehen — weder als 'Wiederholung' vorgezogen noch
    per frisch gelerntem Woerterbuch ersetzt. Qwen ist nicht das Live-Ohr;
    erst der Folgezug (Signal des Anrufers / Woerterbuch) nutzt die Fassung."""
    sit = _sit()
    zug1 = qk.naechster_zug(sit)
    _qwen(sit, zug1, "Brent Campbellt.", "Röntgenbild.", spaet=False)
    assert sit["qwenWoerter"] == {"brent campbellt": "Röntgenbild"}
    text, detail = qk.anwenden(sit, "Brent Campbellt.")
    assert text == "Brent Campbellt."
    assert detail == {}
    # Folgezug: jetzt greifen Woerterbuch UND Vorzug.
    qk.naechster_zug(sit)
    text2, detail2 = qk.anwenden(sit, "Brent Campbellt.")
    assert text2 == "Röntgenbild."
    assert detail2.get("woerterbuch") or detail2.get("vorzug")


def test_prompt_hinweis_verfaellt_wenn_der_zug_ohne_modell_beantwortet_wurde():
    """Beantwortet die Maschine den korrigierten Zug deterministisch, darf der
    Hinweis NICHT im naechsten (fremden) LLM-Zug auftauchen."""
    sit = _sit()
    qk.naechster_zug(sit)
    _qwen(sit, 1, "Brent Campbellt.", "Röntgenbild.")
    qk.naechster_zug(sit)
    qk.anwenden(sit, "Nein, Röntgenbild!")
    assert isinstance(sit.get("qwenKorrekturHinweis"), dict)
    qk.naechster_zug(sit)  # naechster Zug — der Hinweis gehoert zu Zug 2
    assert qk.prompt_hinweis(sit) == ""
    assert "qwenKorrekturHinweis" not in sit


def test_notaus_schaltet_alles_ab(monkeypatch):
    monkeypatch.setenv("QWEN_KORREKTOR", "0")
    sit = _sit(qwenWoerter={"rückenbild": "Röntgenbild"})
    assert _qwen(sit, 1, "Brent Campbellt.", "Röntgenbild.") is None
    assert "qwenSpaet" not in sit
    text, detail = qk.anwenden(sit, "Mein Rückenbild bitte.")
    assert text == "Mein Rückenbild bitte." and detail == {}
    assert qk.hotwords(sit) == []


# ------------------------------------------------------------ Mitschnitt

def _wav(ms: int = 200, rate: int = 24000) -> bytes:
    pcm = b"\x00\x00" * (rate * ms // 1000)
    kopf = struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(pcm), b"WAVE",
                       b"fmt ", 16, 1, 1, rate, rate * 2, 2, 16, b"data", len(pcm))
    return kopf + pcm


def _manifest(tmp_path, sit) -> dict:
    return json.loads((tmp_path / "anrufe" / "bianca" / sit["id"] / "anruf.json").read_text(encoding="utf-8"))


def test_mitschnitt_traegt_ohr_und_spaetes_qwen(monkeypatch, tmp_path):
    monkeypatch.setattr(mit, "DATA_DIR", tmp_path)
    d = Dienst(name="test", start_fn=lambda sit: {}, turn_fn=lambda sit, t, **kw: {})
    sit = _sit(startedAt="2026-09-13T08:00:00+00:00", zuege=[])
    stt = {"pipeline": "audio", "winner": "parakeet", "zug": 1,
           "parakeet": {"text": "Brent Campbellt.", "suspicious": True},
           "qwen": {"text": "", "status": "parallel_zu_spaet"}}
    mit.zug(sit, d, art="listen", text_in="Brent Campbellt.", text="Wie bitte?", stt=stt)
    z = _manifest(tmp_path, sit)["zuege"][0]
    assert z["stt"]["winner"] == "parakeet" and z["stt"]["zug"] == 1
    assert z["stt"]["parakeet"] == {"text": "Brent Campbellt.", "suspicious": True}
    # Qwen kommt spaeter -> haengt sich an den Zug mit stt.zug == 1.
    assert mit.stt_nachtragen(sit, 1, {"qwen": "Röntgenbild.", "auth": True, "s": 4.8,
                                        "gelernt": ["brent campbellt->Röntgenbild"]})
    z = _manifest(tmp_path, sit)["zuege"][0]
    assert z["stt"]["qwen"]["spaet"]["qwen"] == "Röntgenbild."
    assert z["stt"]["qwen"]["status"] == "parallel_zu_spaet"


def test_mitschnitt_haelt_qwen_der_vor_dem_zug_eintrifft(monkeypatch, tmp_path):
    """Qwen kann schneller sein als die Antwort: dann wartet das Ergebnis in
    der Sitzung und haengt sich an, sobald zug() den Eintrag anlegt."""
    monkeypatch.setattr(mit, "DATA_DIR", tmp_path)
    d = Dienst(name="test", start_fn=lambda sit: {}, turn_fn=lambda sit, t, **kw: {})
    sit = _sit(startedAt="2026-09-13T08:00:00+00:00", zuege=[])
    assert not mit.stt_nachtragen(sit, 3, {"qwen": "Röntgenbild.", "auth": True, "s": 0.9})
    mit.zug(sit, d, art="listen", text_in="Rhöngbild.", text="Gerne.",
            stt={"winner": "parakeet", "zug": 3, "parakeet": {"text": "Rhöngbild."}})
    z = _manifest(tmp_path, sit)["zuege"][0]
    assert z["stt"]["qwen"]["spaet"]["qwen"] == "Röntgenbild."
    assert not sit.get("_qwenSpaetOffen")


def test_nachtrag_schreibt_in_den_mitschnitt(monkeypatch, tmp_path):
    monkeypatch.setattr(mit, "DATA_DIR", tmp_path)
    d = Dienst(name="test", start_fn=lambda sit: {}, turn_fn=lambda sit, t, **kw: {})
    sit = _sit(startedAt="2026-09-13T08:00:00+00:00", zuege=[])
    mit.zug(sit, d, art="listen", text_in="Brent Campbellt.", text="Wie bitte?",
            stt={"winner": "parakeet", "zug": 1, "parakeet": {"text": "Brent Campbellt."}})
    _qwen(sit, 1, "Brent Campbellt.", "Röntgenbild.", s=4.8)
    z = _manifest(tmp_path, sit)["zuege"][0]
    assert z["stt"]["qwen"]["spaet"] == {"qwen": "Röntgenbild.", "auth": True, "s": 4.8,
                                         "reason": "", "gelernt": ["brent campbellt->Röntgenbild"]}


# ----------------------------------------------------------- Dienst-Kette

def _dienst_mit_ohr(monkeypatch, gehoert: list[str], qwen_spaet: dict[str, str]):
    """Fake-Ohr: Parakeet liefert `gehoert` der Reihe nach; fuer Texte in
    `qwen_spaet` meldet sich Qwen sofort ueber den Nachtrag-Callback."""
    d = Dienst(name="t", start_fn=lambda sit: {}, turn_fn=lambda sit, t, **k: {})
    gesehen: list[dict] = []
    aufrufe: list[dict] = []

    def antwort(sit, *, art, text_in, extra=None, melde=None, vorab=None):
        gesehen.append({"text": text_in, "stt": dict(sit.get("_sttInfo") or {}),
                        "zug": qk.zug_nr(sit)})
        sit.pop("_sttInfo", None)
        sit.pop("_sttS", None)
        return {"ok": True, "empty": False, "text": "Antwort.", "audioUrl": "", "textIn": text_in}

    d.json_antwort = antwort

    def transcribe(audio, *, mime="audio/wav", name="zug.wav", keywords="", nachtrag=None,
                   qwen_sperre=None):
        text = gehoert.pop(0)
        # W-QWEN-SICHER: das echte Ohr fragt die Sperre mit Parakeets Text.
        sperre = qwen_sperre(text) if qwen_sperre is not None else None
        aufrufe.append({"keywords": keywords, "nachtrag": nachtrag is not None,
                        "sperre": sperre})
        info = {"pipeline": "audio", "winner": "parakeet",
                "parakeet": {"text": text, "suspicious": text in qwen_spaet},
                "qwen": {"text": "", "status": "parallel_zu_spaet"}}
        if nachtrag is not None and text in qwen_spaet:
            nachtrag({"text": qwen_spaet[text], "parakeet": text, "authoritative": True,
                      "reason": "", "spaet": True, "s": 1.1})
        return text, info

    monkeypatch.setattr(dienst_mod.stt_spur, "transcribe", transcribe)
    return d, gesehen, aufrufe


def _zeilen(d: Dienst, sit: dict, **kw) -> list[dict]:
    return [json.loads(z) for z in d.zug_stream(sit, **kw)]


def test_dienst_reicht_nachtrag_hotwords_und_korrektur_durch(monkeypatch):
    """Ende-zu-Ende im Dienst: Zug 1 verhoert (Qwen meldet spaet 'Röntgenbild'),
    Zug 2 Widerspruch -> Korrektur vor dem Hirn, Hotword an Parakeet, Ohr-
    Diagnose je Zug fuer Anrufliste/Studio."""
    d, gesehen, aufrufe = _dienst_mit_ohr(
        monkeypatch, ["Brent Campbellt.", "Nein, Röntgenbild!"],
        {"Brent Campbellt.": "Röntgenbild."})
    sit = {"tenant": {}, "messages": [{"role": "system", "content": "s"}]}
    z1 = _zeilen(d, sit, art="listen", stt_blob=b"x" * 4000, stt_mime="audio/wav", stt_name="a.wav")
    assert z1[-1]["type"] == "reply"
    assert aufrufe[0]["nachtrag"] is True
    assert gesehen[0]["text"] == "Brent Campbellt." and gesehen[0]["zug"] == 1
    assert gesehen[0]["stt"]["winner"] == "parakeet" and gesehen[0]["stt"]["zug"] == 1
    assert "korrektur" not in gesehen[0]["stt"]
    assert sit["qwenSpaet"][0]["qwen"] == "Röntgenbild."
    # Der Anrufer-Satz steht im Verlauf (wie ihn agent.user_turn anhaengen wuerde).
    sit["messages"].append({"role": "user", "content": "Brent Campbellt."})

    z2 = _zeilen(d, sit, art="listen", stt_blob=b"x" * 4000, stt_mime="audio/wav", stt_name="b.wav")
    assert z2[-1]["type"] == "reply"
    assert "Röntgenbild" in aufrufe[1]["keywords"].split(",")  # Hotword fuer Parakeet
    k = gesehen[1]["stt"]["korrektur"]
    assert k["vorzug"] and k["grund"] == "widerspruch" and k["qwenVorher"] == "Röntgenbild."
    assert sit["messages"][1]["content"] == "Röntgenbild."
    assert isinstance(sit.get("qwenKorrekturHinweis"), dict) and sit["qwenKorrekturHinweis"]["zug"] == 2


def test_dienst_ohne_qwen_bleibt_byteidentisch(monkeypatch):
    d, gesehen, aufrufe = _dienst_mit_ohr(monkeypatch, ["Hallo, ich hätte gern einen Termin."], {})
    sit = {"tenant": {}}
    z = _zeilen(d, sit, art="listen", stt_blob=b"x" * 4000, stt_mime="audio/wav", stt_name="a.wav")
    assert z[-1]["type"] == "reply"
    assert gesehen[0]["text"] == "Hallo, ich hätte gern einen Termin."
    assert "korrektur" not in gesehen[0]["stt"]
    assert "qwenSpaet" not in sit and "qwenWoerter" not in sit
    assert aufrufe[0]["keywords"] == ",".join(dienst_mod.tenants.stt_keywords({}))


# ------------------------------------------------ W-QWEN-SICHER (14.09.2026)
# Live-Befunde vom 13./14.09.: der Korrektor lernte "Termin Absage" ->
# "Terminabfrage" (Anruf 3baead87) und "versichert" -> "interessiert"
# (5aa87268); Qwen halluzinierte auf der Nachnamen-Frage "Da sagt Gott"
# fuer Parakeets "Casacop." (48d3ac3f). Namen, Job-Woerter, Antwort-Woerter
# und Zeitwoerter sind seitdem tabu; bei offener Namensfrage/Diktat oder
# schon erkannter Antwort ist Qwen im Zug gesperrt.

def _sit_frage(fid: str, **sammler) -> dict:
    sit = _sit()
    sit["sammler"] = {"frage": fid, **sammler}
    return sit


def test_job_und_antwortwoerter_werden_nie_gelernt():
    sit = _sit_frage("grund")
    qk.naechster_zug(sit)
    # Anruf 3baead87: aus einer Absage waere im Folgezug eine Auskunft geworden.
    _qwen(sit, 1, "Ich möchte eine Termin Absage machen.",
          "Ich möchte eine Terminabfrage machen.")
    assert "qwenWoerter" not in sit
    # Anruf 5aa87268: die Versicherungs-Antwort haette Qwen "verlernt".
    qk.naechster_zug(sit)
    _qwen(sit, 2, "Ich bin gesetzlich versichert.", "Ich bin gesetzlich interessiert.")
    assert "qwenWoerter" not in sit
    # Zeitwoerter: ein Wochentag darf nie in einen anderen umgeschrieben werden.
    qk.naechster_zug(sit)
    _qwen(sit, 3, "Am Montag bitte.", "Am Sonntag bitte.")
    assert "qwenWoerter" not in sit
    assert qk.hotwords(sit) == []


def test_erwartete_antwort_der_offenen_frage_ist_kein_verhoerer():
    """Kassen-Name auf die Versicherungsfrage: Parakeet hat die erwartete
    Antwort, Qwens Lesart ist kein Gewinn — nichts lernen."""
    sit = _sit_frage("versicherung")
    qk.naechster_zug(sit)
    _qwen(sit, 1, "Bei der Barmer.", "Bei der Wärmer.")
    assert "qwenWoerter" not in sit
    # Gegenprobe: dieselbe Lesart auf einer offenen Frage OHNE Erwartungs-
    # Vokabular (Besuchsgrund) wird weiterhin gelernt.
    sit2 = _sit_frage("grund")
    qk.naechster_zug(sit2)
    _qwen(sit2, 1, "Bei der Barmer.", "Bei der Wärmer.")
    assert sit2["qwenWoerter"] == {"barmer": "Wärmer"}


def test_namenszug_ist_keine_lernquelle_und_gibt_keinen_vorzug():
    """Anruf 48d3ac3f: Parakeet 'Casacop.' (auffaellig), Qwen 'Da sagt Gott.'
    — kein Woerterbuch, kein Hotword, und auch die Wiederholung des Namens
    im Folgezug darf Qwens Fassung nicht zum Zug machen."""
    sit = _sit_frage("nachname")
    sit["messages"].append({"role": "user", "content": "Casacop."})
    z = qk.naechster_zug(sit)
    e = _qwen(sit, z, "Casacop.", "Da sagt Gott.")
    assert e["gesperrt"] == "namensfrage:nachname" and e["frage"] == "nachname"
    assert "qwenWoerter" not in sit and qk.hotwords(sit) == []
    # Folgezug: die Maschine fragt nach dem Buchstabieren, der Anrufer
    # wiederholt den Namen — Wiederholung des Verhoerers.
    sit["sammler"]["frage"] = "buchstabieren"
    qk.naechster_zug(sit)
    neu, detail = qk.anwenden(sit, "Casacop.")
    assert neu == "Casacop." and not detail.get("vorzug")
    assert sit["messages"][-1]["content"] == "Casacop."  # Verlauf unangetastet
    assert "qwenKorrekturHinweis" not in sit
    # Auch spaeter, auf einer normalen Frage, gibt der Namens-Zug keinen Vorzug.
    sit["sammler"]["frage"] = "grund"
    qk.naechster_zug(sit)
    neu, detail = qk.anwenden(sit, "Nein, Casacop!")
    assert neu == "Nein, Casacop!" and not detail.get("vorzug")


def test_anwenden_pausiert_waehrend_namensfrage_und_diktat():
    """Ein gelerntes Paar darf einen NAMEN nie 'korrigieren' — und waehrend
    des Ziffern-/Buchstabier-Diktats bleibt der Zug unangetastet."""
    sit = _sit_frage("grund")
    qk.naechster_zug(sit)
    _qwen(sit, 1, "Rentenbild bitte.", "Röntgenbild bitte.")
    assert sit["qwenWoerter"] == {"rentenbild": "Röntgenbild"}
    qk.naechster_zug(sit)
    # Auf die Vornamen-Frage kommt etwas, das dem Verhoerer aehnelt.
    sit["sammler"]["frage"] = "vorname"
    neu, detail = qk.anwenden(sit, "Rentenbald.")
    assert neu == "Rentenbald." and detail == {"pause": "namensfrage:vorname"}
    # Laufendes Buchstabier-Diktat: ebenso Pause.
    sit["sammler"] = {"frage": "grund", "buchstabenTeil": "R E N"}
    neu, detail = qk.anwenden(sit, "Rentenbald.")
    assert neu == "Rentenbald." and detail == {"pause": "diktat"}
    # Gegenprobe: auf der Besuchsgrund-Frage greift das Woerterbuch.
    sit["sammler"] = {"frage": "grund"}
    neu, detail = qk.anwenden(sit, "Rentenbald.")
    assert neu == "Röntgenbild." and detail["woerterbuch"] == ["Rentenbald->Röntgenbild"]


def test_woerterbuch_laesst_geschuetzte_woerter_in_ruhe():
    """Unscharfer Treffer gegen ein Antwort-/Zeitwort: 'versichert' ~
    'versickert', 'Montag' ~ 'sontag' — beides bleibt stehen."""
    sit = _sit_frage("versicherung")
    sit["qwenWoerter"] = {"versickert": "Verschickt", "sontag": "Sonntag"}
    sit["qwenWoerterZug"] = {"versickert": 1, "sontag": 1}
    sit["_zugNr"] = 3
    neu, detail = qk.anwenden(sit, "Ich bin gesetzlich versichert, am Montag.")
    assert neu == "Ich bin gesetzlich versichert, am Montag." and detail == {}


def test_live_sperre_je_frage_kontext(monkeypatch):
    monkeypatch.delenv("QWEN_LIVE_SPERRE", raising=False)
    assert qk.live_sperre(_sit_frage("nachname"), "Casacop.") == "namensfrage:nachname"
    assert qk.live_sperre(_sit_frage("buchstabieren"), "T Z A") == "namensfrage:buchstabieren"
    assert qk.live_sperre(_sit_frage("grund", buchstabenTeil="T Z"), "A N") == "diktat"
    assert qk.live_sperre(_sit_frage("telefon"), "null eins sieben") == "diktat:telefon"
    # Parakeet traegt die erwartete Antwort -> Qwen darf nicht anders lesen.
    assert qk.live_sperre(_sit_frage("versicherung"), "Gesetze versichert.") == \
        "erwartet:versicherung:versichert"
    assert qk.live_sperre(_sit_frage("schonmal"), "Nein, das erste Mal.") == "erwartet:schonmal:erste"
    assert qk.live_sperre(_sit_frage("slotwahl"), "Der frühere.") == "erwartet:slotwahl:frühere"
    # Offen: Besuchsgrund ohne Erwartungs-Vokabular, Lisa ohne Sammler, Notaus.
    assert qk.live_sperre(_sit_frage("grund"), "Brent Campbellt.") == ""
    assert qk.live_sperre(_sit_frage("versicherung"), "Äh, wie bitte?") == ""
    assert qk.live_sperre(_sit(), "Casacop.") == ""
    monkeypatch.setenv("QWEN_LIVE_SPERRE", "0")
    assert qk.live_sperre(_sit_frage("nachname"), "Casacop.") == ""


def test_dienst_fragt_die_sperre_mit_parakeets_text(monkeypatch):
    """Ende-zu-Ende im Dienst: auf der Nachnamen-Frage bekommt das Ohr die
    Sperre, die Diagnose traegt sie fuer die Anrufliste, der Nachtrag lernt
    nichts aus dem Namens-Zug."""
    d, gesehen, aufrufe = _dienst_mit_ohr(
        monkeypatch, ["Casacop."], {"Casacop.": "Da sagt Gott."})
    sit = {"tenant": {}, "messages": [{"role": "system", "content": "s"}],
           "sammler": {"frage": "nachname"}}
    z = _zeilen(d, sit, art="listen", stt_blob=b"x" * 4000, stt_mime="audio/wav", stt_name="a.wav")
    assert z[-1]["type"] == "reply"
    assert aufrufe[0]["sperre"] == "namensfrage:nachname"
    assert gesehen[0]["stt"]["qwen"]["sperre"] == "namensfrage:nachname"
    assert sit["qwenSpaet"][0]["gesperrt"] == "namensfrage:nachname"
    assert "qwenWoerter" not in sit and qk.hotwords(sit) == []


def test_vorab_ohr_der_docks_fragt_dieselbe_sperre(monkeypatch):
    """W-TEMPO-Vorab (`/api/hoeren`) transkribiert VOR dem echten Zug — ohne
    die Sperre haette Qwen dort bei offener Namensfrage gewinnen koennen und
    der Zug waere als TEXT mit Qwens Lesart an /api/listen gegangen."""
    import asyncio
    import io

    from fastapi import UploadFile

    from bianca import server as bianca_server

    sit = _sit_frage("nachname")
    monkeypatch.setattr(bianca_server.session, "holen", lambda sid: sit if sid == "s1" else None)
    gesehen: list[dict] = []

    def transcribe(audio, *, mime="audio/webm", name="turn.webm", keywords="", **extra):
        sperre = extra.get("qwen_sperre")
        gesehen.append({"keywords": keywords,
                        "sperre": sperre("Casacop.") if sperre is not None else None})
        return "Casacop."

    monkeypatch.setattr(bianca_server.stt, "transcribe", transcribe)
    datei = UploadFile(file=io.BytesIO(b"x" * 64), filename="vorab.webm")
    aus = asyncio.run(bianca_server.api_hoeren(sessionId="s1", audio=datei))
    assert aus == {"ok": True, "text": "Casacop."}
    assert gesehen[0]["sperre"] == "namensfrage:nachname"
    # Ohne Sammler-Frage (Lisa/leer) bleibt die Sperre leer wie bisher.
    sit["sammler"] = {}
    datei = UploadFile(file=io.BytesIO(b"x" * 64), filename="vorab.webm")
    asyncio.run(bianca_server.api_hoeren(sessionId="s1", audio=datei))
    assert gesehen[1]["sperre"] == ""
