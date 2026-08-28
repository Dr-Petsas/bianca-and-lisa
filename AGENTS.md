# Arbeitsregeln Bianca & Lisa Telefon-KI

Dieses Repo ist **autark**. Es darf Clara live, Clara-dev, DemoClara,
Lena-Voice und MAS-2 nicht anfassen, nicht neustarten, nicht umbauen.

## Isolation

- Eigener Port **8095** (Clara 8091, v6 8092, Clara-dev 8093, DemoClara 8094).
- Kein Kill fremder Python-Worker.
- Kein Import aus `Clara-Voice*`, `Pickadoc-Demo` oder `MAS-2`.
- Kalender und Patientensuche gehen an Pickadoc-Cloud-Functions.
- MAS ist optional und nur lesend (`MAS_URL`).

## Mandanten

Jede Sitzung trägt `clientId`. Keine Praxis-IDs im Kernel.
Dev-Default: `tenants/meddent.json`. Schreiben: `WRITE_LIVE=1`
(Chef 26.08.2026: echter Kalender — buchen, absagen, verschieben).

## LLM / Stimme

- LLM: vLLM auf der 5090 (`LLM_BASE`, `qwen3.6:35b-a3b`). Kein Ollama.
- TTS-Tauschpunkt ist `kern/tts.py` (`lisa/tts.py` ist nur ein Re-Export).
  Zwei Engines: ElevenLabs (Default) und **LokalTts** gegen die 5090-Container.

## Lokales TTS auf der 5090 (27.08.2026 — nicht rückbauen)

Shootout Chatterbox-Multilingual-V3 gegen Fun-CosyVoice3, Ziel: ElevenLabs
ersetzen (erst Lisa/Bianca, bei Erfolg Demo-Clara + Clara V7 in DEREN Repos).

- `tts_serve/` traegt beide Container (je eigenes Dockerfile, gemeinsamer
  Vertrag `tts_serve/api.md`: `POST /speak {text, voice}` -> rohes PCM16
  mono 24 kHz). Compose-Profile: **nie beide gleichzeitig** (eine GPU,
  vLLM 8000 daneben; Chatterbox 8210, CosyVoice 8211). Blackwell-Falle:
  Chatterbox zwingt torch nach der Modell-Installation auf cu128 zurueck —
  Zeile nicht entfernen. Im CosyVoice-Turbo bestimmt vllm die torch-Version
  (bringt cu128 mit), torchaudio wird im Dockerfile versionsgleich nachgezogen.
- Umschalten NUR ueber `TTS_BASE` in der `.env`: gesetzt = es spricht
  AUSSCHLIESSLICH der lokale Container, **KEIN ElevenLabs-Rueckfall**
  (Chef 27.08.2026: Fehler muessen in der Testphase hoerbar sein —
  `Dienst.stimme()` faengt den RuntimeError, Zug erscheint ohne Audio).
  Leer = ElevenLabs, byte-identisch wie vorher. Stimmname pro Prozess:
  Lisa "lisa", Bianca setzt sich in `bianca/server.py` auf "bianca"
  (Referenzen in `tts_serve/stimmen/`, CosyVoice braucht zusaetzlich
  das wortgetreue Transkript als `.txt`).
- Rollout/Bench/Referenzen: `DEPLOY-5090.md`; Korpus aus ECHTEN Bausteinen
  via `tts_serve/korpus_bauen.py`, Messung via `tts_serve/bench.py`
  (blocking gemessen wie live, WAVs mit derselben Pegel-Schicht).
- App-Container (Lisa 8095 + Bianca 8096, Tenant-Mount read-only) liegen in
  `compose.yml`/`Dockerfile` an der Repo-Wurzel — der stabile Umschlag,
  gegen den der Kollege SIP/Zaluma haengt.
- Tests: `tests/test_tts_lokal.py` (Engine-Wahl, Payload, Pegel, Cache,
 **kein** Fallback-Pfad).
- **Füller-Platten-Cache** (28.08.2026): `tts.speak_dauerhaft()` cached
 statische Sätze (Füller, Begrüßungen — NIE Gesprächsantworten mit
 Patientenbezug) als WAV unter `.data/tts-cache/` (Key: TTS-Basis+Stimme+Text
 — Chatterbox :8210 und CosyVoice :8211 haben getrennte Caches).
 Dienststart damit ~2 s statt ~60 s; Stimmen-/Engine-Wechsel rendert neu,
 weil der Key wechselt. Cache leeren = Ordner löschen.
- **Lautheits-Angleichung statt Peak-Anhebung** (28.08.2026 — nicht
 rückbauen): `kern/tts.py -> pcm16_wav` zieht jede Äußerung auf dasselbe
 Sprach-RMS (`ZIEL_RMS`, anheben UND absenken, Peak-Deckel). Das alte
 Demo-Clara-Peak-Rezept passte nur für ElevenLabs-Audio; bei lokalem TTS
 sprang der Faktor hörbar zwischen den Sätzen ("Pumpen", Chef 28.08.).
 Nach Änderungen an der Pegel-Schicht: Platten-Cache leeren, sonst mischen
 sich alte und neue Lautheit. Tests: `tests/test_tts_gain.py`.
- **Satz-Häppchen + Chunk-Streaming** (28.08.2026): Lange Antworten gehen im
  Zug-Strom häppchenweise raus (`kern/dienst.py -> _vertonen`): Container mit
  `stream: true` im /health (CosyVoice-Turbo) => EIN `/speak-stream`-Aufruf
  mit Gesamttext, WAV-Häppchen sofort über den filler-Kanal (Docks spielen
  sie als Kette), Gain wird aus dem ersten sprach-aktiven Häppchen
  festgehalten; sonst satzweises Blocking (`haeppchen_teile`, splittet nie
  in Ziffern-Punkt wie "am 28. August"). Gewarmte Begrüßungen bleiben EIN
  Block (Cache-Key = Gesamttext). Notaus: `TTS_STREAM=0`. Tests:
  `tests/test_haeppchen.py`, `tests/test_tts_lokal.py`.
- **Stream-Schnitt + Gapless-Docks (Vorfall 28.08.2026 "Rauschen/zerstückelt"
  — nicht rückbauen):** Die HTTP-Chunks aus `/speak-stream` kommen mit
  BELIEBIGEN (auch ungeraden) Byte-Grenzen an. `kern/tts.py -> speak_stream`
  schneidet deshalb NIE mitten im 16-Bit-Sample (Überhang bleibt im Puffer) —
  ein schiefer Schnitt verschiebt den Reststrom um 1 Byte und macht aus
  Sprache Rauschen (live gehört). Pro Häppchen: Äußerungs-Gain festgehalten,
  Peak-Deckel je Stück gegen Clipping, 2-ms-Rampen an den Rändern gegen
  Klicks (`_haeppchen_wav`). Die Docks (`web/app.js`, `bianca_web/app.js`
  -> `spielGapless`) laden Häppchen SOFORT und planen die Wiedergabe per
  WebAudio sample-genau aneinander (`source.start(zeit)`, Planung in
  Ankunftsreihenfolge) statt fetch+decode erst nach dem Ende des vorigen
  Stücks — das war das "Zerstückelte". Barge-in: EIN `bargeOderCap`-Wächter
  pro Kette, `stopLisaVoice`/`stopVoice` stoppen via `ketteStop()` alle
  geplanten Quellen. Test: `test_speak_stream_schneidet_nie_mitten_im_sample`.
- **CosyVoice-Turbo** (28.08.2026): Container lädt mit `load_vllm` (eigenes
 Mini-vLLM fürs 0.5B-Sprach-LLM, Export nach `MODEL_DIR/vllm` beim ersten
 Start) und `load_trt` (TensorRT-Engine für den Flow-Decoder, Bau beim
 ersten Start, gecacht im Volume). VRAM-Deckel: `COSY_VLLM_GPU_UTIL=0.08`
 (Dockerfile-sed patcht CosyVoices hartes 0.2 — Build-Guard grep). Neben
 dem grossen qwen-vLLM (~25,7 GB) bleiben nur ~6,9 GB — Chatterbox und
 CosyVoice-Turbo NIE parallel starten. Notausgänge: `TTS_VLLM=0`,
 `TTS_TRT=0`, `TTS_FP16=0`.

## Lisa zuerst

Bianca-Ordner bleibt leer, bis der Lisa-Kernel Anrufe hält.
Zaluma/SIP hängt ein Kollege später an denselben Sitzungs-Umschlag.

## Zwei Schichten: Job + Talk (27.08.2026 — nicht rückbauen)

`kern/gespraech.py` — abgeschrieben von Demo-Claras COS, gilt für BEIDE Stimmen:

- **Job** = die deterministische Maschine (`bianca/flow`, `bianca/verwalten`,
  `lisa/identitaet`). Sie spricht zuerst und bleibt alleinige Autorität für
  Termine, Namen, Nummern. Nummern-Rückbestätigung (`telefon_check`) bleibt
  IMMER deterministisch.
- **Talk** = Nebenthemen mit Gravity. Wer erzählt oder nachfragt, bekommt den
  Floor: das LLM redet frei mit (mehr Tokens/Temperatur, Plan im Prompt),
  der Frage-Anker (`bianca/agent._nachbessern`) schweigt, eine vom Modell
  trotzdem angehängte Job-Frage wird abgeschnitten. Erzählte Sätze zählen
  NIE als Leerlauf (keine Eskalation mitten in der Geschichte).
- **Rückweg:** Lässt der Anrufer los ("na gut", "alles klar") oder verhungert
  das Thema, gibt es GENAU EINE Brücke zurück zur offenen Frage — nie
  dieselbe Frage zweimal wortgleich in Folge.
- **Wiederholungs-Wächter** (`kern/wiederholung.py`, 27.08.2026 — nicht
  rückbauen): sitzt am ENDE jedes gesprochenen Zuges (Maschine UND LLM,
  beide Stimmen). Wiederholt sich die offene Pflichtfrage wortgleich
  gegen die letzten drei Antworten, kommt die nächste Formulierung aus
  `gehirn.FRAGE_VARIANTEN` (jede Variante trägt die `_FRAGE_KERN`-Wörter,
  damit Anker/Wachen sie weiter erkennen); andere wortgleiche Frage-/
  Langsätze werden gestrichen. NIE angefasst: `telefon_check`-Züge,
  Sätze mit Ziffern/Ziffern-Wörtern (Readbacks), kurze Quittungen.
  Nie stumm: bleibt nichts übrig, greift der Original- bzw. Rückfalltext.
  Tests: `tests/test_wiederholung.py`.
- **Stille-Wächter** (`kern/stille.py`, 27.08.2026 — nicht rückbauen): meldet
  das Dock ~4 s Funkstille (`STUPS_NACH_S`, gemessen in `web/app.js` und
  `bianca_web/app.js` nach dem eigenen Sprech-Ende), ergreift die Stimme
  selbst das Wort: `POST /api/stille` -> `agent.stille_zug` (deterministisch,
  ohne LLM, ohne Kalender). Gehirn an, nie bei null: auf der Job-Spur kommt
  der STAND (Auftrag, was schon eingesammelt ist, offene Frage — Bianca
  `_stand_ansage` aus dem Sammler, Lisa Auftrag + zuletzt gestellte Frage
  mit "Meine Frage war:"-Präfix); läuft gerade ein Nebenthema (Talk-Floor),
  knüpft der ERSTE Stups dort an, der zweite holt auf die Job-Spur.
  `telefon_check` wiederholt deterministisch die Nummer. Max. `MAX_STUPSE`
  (2) Stupse in Folge, dann Schweigen; jedes echte Gehörte setzt zurück
  (`stille.reset` in beiden `user_turn`, Zähler auch im Dock). Jeder Stups
  läuft durch den Wiederholungs-Wächter — nie wortgleich; der Kurz-Stups
  spricht nur Frage-Sätze (`nur_fragesaetze`), keine Begleitsätze doppelt.
  Tests: `tests/test_stille.py`.
- Namens-Wache: Zustände/Prosa ("ich bin ganz aufgeregt", Erzählsätze auf
  die Namensfrage) sind KEINE Namen (`gehirn._KEIN_NAME_RE`, Token-Deckel).
- Tests: `tests/test_gespraech.py` (offline); Sprech-Probe am echten LLM:
  `tests/talk_probe.py` (schreibt nie, bucht nie).
- **Notaus:** `TALK_SCHICHT=0` (Umgebungsvariable) => Verhalten wie vor dem
  27.08.2026 — jeder Zug job, Anker feuert wie früher.

## Fernsteuerung

- Seite: `/fernsteuerung.html` (Handy braucht `#t=…` aus dem lokalen Link).
- Wächter: `tools/lisa_fernsteuerung_watch.ps1` — nur Grok, nur dieser Ordner.
- Kein MAS-Wächter, kein Workspace `F:\`.
