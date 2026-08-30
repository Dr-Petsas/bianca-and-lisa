"""W-MITSCHNITT (30.08.2026): jeder Anruf landet als Ordner unter
.data/anrufe/<stimme>/<sid>/ — Manifest (anruf.json) plus Audio je Zug.
Offline: Dienst ohne TTS/Netz, Audio kommt aus der RAM-Ablage."""

from __future__ import annotations

import json
import struct

import kern.mitschnitt as mit
from kern.dienst import Dienst


def _wav(ms: int = 200, rate: int = 24000) -> bytes:
    pcm = b"\x00\x00" * (rate * ms // 1000)
    kopf = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + len(pcm), b"WAVE",
        b"fmt ", 16, 1, 1, rate, rate * 2, 2, 16,
        b"data", len(pcm),
    )
    return kopf + pcm


def _dienst() -> Dienst:
    return Dienst(name="test", start_fn=lambda sit: {}, turn_fn=lambda sit, t, **kw: {})


def _sit(sid: str = "ab12cd34ef56ab12") -> dict:
    return {
        "id": sid,
        "stimme": "Bianca",
        "tenantId": "meddent",
        "startedAt": "2026-08-30T08:00:00+00:00",
        "patient": {"name": "Martin Berger"},
        "zuege": [],
    }


def _umleiten(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(mit, "DATA_DIR", tmp_path)


def test_eingang_und_zug_schreiben_manifest_und_audio(monkeypatch, tmp_path):
    _umleiten(monkeypatch, tmp_path)
    d = _dienst()
    sit = _sit()
    url = d.audio_legen(_wav(300))

    mit.eingang(sit, _wav(150), "audio/wav")
    mit.zug(sit, d, art="turn", text_in="Ich habe Zahnschmerzen.",
            text="Das tut mir leid. Waren Sie schon einmal bei uns?",
            timings={"stt": 0.4, "llm": 1.1, "tts": 0.3, "total": 1.8},
            audio_url=url, frage="schonmal")

    pfad = tmp_path / "anrufe" / "bianca" / sit["id"]
    m = json.loads((pfad / "anruf.json").read_text(encoding="utf-8"))
    assert m["id"] == sit["id"] and m["stimme"] == "Bianca"
    assert m["patientName"] == "Martin Berger"
    z = m["zuege"][0]
    assert z["nr"] == 1 and z["art"] == "turn"
    assert z["textIn"] == "Ich habe Zahnschmerzen."
    assert z["timings"]["total"] == 1.8 and z["frage"] == "schonmal"
    assert z["offsetMs"] >= 0 and z["zeit"]
    # Anrufer-Audio: Liste (W-HALBSATZ kann zwei Aufnahmen je Zug liefern).
    assert z["audioIn"][0]["datei"] == "z001_anrufer.wav"
    assert z["audioIn"][0]["ms"] == 150
    # Gesprochenes Audio: sofort eingelöst (Blocking-Ablage).
    assert z["audioOut"][0]["datei"] == "z001_stimme.wav"
    assert z["audioOut"][0]["ms"] == 300
    assert (pfad / "z001_anrufer.wav").is_file()
    assert (pfad / "z001_stimme.wav").is_file()


def test_zwei_eingaenge_haengen_am_selben_zug(monkeypatch, tmp_path):
    """W-HALBSATZ: gehaltenes Fragment + Fortsetzung = zwei Aufnahmen, EIN Zug."""
    _umleiten(monkeypatch, tmp_path)
    d = _dienst()
    sit = _sit()
    mit.eingang(sit, _wav(100), "audio/wav")
    mit.eingang(sit, _wav(100), "audio/wav")
    mit.zug(sit, d, art="turn", text_in="Ich habe nächste Woche Dienstag einen Termin.",
            text="Verstanden.", timings={}, audio_url="")
    m = mit.laden("bianca", sit["id"])
    dateien = [e["datei"] for e in m["zuege"][0]["audioIn"]]
    assert dateien == ["z001_anrufer.wav", "z001_anrufer_2.wav"]
    assert not sit.get("_mitEin")


def test_stream_audio_wird_nachtraeglich_eingeloest(monkeypatch, tmp_path):
    _umleiten(monkeypatch, tmp_path)
    d = _dienst()
    sit = _sit()
    aid, push, fertig = d.audio_stream_anlegen()
    push(b"\x00\x00" * 2400)  # 100 ms PCM bei 24 kHz
    url = f"/api/audio-stream/{aid}.wav"

    mit.zug(sit, d, art="turn", text_in="Hallo", text="Guten Tag!",
            timings={}, audio_url=url)
    m = mit.laden("bianca", sit["id"])
    ein = m["zuege"][0]["audioOut"][0]
    assert ein.get("url") == url and not ein.get("datei")  # noch offen

    fertig()
    sit["zuege"] = [{"art": "hangup", "note": "Testnotiz"}]
    mit.ende(sit, d, warte_s=2.0)
    m = mit.laden("bianca", sit["id"])
    ein = m["zuege"][0]["audioOut"][0]
    assert ein["datei"] == "z001_stimme.wav" and "url" not in ein
    blob = (tmp_path / "anrufe" / "bianca" / sit["id"] / "z001_stimme.wav").read_bytes()
    assert blob[:4] == b"RIFF" and len(blob) == 44 + 4800
    # Ende-Stempel + Hangup-Zug aus der Sitzung übernommen.
    assert m["endedAt"] and m["dauerMs"] >= 0
    assert m["zuege"][-1]["art"] == "hangup" and m["zuege"][-1]["note"] == "Testnotiz"


def test_vorab_urls_kommen_vor_dem_rest(monkeypatch, tmp_path):
    """P5-Satz-Vorab: Satz-URLs in Reihenfolge VOR dem Rest-Audio."""
    _umleiten(monkeypatch, tmp_path)
    d = _dienst()
    sit = _sit()
    u1 = d.audio_legen(_wav(100))
    u2 = d.audio_legen(_wav(100))
    rest = d.audio_legen(_wav(100))
    mit.zug(sit, d, art="turn", text_in="x", text="Satz eins. Satz zwei. Rest.",
            timings={}, audio_url=rest, vorab_urls=[u1, u2])
    m = mit.laden("bianca", sit["id"])
    dateien = [e["datei"] for e in m["zuege"][0]["audioOut"]]
    assert dateien == ["z001_stimme_1.wav", "z001_stimme_2.wav", "z001_stimme_3.wav"]


def test_liste_laden_loeschen(monkeypatch, tmp_path):
    _umleiten(monkeypatch, tmp_path)
    d = _dienst()
    a = _sit("aaaa1111aaaa1111")
    b = _sit("bbbb2222bbbb2222")
    b["startedAt"] = "2026-08-30T09:00:00+00:00"
    b["patient"] = {"name": "Erika Muster"}
    mit.zug(a, d, art="start", text="Guten Tag!", timings={})
    mit.zug(b, d, art="start", text="Guten Tag!", timings={})
    mit.ende(b, d, warte_s=0.0)

    eintraege = mit.liste("bianca")
    assert [e["id"] for e in eintraege] == [b["id"], a["id"]]  # neueste zuerst
    assert eintraege[0]["patientName"] == "Erika Muster"
    assert eintraege[0]["offen"] is False and eintraege[1]["offen"] is True

    assert mit.laden("bianca", a["id"])["zuege"][0]["text"] == "Guten Tag!"
    assert mit.laden("bianca", "../boese") is None
    assert mit.audio_pfad("bianca", a["id"], "..\\..\\geheim.txt") is None

    assert mit.loeschen("bianca", a["id"]) is True
    assert mit.laden("bianca", a["id"]) is None
    assert mit.loeschen("bianca", a["id"]) is False


def test_notaus_mitschnitt_null(monkeypatch, tmp_path):
    _umleiten(monkeypatch, tmp_path)
    monkeypatch.setenv("MITSCHNITT", "0")
    d = _dienst()
    sit = _sit()
    mit.eingang(sit, _wav(100), "audio/wav")
    mit.zug(sit, d, art="turn", text_in="x", text="y", timings={})
    mit.ende(sit, d)
    assert not (tmp_path / "anrufe").exists()
    assert not sit.get("_mitEin")


def test_audio_bytes_fertig_blocking_und_stream():
    d = _dienst()
    blob = _wav(120)
    url = d.audio_legen(blob)
    assert d.audio_bytes_fertig(url) == blob

    aid, push, fertig = d.audio_stream_anlegen()
    push(b"\x01\x02" * 100)
    surl = f"/api/audio-stream/{aid}.wav"
    assert d.audio_bytes_fertig(surl) is None  # noch offen
    fertig()
    raus = d.audio_bytes_fertig(surl)
    assert raus[:4] == b"RIFF" and raus[44:] == b"\x01\x02" * 100
    assert d.audio_bytes_fertig("/api/audio-stream/unbekannt.wav") is None
