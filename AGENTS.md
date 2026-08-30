# Arbeitsregeln Bianca & Lisa Telefon-KI

Dieses Repo ist **autark**. Es darf Clara live, Clara-dev, DemoClara,
Lena-Voice und MAS-2 nicht anfassen, nicht neustarten, nicht umbauen.

## Isolation

- Eigener Port **8095** (Clara 8091, v6 8092, Clara-dev 8093, DemoClara 8094).
- Kein Kill fremder Python-Worker.
- Kein Import aus `Clara-Voice*`, `Pickadoc-Demo` oder `MAS-2`.
- Kalender und Patientensuche gehen an Pickadoc-Cloud-Functions.
- MAS (`MAS_URL`): Kalender-Lese-Fallback + Praxisgedächtnis (W-GEDAECHTNIS
  29.08.2026: Gesprächs-Reports an `/brain/events` schreiben, Anrufer-Kontext
  von `/brain/caller-context` lesen — sonst nichts, kein Prozess-Eingriff).

## Mandanten

Jede Sitzung trägt `clientId`. Keine Praxis-IDs im Kernel.
Dev-Default: `tenants/meddent.json`. Schreiben: `WRITE_LIVE=1`
(Chef 26.08.2026: echter Kalender — buchen, absagen, verschieben).

**Sprechformen des Praxisnamens (29.08.2026):** meddent heißt jetzt
"Zahnärzte im Medical Center Düsseldorf". Weil Plural-Namen sich nicht
nach "von der …" beugen lassen, trägt der Mandant die Formen selbst:
`praxisNameMelde` (Biancas Meldung, Nominativ, gern ohne Stadt) und
`praxisNameVon` (gebeugt inkl. Artikel: "den Zahnärzten im Medical Center
Düsseldorf" — Lisas "hier ist Lisa von …", auch in Prompt-Regie und
Einwand-Zeile). Helfer: `kern/tenants.praxis_melde()` / `praxis_von()`;
ohne Felder gilt wie früher `praxisName` bzw. "der {praxisName}".

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
  die Dockerfiles zwingen torch nach der Modell-Installation auf cu128
  zurueck — Zeile nicht entfernen.
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
 — jede Engine-Basis hat ihren eigenen Cache).
 Dienststart damit ~2 s statt ~60 s; Stimmen-/Engine-Wechsel rendert neu,
 weil der Key wechselt. Cache leeren = Ordner löschen.
- **Pausen-Straffung** (29.08.2026 — nicht rückbauen): Qwen3 würfelt in
  Ein-Block-Renders teils weit über eine Sekunde Stille zwischen die Sätze —
  die Begrüßung klang "sehr langsam gesprochen mit zu langen Pausen" (Chef).
  `kern/tts.pausen_straffen()` kappt in FRISCHEN `speak_dauerhaft`-Renders
  (Begrüßung, Füller, feste Fragen) Anlauf-Stille auf 120 ms, Satz-Pausen
  auf 350 ms, Ausklang auf 250 ms — nur Fenster unter der Aktiv-Schwelle
  fallen weg, die Sprache bleibt Sample-identisch. Gesprächs-Antworten
  (Stream, Ziffern-Readbacks) laufen NICHT hindurch. Straffung sitzt VOR
  Längen-Deckel/Gegenhören in `warm()` — abgenommen wird das Audio, das
  später spielt. Notaus: `TTS_PAUSEN=0`. Tests: `tests/test_tts_pausen.py`;
  frisch rendern + nachmessen: `tests/ansage_probe.py`.
- **Satz-Pinning** (28.08.2026 spät — nicht rückbauen): dauerhaft gewarmte
  Sätze liegen im gepinnten RAM-Bereich (`kern/tts.py -> _FEST`), den das
  48er-LRU nie verdrängt. Bianca wärmt beim Start zusätzlich ALLE festen
  Maschinen-Fragen (`bianca/gehirn.py -> feste_saetze()`, in Sanitize-Form).
 `Dienst.stimme()` spricht mehrsätzige Antworten satzweise und fügt die
 Teile zu EINEM WAV (`tts.wav_fuegen`, kein Streaming, keine Naht im Wort):
 gewarmte Fragen kosten ~0,0 s statt ~1-2 s Synthese, Quittungen landen
 einzeln im LRU. Gewarmte Gesamttexte (Begrüßung/Füller) bleiben EIN Block
 (`tts.im_cache`-Vorabfrage — Satz-Split würde ihren Cache-Key verfehlen).
 Beim Wärmen prüft `tts.warm()` die Render-Länge (`_warm_unplausibel`):
 unplausibel lange Würfe werden EINMAL neu geholt, der kürzere gepinnt.

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
- Nachkorrektur: `stt_serve/postcorrect.py` = **KOPIE** von Claras
  `services/stt_postcorrect.py` (Fuzzy-Hotwords, Anlaut-Gruppen P/B & T/D/Z,
  Token-Paare, `assess_name_certainty` für Buchungs-Wachen). Kopie statt
  Import — dieses Repo fasst Clara-Voice nie an. Phrasen-Fixes (Heads-up/
  Teleskopkrone/Kons) sind Marker-gated; Lisa/Bianca senden keine Marker.
- Keywords: `kern/tenants.py -> stt_keywords()` liefert die Behandler-
  Nachnamen des Mandanten ("Petsas", "Nikolaou", "Patrikis"), `kern/stt.py`
  schickt sie je Request mit ("Betsas" -> "Petsas" VOR dem LLM).
- Umschalten NUR über `STT_BASE` in der `.env`: gesetzt = ALLE Züge über den
  Container, **KEIN ElevenLabs-Rückfall** (gleiches Muster wie `TTS_BASE`);
  leer = Scribe wie früher. Tests: `tests/test_stt_lokal.py`.
- Gemessen 28.08.2026: Container 0,34-0,43 s je Zug (Server-lokal, wortgenau
  gegen Referenztranskript), E2E im Bianca-Dienst `timings.stt` = 0,44 s —
  Scribe lag bei 0,8-2,0 s. Messwerkzeuge: `tests/latenz_e2e.py`,
  `tests/timing_bericht.py`, `stt_serve/latenz_probe.sh`.
- **Stille-Trim im Container (W-STT-TRIM 29.08.2026 — nicht rückbauen):**
  Parakeet-TDT normalisiert die Log-Mel-Features über das GANZE Segment —
  die Dock-Blobs (Zöger-Vorlauf + ~0,7 s Nachlauf-Stille) drückten kurze
  Antworten weg: "Ja"/"Nein" gepolstert -> leeres Transkript, bei "Ja,
  gerne." fraß der Nachlauf sogar das zweite Wort (NeMo #15757; Baseline
  29.08.: 5/13 Proben rot). `stt_serve/server.py -> _stille_trimmen()`
  schneidet Vor-/Nachlauf-Stille VOR der Inferenz energie-basiert ab
  (20-ms-RMS, Schwelle max(5 % vom Peak, 0.003), Rand 160 ms vorn /
  320 ms hinten); reine Stille-/Brumm-Blobs werden verworfen statt
  halluziniert (4 s Stille: 49 ms statt Voll-Decode). Dazu Retry-Guard
  für onnx-asr #138 (AssertionError -> ein Wurf mit +40 ms Stille).
  Notaus: `STT_TRIM=0` (compose reicht durch) = byte-identisches
  Alt-Verhalten; `/health` zeigt `trim`. Image-Versionen seit 29.08.
  gepinnt (onnx-asr 0.12.0, onnxruntime 1.29.0, numpy 2.4.6). Abnahme:
  `tests/stt_kurz_probe.py` (13/13 grün; Referenzsatz lisa.wav wortgenau,
  Latenz 140-215 ms unverändert).
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

## Whisper-GPU-Ohr mit Parakeet-Rückfall (W-STT-WHISPER 30.08.2026 — nicht rückbauen)

Chef 30.08.2026: der Whisper-Container auf dem Dev-Rechner (Projekt
pickadoc-stt, faster-whisper **large-v3** auf der Dev-GPU, `int8_float16`)
soll Bianca/Lisa auf pickadoc1 zuhören — auf die 5090 passt er nicht
(gemessen: 1,4 GB frei, Whisper braucht ~4,5 GB). Kein DynDNS, keine
öffentliche Domain: beide Rechner sind im selben Tailscale-Netz.

- **Weg:** Windows-Portproxy `100.81.214.94:8092 -> 127.0.0.1:8092` +
  Firewall-Regel "STT Whisper (nur Tailscale)" (eingehend NUR 100.64.0.0/10)
  auf dem Dev-Rechner; der Container selbst (fremdes Projekt, läuft auf
  `127.0.0.1:8092`) bleibt unangetastet — nie neu starten.
- **Adapter** (`kern/stt.py`): der Container spricht WebSocket-Streaming
  (Bearer-Auth, `begin`/PCM16-16-kHz-Frames/`end` -> `final`), kein
  Datei-Upload. `_pcm16k()` dekodiert Zug-Audio (webm/m4a) über ffmpeg
  (im App-Image vorhanden), passendes WAV geht direkt; Keywords biasen
  als `initial_prompt` den Decoder, danach läuft DIESELBE Fuzzy-
  Nachkorrektur wie bei Parakeet im Prozess (`stt_serve/postcorrect.py`,
  wird jetzt ins App-Image kopiert — Dockerfile/.dockerignore).
- **Umschalten:** `STT_WHISPER_BASE` in der `.env` (z. B.
  `ws://100.81.214.94:8092`, `STT_WHISPER_KEY` Default pickadoc-stt-dev-key).
  GESETZT = Whisper hört ZUERST; Fehlschlag (Dev-Rechner aus, Tunnel weg)
  = automatischer Rückfall auf `STT_BASE` (Parakeet, Chef 30.08.2026)
  und 30 s Whisper-Pause (`WHISPER_PAUSE_S`), damit nicht jeder Zug den
  2-s-Connect-Timeout bezahlt. NIE still auf ElevenLabs: ohne STT_BASE
  fliegt der RuntimeError hörbar. Leer = alles wie vor W-STT-WHISPER.
- **Gemessen 30.08.:** Whisper über Tailscale 1,4 s je Zug (Testsatz
  wortgenau inkl. "Petsas" per Hotword-Bias), Rückfall-Zug 2,75 s
  (einmalig, danach 0,33 s Parakeet-direkt), webm-Pfad grün.
  Parakeet bleibt die schnellere Engine — Whisper ist der Qualitäts-Test.
- Health-/Dock-Anzeige: `engine_anzeige()` zeigt "Whisper large-v3
  (Dev-GPU) + Parakeet-Rueckfall" bzw. "(…, Whisper pausiert)".
- Tests: `tests/test_stt_whisper.py` (offline: Vorrang, Rückfall+Pause,
  nie Scribe, WAV-Direktspur, Nachkorrektur); Live-Probe:
  `tests/stt_whisper_probe.py` (echter Container + echter Rückfall).

## Nichts mehr verschlucken (W-STT-SCHWANZ 30.08.2026 — nicht rückbauen)

Kollegen-Befund 30.08.: beim Transkribieren wurden manchmal die letzten
Ziffern verschluckt. Vorbild ist die abgesicherte STT-Strecke des
phone_agent (NUR gelesen, nichts dort angefasst): 500 ms Pre-Roll
(`VAD_PREROLL_MS`), Diktat-Geduld `SMART_ENDPOINT_DICTATION_HANG_MS=1800`
und die Lektion aus `providers/stt/streaming.py` (Final-Pass-VAD
min_silence 2000 ms, weil Diktier-Pausen sonst als Segmentende galten und
die Sprache DANACH verworfen wurde). Vier Bausteine bei uns:

1. **Diktat-Geduld** (`bianca/gehirn.stille_ms`): telefon/buchstabieren
 650 → **1500 ms** — wer vor der letzten Ziffern-Gruppe zögert, dem wird
 der Zug nicht mehr mitten in der Nummer geschnitten. Kurz-/Default-
 Schwellen (350/500) unverändert; Brücke und Docks übernehmen den Wert
 wie gehabt über das `stilleMs`-Feld.
2. **Hysterese in der Brücken-VAD** (`sip_bridge/server.py`): am Satzende
 senkt sich die Stimme um 10–20 dB — leise Schluss-Ziffern lagen unter
 der Ein-Schwelle und `still_seit` lief mitten im Wort los. Jetzt hält
 ein leiser Auslauf (>= 45 % der Ein-Schwelle, `HALTE_FAKTOR`) das
 Zugende offen, gedeckelt auf `HALTE_MAX_S` (1 s) nach dem letzten klar
 lauten Rahmen — Dauerpegel zwischen den Schwellen kann die Aufnahme nie
 endlos aufhalten.
3. **Trim-Grenzen im STT-Container** (`stt_serve/server.py`): die strenge
 5-%-vom-Peak-Schwelle bestimmte auch die SCHNITT-Grenzen — ein leise
 ausklingendes Nummern-Ende länger als die 320-ms-Marge wurde
 weggeschnitten, bevor Parakeet es sah. Schnitt-Grenzen laufen jetzt
 über die zarte Schwelle (`_TRIM_REL_ZART` 1,5 %, nie unter dem
 Grundrausch-Boden); die Verwerfen-Gates (Stille/Transient) urteilen
 weiter streng. Braucht einen Rebuild des stt-Containers auf der 5090.
4. **Brücken-Vorlauf** 300 → **500 ms** (`VORLAUF_FRAMES` 25) — wie der
 phone_agent gegen abgeschnittene weiche Anlaute ("gesetzlich" →
 "ersetzlich").

Der Whisper-Pfad (W-STT-WHISPER) hat die Final-Pass-Lektion bereits im
Container (min_silence 2000, hotwords statt initial_prompt-Echo). Tests:
`tests/test_stt_trim.py` (Trim-Grenzen offline), Hysterese-Block in
`tests/test_sip_vad.py`, 1500er-Werte in `test_stille_ms_nach_fragetyp`.

## Ziel-Pipeline Lisa/Bianca (Stand 28.08.2026 spät)

**Parakeet (STT, 8212) -> bewährte Guards/Wächter -> Qwen 3.6 (vLLM, 8000)
-> lokales TTS, blocking `/speak`.** Alles lokal auf der 5090, die Worker
(8095/8096) bleiben lokal auf dem Dev-Rechner. Nie mehrere TTS-Container
zugleich (eine GPU). Clara V7 und Demo-Clara werden NICHT angefasst, bis
Lisa/Bianca vernünftig funktionieren.

- **Aktiv: Qwen3-TTS 0.6B-Base Hybrid (8213)** — Triton-Kerne + CUDA-Graph
  (`qwen3-tts-triton` TritonFasterRunner, Chef 29.08.2026). Blocking
  `/speak`, kein Audio-Stream, kein TurboQuant, kein vLLM-Omni, nicht 1.7B
  (35B-vLLM teilt die 5090; 0.6B sprach Ziffern 5/5). Health: `engine=
  qwen3-hybrid`. Notaus: `TTS_HYBRID=0` im Qwen-Container. Gemessen
  29.08. nachts: Readback 1,5–2,3 s (nacktes Qwen 4,4–5,1 s; Cosy-Turbo
  0,6–1,2 s inkl. Nachhoeren), Kurzsaetze 0,5–1,3 s. Ziffern-Probe 5/5.
  **Phase 2 AKTIV (29.08.2026): Audio-Chunk-Streaming.** Der GANZE Satz geht
  als Text an `/speak-stream`, PCM-Stuecke kommen zurueck, sobald der Codec
  sie liefert — KEIN Text-Schnitt (das war das Genuschel vom 28.08., bleibt
  verboten). Gemessen: erster Ton nach ~0,2 s statt 0,6–2,3 s Voll-Render.
  Kette: `kern/tts.py -> LokalTts.speak_stream` (Gain aus dem ersten sprach-
  aktiven Stueck, dann KONSTANT; fertiger Satz landet normal gepegelt im
  LRU) -> `kern/dienst.py -> stimme_stream` (sofortige URL, Feeder-Faden) ->
  `GET /api/audio-stream/<id>.wav` (offener WAV-Header, waechst) -> Docks
  spielen Stream-URLs ueber `<audio>` progressiv (decodeAudioData braucht
  die ganze Datei). BLOCKING bleiben: Ziffern-/Readback-Saetze (der
  Nachhoer-Waechter braucht das komplette Audio VOR dem Anrufer — sie werden
  verifiziert in den Strom gelegt), Cache-Treffer (eh sofort) und der
  ElevenLabs-Pfad. Notaus: `TTS_AUDIO_STREAM=0` (Dienst) => alles blocking
  wie vor Phase 2; Container-Health zeigt `stream:true`.
- CosyVoice-Turbo (8211) bleibt als Image liegen. Roh halluziniert die
  Engine bei Zahlwort-Ketten — deshalb drei Schichten in `kern/tts.py`
  (nur lokaler Pfad, ElevenLabs unberuehrt — nicht rueckbauen):
  1. **Ziffern-Transformation** `_ziffern_einzeln`: Ketten ab zwei
     Zahlwoertern gehen als Einzelziffern an den Container ("null eins
     sieben sieben" -> "0 1 7 7", gemessen 5/5 statt 1/5; Ziffern
     GRUPPIERT "0177" liest Cosy die fuehrende Null weg — nie so senden).
     Cache-Key, Logs und Transkript behalten die Wortform. Uhrzeiten
     ("neun Uhr fuenfzehn") bleiben unberuehrt.
  2. **Nachhoer-Waechter** fuer Saetze mit >= 4 Ziffern: Parakeet hoert
     jeden frischen Render gegen (~0,4 s); fehlen Ziffern, wird neu
     gewuerfelt (max. 3 Wuerfe, Log `tts-ziffern:`). Erst der verifizierte
     Wurf erreicht Anrufer und LRU. E2E gemessen: Readback frisch ~1,0-1,2 s
     inkl. Pruefung (Qwen3 brauchte 4,4-5,1 s). Notaus: `TTS_ZIFFERN_CHECK=0`.
  3. **Warm-Abnahme per Gegenhoeren** (`_warm_score`): beim Vorwaermen
     faellt Babble ("hissio") jetzt auch dann auf, wenn die Laenge plausibel
     ist — zu wenig Soll-Woerter im Gehoerten => neuer Wurf, der bessere
     wird gepinnt. Nur beim ERSTEN Waermen (Platten-Eintrag = abgenommen,
     Dienststart bleibt ~2 s). Notaus: `TTS_WARM_CHECK=0`.
  Die Ziffern-Probe `tests/tts_ziffern_probe.py` (Render 5x + Parakeet-
  Gegenhoeren, prueft die PRODUKTIONS-Form inkl. Transformation) ist fuer
  JEDEN Engine-Wechsel Pflicht: 5/5 oder die Engine geht nicht live.
  Engine-Wechsel danach: Platten-Cache leeren (`.data/tts-cache/`), damit
  alte Pins neu durch die Abnahme laufen.
- **Rückbau-Anker: Tag `bianca-lisa-v1.0`** = Stand mit Qwen3-TTS (8213,
  langsamer, aber ziffernfest auch ohne Waechter); Platten-Cache traegt die
  Basis im Key. Umschalten = `TTS_BASE` in `.env` + auf der 5090
  `docker compose --profile <alt> down && --profile <neu> up -d`
  (Repo dort: /home/cursor/telefonki).
- Chatterbox (8210) bleibt als gebautes Image/Profil liegen, läuft nicht.
- **.env-BOM-Falle (29.08.2026):** PowerShell-Redirects schreiben die .env
  MIT UTF-8-BOM — dotenv las `\ufeffWRITE_LIVE` und das Live-Schreiben war
  still aus. `kern/config.py` liest jetzt `utf-8-sig`; .env trotzdem nie
  per PowerShell-Redirect schreiben.

## Neustart vom Mitternachts-Stand (28.08.2026 spät — Chef-Entscheid)

Die Streaming-/Häppchen-Ära vom 28.08. vormittags ("Genuschel") und die
Tagesfeatures vom Nachmittag sind AUSGEBAUT: Branch `neustart-mitternacht`
setzt auf dem Gesprächs-Stand von 02:18 auf (Chef: "weltklasse") und trägt
NUR die STT-/TTS-Anbindung (Parakeet 8212, Qwen3-TTS 8213, RMS-Lautheit,
Satz-Pinning). Der komplette Abendstand liegt unangetastet auf dem Branch
`sicherung-2026-08-28-abend` — Features von dort nur EINZELN und bewusst
zurückholen, nie pauschal mergen. Es gibt KEIN TTS-Streaming auf diesem
Stand: eine Äußerung = ein blockierender `/speak` (bzw. satzweise gefügt).

## Versichertenstatus + Vornamen-Wächter (29.08.2026 — nicht rückbauen)

Chef-Vorgabe: privat/gesetzlich gehört in die Kartei, Anrufer werden
geschlechtsspezifisch angesprochen.

- **Versicherungs-Frage** (`bianca/gehirn.py -> _versicherung_frage`):
  Neupatienten (warSchonMal=False) als LETZTE Pflichtfrage; Bestandsakten
  NUR, wenn der letzte Besuch >6 Monate her ist (`letzterBesuch` via
  masPatientLastDoctor im Hintergrund), als Ja/Nein-Rückfrage gegen den
  Kartei-Stand. NUR der Wechsel privat<->gesetzlich zählt — Kassenwechsel
  (AOK->TK) ist bewusst KEIN Wechsel (Kassen-Namen zählen als "gesetzlich").
  Bestand OHNE Kartei-Treffer wird nicht verhört. "Nein/geändert" auf die
  Rückfrage heißt deterministisch das GEGENTEIL des Kartei-Stands.
- **Kartei-Schreibwege:** Neupatient über `akte_anlegen`/masCreatePatient
  (`privateInsurance`-Feld); Bestands-Wechsel SOFORT über
  `masUpdatePatientInsurance` (neu, pickadoc-live-base) mit Sicherheitsnetz
  in `_buchen` VOR der Buchung — so trägt der Termin-Schnappschuss
  (Terminpopup) den richtigen Status. Scheitert das Update oder bleibt die
  Frage unklar (Eskalation), hängt `_buchen` eine Praxis-Notiz an den Termin.
  masSearchPatients liefert `privateInsurance` jetzt mit (additiv).
- **Vornamen-Wächter** (`kern/vornamen.py`): kuratierte Listen + konservative
  -a-Heuristik; Doppelnamen entscheidet der erste Teil; mehrdeutige Namen
  (Kim, Sascha, Toni …) liefern "". Chef-Default: unklarer Vorname =>
  WEIBLICH + Termin-Notiz "Bitte Geschlecht aktualisieren". Kartei-Geschlecht
  (`geschlechtQuelle=akte`, via hintergrund) schlägt IMMER die Schätzung.
  Anrede: `gehirn.anrede()` ("Frau Müller" / gebeugt "Herrn Müller") im
  Readback ("für Frau Müller"); Lisa rät weiterhin NICHT (voller Name bei
  mehrdeutigen Vornamen), nutzt den Wächter nur bei eindeutigen.
- Neue Akten bekommen das Geschlecht (m/f) über masCreatePatient registriert.
- Tests: `tests/test_versicherung_geschlecht.py` (Teil von lauf_bianca).

## Rückblick + Zahnreinigung-Mitbuchung (29.08.2026 — nicht rückbauen)

Bestandspatienten mit Kartei-Historie werden EINMAL pro Anruf auf den
letzten Besuch angesprochen (`gehirn.rueckblick_faellig`/`rueckblick_text`:
Abstand sprechbar + Verlaufs-Frage je Behandlung — verheilt/zufrieden/
Schlaflabor-Werte/Zahn ruhig). Danach bietet Bianca die PZR zum Mitbuchen
an (`pzr_faellig`/`pzr_frage`, Einschub in `flow._einschub`). Chef 29.08.
("vortermin zwar gefunden aber keine zahnreinigung mit angeboten!!"):
das Angebot kommt, SOBALD der Vortermin gefunden ist — KEINE 6-Monats-
Schranke mehr auf dem letzten Besuch. Ausnahmen: der neue Termin ist
selbst eine Zahnreinigung, Schmerz-/Notfall-Termin, oder der LETZTE
Besuch war selbst eine PZR und liegt unter 6 Monaten zurück (frisch
gereinigt). Der Zeitbezug in der Frage ("schon eine Weile her") wird nur
gesprochen, wenn er stimmt. Zusage landet als "PLUS PZR heute" in der
Termin-Notiz. Tests: `tests/test_rueckblick_pzr.py`.

## Behandler-Wahl zu Gesprächsbeginn (29.08.2026 — nicht rückbauen)

Chef: "es gibt dr petsas dr patrikis und dr nikolaou … es muss zu beginn
geklärt werden in welchem kalender und bei welchem arzt du suchen sollst."
Jeder Behandler hat seinen eigenen Kalender samt Id; Neupatienten wurden nie
gefragt und die Suche lief stumm ohne Behandler-Klärung.

- **Neupatienten** (warSchonMal=False) bekommen direkt nach der
  Schonmal-Frage die Behandler-WAHL mit allen Namen aus den Tenant-Kalendern
  (`gehirn.arztwahl_frage`, Sprechform ohne Vorname via
  `kern.patients.arzt_sprechname`) — nur bei >= 2 Kalendern, ein einziger
  Kalender bleibt fraglos.
- **Bestand** behält die Akten-Frage "bei welchem Behandler waren Sie
  zuletzt?" (anderer Zweck: Kartei-Auflösung).
- **"Egal" bleibt gültig** (typ=egal): Slot-Suche läuft ohne calendarId,
  die Cloud Function wählt global den schnellsten Arzt (wie gehabt).
- **Wiederholungs-Wächter** tauscht bei Neupatienten auf eigene Formen
  (`gehirn.ARZTWAHL_VARIANTEN`) — nie "bei wem waren Sie zuletzt?" an
  jemanden, der nie da war. Kern-Wort-Regel gilt: jede Form trägt "Behandler".
- `feste_saetze(tenant)` wärmt die Wahl-Frage mit den echten Namen vor
  (bianca/server ruft sie MIT Tenant).
- Tests: Behandler-Wahl-Block in `tests/test_bianca_bausteine.py`.

## SIP-Telefonie: AudioSocket-Brücke (W-SIP 29.08.2026 — nicht rückbauen)

Bianca ist unter **+49 211 54244101** und **+49 211 54244110** echt
anrufbar (W-SIP-110 30.08.2026: die 4110 zeigte vorher auf den alten
lokalen phone_agent via LiveKit-Trunk; ihr Eintrag steht jetzt ebenfalls
in `extensions_bianca.conf` mit eigener Dialplan-UUID `…4110` — die Datei
wird VOR `extensions_numbers.conf` eingebunden, der erste Treffer gewinnt,
die Number-API darf ihren livekit-Eintrag behalten, er greift nur nicht
mehr; Backup: `extensions_bianca.conf.bak-20260830`). Kette:
Zaluma → Asterisk (87.106.34.137, `[from-zaluma]`) → `Answer()` +
`Dial(AudioSocket/127.0.0.1:40101/<uuid>)` → **SSH-Rücktunnel** →
`sip_bridge/` auf pickadoc1 → Bianca (8096) über ihre normale Dock-API.

- **`sip_bridge/server.py`** ist ein reiner Übersetzer, KEINE Gesprächslogik:
  Anrufer-PCM (8 kHz) sammeln, Zugende per RMS-Stille (Schwelle kommt je
  Frage aus `stilleMs`, W-TEMPO), als 16-kHz-WAV an `POST /api/listen`;
  Biancas NDJSON (filler/transcript/warte/reply) steuert die Wiedergabe
  (24-kHz-WAVs → 8 kHz, 20-ms-Takt, progressive Stream-URLs spielen beim
  Laden). Barge-in: Reinsprechen stoppt die Wiedergabe sofort, Quittung
  („Hm.") spielt, der Zug trägt bargeUrl+bargeMs → W-BARGE arbeitet
  unverändert. ~4 s Funkstille → `POST /api/stille`. `hangup:true` →
  ausspielen, Ende-Rahmen, `POST /api/hangup` (Nacharbeit/Gedächtnis wie
  im Dock). MP3 (Verbinden-Jingle) dekodiert ffmpeg (im App-Image).
- **Tunnel:** Compose-Service `tunnel` (alpine+ssh, sudo-frei) hält auf dem
  Asterisk `127.0.0.1:40101` offen (`-R … :sipbridge:40101`). Key
  `~/.ssh/id_ed25519_asterisk_tunnel` (pickadoc1) ist auf dem Asterisk mit
  `permitlisten="40101",no-pty,…,command=…` beschnitten — kein Shell-Zugang.
  Achtung: `restrict` + `permitlisten` verweigert auf OpenSSH 8.9 den
  Forward — deshalb die Einzel-Optionen.
- **Asterisk:** Route liegt in `/etc/asterisk/extensions_bianca.conf`
  (eigene Include-Datei in `[from-zaluma]`, überlebt jede Regenerierung der
  Number-API; Backup: `extensions.conf.bak-bianca`). Die Number-API führt
  die DID bewusst NICHT (nur Backends elevenlabs/livekit). Blessing,
  MedDent und der LiveKit-Test sind unangetastet.
- **Leitungs-VAD adaptiv (W-SIP-RAUSCH 29.08.2026 spät — nicht rückbauen):**
  Erste echte Anrufe scheiterten an der starren RMS-Schwelle 400 — das
  DAUER-Grundrauschen der Telefonleitung löste nach 400 ms einen falschen
  Barge aus („Zahnarzt… hm… äh"), die Aufnahme fand nie ein Stille-Ende,
  kein Zug erreichte Bianca. Seitdem: adaptiver Rauschteppich `_floor`
  (fällt schnell auf leise Rahmen, steigt ~+50 %/s auf laute),
  Sprech-Schwelle = max(400, 3×Teppich), Barge-Schwelle = max(1100,
  5×Teppich) bei 280 ms Mindestdauer. Außerdem sendet die Brücke in
  Sprechpausen DAUER-STILLE-Rahmen Richtung Asterisk (der Medienstrom darf
  nie abreißen — RTP-Timeout beendet sonst den Anruf, sobald Bianca
 zuhört), und der Stups-Timer zählt erst ab dem ÜBERGANG spielen→leer
 (vorher wurde `fertig_seit` jeden Tick überschrieben, der 4-s-Stups
 feuerte nie). Barge-/Zug-Logs tragen rms+floor für die Feld-Diagnose.
- **Kurze Antworten zählen (W-SIP-KURZJA 30.08.2026 — nicht rückbauen):**
 Live 16:23: Anrufer sagte mehrfach "Ja" auf die Schonmal-Frage — die
 Brücke verwarf alles ("zug verworfen (5 Sprach-Frames)"), zwei Stupse,
 Auflegen. Zwei Ursachen, zwei Fixes in `sip_bridge/server.py`:
 (1) Ein gesprochenes "Ja" hat nur ~100-200 ms Stimmanteil, der
 Knacser-Filter verlangte 240 ms (`MIN_SPRACHE_FRAMES=12`) — jetzt
 Kurz-aber-laut-Ausnahme: ab `KURZ_FRAMES` (4 = 80 ms) reicht ein
 Spitzenpegel >= `KURZ_PEAK` (1200); echte Knackser (1-3 Frames) bleiben
 draußen, Rest fängt der Stille-Trim im STT-Container. (2) Der 800-ms-
 Echo-Sperr-Schwanz nach Biancas Sprechende blockte schnelle Antworten
 (Wortanfang galt als Echo, Rest schaffte die 3 Start-Frames nicht) —
 die Echo-Referenz klingt jetzt AB (`echo_pegel`: voll bis `ECHO_VOLL_S`
 0,3 s, dann linear auf 0 bis 800 ms). Während der Wiedergabe bleibt die
 Halbduplex-Wache unverändert (volles 2-s-Fenster, Barge braucht weiter
 280 ms). Zug-Logs tragen jetzt auch `peak=`. Tests:
 `tests/test_sip_vad.py` (offline, Fake-Uhr gegen die VAD-Rahmenlogik).
- **Echo-Sperre raus (W-SIP-ECHO-RAUS 30.08.2026, Chef: „schmeiss das echo
 gedöhns raus fürs stt"):** Die Halbduplex-Echo-Sperre aus W-SIP-RAUSCH
 (Eingang zählt nur als Sprache, wenn er 30 % über dem juengst Gesendeten
 liegt) hielt beim Kollegen-Test echte Antworten vom STT fern (Sprache
 rms 8000–9000 bei echoRef 12000–15000 → verschluckt, Barge-in während
 Biancas Sprechen praktisch unmöglich). Sie ist jetzt DEFAULT AUS
 (`BRIDGE_ECHO=0`); der Rest von W-SIP-RAUSCH (adaptiver Rauschteppich,
 Dauer-Stille-Rahmen, Stups-Timer) bleibt unverändert. Absicherung:
 das Leitungsecho ist seit W-SIP-PEGEL 6 dB leiser, und ein doch
 durchgerutschtes Echo-Transkript fängt die Text-Echo-Wache im Dienst
 (`unterbrechung.ist_echo`: verwerfen + weitersprechen). Rückweg:
 `BRIDGE_ECHO=1` = Alt-Verhalten. `echo_pegel()` läuft für die
 Pegel-Diagnose (echoRef im Log) weiter mit.
- **Telefon-Pegel gedämpft (W-SIP-PEGEL 30.08.2026 — nicht rückbauen):**
 Biancas Renders fahren mit Sprach-RMS −14 dBFS und Peaks am 0,95-Deckel
 (Chef-Abnahme 28.08. für die Docks) — auf der G.711-Strecke klang das
 „sehr übersteuert" (Kollege 30.08., gemessen: jeder Zug am Peak-Deckel,
 0,2–0,3 % geclippte Samples). Die Brücke dämpft deshalb NUR Richtung
 Asterisk um 6 dB: `BRIDGE_GAIN` (Default 0.5, 1.0 = Alt-Verhalten),
 angewendet an der einen Sende-Stelle in `Wiedergabe.lauf()` VOR der
 Echo-Referenz — Halbduplex-Wache bleibt konsistent, weil das echte
 Leitungsecho ebenso leiser wird. Docks und die TTS-Pegel-Schicht
 (`kern/tts.py`) sind unangetastet. Nebenbefund: auch das ANRUFER-Audio
 kommt von der Zaluma-Strecke heiß an (~1 % Clipping, A-law-Vollausschlag)
 — das erklärt STT-Verhörer wie „Zermin"; liegt vor unserer Kette.
- **Probe:** `tests/sip_bridge_probe.py` simuliert Asterisk (UUID + PCM-
  Rahmen, echtes deutsches TTS-Audio als Anrufer) gegen eine laufende
  Brücke; Kettentest vom Asterisk: `channel originate
  Local/21154244101@from-zaluma application Wait 10` → Brücken-Log zeigt
  die Dialplan-UUID `b1a2ca00-…-4101`.
- Die Browser-Docks (8095/8096) laufen unverändert parallel — die Brücke
  ist nur ein weiterer Klient derselben API.

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

## Barge-in mit Fortsetzung (W-BARGE 29.08.2026 — nicht rückbauen)

Chef: "wenn sich unsere sprachen kreuzen, muss die KI-Assistentin aufhören,
mit hmm oder okay konkret auf den Einwand reagieren und dann erst nach
Klärung fortfahren, wo sie stehengeblieben ist." Gilt für BEIDE Stimmen;
Logik in `kern/unterbrechung.py`, eingehängt in `kern/dienst.py` —
reine Textarbeit, kein LLM, kein Netz.

- **Sofort-Quittung:** Docks laden beim Boot `GET /api/quittung` ("Hm."/
  "Okay.", beim Start vorgewärmt, Platten-Cache) und spielen beim
  Reinsprech-Stopp SOFORT eine ab — noch vor Aufnahme und Einwand-Zug;
  rotierend, nie zweimal dieselbe in Folge.
- **Satz-Karte:** `stimme`/`_sprech_blob`/`stimme_stream` schreiben je
  Äußerung die Sätze + End-Zeitpunkte (ms im Audio) mit; beim Stream füllt
  der Feeder die Karte WÄHREND des Sprechens (Listen referenziert, nicht
  kopiert). ElevenLabs-MP3 trägt keine Zeiten => Barge dort = ganze
  Äußerung ist Rest.
- **Eingang:** Docks melden `bargeUrl`+`bargeMs` (Abspielposition beim
  Stopp) im nächsten `/api/turn` bzw. `/api/listen`. `eingang()` bestimmt
  den ungesprochenen Rest (angespielter Satz zählt als ungesprochen) und
  STUTZT das Protokoll auf das wirklich Gesagte — LLM und Wiederholungs-
  Wächter dürfen nicht glauben, der Anrufer hätte Ungespieltes gehört.
  Fremde/verbrauchte URLs (Füller, Stups, alter Zug) => kein Rest.
- **Fortsetzen:** Nach dem Einwand-Zug hängt `fortsetzen()` Brücke
  ("Also, wo war ich: …", rotierend) + Rest an die Antwort — NUR wenn der
  Einwand den Zustand nicht bewegt hat: keine Buchung (`reply.book`) und
  keine Frage in der Antwort (fragt die Maschine neu, wäre der alte Rest
  doppelt oder veraltet). Ein ABBRUCH-Befehl als Einwand ("Stopp.",
  "Hör auf", "Sei still" — `ist_abbruch`) verwirft den Rest IMMER
  (live 29.08.2026: auf "Stopp." kam "Alles klar, ich höre auf … Also,
  wo war ich:" und die komplette Ansage lief erneut). Wortgleich
  enthaltene Rest-Sätze fallen weg; der gesprochene Anhang wird ins
  Protokoll NACHGETRAGEN.
- **Fehlalarm:** nichts/zu wenig gehört => Dock ruft `POST /api/weiter`
  (`weiter_sprechen`): der Rest wird an der Unterbrechungsstelle
  weitergesprochen — deterministisch, ohne LLM, ohne Brücke. Ein
  Lautsprecher-Echo der eigenen Stimme (ab 3 Wörtern, wortgleich im gerade
  Gesagten; kurze echte Antworten "ja/nein/stopp" NIE) wird verworfen und
  ebenso fortgesetzt (Claras Echo-Regel, aufs Dock übersetzt).
- Tests: `tests/test_unterbrechung.py` (18 Fälle, offline). Live-Probe
  29.08.: Zwei-Satz-Zug (4,9 s), Barge 1,5 s vor Ende => nur der
  Schlusssatz kam als Rest, "Gut." zählte als gesprochen.
- **Notaus:** `BARGE_WEITER=0` (Umgebungsvariable) => Eingang/Fortsetzen
  stumm, `/api/quittung` liefert keine URLs — Verhalten wie vor W-BARGE.

## Zug-Tempo: adaptive Stille + Vorab-STT (W-TEMPO 29.08.2026 — nicht rückbauen)

Chef: "ich will 300 ms schneller werden." Zwei Bausteine, beide Docks:

- **Adaptive Ruhe-Schwelle:** Das Zugende-Kriterium im Dock (`stilleSoll`,
  Default 500 ms) sagt jetzt der Server an: Feld `stilleMs` in jeder Zug-/
  Weiter-Antwort (`kern/dienst._stille_feld`, Hook `stille_fn` im
  Konstruktor). Bianca: `gehirn.stille_ms` — 350 ms nach Ja/Nein-/Wahlfragen
  (schonmal, arzt, slotwahl, bestaetigung, versicherung*, pzr, telefon_alt,
  telefon_check, rueckblick), Diktat-Geduld beim telefon-/buchstabieren-
  Diktat (NIE mitten in der Nummer schneiden; seit W-STT-SCHWANZ 1500 ms
  statt 650), sonst die bewährten 500 ms.
  Lisa hat keinen Hook => Feld fehlt => ihr Dock bleibt bei 500.
- **Vorab-STT:** ab 200 ms Ruhe schickt das Dock den Aufnahme-Stand an
  `POST /api/hoeren` (reines Ohr: Session-Hotwords wie der echte Zug,
  kein Zug, kein Zustand, kein Protokoll) — die Rest-Stille bis zum
  Zugende überlappt mit der Transkription. Liegt das Transkript binnen
  700 ms nach Zugende vor, geht der Zug als TEXT an /api/turn
  (timings.stt entfällt, STT war schon bezahlt); sonst Audio-Weg wie
  bisher. Spricht der Anrufer doch weiter, wird das Vorab verworfen und
  bei der nächsten Ruhephase frisch gestartet. Der Stille-Trim im
  STT-Container (W-STT-TRIM) macht Vorab- und Final-Transkript identisch.
- **Echo-Wache bleibt dicht:** der TEXT-Pfad in `kern/dienst.zug_stream`
  prüft bei gemeldetem Barge jetzt ebenfalls `unterbrechung.ist_echo` —
  ein Lautsprecher-Echo, das als Vorab-TEXT ankommt, wird verworfen und
  weitergesprochen wie im Audio-Pfad.
- Gewinn je Zug: −150 ms bei kurzen Antworten (Schwelle) plus −200 bis
  −400 ms verstecktes STT. Web-Speech bleibt draußen (28.08.2026) — das
  Vorab ist Server-Parakeet, kein Browser-STT.
- Tests: `test_stille_ms_nach_fragetyp` / `test_dienst_traegt_stille_feld`
  (test_bianca_bausteine). Live-Probe 29.08.: stilleMs 350/350/500 je nach
  Frage, /api/hoeren transkribiert Referenz-Audio wortgenau.

## Halbsatz-Wache + Termin-Auskunft (W-HALBSATZ 29.08.2026 — nicht rückbauen)

Live 09:34: „Hallo, ich habe nächste Woche Dienstag ein" — das Stille-Zugende
(350-650 ms) schnitt in der Denkpause; Bianca beantwortete den halben Satz,
verstand nur „Termin" und lief in die NEUBUCHUNG (schonmal-Frage) statt zur
Frage nach dem BESTEHENDEN Termin. Der Anrufer setzte dreimal an und legte auf.

- **Halbsatz-Wache** (`kern/halbsatz.py`, Einhängung `kern/dienst.zug_stream`
 NACH der Transkription, VOR Fluss/LLM — gilt für Lisa UND Bianca): klingt
 das Gehörte unfertig (Komma-/Gedankenstrich-Ende oder hängendes
 Funktionswort: Artikel, Konjunktion, Präposition, Hilfsverb), antwortet die
 Stimme NICHT. Das Dock bekommt `{"type":"warte","stilleMs":900}`: kein Ton,
 kein Füller, Watchdog aus, weiterhören mit 900 ms Ruhe-Schwelle. Der
 nächste Zug wird SERVERSEITIG an das gemerkte Fragment gefügt (Protokoll
 und LLM sehen den ganzen Satz). Deckel: max. 2 Verlängerungen pro Satz.
 NIE gehalten: Ziffern-Züge (Nummern-Diktat hat seine Teil-Logik). NIE
 verschluckt: ein leeres Nach-Transkript beantwortet das Fragment direkt,
 und der Stille-Stups (`/api/stille`, beide Server) flusht es als echten
 Zug. Notaus: `SATZ_HOLD=0`. Tests: `tests/test_halbsatz.py`.
- **Termin-Auskunft statt Zwangs-Buchung** (`bianca/gehirn._AUSKUNFT_RE`):
 „ich habe <Zeitangabe> … einen Termin" (Feststellung ohne Wunsch-Wörter wie
 brauche/hätte/Zeit/Urlaub/Schmerzen) und „… Termin … weiß nicht (mehr)"
 schalten auf `modus=auskunft` — auch mitten in einer schon angelaufenen
 Buchung. Dann übernimmt `bianca/verwalten.py`: Name erfragen →
 agentFindPatientAppointments → Termin VORLESEN („Ihr nächster Termin: …")
 mit Verschieben-/Absagen-Angebot. Wunsch-Sätze bleiben Neubuchung
 (`test_auskunft_erkennung_*` in test_bianca_bausteine).
- **Dock-Fix nebenbei:** `leseZug` übernahm `stilleMs` aus NDJSON-Antworten
 nie — die W-TEMPO-Schwellen (350/650) kamen im Stream-Pfad still nicht an.
 Jetzt kopiert der reply-Zweig das Feld (beide Docks, Cache-Buster b14/call31).

## Termin-Suche Absagen/Verschieben (W-SAMMELN 29.08.2026 — nicht rückbauen)

Chef: "darin liegt die kunst erstmal alle daten pö a pö aufzusammeln und dann
zu suchen." Vorher fragte Bianca bei absagen/verschieben sofort den Namen und
las bei mehreren Treffern stur die Liste vor. Jetzt sammelt
`bianca/verwalten.py -> _sammeln` (gleiche Prozedur für BEIDE Anliegen):

1. **WANN ist der Termin?** (frage=wann). Klare Antwort (Wochentag, Uhrzeit,
 "nächste Woche", Datum — `parse_slot_wish`) wird `verwHinweis` und filtert
 die Treffer (`_hinweis_passt`: Datum/Wochentag/Stunde ±1 h/Tageszeit).
 Zeitangabe schon im Einstiegssatz ("Termin am Donnerstag absagen") =
 Frage übersprungen; beim Verschieben trennt `_ALT_REF_RE` das am/vom-Stück
 (alter Termin) vom auf/zu-Stück (Neu-Wunsch), und die Wann-Antwort läuft
 über einen Schnappschuss (`verwWunschAlt`) NIE in den Neu-Wunsch.
 Antwortet der Anrufer stattdessen mit dem Namen -> kein Nachbohren
 (verwWann=uebergangen, direkt weiter).
2. **"Weiß nicht mehr"** (`_UNKLAR_RE`) -> **Behandler-Frage** (frage=arzt,
 einmal, nur bei >= 2 Kalendern): "um nicht in allen kalendern zu suchen" —
 der genannte Behandler filtert über calendarId. "Weiß auch nicht" ist ok,
 dann geht es hilfsweise ohne weiter.
3. **NAME** (bestehende Frage) -> erst DANN `agentFindPatientAppointments`.
4. **Treffer bestätigen mit Anrede** (Chef: "Herr/Frau xy, ja?"):
 "Gefunden — {Termin}. Soll ich den Termin wirklich absagen, Herr Berger?"
 (gehirn.anrede; Vornamen-Wächter/Kartei). Bei Ja löscht
 agentCancelAppointmentById; verschieben bestätigt den Fund und fragt dann
 den Neu-Wunsch (bzw. bietet direkt an, wenn der Wunsch schon fiel).
5. **Mehrere Treffer trotz Hinweisen** -> hilfsweise BEHANDLUNGS-Frage
 (frage=behandlung, einmal, nur wenn die Motive sich unterscheiden;
 `_behandlung_passt` gegen motivName/gemappte motivId) -> danach die
 bekannte Auswahl-Liste (phase=wahl). Bei EINEM Termin, der die Hinweise
 verfehlt: "Zu diesen Angaben finde ich nichts — ich sehe: {…}. Meinen Sie
 den?" (Ja wählt ihn, phase=wahl).
6. **Nicht gefunden** (notFound, keine kommenden Termine oder "Nein" auf die
 Rückfrage) -> ehrlich + ECHTE Notiz: Zeile in `.data/praxis_notizen.jsonl`
 (Zeit, Anliegen, Name, Telefon, Wann-/Behandler-/Behandlungs-Hinweis),
 `sit["praxisNotiz"]` (Dock "Letzter Anruf" zeigt sie, session._mit_sammler),
 merke_tool `praxis_notiz`. Gesprochen: "keine Sorge — ich schreibe eine
 Notiz, und die wird Doktor XY vorgelegt" (arzt_sprechname, sonst "dem
 Praxisteam") + Angebot Neubuchung (frage=neubuchung wie gehabt).

Ein im Anruf schon bestimmter Termin (Auskunft davor, frische Buchung mit
booking.appointmentId, Wahl-Liste) überspringt das Sammeln — nie den Anrufer
ausfragen, was schon klar ist. Die AUSKUNFT bleibt beim alten Weg (Name ->
vorlesen): wer fragt "wann ist mein Termin?", dem beantwortet man das Wann,
statt es zu erfragen. Sammel-Stand räumt `_verw_reset` (nach Storno/Move/
Notiz).

**Nachtrag W-ABSAGE-NEUSTART (29.08. 11:51, Peter-Müller-Gespräch — nicht
rückbauen):** STT hörte "Peter Möbel", die Suche scheiterte ehrlich — dann
wurde "Nein, ich möchte meinen Termin absagen, Peter Müller." vom Nein-Zweig
der Neubuchungs-Frage verschluckt und das nackte "Ich möchte meinen Termin
absagen." fiel ans LLM, weil `modus` auf "absagen" klebte (`einsammeln`
bewaffnete nur bei Modus-WECHSEL neu). Seitdem:

- `gehirn.einsammeln`: absagen/verschieben bewaffnen auch bei GLEICHEM Modus
  neu, wenn `phase == "fertig"` (Anliegen war abgeschlossen); eine
  Auskunfts-Frage nach fertigem absagen/verschieben schaltet auf auskunft.
- `verwalten._nicht_gefunden` setzt `verwNotFound`; der nächste Neustart der
  Sammel-Prozedur erfragt Name/Kartei FRISCH (haeufigste Fehlerursache ist
  der verhörte Name) statt stur dieselbe Sackgasse zu suchen.
- `_ABSAGE_RE` versteht die Sprech-Varianten: stornieren, canceln (alle
  Formen), löschen/streichen/aufheben/rückgängig/entfernen (nur MIT
  Termin-Bezug im Satz — "Nummer löschen" ist keine Absage), "Termin fällt
  aus" (nur Termin-Subjekt — "mir fällt ein Zahn aus" nicht), "platzen
  lassen", "nicht wahrnehmen/kommen/schaffen/einhalten", Substantiv "Absage".
- Die Verwaltungs-Fragen tragen jetzt Wächter-Varianten: `FRAGE_VARIANTEN`/
  `_FRAGE_KERN` um "wann", "behandlung", "neubuchung" ergänzt — beim
  Neustart im selben Anruf formuliert der Wiederholungs-Wächter die Frage
  um, statt sie zu streichen (live blieb sonst nur "Das machen wir." und
  beim zweiten "nicht gefunden" fehlte die Neubuchungs-Frage, obwohl der
  Zustand auf ihre Antwort wartete).
- Tests: `test_absage_varianten_erkannt`, `test_absage_verben_ohne_termin_
  bezug_zuenden_nicht`, `test_absage_neustart_nach_notfound_mit_
  namenskorrektur` (Live-Gespräch wortgleich), `test_absage_wiederholt_
  nach_abschluss_startet_neu`. Tests: `test_absage_fluss_komplett`, `test_absage_hinweis_im_
einstiegssatz_ueberspringt_wann`, `test_absage_name_statt_wann_antwort`,
`test_verwaltung_kein_termin_gefunden`, `test_verwaltung_hinweis_passt_
nicht_ehrliche_rueckfrage`, `test_verwaltung_wahl_nein_fuehrt_zu_notiz`,
`test_verwaltung_behandlung_grenzt_ein`, `test_verwaltung_behandler_
filtert_kalender`, `test_verschieben_alt_neu_trennung`,
`test_verschieben_fluss_komplett` (Dock-Buster b15).

## Praxisgedächtnis (W-GEDAECHTNIS 29.08.2026 — nicht rückbauen)

Chef: "schreiben bianca und lisa reports in das MAS gedächtnis? die müssen
geschrieben werden als Gesprächszusammenfassung ähnlich wie in dem
terminpopup ... das muss sichergestellt sein ab jetzt und bianca muss prüfen
ob irgendetwas im kontext vorliegt während sie mit dem user spricht ... im
Hintergrund". Modul: `kern/gedaechtnis.py`, gilt für BEIDE Stimmen.

- **Report am Gesprächsende:** die hangup-Nacharbeit (läuft schon als
  Daemon-Thread) postet EIN Event an `POST {MAS_URL}/brain/events` — Kanal
  `bianca_call`/`lisa_call` (im MAS-Schema vorgesehen), idempotente Id
  `telefonki:<kanal>:<sessionId>`, Zusammenfassung im Terminpopup-Stil
  ("Laut Anruf (Bianca): Martin Berger — Termin vereinbart am 02.09. um
  09:00 Uhr bei Dr. Patrikis wegen Zahnschmerzen." + `notes.besondere_zeilen`).
  Eine offene Rückruf-Notiz (W-SAMMELN) macht das Event `open` +
  `callbackRequested` → das MAS legt daraus einen VORGANG an und legt ihn
  der Praxis vor ("die Notiz wird Doktor XY vorgelegt" ist damit echt);
  erledigte Anrufe sind `status=none` (kein Ticket). Leere Gespräche (kein
  Anrufer-Wort, kein Werkzeug) schreiben nichts.
- **Kontext während des Gesprächs:** sobald Name oder Telefon feststehen
  (`kontext_anstossen`, key-gesichert — Bianca: `hintergrund.anstossen` +
  `agent.user_turn`; Lisa: `start_reply` + `user_turn`), fragt ein
  Daemon-Thread `GET /brain/caller-context?phone=` (dafür gebauter,
  sprechfertiger Text, 14-Tage-Fenster) bzw. hilfsweise
  `GET /brain/karteikarte?name=` (Events zu max. 3 Zeilen gefaltet) ab →
  `sit["gedaechtnis"]` → Block "PRAXISGEDÄCHTNIS (frühere Kontakte)" in
  beiden System-Prompts. So erkennt Bianca z. B. den Rückrufer, den Lisa
  gestern nicht erreicht hat, statt bei Null anzufangen.
- **Ziel/Auth:** `MAS_URL` (Default `http://127.0.0.1:4000`), Header
  `X-Client-Id` = `MAS_CLIENT_ID` (Firebase-Mandant der Praxis, Default
  `MEe4ZQHEzOPzLcexyhdT`), optional `X-Service-Token` aus `MAS_TOKEN`
  (peek auf die MAS-.env `MAS_SERVICE_TOKEN` — nur nötig, wenn das MAS
  Auth erzwingt). `/health` beider Dienste zeigt `gedaechtnis`.
- **Nie blockierend:** Report im hangup-Thread, Kontext in eigenen
  Daemon-Threads; Fehler werden geloggt und verschluckt — das Telefonat
  leidet nie. Das lokale Sitzungs-Gedächtnis (`.data/*_sessions`,
  last_call, praxis_notizen.jsonl) bleibt unverändert bestehen.
- **Notaus:** `MAS_GEDAECHTNIS=0` (oder leere `MAS_URL`) => kein Netz,
  Verhalten wie vor W-GEDAECHTNIS. Tests: `tests/test_gedaechtnis.py`.

## Anruf-Mitschnitt + Anrufliste (W-MITSCHNITT 30.08.2026 — nicht rückbauen)

Chef: nach Anrufen bei Bianca soll der Browser eine Liste der Unterhaltungen
zeigen — mit Audio, Transkript und allen Zeiten (wie im phone_agent-Portal).
Modul `kern/mitschnitt.py`, gilt für BEIDE Stimmen.

- **Ablage:** `.data/anrufe/<stimme>/<sessionId>/` — `anruf.json` (Manifest)
 plus Audio je Zug: `zNNN_anrufer.*` (Dock-Aufnahme webm/m4a, SIP-WAV) und
 `zNNN_stimme[_i].wav` (gesprochene Antwort inkl. P5-Vorab-Sätze in
 Reihenfolge). Jeder Zug wird SOFORT geschrieben (kein 24er-Deckel, Absturz
 verliert höchstens den laufenden Zug); Kopfdaten (patientName, lastBook/
 Cancel/Move/Note, praxisNotiz, tools) frischt jeder Flush auf.
- **Zeiten je Zug:** ISO-Zeitstempel + offsetMs seit Anrufbeginn + die
 timings (stt/llm/tts/total) des Zugs; Manifest trägt startedAt/endedAt/
 dauerMs.
- **Einhängung (kern/dienst.py):** `mitschnitt.eingang()` nach erfolgreichem
 STT im Zug-Strom (W-HALBSATZ: mehrere Aufnahmen hängen als Liste am EINEN
 Zug), `mitschnitt.zug()` am Ende von `json_antwort` und `weiter_sprechen`;
 die Stille-Stupse melden beide Server selbst. Stream-Audio (Phase 2) ist
 beim Zug-Ende oft noch nicht fertig: der Eintrag hält die URL als "offen",
 jeder Flush und die Hangup-Nacharbeit (`mitschnitt.ende`, wartet bis 10 s)
 lösen sie über `Dienst.audio_bytes_fertig()` ein (geschlossener
 WAV-Header, nicht der offene Stream-Header).
- **Vorab-TEXT-Züge (W-TEMPO):** das Bianca-Dock schickt den Zug jetzt als
 text+audio an `/api/listen` statt nackt an `/api/turn` — der Server nutzt
 weiter den Text (kein zweites STT), archiviert aber das Anrufer-Audio.
- **Browser:** Biancas Dock trägt den Kopf-Link **„Anrufe"** → `/anrufe`
 (`bianca_web/anrufe.html` + `anrufe.js`, relative Pfade — läuft auch
 hinter Lisas `/bianca/`-Durchreiche). Liste (Zeit, Dauer, Name, Ergebnis-
 Marke) + Gespräch (Blasen mit Abspiel-Knöpfen je Zug, Timing-Chips,
 „Anruf abspielen" spielt alles in Reihenfolge, Löschen-Knopf).
- **Routen (bianca/server.py):** `GET /api/anrufe`, `GET /api/anrufe/{sid}`,
 `GET /api/anrufe/{sid}/audio/{datei}` (Dateinamen-Whitelist, kein
 Traversal), `POST /api/anrufe/{sid}/loeschen`. Lisa zeichnet über
 dieselben Kern-Hooks auf (`.data/anrufe/lisa/`), hat aber noch keine
 eigene Seite.
- **Nie blockierend:** alle Schreibwege fangen Fehler und verschlucken sie —
 der Anruf-Pfad leidet nie. Notaus: `MITSCHNITT=0` => kein Ordner, kein
 Byte. Tests: `tests/test_mitschnitt.py`.

## Stille-Garantie (W-STILLE 29.08.2026 — nicht rückbauen)

Chef: "es darf NIE zum Schweigen kommen … nie länger als 1,5 Sekunden …
es darf nie das Gefühl gegeben werden, dass die KI abgestürzt ist."
Zwei Verteidigungslinien, beide Stimmen:

- **Server-Füller nur bei Kalender/Werkzeug** (29.08. abends, Chef: auf
  „wie heißt du" kam „einen Moment, ich schaue eben nach"): Der 0,9-s-
  Allgemein-Füller gewann nach P5 das Rennen gegen den echten ersten
  Satz und behauptete ein Nachschauen, das nicht stattfand. `frist_setzen`
  feuert jetzt NUR noch nach `filler.vermutet()` (Kalender/Akte) oder
  echtem `melde()`; Plauder- und Maschinen-Züge warten auf Vorab-Satz
  oder Antwort. Hängt der Server, spricht der Dock-Watchdog eine
  **neutrale** Ansage. `_ALLGEMEIN` behauptet kein Nachschauen mehr
  („schaue nach" ist raus). Identität/Smalltalk (`_RE_PLAUSCH`) nie
  Kalender-Füller.
- **Füller-Nachschub:** steht die Antwort nach einem Füller weiter aus,
  spricht alle `FILLER_NACHSCHUB_S` (2,4 s, gerechnet ab Füller-BEGINN,
  Audio ~1,2 s => Lücke < 1,5 s) der nächste rotierte Satz — Deckel
  `FILLER_MAX` (3). Inhalt (Vorab-Satz, `sag:`-Ansage, festes Audio)
  beendet die Kette; ein Werkzeug-`melde()` nach einem Warte-Füller
  schärft nur die Gruppe des NÄCHSTEN Nachschubs (nie zwei direkt
  hintereinander).
- **Dock-Watchdog (zweite Linie, greift auch bei totem Server/Netz):**
  beide Docks laden beim Boot `GET /api/notfall`
  (`dienst.NOTFALL_SAETZE`, 3 Eskalationsstufen bis "bleiben Sie dran")
  als **BLOB** vor. Nach dem Sprechende des Anrufers (`wachtStart` in
  `hoeren`) prüft ein 150-ms-Tick: lief `WACHT_MS` (1,4 s) kein Ton
  (`kiSpricht`/`lisaSpricht`), spielt die nächste lokale Ansage über ein
  EIGENES Audio-Objekt — die playUrl-/Füller-Kette bleibt unberührt, bei
  echtem Ton oder Barge (`stopVoice`/`stopLisaVoice`) verstummt sie
  sofort. Max. `WACHT_MAX` (3) Ansagen je Zug. Ein Netz-/Serverfehler im
  `sendeZug`-catch spielt hörbar die Dran-bleiben-Ansage (`wachtNot`)
  statt still zu scheitern.
- Tests: `tests/test_stille_notfall.py` (Frist gilt überall, Nachschub
  rotiert bis Deckel, Produktions-Fristen halten die 1,5-s-Regel).
  Live-Probe 29.08.: LLM-Plauderzug — Füller nach 0,92 s, Vorab-Satz
  2,71 s, Antwort 3,43 s; `/api/notfall` liefert je 3 URLs (8095/8096).

## Readback-Parallelisierung (P1 29.08.2026 — nicht rückbauen)

Nummern-Rückbestätigung als DREI Sätze (`gehirn.readback_text`): gewärmter
Vorsatz „Ich wiederhole die Nummer." spielt SOFORT aus dem Pin-Cache,
während der Feeder den Ziffern-Satz blocking rendert und der Nachhör-
Wächter ihn verifiziert; Schlussfrage „Stimmt das so?" ebenfalls gewärmt.
`stimme_stream` lohnt den Strom trotz Cache+Ziffern, WENN der erste Satz
sofort lieferbar ist — beginnt der Text direkt mit dem Ziffern-Satz,
bleibt der bewährte Blocking-Pfad. Sicherheit unverändert (Ziffern nie
am Wächter vorbei). Tests: `test_readback_text_ist_dreisatzform`,
`test_stimme_stream_readback_vorsatz_spielt_sofort`.

## Speculative Decoding (P4 29.08.2026 — geprüft, nicht umgesetzt)

Gemessen auf der 5090: vLLM 25,6 GB + Qwen3-TTS 4,9 GB = 30,5 / 32,6 GB.
Ein Draft-Modell (Qwen 0,6B, ~1,5–2 GB) passt neben TTS nicht, ohne das
35B-Fenster oder den Hybrid-Mund zu gefährden. Alle Worker (Clara, Demo,
Lisa, Bianca) sprechen denselben Qwen-Container auf der 5090
(`:8000/v1`) — auf der 3060 läuft kein 4B/Ollama mehr. N-Gram-
Spekulation bräuchte einen vLLM-Neustart (läuft seit 08.08. mit Prefix-
Cache und `--gpu-memory-utilization 0.70`); ohne Extra-VRAM-Gewinn und
mit Restart-Risiko bewusst gelassen. Wieder aufmachen, wenn TTS von der
5090 weg ist (z. B. 3060, ohne Lena zu verdrängen) oder vLLM ohnehin
neu startet.

## Satzweises LLM→TTS (P5 29.08.2026 — nicht rückbauen)

`chat_stream` meldet JEDEN fertigen Satz (erster Block: 25-Zeichen-Regel,
danach jeder bestätigte Satz) an `erster_satz`. `dienst.vorab` vertont
jeden Satz im eigenen Faden, während der Stream weiterliest — URLs gehen
IN REIHENFOLGE an das Dock (Füller-Kette). Der Rest nach dem gesprochenen
Prefix wird wie bisher als reply-Audio gerendert. Ganze Sätze, kein
Text-Schnitt (Genuschel-Lektion 28.08.). Nur wo Vorab schon erlaubt war
(kein Buchungs-Umbau durch `_nachbessern`). Notaus: `LLM_SATZ_STREAM=0`
=> nur der erste Block wie vor P5. Tests: `test_neue_stream_saetze_*`.

## Satz-Deckel im LLM-Stream (P2 29.08.2026 — nicht rückbauen)

Prompt sagt „höchstens zwei kurze Sätze plus EINE Frage" — Qwen hält sich
nicht immer dran. `kern/llm.chat_stream` schließt den Stream hart, sobald
zwei Sätze plus offene Frage (sonst drei Sätze) stehen — ganze Sätze,
nichts Abgehacktes, Werkzeug-Züge unangetastet. Abkürzungen/Uhrzeiten
(Dr., 13:00) zählen nicht als Satzende. Notaus: `LLM_SATZ_DECKEL=0`.
Tests: `tests/test_llm_deckel.py`.

## Weiterleitung an die Ärzte (W-VERBINDEN 29.08.2026 — nicht rückbauen)

Chef: „wenn der anrufer mit dr petsas oder dr patrikis sprechen möchte oder
sich verbinden lassen möchte musst du doch das jingle abspielen und den
Kiri-grußsatz. momentan verneinst du eine weiterleitung." Live 08:44 rutschten
„Könnte ich bitte mit Doktor Petzers verbunden?" und „Ich möchte verbunden."
an `bianca/weiterleiten.erkannt()` vorbei — das LLM erfand eine Ablehnung
(„Hier spricht man nicht mit den Ärzten am Telefon"), um 07:15 sogar ein
Fake-Verbinden ohne Jingle. Seitdem gilt:

- `_VERBINDEN_RE` kennt die „verbunden"-Formen ohne mich/uns („verbunden
  werden", „ich möchte … verbunden", „mit Doktor X … verbunden"); Preis-/
  Sachfragen („Ist das mit Kosten verbunden?") bleiben bewusst draussen.
- **Namens-Weg:** Behandler-Name (fuzzy über `arzt.deute`, „Petzers"→Petsas)
  plus Sprech-/Verbinde-Verb zählt auch OHNE Doktor-Titel („Kann ich Herrn
  Petsas sprechen?", „… ans Telefon/an den Apparat"); Sätze mit „Termin"
  sind ausgenommen (Buchung bleibt Buchung).
- Mitarbeiter-Wortliste um Chef/Inhaber/Praxisleitung/Boss erweitert.
- **Prompt-Leitplanke WEITERLEITEN** (`bianca/prompt.py`): das LLM lehnt
  Weiterleitungen NIE ab, verbindet nie selbst, fragt nur „Zu welchem
  unserer Ärzte darf ich Sie verbinden?" — und der Rückweg in
  `weiterleiten.zug` wertet nach so einer Rückfrage (letzte
  Assistentin-Zeile, `_RUECKFRAGE_RE`) den blossen Behandler-Namen als
  Zielangabe.
- Tests: Live-Sätze wortgleich in `tests/test_weiterleiten.py`; Live-Probe
  `.data/verbinden_probe.py` (Jingle-URL + Kirri-Zeile + hangup, Preisfrage
  bleibt beim LLM).

## Test-Studio auf der 5090 (W-STUDIO-5090 30.08.2026 — nicht rückbauen)

Chef: „das muss auch auf den server." Das Baukasten-Studio läuft jetzt auch
auf pickadoc1 — Aufruf: `http://100.82.122.62:8096/studio` (durch die
Live-Bianca, KEIN eigener öffentlicher Port; die 8015 aus dem alten
Browser-Tab war nie ein Port dieses Projekts).

- **Image trägt `tests/`** (Dockerfile + .dockerignore: nur Code und
  `editor_web`, die Render-Caches `audio/`/`berichte/` bleiben draußen).
- **Zwei neue Compose-Services** (nur im Compose-Netz, keine Host-Ports):
  `studio` (Editor 8097, `STUDIO_BIANCA_BASE=http://bianca-test:8098`) und
  `bianca-test` (8098) — Testläufe stören NIE die Live-Bianca (8096).
  Die Live-Bianca proxied `/studio/api` über `STUDIO_BASE=http://studio:8097`;
  lokal auf dem Dev-Rechner bleiben beide Defaults 127.0.0.1 (8097/8098).
- **Volumes:** `telefonki-berichte` (Berichte + Autolösch-Schlange, geteilt
  von bianca/bianca-test/studio — der Testtermin-Wächter der Live-Bianca
  sieht die Schlange), `telefonki-klang` (Anrufer-Audio-Cache, Key trägt
  die TTS-Basis — Server rendert eigene WAVs über den 8213-Container).
- Abnahme 30.08.: Story s01-julia-invisalign lief auf dem Server komplett
  durch (gebucht, Motiv/Telefon/Nachname grün, Autolösch-Eintrag 19:05).

## Schaufenster „Das kann ich" (29.08.2026)

Biancas Dock (8096) trägt neben dem Anruf-Knopf den Knopf **„Das kann ich"**:
Overlay mit zwei Reitern — „Können" (alle Fähigkeiten in Klartext: Termine,
Akte/Versicherung/Geschlecht, MAS-Gedächtnis, Gesprächsführung) und „Technik"
(Ohr/Hirn/Mund-Pipelines inkl. Zero-Shot-Voice-Cloning, Live-Zeile aus
`/health`, ALLE Patches/Fixes/Upgrades tabellarisch mit exakten Kürzeln).
Reine Anzeige, kein Einfluss auf den Anruf-Pfad; beim Anruf-Start schließt
sich das Overlay. Daten liegen in `bianca_web/app.js` (`KOENNEN` / `TECHNIK` /
`PATCHES`) — bei neuen Features/Patches dort MITPFLEGEN, sonst lügt das
Schaufenster.

## Fernsteuerung

- Seite: `/fernsteuerung.html` (Handy braucht `#t=…` aus dem lokalen Link).
- Wächter: `tools/lisa_fernsteuerung_watch.ps1` — nur Grok, nur dieser Ordner.
- Kein MAS-Wächter, kein Workspace `F:\`.
