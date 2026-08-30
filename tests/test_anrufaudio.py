"""W-CALLAUDIO (30.08.2026): Anruf-MP3 -> Firebase Storage, offline.

Geprueft ohne Netz: Notaus, Pfad-/URL-Form (identisch zur ElevenLabs-CF:
clients/{clientId}/locations/{locationId}/phoneCalls/{phoneCallId}.mp3,
Download-URL mit firebaseStorageDownloadTokens), WAV-Rueckfall ohne ffmpeg
und die Einhaengung in agentprofil.call_abschliessen (audioRecordingUrl
im post-Payload).
"""

from __future__ import annotations

import copy
import json

import kern.anrufaudio as anrufaudio
from bianca import session
from kern import agentprofil, mitschnitt
from tests.test_agentprofil import CF_PRE


def _sit() -> dict:
    t = agentprofil.tenant_von_pre(copy.deepcopy(CF_PRE), did="4930111222")
    sit = session.neu(tenant=t)
    sit["phoneCallId"] = "pc-1"
    return sit


def test_notaus_schaltet_upload_aus(monkeypatch):
    monkeypatch.setenv("CALL_AUDIO_UPLOAD", "0")
    assert anrufaudio.an() is False
    assert anrufaudio.hochladen(_sit()) == ""


def test_hochladen_baut_cf_identischen_pfad(monkeypatch):
    monkeypatch.setattr(anrufaudio, "an", lambda: True)
    monkeypatch.setattr(mitschnitt, "anruf_wav", lambda stimme, sid: b"RIFFwav")
    monkeypatch.setattr(anrufaudio, "_mp3", lambda wav: b"MP3DATEN")
    gesehen: dict = {}

    def _fake_upload(pfad, blob, ctype):
        gesehen.update(pfad=pfad, blob=blob, ctype=ctype)
        return "https://firebasestorage.googleapis.com/fake"

    monkeypatch.setattr(anrufaudio, "_upload", _fake_upload)
    url = anrufaudio.hochladen(_sit())
    assert url == "https://firebasestorage.googleapis.com/fake"
    assert gesehen["pfad"] == "clients/client-fremd/locations/loc-fremd/phoneCalls/pc-1.mp3"
    assert gesehen["blob"] == b"MP3DATEN" and gesehen["ctype"] == "audio/mpeg"


def test_hochladen_ohne_ffmpeg_faellt_auf_wav(monkeypatch):
    monkeypatch.setattr(anrufaudio, "an", lambda: True)
    monkeypatch.setattr(mitschnitt, "anruf_wav", lambda stimme, sid: b"RIFFwav")
    monkeypatch.setattr(anrufaudio, "_mp3", lambda wav: None)
    gesehen: dict = {}
    monkeypatch.setattr(anrufaudio, "_upload",
                        lambda pfad, blob, ctype: gesehen.update(
                            pfad=pfad, blob=blob, ctype=ctype) or "u")
    assert anrufaudio.hochladen(_sit()) == "u"
    assert gesehen["pfad"].endswith("/phoneCalls/pc-1.wav")
    assert gesehen["blob"] == b"RIFFwav" and gesehen["ctype"] == "audio/wav"


def test_hochladen_ohne_phonecallid_oder_mitschnitt_still(monkeypatch):
    monkeypatch.setattr(anrufaudio, "an", lambda: True)

    def _knall(*a, **k):
        raise AssertionError("ohne Datensatz/Mitschnitt darf nichts hochgeladen werden")

    monkeypatch.setattr(anrufaudio, "_upload", _knall)
    # Kein phoneCallId -> still.
    sit = _sit()
    sit.pop("phoneCallId")
    assert anrufaudio.hochladen(sit) == ""
    # Kein Mitschnitt-Audio -> still.
    monkeypatch.setattr(mitschnitt, "anruf_wav", lambda stimme, sid: None)
    assert anrufaudio.hochladen(_sit()) == ""


def test_upload_url_traegt_token_und_kodierten_pfad(monkeypatch):
    """Die Download-URL muss die Form von firebase-admin getDownloadURL()
    haben — das Portal spielt sie direkt im <audio>-Element."""
    gesehen: dict = {}

    class _Antwort:
        status_code = 200
        text = ""

    def _fake_post(url, **kw):
        gesehen.update(url=url, **kw)
        return _Antwort()

    monkeypatch.setattr(anrufaudio.httpx, "post", _fake_post)
    monkeypatch.setattr(anrufaudio, "_access_token", lambda: "tok")
    url = anrufaudio._upload("clients/c/locations/l/phoneCalls/p.mp3",
                             b"MP3", "audio/mpeg")
    assert url.startswith(
        f"{anrufaudio._DOWNLOAD_BASE}/{anrufaudio.FIREBASE_BUCKET}/o/"
        "clients%2Fc%2Flocations%2Fl%2FphoneCalls%2Fp.mp3?alt=media&token=")
    # Multipart-Body traegt das Download-Token als Storage-Metadatum.
    body = gesehen["content"]
    kopf = body.split(b"\r\n\r\n")[1]
    meta = json.loads(kopf.split(b"\r\n")[0])
    assert meta["metadata"]["firebaseStorageDownloadTokens"] == url.rsplit("token=", 1)[1]
    assert meta["name"] == "clients/c/locations/l/phoneCalls/p.mp3"
    assert gesehen["headers"]["Authorization"] == "Bearer tok"


def test_call_abschliessen_traegt_audio_url(monkeypatch):
    monkeypatch.setattr(agentprofil, "enabled", lambda: True)
    gesendet: list[dict] = []
    monkeypatch.setattr(agentprofil, "_cf_senden",
                        lambda body: gesendet.append(body) or {"status": "success"})
    monkeypatch.setattr(agentprofil, "_analyse_llm", lambda transcript: {})
    monkeypatch.setattr(anrufaudio, "hochladen", lambda sit: "https://fake/anruf.mp3")
    agentprofil.call_abschliessen(_sit())
    assert gesendet[0]["phase"] == "post"
    assert gesendet[0]["audioRecordingUrl"] == "https://fake/anruf.mp3"


def test_call_abschliessen_ohne_audio_laesst_feld_weg(monkeypatch):
    monkeypatch.setattr(agentprofil, "enabled", lambda: True)
    gesendet: list[dict] = []
    monkeypatch.setattr(agentprofil, "_cf_senden",
                        lambda body: gesendet.append(body) or {"status": "success"})
    monkeypatch.setattr(agentprofil, "_analyse_llm", lambda transcript: {})
    monkeypatch.setattr(anrufaudio, "hochladen", lambda sit: "")
    agentprofil.call_abschliessen(_sit())
    assert gesendet[0]["phase"] == "post"
    assert "audioRecordingUrl" not in gesendet[0]
