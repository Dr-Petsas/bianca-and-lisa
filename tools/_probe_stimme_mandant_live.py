"""Live-Abnahme W-STIMME-MANDANT (15.09.2026) im DEPLOYTEN Container.

Read-only: kein Kalender-Write, kein Anruf, keine Sitzung. Prueft, dass die
neue Praxis Ruether als "Ben" maennlich spricht UND dass sich die drei
Live-Praxen nicht geruehrt haben.

    docker exec -w /app telefonki-bianca-test-1 python tools/_probe_stimme_mandant_live.py

Mit ``--hoeren`` rendert die Probe zusaetzlich Bens Begruessung im echten
TTS-Container und laesst sie vom STT-Container gegenhoeren (braucht 8213/8212).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bianca import gehirn  # noqa: E402
from bianca.greeting import begruessung  # noqa: E402
from bianca.prompt import system_prompt  # noqa: E402
from kern import assistent, dienst as dienst_mod, tenants, tts  # noqa: E402

fehler: list[str] = []


def pruef(was: str, ist, soll) -> None:
    if ist == soll:
        print(f"  OK   {was}: {ist!r}")
    else:
        print(f"  FAIL {was}: {ist!r} != {soll!r}")
        fehler.append(was)


def wahr(was: str, bedingung: bool) -> None:
    pruef(was, bool(bedingung), True)


print("== Mandanten: wer spricht? ==")
ruether = tenants.laden("ruether")
pruef("ruether name", assistent.name(ruether), "Ben")
pruef("ruether genus", assistent.genus(ruether), "m")
pruef("ruether stimme", assistent.stimme(ruether), "ben")
pruef("ruether fachgebiet", ruether.get("fachgebiet"), "gynaekologie")
pruef("ruether did", ruether.get("dids"), ["+4921154244160"])

print("== Gegenprobe: Live-Praxen unberuehrt ==")
for mid in ("meddent", "thaler", "blessing"):
    t = tenants.laden(mid)
    pruef(f"{mid} name", assistent.name(t), "Bianca")
    pruef(f"{mid} genus", assistent.genus(t), "f")
    pruef(f"{mid} stimme (leer = Prozess)", assistent.stimme(t), "")
    satz = "Sie sprechen mit Bianca, der Telefonassistentin der Praxis."
    pruef(f"{mid} formen() laesst den Text unangetastet",
          assistent.formen(satz, t), satz)

print("== Begruessung + Prompt ==")
gruss_ben = _s = begruessung(tenants.praxis_melde(ruether), ruether)
print(f"       {gruss_ben}")
wahr("Begruessung nennt Ben", "Ben" in gruss_ben)
wahr("Begruessung nennt nicht Bianca", "Bianca" not in gruss_ben)
# Der Mandant traegt einen eigenen Begruessungstext — der gewinnt live.
print(f"       DB/Datei-Gruss: {ruether.get('begruessungText')}")
wahr("Mandanten-Gruss nennt Ben", "Ben" in str(ruether.get("begruessungText")))

p_ben = system_prompt(praxis="Praxis Doktor Ruether", behandler="Doktor Ruether",
                      sit={"tenant": ruether})
wahr("Prompt: 'Du bist Ben, Empfangsassistent'",
     "Du bist Ben, Empfangsassistent" in p_ben)
wahr("Prompt ohne 'Bianca'", "Bianca" not in p_ben)
wahr("Prompt ohne 'Empfangsassistentin'", "Empfangsassistentin" not in p_ben)

p_bianca = system_prompt(praxis="Praxis MedDent", behandler="Doktor Petsas",
                         sit={"tenant": tenants.laden("meddent")})
wahr("MedDent-Prompt unveraendert weiblich",
     "Du bist Bianca, Empfangsassistentin" in p_bianca)

print("== Dativ-Beugung (der haeufigste Fehler) ==")
pruef("Apposition",
      assistent.formen("Sie sprechen mit Bianca, der Telefonassistentin der Praxis.",
                       ruether),
      "Sie sprechen mit Ben, dem Telefonassistenten der Praxis.")
for satz in ("Frau Doktor Ruether ist heute in der Praxis.",
             "Ihre Kollegin hat den Termin vereinbart.",
             "Doktor Myriam Roerig hat einen eigenen Kalender."):
    pruef(f"Praxis-Fakt bleibt: {satz[:28]}...", assistent.formen(satz, ruether), satz)

print("== Warm-Lauf: gewaermt wird, was der Mund spricht ==")
ben_saetze = gehirn.feste_saetze(ruether)
wahr("Ben waermt 'Ich bin der Neue'",
     any("Ich bin der Neue" in s for s in ben_saetze))
wahr("Ben waermt NICHT 'Ich bin die Neue'",
     not any("Ich bin die Neue" in s for s in ben_saetze))
bianca_saetze = gehirn.feste_saetze(tenants.laden("meddent"))
wahr("MedDent waermt weiter 'Ich bin die Neue'",
     any("Ich bin die Neue" in s for s in bianca_saetze))

print("== TTS: Stimme gilt pro Anruf ==")
pruef("Prozess-Default", tts.stimme_jetzt(), tts._VOICE_NAME)
with tts.stimme("ben"):
    pruef("im Kontext", tts.stimme_jetzt(), "ben")
    ben_key = tts._lokal_schluessel("Einen Moment.")
pruef("nach dem Kontext", tts.stimme_jetzt(), tts._VOICE_NAME)
with tts.stimme("bianca"):
    bianca_key = tts._lokal_schluessel("Einen Moment.")
wahr("Cache-Schluessel trennt die Stimmen", ben_key != bianca_key)

token = dienst_mod.stimme_aus_sitzung({"tenant": ruether})
pruef("stimme_aus_sitzung(ruether)", tts.stimme_jetzt(), "ben")
tts.stimme_zuruecksetzen(token)
token = dienst_mod.stimme_aus_sitzung({"tenant": tenants.laden("meddent")})
pruef("stimme_aus_sitzung(meddent)", tts.stimme_jetzt(), tts._VOICE_NAME)
tts.stimme_zuruecksetzen(token)

gehoert: list[str] = []
with tts.stimme("ben"):
    f = dienst_mod.faden(lambda: gehoert.append(tts.stimme_jetzt()))
    f.start()
f.join(5)
pruef("Faden nimmt die Stimme mit", gehoert, ["ben"])

print("== Vorgerenderte Saetze je Stimme ==")
d = dienst_mod.Dienst(name="probe", start_fn=lambda sit: {},
                      turn_fn=lambda sit, t, **k: {})
stimmen = d.stimmen_im_haus()
print(f"       stimmen_im_haus: {stimmen}")
pruef("Prozess-Default zuerst", stimmen[0], "")
wahr("'ben' ist dabei", "ben" in stimmen)
d.quittung_urls = {"": ["/q/bianca"], "ben": ["/q/ben"]}
d.notfall_urls = {"": ["/n/bianca"], "ben": ["/n/ben"]}
pruef("Quittung fuer Ben", d.quittungen_fuer({"tenant": ruether}), ["/q/ben"])
pruef("Quittung fuer MedDent", d.quittungen_fuer({"tenant": tenants.laden("meddent")}),
      ["/q/bianca"])
pruef("Quittung ohne Sitzung (Dock-Boot)", d.quittungen_fuer(None), ["/q/bianca"])
pruef("Notfall fuer Ben", d.notfall_fuer({"tenant": ruether}), ["/n/ben"])
pruef("unbekannte Stimme faellt auf Prozess zurueck",
      d.quittungen_fuer({"tenant": {"stimme": "gibtsnicht"}}), ["/q/bianca"])

if "--hoeren" in sys.argv:
    print("== Gegenhoeren: echter TTS-Container + STT ==")
    import httpx

    text = str(ruether.get("begruessungText"))
    with tts.stimme("ben"):
        mund = tts.LokalTts()
        pcm = mund.speak(text)
    wahr("Ben liefert Audio", len(pcm) > 20000)
    print(f"       {len(pcm)} Bytes PCM ({len(pcm)/2/24000:.1f} s)")
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(pcm)
    try:
        from kern.stt import STT_BASE

        r = httpx.post(f"{STT_BASE}/transcribe",
                       files={"file": ("ben.wav", buf.getvalue(), "audio/wav")},
                       timeout=30.0)
        gehoert_text = str((r.json() or {}).get("text") or "")
        print(f"       gegengehoert: {gehoert_text!r}")
        wahr("Ben nennt sich Ben", "ben" in gehoert_text.lower())
    except Exception as e:
        print(f"  WARN STT nicht erreichbar: {e}")

print()
if fehler:
    print(f"ROT — {len(fehler)} Pruefung(en) gescheitert: {fehler}")
    raise SystemExit(1)
print("GRUEN — alles wie gewollt.")
