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

- `tts_serve/` traegt die Container (je eigenes Dockerfile, gemeinsamer
  Vertrag `tts_serve/api.md`: `POST /speak {text, voice}` -> rohes PCM16
  mono 24 kHz). Compose-Profile: **nie zwei gleichzeitig** (eine GPU,
  vLLM 8000 daneben; Chatterbox 8210, CosyVoice 8211, Qwen3 8213).
  Aktuell im Test: **Qwen3-TTS-12Hz-0.6B-Base** (`--profile qwen3`).
  Blackwell-Falle: nach der Modell-Installation torch auf cu128 zurueckzwingen
  — Zeile nicht entfernen. CosyVoice-Turbo: vllm bestimmt die torch-Version.
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
 Seit 28.08. nachmittags zusätzlich: gewarmte Sätze sind im RAM **gepinnt**
 (`tts._FEST`, faellt nie aus dem 48er-LRU) und Bianca wärmt ihre festen
 Maschinen-Fragen mit (`bianca/gehirn.feste_saetze()`, Warm-Form =
 `sprech.sanitize`) — ein Maschinen-Zug spricht damit in ~0,1 s statt
 ~1,2 s lokaler Synthese. Drift-Wache: `tests/test_feste_saetze.py`
 (Quelltext-Abgleich gegen `naechste_frage`).
- **Lautheits-Angleichung statt Peak-Anhebung** (28.08.2026 — nicht
 rückbauen): `kern/tts.py -> pcm16_wav` zieht jede Äußerung auf dasselbe
 Sprach-RMS (`ZIEL_RMS=0.22`, ~−13 dBFS wie Clara Demo/V7 + ElevenLabs
 speaker_boost; anheben UND absenken). Gain kommt NUR aus dem RMS —
 ein Peak-Deckel auf den Faktor hielt Qwen bei −19 dBFS (Peak 0,68 /
 RMS 0,08). Spitzen werden NACH dem Gain auf `PEAK_DECKEL` gekappt.
 Nach Änderungen an der Pegel-Schicht: Platten-Cache leeren, sonst mischen
 sich alte und neue Lautheit. Tests: `tests/test_tts_gain.py`.
- **Lisa und Bianca sprechen ganz** (Chef 28.08.2026, nach dem
  Genuschel-Vorfall): beide Dienste `ganz=True` — jede Äußerung EIN
  `/speak`, kein Stream-Schnitt, kein Satz-Split. Qwen3-0.6B meldet
  `stream: false`; `.env` trägt `TTS_STREAM=0`. Test:
  `test_ganz_spricht_immer_einen_block`.
- **Satz-Häppchen + Chunk-Streaming** (28.08.2026): Lange Antworten gehen im
  Zug-Strom häppchenweise raus (`kern/dienst.py -> _vertonen`): Container mit
  `stream: true` im /health => EIN `/speak-stream`-Aufruf
  mit Gesamttext, WAV-Häppchen sofort über den filler-Kanal (Docks spielen
  sie als Kette), Gain wird aus dem ersten sprach-aktiven Häppchen
  festgehalten; sonst satzweises Blocking (`haeppchen_teile`, splittet nie
  in Ziffern-Punkt wie "am 28. August"). Gewarmte Begrüßungen bleiben EIN
  Block (Cache-Key = Gesamttext). Notaus: `TTS_STREAM=0`. Tests:
  `tests/test_haeppchen.py`, `tests/test_tts_lokal.py`.
  Seit 28.08. nachmittags: **Chatterbox streamt auch** — der Container
  synthetisiert stückweise (eigener Schnitt `tts_serve/chatterbox/schnitt.py`:
  erstes Stück früh am Komma ab 24 Zeichen, dann satzweise; Kill-Switch
  `CHATTERBOX_STREAM=0`). Client-seitig wachsen die Häppchen progressiv
  (`kern/tts.py`: erstes ~0,5 s, dann verdoppelnd bis 3,2 s) und der
  **LLM-Vorab-Satz** geht über den Stream statt blocking
  (`kern/dienst.py -> zug_stream/vorab`, Test `tests/test_vorab_stream.py`).
  Gemessen 5090: erster Ton Kurzsatz 0,48 s, Langsatz ~1,2 s (vorher
  1,2-3,5 s blocking).
- **Stream-Schnitt + Gapless-Docks (Vorfälle 28.08.2026 "Rauschen/zerstückelt"
  und "Artefakte/Genuschel" — nicht rückbauen):** Die HTTP-Chunks aus
  `/speak-stream` kommen mit BELIEBIGEN (auch ungeraden) Byte-Grenzen an.
  `kern/tts.py -> speak_stream` schneidet deshalb NIE mitten im 16-Bit-Sample
  (Überhang bleibt im Puffer) — ein schiefer Schnitt verschiebt den Reststrom
  um 1 Byte und macht aus Sprache Rauschen (live gehört). Und er schneidet
  NUR in Sprechpausen (`_PausenSpur`, Fenster-RMS < `PAUSE_RMS`; ohne Pause
  nach einer Extra-Sekunde Notschnitt an der leisesten Stelle): der stumpfe
  Byte-Schnitt an der Fahrplan-Schwelle legte die Naht mitten in Wörter —
  mit 2-ms-Rampen und eigenem Decode je Häppchen wurde daraus alle 0,5-2 s
  ein verwaschener Übergang ("Genuschel", live gehört am Nachmittag).
  Pro Häppchen: Äußerungs-Gain festgehalten, Peak-Deckel je Stück gegen
  Clipping, 2-ms-Rampen an den Rändern gegen Klicks (`_haeppchen_wav`).
  Die Docks (`web/app.js`, `bianca_web/app.js` -> `spielGapless`) laden
  Häppchen SOFORT und planen die Wiedergabe per WebAudio sample-genau
  aneinander (`source.start(zeit)`, Planung in Ankunftsreihenfolge) statt
  fetch+decode erst nach dem Ende des vorigen Stücks — das war das
  "Zerstückelte". Barge-in: EIN `bargeOderCap`-Wächter pro Kette,
  `stopLisaVoice`/`stopVoice` stoppen via `ketteStop()` alle geplanten
  Quellen. Tests: `test_speak_stream_schneidet_nie_mitten_im_sample`,
  Pausen-Schnitt-Fälle in `tests/test_tts_lokal.py`.
- **Chatterbox-Nachbearbeitung (Vorfall 28.08.2026 "Artefakte/Genuschel" —
  nicht rückbauen):** Chatterbox hängt manchen Stücken sekundenlange
  Fast-Stille mit Nuschel-Resten an (live: Häppchen mit 54-69 % Stille) und
  rennt selten in Runaway-Babble (5,88 s für "Wie lautet der Nachname?",
  24 Zeichen — als gepinnter Warm-Render bei JEDER Nachnamen-Frage hörbar).
  `tts_serve/chatterbox/pegel.py` kappt deshalb je Synthese-Stück die
  Rand-Stille (Polster 150 ms, innere Pausen bleiben) und rendert
  unplausibel lange Stücke (> ~1,4× Sprechdauer-Erwartung) EINMAL neu —
  das kürzere gewinnt (`_synthese` in `server.py`, gilt für /speak,
  /speak-stream UND alle Warm-Renders). Zweite Wache beim Wärmen selbst:
  `kern/tts.py -> warm()` verwirft einen trotzdem unplausiblen Render
  (RAM-Pin + Platte) und holt EINMAL neu, erst dann wird gepinnt.
  Nach Änderungen an Trim/Gate: Platten-Cache leeren (`.data/tts-cache`
  lokal + im App-Volume), sonst bleiben vermurkste Alt-Renders gepinnt.
  Tests: `tests/test_chatterbox_pegel.py`, Warm-Fälle in
  `tests/test_tts_lokal.py`; Cache-Audit: `tests/cache_pruefen.py`.
- **CosyVoice-Turbo** (28.08.2026): Container lädt mit `load_vllm` (eigenes
 Mini-vLLM fürs 0.5B-Sprach-LLM, Export nach `MODEL_DIR/vllm` beim ersten
 Start) und `load_trt` (TensorRT-Engine für den Flow-Decoder, Bau beim
 ersten Start, gecacht im Volume). VRAM-Deckel: `COSY_VLLM_GPU_UTIL=0.08`
 (Dockerfile-sed patcht CosyVoices hartes 0.2 — Build-Guard grep). Neben
 dem grossen qwen-vLLM (~25,7 GB) bleiben nur ~6,9 GB — Chatterbox und
 CosyVoice-Turbo NIE parallel starten. Notausgänge: `TTS_VLLM=0`,
 `TTS_TRT=0`, `TTS_FP16=0`.

## Lokales STT auf der 5090: Parakeet wie Clara (28.08.2026 — nicht rückbauen)

Chef 28.08.2026: **"es geht nichts mehr zu elevenlabs"** — auch die
Transkription nicht. Und: **"bianca und lisa sollten stt parakeet nutzen
mit allen entwicklungsstufen ... nur das beste und bewährteste von
clara v7 und demo clara."** Deshalb trägt `stt_serve/` Claras bewährte
Telefon-Strecke als eigenen Container auf der 5090, Port **8212**
(Landkarte: vLLM 8000, Chatterbox 8210, CosyVoice 8211, STT 8212):

- Engine: **primeline-parakeet** (deutsches TDT-Finetune, 2,95 % WER) als
  ONNX über `onnx-asr`, **CPU-only** wie Claras Produktion — die GPU
  (qwen-vLLM, TTS) bleibt komplett unberührt. Modell liegt als Bind-Mount
  in `stt_serve/modell/` (Kopie aus Claras `.cache/parakeet-primeline-onnx`,
  nur lesend gezogen; Quelle sonst: HF geier/deskscribe-parakeet-primeline-onnx).
- Nachkorrektur: `stt_serve/postcorrect.py` = **KOPIE** von Clara V7
  (`Clara-Voice-dev/services/stt_postcorrect.py`): Fuzzy-Hotwords,
  Anlaut-Gruppen P/B & T/D/Z, Token-Paare, `buchstabiertes_zusammenziehen`
  (T-Z-A-N-N-I-S / „T wie Theodor…“), y→i, `assess_name_certainty`.
  Zusätzlich immer an (ohne Marker): Telefon-Garbles (`welcher Tacken`→Tag,
  Wurzelkanal, Nachmittach, Zülung→Füllung). Heads-up/Teleskop/Kons bleiben
  Marker-gated. Kopie statt Import — Clara-Voice nie anfassen.
- Keywords: `kern/tenants.py -> stt_keywords()` = Behandler + Lexikon
  (`kern/stt_lexikon.py`: Vornamen, Praxiswörter, Kartei-Nachnamen). Nie
  Heads-up/Kons/Teleskopkrone. `kern/stt.py` schickt sie je Request mit
  und filtert Clara-V7-Atem-/Untertitel-Halluzinationen („Tschüss“ bleibt).
- Umschalten NUR über `STT_BASE` in der `.env`: gesetzt = ALLE Züge über den
  Container, **KEIN ElevenLabs-Rückfall** (gleiches Muster wie `TTS_BASE`);
  leer = Scribe wie früher. Tests: `tests/test_stt_lokal.py`.
- Gemessen 28.08.2026: Container 0,34-0,43 s je Zug (Server-lokal, wortgenau
  gegen Referenztranskript), E2E im Bianca-Dienst `timings.stt` = 0,44 s —
  Scribe lag bei 0,8-2,0 s. Messwerkzeuge: `tests/latenz_e2e.py`,
  `tests/timing_bericht.py`, `stt_serve/latenz_probe.sh`.
- Health-/Dock-Anzeige: `kern/stt.py -> engine_anzeige()` ("Ohr: Parakeet
  (lokal)" neben "Stimme: Chatterbox (lokal)").
- **Clara-Schutz:** Claras laufender Parakeet, Clara V7/dev, Demo-Clara und
  Lena-Voice sind NICHT beteiligt — eigener Container, eigene Modell-Kopie,
  anderer Rechner. Dieses Repo fasst deren Prozesse/Dateien nie an.
- **Beide Docks ohne Browser-Live-STT (28.08.2026):** Die Web-Speech-
 Live-Transkription lieferte kaputte Transkripte und machte Züge lahm —
 Bianca und Lisa hören nur noch über Aufnahme (`recordUntilSilence`) +
 Server-STT mit Vorab-Lauf. `liveOhr` bleibt in beiden Docks als
 immer-null-Feld (bargeOderCap strukturgleich; Barge-in läuft über den
 Mikro-Pegel-Pfad). Lisas Diktat-Knopf fürs Auftragsfeld (VOR dem Anruf)
 nutzt weiter Web Speech, mit Aufnahme+`/api/transcribe` als Rückfall.
- Der erste Wurf (NVIDIA-Conformer über NeMo, Image `stt-conformer-de:v1`)
  ist verworfen: 13,9-GB-Image, brauchte GPU (OOM — 5090 war voll belegt)
  bzw. träge CPU-Torch-Inferenz. Parakeet-ONNX: 1,07-GB-Image, CPU reicht.
- **Vorab-Transkript im Stille-Fenster** (28.08.2026 — nicht rückbauen):
  Die Docks schicken den Mitschnitt schon beim Stille-VERDACHT (~150 ms
  Pegel-Ruhe, `recordUntilSilence`) an `POST /api/hoervorab`; Parakeet
  rechnet, während das Dock die restlichen ~350 ms Stille bestätigt. Der
  Zug (`/api/listen` mit `vorabId`) heiratet das Ergebnis: `kern/dienst.py
  -> hoervorab()/_vorab_ergebnis()` (Warte-Deckel 1,5 s). Gemessen: STT auf
  dem kritischen Pfad 0,5 s -> 0,0 s (Transcript liegt beim Zug-Start vor).
  Redet der Anrufer weiter, verwirft das Dock die Kennung (nur ein umsonst
  gerechneter CPU-Decode); max. 2 Vorab-Versuche pro Zug. Fällt das Vorab
  aus (Timeout/Fehler/falsche Kennung), läuft der Normalpfad mit dem
  Final-Blob — nie schlechter als vorher. `timings.stt` misst seither die
  RESTWARTEZEIT auf dem kritischen Pfad, nicht die volle Decode-Dauer.
  Notaus: `STT_VORAB=0` (Worker) => Docks schicken ins Leere, Zug wie früher.
  Tests: `tests/test_stt_vorab.py`; Messung: `tests/latenz_e2e.py <basis> vorab`.

## Ziel-Pipeline Lisa/Bianca (Chef 28.08.2026)

**Parakeet (STT, 8212) -> bewährte Guards/Wächter -> Qwen 3.6 (vLLM, 8000)
-> Qwen3-TTS-12Hz-0.6B-Base (8213).** Eine Äußerung = ein `/speak`, kein
Stream-Schnitt (Genuschel 28.08.2026). Chatterbox 8210 und CosyVoice 8211
liegen als Image, laufen nicht. Nie zwei TTS zugleich. Clara V7 und
Demo-Clara werden NICHT angefasst, bis Lisa/Bianca vernünftig funktionieren.

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
