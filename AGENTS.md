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

## Mandant per angerufener Nummer (W-MANDANT 30.08.2026 — nicht rückbauen)

Chef: "anhand der angerufenen nummer müssen wir in der db den passenden
agent laden und somit alle nötigen informationen erhalten" und (später,
wörtlich): "die Konfig und somit die begrüßung MUSS aus der DB kommen!!"
— die DB ist die Wahrheit, lokale Dateien sind nur Rückfall. Der Weg ist
derselbe wie im alten phone_agent: `calledNumber` -> Cloud Function
`onPickadocPhoneCall` (phase=pre) -> Agent samt clientId/locationId/
Kalender/Motive/Begrüßung/Keywords/Prompts. Kette bei uns:

- **Brücke** (`sip_bridge/server.py -> did_von_uuid`): der Dialplan trägt
 je DID eine FESTE AudioSocket-UUID (…4101/…4110/…4120); ihr Hex-Ende wird
 über `BRIDGE_DID_MAP` (Default: alle Live-Nummern) in die E.164-Nummer
 übersetzt und als `did` an `POST /api/start` gemeldet. Neue DID = neuer
 Dialplan-Eintrag mit eigener UUID + Map-Eintrag. Seit 30.08.2026 abends
 auch **+49 211 54244120 = Blessing** (Hautarztpraxis Doktor Blessing,
 Agent samt Begrüßung kommt komplett aus der DB, clientId UUJnPzoYPa4yYyzcaGlm,
 kein lokales tenants-JSON; Asterisk-Backup
 `extensions_bianca.conf.bak-20260830-4120`).
- **Auflösung** (`kern/agentprofil.fuer_did`, in `bianca/server.api_start`)
 — DB ZUERST (Chef 30.08.2026 abends, davor stand die lokale Datei vorn):
 1. Cloud Function (Auth `PICKADOC_PHONE_CALL_API_TOKEN` als Bearer +
 x-api-key, URL `PICKADOC_PHONE_CALL_URL` oder `{CF_BASE}/onPickadocPhoneCall`,
 Token-Peek auf die phone_agent-.env; Quelle des Secrets: Firebase
 `firebase functions:secrets:access PICKADOC_PHONE_CALL_API_TOKEN --project
 docgenda`). **Token-Falle (30.08.2026, live erlebt):** der Wert BEGINNT
 mit `#` und enthält ein `$` — in der Server-.env (Compose env_file +
 Interpolation) MUSS er in EINFACHEN Quotes stehen; doppelt quotiert
 expandiert Compose das `$…` weg (401), unquotiert schneidet `#` alles ab.
 `callerPhone` ist CF-Pflicht — seit W-ANRUFER (30.08.2026 spät, s. u.)
 liefert die Brücke die echte Anrufernummer aus dem UUID-Kopf mit
 (`_cf_pre` normalisiert auf +E164); nur bei unterdrückter Nummer geht
 weiter `anonymous` (kein Patient matcht, der Agent kommt trotzdem). Passt die clientId der Antwort zu einer
 lokalen tenants/*.json, dient die Datei nur als BASIS für Felder, die
 die DB nicht kennt (Sprechformen, wissen; `_quelle=cf+datei`) — die
 DB GEWINNT immer bei: Begrüßung (`begruessungText` = agent.firstMessage,
 Vorrang in `bianca/agent.start_reply`), Kalender, Motive, Keywords
 (gemergt) und dem Agent-Prompt (s. u.). TTL-Cache je Nummer
 (`AGENT_PROFIL_TTL_S`, 300 s; Fehlschläge 60 s negativ) — DB-Änderungen
 greifen also nach max. 5 min; sofort: `POST /api/mandant-cache/leeren`
 (auch ein Container-Neustart leert ihn);
 2. lokaler Mandant, dessen `dids`-Feld die Nummer trägt — NUR Rückfall
 (CF aus, CF down, kein Agent zur Nummer);
 3. nichts gefunden -> DEFAULT_TENANT, der Anruf wird IMMER angenommen.
- **Prompt-Merge (Chef 30.08.2026):** `agentprofil.db_prompt_von_agent`
 baut aus den Agent-Feldern der DB (rolePrompt, tasksPrompt,
 specialFeaturesPrompt, locationPrompt, patientsPrompt, appointmentPrompt,
 referrerPrompt, mandatoryPrompt, miscellaneousPrompt; sind alle leer:
 systemPrompt-Blob) den Praxis-Fakten-Text — gleiche Felder/Überschriften
 wie phone_agent `assemble_persona_instructions`, aber OHNE dessen
 Verhaltens-Vorspann/Tool-Schwanz; `{{current_time}}`-artige Platzhalter
 werden eingelöst. Er landet als `tenant["dbPrompt"]` und wird in
 `bianca/prompt.system_prompt` als Block "PRAXIS-PROFIL … ENDE
 PRAXIS-PROFIL" gemerged, samt Leitplanke: bei Widerspruch gelten die
 Verhaltensregeln des festen Prompts, Tool-/Skript-Namen aus dem Profil
 nie ausführen/aussprechen. Der FESTE Prompt ist seitdem praxis-neutral
 (keine echten Behandler-/Orts-Namen mehr — das Petsas/Patrikis-Beispiel
 ist raus); das VERHALTEN (Buchungsweg, Gesprächsregeln, Wächter) bleibt
 hart im Code/Prompt, die Praxis-FAKTEN kommen aus der DB.
- **Session:** `session.neu(tenant=…)` nimmt das fertige Dict; CF-Mandanten
 werden MIT Tenant-Blob persistiert (kein lokales JSON zum Nachladen).
 Das MAS-Gedächtnis läuft seitdem unter der clientId des SITZUNGS-Mandanten
 (`gedaechtnis._client_id`), Fallback bleibt `MAS_CLIENT_ID` (= meddent).
- Docks unverändert (Dropdown sendet weiter `tenant`); `did` schlägt
 `tenant`, wenn beides kommt. Health zeigt `mandant`.
- **Notaus:** `DID_AGENT=0` => kein CF-Lookup (lokale `dids` gelten weiter).
 Tests: `tests/test_agentprofil.py`.
- **Call-Status + Zusammenfassung (W-CALLSTATUS 30.08.2026):** Chef: "wenn
 der call beendet ist muss die entsprechende cloud function aufgerufen
 werden, dann wird der status auf aufgelegt oder so aehnlich gesetzt und
 eine zusammenfassung erstellt." Die pre-Phase legt je Anruf einen
 PhoneCall-Datensatz an (inProgress); `agentprofil.call_erfassen` (in
 api_start) holt dessen phoneCallId in die SITZUNG — bei Cache-Treffern
 registriert ein Daemon-Thread den Anruf nach (die Begruessung wartet nie
 auf die CF); die phoneCallId wird NIE mitgecacht. Nach dem Auflegen sendet
 `agentprofil.call_abschliessen` (hangup-Nacharbeit, NACH mitschnitt.ende)
 `phase=post` (Status -> callCompleted = "aufgelegt", Transkript aus dem
 Mitschnitt-Manifest mit timeInCallSecs aus offsetMs, Dauer, endReason,
 harte Kategorien: appointment/cancellation/callbackRequest aus lastBook/
 lastMove/lastCancel/praxisNotiz) und `phase=analysis` (summary + weiche
 Kategorien + Bewertung per LLM-Analyse wie phone_agent call_analysis,
 lokales vLLM; ohne Anrufer-Zeile oder bei LLM-Fehler deterministischer
 Rueckfall: `gedaechtnis.zusammenfassung`, Zufriedenheit 3/unknown).
 **CF-Falle (live erlebt 30.08.2026):** die analysis-Phase baut IMMER ein
 evaluation-Update; fehlen Bewertungsfelder im Request, stehen dort
 undefined-Werte, der Firestore-Write wirft und `updatePhoneCall` faengt
 den Fehler still — die CF meldet trotzdem success und der Datensatz
 bleibt ohne Summary. Deshalb belegt `_cf_evaluation` JEDES Feld
 (toolError/Details deterministisch aus sit["tools"]). Nur fuer
 CF-Mandanten (`_quelle=cf*`) — Dock-Anrufe ohne DID und Datei-Mandanten
 schreiben nichts. Nie werfend, nie auf dem Anruf-Pfad.
- **Anrufernummer im Portal (W-ANRUFER 30.08.2026 — nicht rückbauen):**
 Chef: im Portal stand überall "Unterdrückte Nummer" statt Nummer + Name des
 Bestandspatienten. Ursache: AudioSocket übergibt der Brücke NUR die UUID —
 die Anrufernummer (laut Asterisk-CDR sehr wohl da, Zaluma-Format
 `004915…`) ging verloren, `_cf_pre` sendete pauschal `anonymous`, die
 CF-Patientensuche lief leer. Fix ohne neuen Kanal: der Dialplan
 (`extensions_bianca.conf`, Referenzkopie im Repo unter `sip_bridge/`,
 Backup `.bak-20260830-anrufer`) packt die CALLERID-Ziffern (FILTER 0-9 —
 Ziffern sind gültige Hex-Zeichen) RECHTSBÜNDIG in die ersten 20 Hex-Zeichen
 der AudioSocket-UUID, links mit `f` gepolstert; das UUID-ENDE bleibt die
 feste DID-Kennung (…4101/…4110, `did_von_uuid` unverändert). Die Brücke
 (`caller_von_uuid`) akzeptiert den Kopf NUR, wenn nach dem f-Polster >= 5
 reine Ziffern stehen — alte feste UUIDs (`b1a2ca00…`), Zufalls-UUIDs der
 Proben und reines f-Polster (unterdrückte Nummer) geben "" und damit
 `anonymous` wie bisher. Weg: UUID -> `/api/start` (Feld `caller`, gab es
 schon) -> `agentprofil._cf_pre` normalisiert via `tenants.nummer_norm` auf
 `+E164` (CF trimPhoneNumber matcht Patienten über `+49…`) -> PhoneCall
 trägt Nummer + Patient (Name/Geschlecht/Geburtsdatum) wie beim alten
 phone_agent. Gilt für Cache-Treffer genauso (call_erfassen reicht caller
 an die Hintergrund-Registrierung durch). Tests:
 `test_bruecke_liest_anrufer_aus_uuid_kopf`,
 `test_cf_pre_normalisiert_anrufer_auf_e164` (test_agentprofil).
- **Anruf-Audio im Portal (W-CALLAUDIO 30.08.2026 — nicht rückbauen):**
 Chef: die Portal-Anrufliste (CallR) muss das Gespräch abspielen können —
 früher setzte die ElevenLabs-CF `audioRecordingUrl` (MP3 im Firebase
 Storage), seit Bianca die Anrufe hält, lud niemand mehr Audio hoch.
 `kern/anrufaudio.py` baut in der hangup-Nacharbeit (NACH mitschnitt.ende,
 in call_abschliessen) den kompletten Anruf aus dem Mitschnitt
 (`mitschnitt.anruf_wav`), kodiert per ffmpeg zu MP3 (64 kbit mono; ohne
 ffmpeg WAV-Rückfall) und lädt ihn auf EXAKT den alten CF-Pfad
 `clients/{clientId}/locations/{locationId}/phoneCalls/{phoneCallId}.mp3`
 (Bucket `docgenda.appspot.com`); die Download-URL (getDownloadURL-Form mit
 firebaseStorageDownloadTokens) geht als `audioRecordingUrl` im post-Payload
 mit — die CF speichert sie, das Portal-`<audio>` spielt sie. Auth:
 Service-Account-JSON -> selbstsigniertes RS256-JWT -> OAuth2 (cryptography
 + httpx, KEIN google-auth-Stack); Key-Suche: `FIREBASE_CREDENTIALS`, dann
 `secrets/docgenda-service-account.json` (Compose mountet `./secrets` ro,
 Quelle: docgendaweb/functions/docgenda-635adf3e6507.json), dann Peek auf
 die phone_agent-.env. Nur für CF-Mandanten (gleiche Gates wie post:
 phoneCallId+clientId+locationId), nie werfend, nie auf dem Anruf-Pfad.
 Notaus: `CALL_AUDIO_UPLOAD=0`. Health zeigt `anrufAudio`. Tests:
 `tests/test_anrufaudio.py`; Live-Probe (echter Bucket, räumt auf):
 `python -m tests.anrufaudio_probe` — 30.08. grün. ROLLOUT-PFLICHT auf
 pickadoc1: Key nach `/home/cursor/telefonki/secrets/` kopieren + App-Image
 neu bauen (requirements trägt jetzt cryptography).
- **Nebenbefund 30.08.:** nemo_toolkit (Rest des verworfenen NeMo-Versuchs)
 legt ein top-level `tests`-Paket in die site-packages und überdeckte
 unseren `tests/`-Ordner (lauf_bianca und der Autolösch-Import in
 bianca/server.py liefen auf ModuleNotFoundError). Fix: `tests/__init__.py`
 macht den Repo-Ordner zum regulären Paket — der gewinnt die Auflösung.

## Erkannten Anrufer vorlesen statt erfragen (W-ANRUFER-CHECK 31.08.2026 — nicht rückbauen)

Chef: "wenn jemand anruft und seine nummer mitsendet und wir den dann in
unserer db finden als patient, dann wäre es besser den namen und die
telefonnummer bei der buchung oder beim absagen vorzulesen als kontrolle
anstatt das nochmal zu erfragen. nur wenn der patient das nicht bestätigt,
dann erst nach namen und nummer fragen."

- **Ernte** (`kern/agentprofil._anrufer_von_pre`): die CF-pre-Antwort trägt
 `patient` (id/firstName/lastName/fullName/gender/birthDate — gleiche Felder
 wie phone_agent `patient_from_pre`), wenn trimPhoneNumber die callerPhone
 einem Patienten zuordnen konnte. Der Treffer liegt transient als
 `t["_anrufer"]` am Tenant und wird wie `_phoneCallId` NIE gecacht (der
 nächste Anrufer auf der DID ist ein anderer Mensch); `call_erfassen` holt
 ihn samt +E164-Anrufernummer in die Sitzung (`sit["anrufer"]` =
 {vorname, nachname, patientId, geschlecht, geburtsdatum, telefon}) — auch
 auf dem Cache-Treffer-Pfad (Hintergrund-Registrierung reicht nach). Ohne
 echte Nummer (anonymous) nie; Docks haben das Feld nie.
- **Buchung** (`gehirn.naechste_frage`, VOR der schonmal-Frage): steht ein
 Treffer und ist noch kein Name gefallen, kommt EINMAL
 `frage=anrufer_check` (`gehirn.anrufer_check_frage`: "Ich habe Sie an
 Ihrer Rufnummer erkannt: {Name}, unter {Ziffern}. Stimmt das so?").
 Ja (`einsammeln`): Name in Kartei-Schreibweise (buchstabiert=True,
 bekannt=True, patientId), Geschlecht als Quelle "akte", Telefon gilt als
 rückbestätigt (telefonOk), warSchonMal=True — schonmal-, Namens-,
 Buchstabier- und Telefon-Frage entfallen komplett; die Hintergrund-Kartei
 reichert wie gehabt an (aktePhone/letzterBesuch/Versicherung → Rückblick/
 PZR laufen normal). Nein: Treffer verworfen (anruferCheck="nein", kommt
 nie wieder), klassische Fragen wie vor dem Patch. NIE gefragt: bei
 `fuerWen` (Termin für Dritte) oder warSchonMal=False (Angehöriger am
 selben Anschluss); ein Kind, das den Hörer der Mutter nutzt, verneint.
- **Absage/Verschieben/Auskunft** (`verwalten._sammeln` bzw. Auskunfts-Zweig
 in `verwalten.zug`): dieselbe Frage ersetzt die Nachnamen-Frage; ein Ja
 sucht SOFORT mit Kartei-Name, patientId und Anrufernummer
 (`agentFindPatientAppointments` bekommt phone=callerPhone mit).
- **Deterministisch wie telefon_check:** die Frage trägt Ziffern
 (Wiederholungs-Wächter fasst sie nie an, TTS-Ziffern-Wächter verifiziert
 den Render), Antwort-Leerlauf bleibt beim festen Text ("Habe ich Sie
 richtig erkannt? Ein kurzes Ja oder Nein genügt."), zwei unklare Antworten
 => `flow._eskalieren` verwirft den Treffer (Sicherheit vor Tempo — nie
 eine Identität raten). Kurze Ruhe-Schwelle 350 ms (`_STILLE_KURZ`),
 Frage-Kern in `agent._FRAGE_KERN["anrufer_check"]`.
- **Notaus:** `ANRUFER_CHECK=0` (gehirn.anrufer_bekannt liefert {}) =>
 Verhalten wie vor dem Patch. Tests: W-ANRUFER-CHECK-Blöcke in
 `tests/test_bianca_bausteine.py` (Buchung ja/nein, Neupatient/Dritte,
 Absage, Auskunft, Eskalation) und `tests/test_agentprofil.py`
 (Ernte, +E164, nie im Cache, Nachreichen beim Cache-Treffer).

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
     jeden frischen Render gegen (~0,4 s); weicht die Ziffernfolge vom Soll
     ab (fehlende ODER Extra-Ziffern — 30.08.2026 live: Engine haengte
     '…4600 46' an, der alte Substring-Vergleich liess das durch), wird neu
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
- **Start-Ruhe (W-START-RUHE 31.08.2026):** Chef: "manchmal hackt es am
 anfang oder der agent spricht schon aber die leitung steht noch gar nicht
 ... und es klingt eh natürlicher, wenn der nicht sofort abnimmt." Zwischen
 Abheben (UUID-Rahmen) und Begrüßung liegt jetzt MINDESTENS
 `BRIDGE_START_RUHE_S` (Default 1,0 s, compose reicht durch; 0 = aus) —
 die Laufzeit von `/api/start` (CF-Mandanten-Lookup) wird angerechnet,
 gewartet wird nur der Rest. Nur die Brücke; Docks unverändert.
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
- **Codec-Verzerrer behoben (W-SIP-SLIN 30.08.2026 — nicht rückbauen):**
 Anrufer über µ-law-Zubringer klangen „richtig übel verzerrt": der
 AudioSocket-KANALTREIBER (`Dial(AudioSocket/…)`) handelt den nativen
 Codec aus und reichte G.711 roh durch; die Brücke riet das Format nur
 über die Frame-Länge (160 B = alaw) — µ-law hat aber GENAUSO 160-Byte-
 Frames und wurde mit der A-law-Kennlinie dekodiert. Rauchende Pistole
 in den Logs: konstanter `floor≈880` (µ-law-Stille 0xFF als alaw gelesen
 = +848; echte A-law-Anrufe hatten floor≈60). Fix an der URSACHE:
 `extensions_bianca.conf` nutzt für beide DIDs die AudioSocket()-
 **APPLIKATION** (`AudioSocket(<uuid>,127.0.0.1:40101)`) statt Dial —
 sie zwingt den Kanal auf slin, Asterisk transkodiert selbst, die Brücke
 bekommt IMMER slin (320-B-Frames, Log `bruecke-format slin`). Der
 alaw-Zweig in `_eingang` bleibt nur als Rückfall für einen alten
 Dialplan. Backup: `extensions_bianca.conf.bak-20260830-slin`. Der
 Asterisk (Alias `asterisk-strato`) ist vom Dev-Rechner nur über
 ProxyJump erreichbar: `ssh -J pickadoc1 asterisk-strato` (Port 22 lässt
 nur pickadoc1 durch). Vermutlich erklärt derselbe Verwechsler auch den
 früheren „~1 % Clipping"-Nebenbefund und STT-Verhörer wie „Zermin".
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
  **W-REPEAT 01.09.2026:** nie `or text` — sind alle Varianten verbrannt,
  kommt Presence („Sind Sie noch dran?"), nicht der Originalwortlaut
  zurück; Varianten auch für `anrufer_check`/`rueckblick`. Dazu
  `kern/antwort_wache.py` (phone_agent-Gates: eine Identitätsfrage/Zug,
  Re-Greeting streichen). Tests: `tests/test_wiederholung.py`,
  `tests/test_antwort_wache.py`.
- **Stille-Wächter** (`kern/stille.py`, 27.08.2026 — nicht rückbauen): meldet
  das Dock ~4 s Funkstille (`STUPS_NACH_S`, gemessen in `web/app.js` und
  `bianca_web/app.js` nach dem eigenen Sprech-Ende), ergreift die Stimme
  selbst das Wort: `POST /api/stille` -> `agent.stille_zug` (deterministisch,
  ohne LLM, ohne Kalender). Gehirn an, nie bei null — aber auch nie als
  Sermon (**W-STUPS-PRESENCE 01.09.2026**, phone_agent: Silence = Presence,
  nicht Frage-Wiederholung — ersetzt W-STUPS-KURZ): Biancas ERSTER Job-Stups
  ist NUR Presence („Sind Sie noch dran?"), der ZWEITE die kurze offene
  Frage (Variante/Präfix), kein Stand-Sermon; `telefon_check` bleibt
  kurz→Ziffern wie gehabt. Denk-Cue („Moment", „überlegen") unterdrückt
  Stups ~7 s. Lisa unverändert mit Auftrag + „Meine Frage war:"-Präfix.
  Max. `MAX_STUPSE` (2) Stupse in Folge, dann Schweigen; jedes echte
  Gehörte setzt zurück (`stille.reset` in beiden `user_turn`, Zähler auch
  im Dock). Jeder Stups läuft durch den Wiederholungs-Wächter — nie
  wortgleich. Tests: `tests/test_stille.py`.
- **Buchungs-Retry-Deckel** (W-BOOK-RETRY 01.09.2026 — nicht rückbauen):
  live „Termin ist gerade weg" ×5–10 (Rebrovic/Papiert). Max. **2**
  `slotTaken`-Fails → Rückruf-Notiz, kein neuer Slotwahl-Loop;
  gescheiterte ISOs in `sit["slotGesperrt"]` nie wieder anbieten; nach
  erstem Ja+Fail Alternativ-Slot **ohne** zweites „Dann halte ich fest…".
  `yeah`/`yea` zählen als Ja; „gleich"/"heute noch" auf die Wunschfrage
  setzen Datum=heute. book_slot-Fails loggen calendarId/Motiv/ISO.
  Tests: Book-Retry-/Yeah-/Wunsch-Blöcke in `tests/test_bianca_bausteine.py`.
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

## Termin-Suche Absagen/Verschieben (W-SAMMELN 29.08. / W-NACHNAME 31.08.2026 — nicht rückbauen)

Chef 31.08.2026 (nach dem Tzannes-Anruf 09:50: "Wie ist Ihr Vor- und
Nachname?" nervte, die Suche scheiterte, der Fluss rutschte in die
Neubuchung): "der soll nur nach dem nachnamen fragen und dann erstmal sehen
ob er einen termin findet. findet er mehrere termine mit gleichem nachnamen
und unterschiedlichen vornamen dann soll er nach dem vornamen fragen." —
wie der alte phone_agent (`findPatientAppointments`: required nur lastName).
Die Wann-zuerst-Sammelei von W-SAMMELN ist damit AUSGEBAUT; geblieben sind
Hinweis-Filter, Anrede-Bestätigung, Behandlungs-Frage, Auswahl-Liste und
Notiz-Weg. `bianca/verwalten.py -> _sammeln` (BEIDE Anliegen):

1. **NUR der NACHNAME** (frage=nachname; Absage/Verschieben laden direkt zum
 Buchstabieren ein: "Wie ist Ihr Nachname? Buchstabieren Sie ihn am besten
 gleich einmal." — Chef 31.08.2026, der verhoerte Nachname ist die
 haeufigste Fehlsuchen-Ursache; frage=nachname zaehlt seitdem als Diktat:
 `_STILLE_DIKTAT` 1500 ms statt 500) -> SOFORT
 `agentFindPatientAppointments` (lastName reicht; vorhandener Vorname/
 Anrufer-Telefon gehen mit). Sagt der Anrufer den vollen Namen, erntet
 `gehirn._name_aufnehmen` auf die Nachnamen-Frage BEIDE Teile. Freiwillige
 Angaben werden weiter geerntet und filtern die Treffer, nur VORAB gefragt
 wird nichts mehr: Zeitangabe im Einstiegssatz ("Termin am Donnerstag
 absagen" — `parse_slot_wish`) wird `verwHinweis` (`_hinweis_passt`:
 Datum/Wochentag/Stunde ±1 h/Tageszeit), ein genannter Behandler filtert
 über calendarId; beim Verschieben trennt `_ALT_REF_RE` das am/vom-Stück
 (alter Termin) vom auf/zu-Stück (Neu-Wunsch). Die Auskunft fragt analog
 nur noch den Nachnamen ("Damit ich in den Kalender schauen kann: …").
2. **Mehrere PATIENTEN mit gleichem Nachnamen:** die CF antwortet
 409/conflict/ambiguous -> `kern/calendar.find_patient_appointments`
 liefert `mehrdeutig` (nie gecacht) -> `_vorname_frage` (frage=vorname,
 "Da haben wir mehrere Patienten mit dem Nachnamen X. Wie ist denn Ihr
 Vorname?") -> mit firstName erneut suchen. Immer noch mehrdeutig (Vorname
 lag schon vor) -> ehrlich + Notiz wie "nicht gefunden".
2b. **Namens-Korrektur-Chance (W-NAMESKORREKTUR 31.08.2026 — nicht
 rückbauen; Zannes-Anruf 10:33: "der gibt zu schnell auf, der patient muss
 zumindest einmal die möglichkeit haben den nachnamen zu korrigieren"):
 der ERSTE `notFound` schreibt KEINE Notiz mehr, sondern fragt
 `_korrektur_frage` ("Unter X finde ich gerade keinen Termin. Vielleicht
 habe ich den Nachnamen falsch verstanden — sagen oder buchstabieren Sie
 ihn mir bitte noch einmal?", frage=nachname, einmal je Anlauf:
 `verwKorrektur`, geräumt in `_verw_reset`). Nennt die Korrektur nur den
 Nachnamen, fliegt ein Vorname aus derselben verhörten Äußerung mit raus
 (Schnappschuss `verwKorrekturVorname` — "Sannes Czannis" hätte sonst als
 firstName=Sannes die korrigierte Suche vergiftet; `_ctx` räumt geleerte
 Felder auch aus dem booking-Dict). Dazu drei Netze: (a) `kern/calendar.
 find_patient_appointments` fasst bei 404 MIT firstName einmal NUR mit dem
 Nachnamen nach (`vornameVerworfen` in der Antwort: `_finden` nimmt dann
 den Kartei-Vornamen, bei mehrdeutig leert `_dispatch` den Vornamen vor
 der Vornamen-Frage); (b) `gehirn.einsammeln` erntet explizite Zuweisungen
 ("Nein, mein Nachname ist Zannes.", `_TEIL_*_RE`; nach Fehlsuche auch
 "ich heiße …") IMMER — auch wenn längst ein Nachname steht und keine
 Namensfrage offen ist (vorher versank die Korrektur im Nein-Zweig der
 Neubuchungs-Frage: "Alles klar."); (c) der Neubuchungs-Zweig in
 `verwalten.zug` behandelt einen frischen Namen (ohne Ja) als Korrektur
 und sucht sofort neu, statt ihn als Nein zu schlucken. Ein voller Name
 auf die Nachnamen-Frage überschreibt jetzt BEIDE Teile. Zweiter
 Fehlschlag -> Notiz-Weg wie unter 5. Tests:
 `test_absage_korrektur_chance_nach_erstem_fehlschlag`,
 `test_absage_korrektur_am_nein_zweig_vorbei`,
 `test_vorname_verworfen_kartei_schlaegt_verhoer`,
 `test_find_patient_appointments_nachfass_ohne_vorname`.
3. **Treffer bestätigen mit Anrede** (Chef: "Herr/Frau xy, ja?"):
 "Gefunden — {Termin}. Soll ich den Termin wirklich absagen, Herr Berger?"
 (gehirn.anrede; Vornamen-Wächter/Kartei). Bei Ja löscht
 agentCancelAppointmentById; verschieben bestätigt den Fund und fragt dann
 den Neu-Wunsch (bzw. bietet direkt an, wenn der Wunsch schon fiel).
4. **Mehrere TERMINE trotz Hinweisen** -> hilfsweise BEHANDLUNGS-Frage
 (frage=behandlung, einmal, nur wenn die Motive sich unterscheiden;
 `_behandlung_passt` gegen motivName/gemappte motivId) -> danach die
 bekannte Auswahl-Liste (phase=wahl). Bei EINEM Termin, der die Hinweise
 verfehlt: "Zu diesen Angaben finde ich nichts — ich sehe: {…}. Meinen Sie
 den?" (Ja wählt ihn, phase=wahl).
5. **Nicht gefunden** (notFound, keine kommenden Termine oder "Nein" auf die
 Rückfrage) -> ehrlich + ECHTE Notiz: Zeile in `.data/praxis_notizen.jsonl`
 (Zeit, Anliegen, Name, Telefon, Wann-/Behandler-/Behandlungs-Hinweis),
 `sit["praxisNotiz"]` (Dock "Letzter Anruf" zeigt sie, session._mit_sammler),
 merke_tool `praxis_notiz`. Gesprochen: "keine Sorge — ich schreibe eine
 Notiz, und die wird Doktor XY vorgelegt" (arzt_sprechname, sonst "dem
 Praxisteam") + Angebot Neubuchung (frage=neubuchung wie gehabt).

Ein im Anruf schon bestimmter Termin (Auskunft davor, frische Buchung mit
booking.appointmentId, Wahl-Liste) überspringt das Fragen — nie den Anrufer
ausfragen, was schon klar ist. Stand räumt `_verw_reset` (nach Storno/Move/
Notiz; poppt auch die W-SAMMELN-Altlasten verwWann/verwArztGefragt aus alten
Sitzungen).

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
  Prozedur erfragt Name/Kartei FRISCH (haeufigste Fehlerursache ist der
  verhörte Name) statt stur dieselbe Sackgasse zu suchen — AUSSER der
  Neustart-Satz trägt den Namen schon korrigiert (name/nachname in `neu`,
  W-NACHNAME): dann wird der frische Name direkt gesucht.
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
  nach_abschluss_startet_neu`. Tests: `test_absage_fluss_komplett`,
`test_absage_mehrere_patienten_gleicher_nachname` (W-NACHNAME),
`test_absage_hinweis_im_einstiegssatz_filtert`,
`test_absage_name_im_einstiegssatz_sucht_sofort`,
`test_verwaltung_kein_termin_gefunden`, `test_verwaltung_hinweis_passt_
nicht_ehrliche_rueckfrage`, `test_verwaltung_wahl_nein_fuehrt_zu_notiz`,
`test_verwaltung_behandlung_grenzt_ein`, `test_verwaltung_behandler_
filtert_kalender`, `test_verschieben_alt_neu_trennung`,
`test_verschieben_fluss_komplett` (Dock-Buster b34).

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

## Satz-Naht-Wache (W-TTS-NAHT 31.08.2026 — nicht rückbauen)

Chef: „die sätze und wörter werden manchmal mittendrin abgehackt … schau mal
im alten phone_agent da hatten wir das schon optimiert." Vorbild ist
`phone_agent/services/llm_inbound_agent/tts_chunks.py` (`_splittable_prefix`
+ `MIN_PIECE_CHARS`) — NUR gelesen, nichts dort angefasst. Zwei Löcher bei uns:

- **Falsche Satzenden im LLM-Stream** (`kern/llm._satz_ende`): die alte
 Abkürzungsliste war zu klein („Bahnhofstr.", „Tel.", „etc.", Wochentage
 fehlten, keine Einzelbuchstaben-Regel). Folge: der P5-Vorab vertonte halbe
 Phrasen, und der P2-Deckel zählte falsche Satzenden mit und KAPPTE die
 Antwort mitten im Satz — der Rest wurde nie generiert.
- **Naiver TTS-Split in `kern/dienst.py`** (`_sprech_blob`/`stimme_stream`):
 `(?<=[.!?]) +(?=[A-ZÄÖÜ])` schnitt „im 3. Stock" und „St. Martin" in zwei
 Renders — Satzende-Prosodie mitten in der Phrase. `sprech.sanitize` fängt
 zwar Dr./z. B./Datumsformen, aber nicht Nr./St./Tel./freie Ordnungszahlen.

Fix: EINE gemeinsame Grenz-Wache `kern/sprech.kein_satzende(davor)` (Ziffer,
Abkürzungsliste des phone_agent, Einzelbuchstabe, `…str`-Straßennamen) plus
geschützter Splitter `sprech.tts_saetze(text)` — genutzt von BEIDEN
dienst-Split-Stellen und von `llm._satz_ende` (damit Vorab, Deckel und
TTS-Split dieselben Grenzen sehen). Dazu `llm.VORAB_MIN` (20 Zeichen,
phone_agent MIN_PIECE_CHARS): kurze FOLGE-Sätze („Gut.") warten auf den
Folgesatz statt als Mini-Render in die Füller-Kette zu gehen; ein kurzer
SCHLUSS-Satz bleibt ungemeldet und läuft im Rest-Render mit (nie doppelt,
nie verloren). Ganze Sätze bleiben Gesetz — KEIN Komma-Schnitt (Genuschel-
Lektion 28.08. gilt weiter). Tests: W-TTS-NAHT-Blöcke in
`tests/test_llm_deckel.py` und `tests/test_sprech.py`.

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
 Seit 31.08.2026 (live 14:11: „Verbinde mich mit Dr. Petzos jetzt." fiel
 durch ALLE Formen, das LLM fragte in jedem Anruf aufs Neue „Zu welchem
 unserer Ärzte …" — DAS war die „wiederholt sich ständig"-Beschwerde des
 Chefs) auch der nackte Imperativ `verbinde mich/uns`; `_SPRECH_VERB_RE`
 matcht `verbind\w*` statt nur „verbinden", damit der Namens-Weg
 („Verbinde mich mit Dr. Petzos") auch bei verhörtem Namen zieht
 (arzt.deute faltet Petzos/Petzl -> Petsas). Test:
 `test_live_saetze_31_08_imperativ_und_verhoerte_namen` (voller Fluss
 bis Jingle+hangup mit den Live-Transkripten).
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

## Echte Weiterleitung (W-VERBINDEN-ECHT 31.08.2026 — nicht rückbauen)

Chef: "wenn ein client weiterleitungen eingerichtet hat dann müssen wir zu
dem entsprechenden arzt weiterleiten. siehe phone_agent repo da hatte das
schon funktioniert." Der phone_agent transferierte per LiveKit-SIP-REFER
(`services/phone/sip_transfer.py`), die Ziele kamen aus dem DB-Agent
(`callForwardingToolEnabled` + `callForwardings`, je Eintrag name/number,
Routing-Bedingung oft in prompt/condition). Unsere Kette hat kein LiveKit —
darum eigener Weg, Ende-zu-Ende:

- **Ziele ernten** (`kern/agentprofil._weiterleitungen`): die CF-pre-Antwort
 traegt die Agent-Felder; nur mit Schalter AN und echter Nummer, Nummern
 normalisiert auf +E164 -> `tenant["weiterleitungen"]`
 ([{name, nummer, hinweis}]). Die DB entscheidet KOMPLETT — auch das AUS
 (leere Liste ueberschreibt eine Datei-Basis). Lokale tenants/*.json
 duerfen das Feld fuer Dock-Tests selbst tragen (meddent traegt keins).
- **Ziel aufloesen** (`bianca/weiterleiten.weiterleitungs_ziel`): ein
 Namens-Wort des Ziel-Kalenders ("Petsas", Titel-/Fuellwoerter gefiltert)
 muss im Eintrag (name ODER hinweis) vorkommen; ohne Treffer gilt ein
 EINZELNER Eintrag als Praxis-Ziel fuer alle Behandler, bei mehreren wird
 NIE geraten (dann Platzhalter-Weg). `zaluma_weiterleitung` liefert bei
 Treffer `transfer={nummer,name}` + hangup, text="" (Ansage + Jingle
 liefen als Filler; nach dem Jingle klingelt es) — der Kirri-Zettel kommt
 NUR noch ohne eingerichtete Weiterleitung. `sit["weiterleitungZiel"]`
 haelt das Ziel fuer Nacharbeit/Report; `dienst.json_antwort` reicht
 `transfer` durch (Docks ignorieren es und legen auf wie bisher) und
 verwirft einen offenen Barge-Rest (nie "Also, wo war ich:" nach Jingle).
- **Bruecke** (`sip_bridge/server.py`): reply mit `transfer` -> die Nummer
 wird je Anruf-UUID vorgemerkt (`transfer_merken`, TTL 300 s, EINMAL
 abholbar). Der Dialplan fragt sie NACH dem AudioSocket-Ende per CURL auf
 DEMSELBEN Port 40101 ab — die Bruecke unterscheidet an den ersten drei
 Bytes ("GET" = HTTP-Abfrage, sonst AudioSocket-Rahmenkopf; `_klient`
 reicht die drei Bytes als vorab an den Anruf weiter). Kein zweiter
 Tunnel-Port, keine neue Firewall-Regel.
- **Dialplan** (`extensions_bianca.conf`, Referenzkopie im Repo): Asterisk
 18 beendet nach dem AudioSocket-Ende den KANAL (App liefert -1 — 31.08.
 empirisch gemessen: Zeile hinter der App laeuft NIE). Deshalb laeuft die
 App jetzt in einem Local-Leg (`[bianca-audiosocket]`, `/n` gegen die
 Optimierung, UUID vererbt via `__BUUID`); `Dial(Local/...,,g)` kehrt beim
 Leg-Ende zurueck, dann `CURL(http://127.0.0.1:40101/transfer?uuid=…)` ->
 leer = `Hangup()` wie bisher; Nummer = `Dial(PJSIP/zaluma-trunk/
 sip:+49…@vc.zaluma.tel,45,r)` (gleicher Trunk-Weg wie die alten
 REFER-Transfers, CLI des Anrufers geht mit). Behandler besetzt/geht
 nicht ran -> `Goto(bianca)`: der Anrufer landet in einer FRISCHEN
 Bianca-Sitzung statt in Totenstille (der Transfer-Eintrag ist
 verbraucht, keine Schleife). ACHTUNG: der `[bianca-audiosocket]`-Kontext
 MUSS am DATEIENDE stehen (alles darunter laege nicht mehr in
 [from-zaluma]); Backup `extensions_bianca.conf.bak-20260831-wl`.
- **Hangup-Nacharbeit unveraendert:** die Bruecke schliesst nach dem
 Ausspielen wie bei jedem hangup (Ende-Rahmen, POST /api/hangup) —
 Mitschnitt/Report/CF-Abschluss laufen normal, waehrend der Anrufer
 schon beim Behandler klingelt.
- **Agent-Falle (31.08. live erlebt, erste Probe):** das Transfer-Reply
 traegt text="" (Ansage + Jingle liefen als Filler) — `bianca/agent.
 user_turn` wertete leeren Text als "Maschine schweigt", das LLM
 uebernahm ("Zu welchem unserer Ärzte …") und der Transfer fiel weg.
 Seitdem zaehlt ein Reply MIT hangup/transfer immer als Maschinen-Zug,
 und user_turn reicht das transfer-Feld explizit in die Antwort durch
 (vorher ueberlebten nur text/book/hangup). Test:
 `test_agent_reicht_transfer_durch_ohne_llm` (LLM-Aufruf = Testbruch).
- Tests: W-VERBINDEN-ECHT-Bloecke in `tests/test_weiterleiten.py`
 (Ziel-Aufloesung, transfer-Reply, Platzhalter-Rueckfall),
 `tests/test_agentprofil.py` (Ernte + Schalter-aus) und
 `tests/test_sip_vad.py` (Transfer-Store einmal/TTL, HTTP-Peek
 Ende-zu-Ende gegen einen echten asyncio-Server). Live-Probe:
 `.data/transfer_probe.py` (laeuft IM bianca-Container auf pickadoc1
 gegen die echte Bruecke: DID 4110, "Doktor Petsas", danach die
 CURL-Abfrage wie der Dialplan) — 31.08. gruen: Nummer +49211302…
 einmal abholbar, zweite Abfrage leer, Ende-Rahmen kam.

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

## Session-Hirn + Intent-Schicht (W-HIRN / W-INTENT 03.09.2026 — nicht rückbauen)

Chef: „erst erkennen, dann handeln" — Bianca rannte bei jedem Terminwort in
den Buchungs-Default, dabei ist Buchen nur EINE Lösung für EINES von mehreren
Anliegen (Meddent-Auswertung: verbinden, Auskunft, absagen ohne Ersatz,
Rückruf …). Jetzt schwingt eine LLM-Erkennung bei JEDEM Satz mit, vor den
deterministischen Maschinen. Fable 5 hat das gebaut; LLM-Config, STT, TTS,
Routen und Ports sind unangetastet.

- **`kern/hirn.py` (Session-Brain, beide Stimmen):** `sit["hirn"]` hält die
  Anliegen-Queue (aktiv/offen/geparkt/erledigt, max. 8), abstrahiert als
  Handlung×Gegenstand: ERREICHEN, WISSEN, AENDERN (ersatz ja/nein), ANLEGEN,
  ABGEBEN × PERSON/VORGANG/SACHE/REGEL. NUR das Hirn schaltet Biancas
  `sammler["modus"]` (buchen/absagen/verschieben/auskunft); der Wechsel
  signalisiert sich über `sit["hirnModusNeu"]` → `flow.zug` hebt es in die
  Ernte-Menge (`neu.add("modus")`), damit verwaltens Einstiegs-Reset läuft
  wie früher bei der Regex. Phase `gebucht` bleibt beim Schalten stehen
  (Frisch-Absage-Sonderwege). ERREICHEN legt `sit["hirnVerbinden"]`
  (weiterleiten.zug konsumiert ihn, auch ohne Regex-Treffer), ABGEBEN legt
  `sit["hirnAbgeben"]` (flow._abgeben_zug: Name+Nummer, echte Notiz via
  verwalten.abgeben_notiz, kein Termin-Angebot). Lisa: Seed aus dem
  Chef-Auftrag (`seed_von_auftrag`, deterministisch), `/api/auftrag` hängt
  Nachschub als neues Anliegen an; Wirkung über `stand_block()` im Prompt.
- **`kern/intent.py` (Erkennung — synchron IMMER 0 ms):** Der Zug wartet
  NIE auf ein Modell (Chef 03.09.2026 nachmittags: gemessene 2,3–2,4 s je
  synchronem Intent-Call am ~22-Token/s-vLLM = „Desaster", Antworten ~8 s).
  1. Fast-Paths: Formular-Antworten (Ziffern, Buchstabieren, Ja/Nein,
     Slotwahl) → `verfeinern`; ohne Wechsel-Signal im laufenden Anliegen →
     `halten`; eindeutige Erstsätze (genau EIN Kategorie-Treffer, keine
     Verneinung: „Termin absagen", „Doktor sprechen") → sofort.
  2. Heuristik (0 ms): bei Wechsel-Verdacht/unklarem Erstsatz entscheiden
     die Regexes SOFORT; buchen NUR bei ausdrücklichem Terminwunsch, NIE
     als Default. Im laufenden Slot-Angebot meint „absagen/passt nicht"
     das ANGEBOT (verfeinern).
  3. Nachzug (asynchron, GEDROSSELT): NUR wenn die Heuristik ratlos blieb
     (halten/KEINE), geht der Satz ans vLLM (Temperatur 0, Mini-JSON,
     max_tokens 44, statischer Prompt = Prefix-Cache), höchstens EIN
     Auftrag je Sitzung zugleich — ungedrosselt liefen Nachzüge am
     gesättigten vLLM 9,5–20,6 s und stahlen der GPU von TTS/STT die Luft
     (Audio-Aussetzer, Chef 03.09.2026 abends). `intent.nachzug()` arbeitet
     das Ergebnis am ANFANG des nächsten Zugs ein — richtige Heuristik
     dedupliziert `hirn.anwenden`, falsche wird einen Zug später umgelenkt.
     Notaus nur fürs Hintergrund-LLM: `INTENT_NACHZUG=0` (steht seit
     03.09.2026 abends auf dem Server in `.env`, bis der GPU-Druck bzw.
     die Audio-Qualität geklärt ist).
- **Einbau:** `bianca/agent.user_turn` Schritt 0 (sync → erkennen →
  anwenden, vor `flow.zug`); `lisa/agent.user_turn` nach der Identität, vor
  dem Modell. Anliegen-Stand steht als ANLIEGEN-Block im Systemprompt
  (über den `plan`-Parameter, kein Prompt-Signatur-Umbau).
- **Gate:** `gehirn.einsammeln` öffnet den Modus per Regex NUR noch, wenn
  die Sitzung kein Hirn trägt (Alt-Sitzungen mitten im Deploy) oder der
  Notaus greift. Biancas Session-Auftrag ist nicht mehr „Terminwunsch
  aufnehmen und buchen", sondern „Anliegen erkennen und passend lösen".
- **Notaus:** `INTENT_SCHICHT=0` → Erkennung aus, Regex-Modus wieder aktiv,
  Verhalten wie vor W-HIRN. Tests: `tests/test_hirn.py` (33, offline —
  LLM gestummt).

## Besuchsgrund-Katalog-Mapping (W-MOTIV-KATALOG 03.09.2026 — nicht rückbauen)

Chef (wörtlich): "bianca muss den besuchsgrund besser mappen lernen auf die
realen besuchsgründe in der Praxis. die besuchsgründe müssen auf jeden fall
parat stehen in einem RAG oder ähnlichem, weil viele user eigene
besuchsgründe editieren oder erstellen. [...] entsprechende kurznotizen
bitte nicht vergessen [...] bei Besuchsgründen mit xy klein oder xy gross
[...] nehmen wir grundsätzlich die klein variante"

- **Das "RAG":** der Katalog steht pro Anruf frisch in der Sitzung
  (`kern/motive.anstossen` -> `masVisitMotives`, einmal, im Hintergrund).
  Die CF liefert seit 03.09.2026 zusätzlich die **Erklärtexte**:
  `patientInfo` (Einstellungsseite) + `landingPageHeadline`/
  `landingPageDescription` (Landingpage), HTML-bereinigt, 400-Zeichen-Kappe
  (Commit 70288461 in pickadoc-live-base, deployt auf docgenda).
- **Drei Stufen** beim Mapping (`bianca/besuchsgrund.py`):
  1. kuratierte KONZEPTE (Zahnarzt-Muster, wie gehabt),
  2. NEU `katalog_treffer()`: generisches Scoring gegen Namen (3 Punkte)
     UND Erklärtexte (1 Punkt), Schwelle 3, wortstamm-tolerant
     (`_token_passt`: exakt / Substring ab 5 / Stamm-Präfix / Präfix 6) —
     trifft kundeneigene Gründe ("Füllung", "Funktionsanalyse", "Botox"),
  3. Kontrolle/Besprechungs-Fallback (wie gehabt).
  Grössen-Marker (klein/gross) sind Stoppwörter — sie entscheiden NIE das
  Matching, nur die Klein-Regel am Ende ("Füllung" -> "KCH Füllung klein",
  auch wenn der Anrufer "grosse Füllung" sagt).
- **Behandlerspezifisch:** `gehirn.motiv_fuer_kalender` versucht
  `katalog_treffer` mit dem Wortlaut, bevor altes Motiv/Fallback greifen.
- **Kurznotiz:** deckt der gebuchte Grund den O-Ton nicht wörtlich ab
  (`besuchsgrund.deckt_ab`), hängt `flow._buchen` an den Termin:
  "Anrufer wörtlich: „…" — gebucht als <Motiv>." (note_appointment).
- **Falsch-Positiv-Wachen:** Stoppwörter (Floskeln, Allerweltsverben wie
  "stellen" — Taxi-Abschweifer traf sonst "Planerstellung"), Stamm-Vergleich
  nur als Präfix-Beziehung, Score-Schwelle 3. `tests/test_baukasten.py::
  test_abschweifer_ernten_keinen_grund` ist die Regressionswache.
- Tests: `tests/test_motiv_katalog.py` (15, offline). Live-Probe (read-only):
  `.data/motiv_probe.py` gegen den echten Meddent-Katalog (133 Motive,
  102 mit Erklärtext).

## Erst Besuchsgrund, dann Slots (W-MOTIV-FENSTER 03.09.2026 — nicht rückbauen)

Chef (wörtlich): „wenn du VOR dem Besuchsgrund nach terminslots suchst,
kannst du gar nicht die spezialsprechzeiten beruecksichtigen. du musst erst
wissen welcher besuchsgrund gefordert ist [...] ohne kenntnis des grundes
tappst du im dunkeln."

Hintergrund: `getFreeTimeSlots` filtert die Fenster NACH `visitMotiveId`
(Spezialsprechzeiten: PZR-Slots ≠ Kontroll-Slots, nicht jedes Motiv in
jedem Raum). Vorher suchte der Hintergrund-Vorrat blind mit dem
Kontroll-Default, sobald nur der Behandler feststand.

- **`hintergrund.vorrat_schluessel`** (früher `_vorrat_schluessel`) liefert
  `""` ohne gemapptes Motiv — der Vorrat wartet, bis `einsammeln` den Grund
  auf ein Motiv gemappt hat (Fragenkette fragt den Grund VOR der
  Wunschzeit, der Vorsprung bleibt also). Der Schlüssel trägt die
  behandlerspezifisch AUFGELÖSTE Motiv-ID (`gehirn.motiv_fuer_kalender`,
  rein lokal am Katalog) — Hintergrund-Lauf, Marker und Angebots-Check
  sprechen dieselbe Sprache.
- **`sit["vorratFuer"]`:** der Hintergrund-Lauf (und `flow._laden`) stempelt
  nach ERFOLGREICHEM Laden, für welchen Rahmen der Vorrat gilt.
  `flow._angebot` nutzt einen Vorrat NUR bei passendem Stempel — sonst
  synchron nachladen mit dem richtigen Motiv. Schließt das Rennen „Anrufer
  nennt den Grund, alter Blind-Vorrat liegt noch in der Sitzung".
- Der Hintergrund-Lauf löst das Motiv ebenfalls per `motiv_fuer_kalender`
  auf, statt roh `s["motivId"]` zu senden.
- Verschieben war schon sauber: `_verschieb_angebot` sucht mit dem Motiv
  des BESTANDstermins.
- Tests: `tests/test_motiv_fenster.py` (6, offline). Beim Testen mit
  handgesetztem `slotVorrat` IMMER `motivId` + `vorratFuer =
  hintergrund.vorrat_schluessel(sit)` setzen, sonst lädt `_angebot` nach.

## Behandler-Reihenfolge + Standard-Arzt (W-ARZT-DEFAULT 03.09.2026 — nicht rückbauen)

Chef (wörtlich): „erwähne nicht die Namen in dieser RehenFolge: Dr. Nikolaou,
Dr.Patrikis und Dr. Petsas. sondern umgekehert. [...] Dr. Petsas,
Dr. Patrikis oder Dr. Nikolaou. wenn jemand nicht weiss zu welchem arzt er
soll dann immer bei dr. Petsas buchen."

- **Sprech-Reihenfolge** (`kern.tenants.behandler_reihe`): der Standard-
  Behandler (`defaultCalendarId`) zuerst, die übrigen in umgekehrter
  Kalender-Reihenfolge — Meddent: Petsas, Patrikis, Nikolaou. Nutzt
  `gehirn.arztwahl_frage` (Neupatienten-Arztwahl) und `agent._behandler_alle`
  (LLM-Prompt BEHANDLER-Zeile).
- **"Weiß nicht/egal" → Standard-Behandler** (`gehirn.arzt_default`, typ
  bleibt "egal" aber MIT calendarId): greift in `einsammeln` (egal-Antwort),
  `flow._eskalieren` ("arzt"-Frage zweimal unklar) und als letzter Fallback
  in `flow._angebot` (auch fuer Bestand "weiß nicht bei wem ich war", wenn
  die Kartei-Recherche nichts hergibt). Die globale Schnellster-Arzt-Suche
  (egal=True an die CF) läuft nur noch, wenn ein Tenant KEINEN
  Default-Kalender hat.
- Tests: `tests/test_arzt_default.py` (7, offline);
  `test_buchung_bindet_angebots_kalender` wurde auf die neue Regel gedreht
  (Bindungs-Wache selbst unverändert).

## Bleaching-Angebot zur Zahnreinigung (W-BLEACHING 03.09.2026 — nicht rückbauen)

Chef (wörtlich): „wenn jemand anruft um eine Zahnreinigung zu buchen kannst
du auch fragen ob die Zähne mit aufgehellt werden sollen.. Die Aufhellung /
bleaching dauert ca 1 Stunde länger und kostet 350 euro zusätzlich. Sie ist
unter Umständen nicht möglich, wenn in der Front Zahnersatz [...] es sei
denn die Zähne sollen bei zu hellen kronen durch bleaching an die
zahnkronen angepasst werden. [...] wenn der Patient sich ungewiss ist [...]
sagst du du hast eine notiz gemacht und der Doktor schaut sich das in Ruhe
an und berät sie"

- **Zustandsmaschine** (`sammler["bleaching"]`): "" → "gefragt" (Angebot als
  `flow._einschub`, wie die PZR-Mitbuch-Frage; nennt die Dauer, aber KEINEN
  Preis — Chef 03.09.2026: „kosten nur bei nachfrage nennen. nicht mit den
  kosten ins haus fallen", der Preis kommt nur übers LLM, wenn der Anrufer
  fragt) → bei Ja
  "check" (Zahnersatz-Rückfrage: Kronen/Brücken/Veneers/Implantate vorne?)
  → "ja" | "nein" | "beratung" (+ `bleachingInfo`: "zahnersatz"/"unsicher").
  EINMAL pro Anruf; zweimal keine klare Antwort → `_eskalieren` setzt
  "nein" (Angebot) bzw. "beratung" (Check).
- **Tenant-Wache** (`gehirn.bleaching_faellig`): nur wenn der NEUE Termin
  selbst eine Zahnreinigung ist (`ist_pzr_grund`) UND der Motiv-Katalog der
  Praxis eine Aufhellung führt (`_BLEACH_RE` gegen Namen). Derma-Praxen
  (Blessing) sehen die Frage nie. Preis (350 €) und Dauer (+1 Std.) sind die
  Chef-Ansage für SEINE Praxis — führt ein anderer Zahn-Tenant Bleaching,
  vorher Preis/Dauer klären!
- **Gebucht wird IMMER die Zahnreinigung** (kein zweiter Slot, kein
  Motiv-Wechsel — Meddent hat kein Kombi-Motiv): bei "ja" bekommt der Termin
  „PLUS Zahnaufhellung/Bleaching … (ca. +1 Std., 350 Euro zusätzlich) —
  bitte Terminlänge anpassen." als Popup-Notiz; bei "beratung" die passende
  Berate-Notiz (Zahnersatz vorne bzw. unsicher).
- **Bianca berät NIE selbst medizinisch:** bei Unsicherheit/Zahnersatz sagt
  sie den Chef-Satz (Notiz gemacht, der Doktor schaut es sich in Ruhe an
  und berät). Faktenwissen fürs LLM (Nachfragen wie „Was kostet das?")
  hängt `flow.status_zeile` an, solange die Frage offen ist — kein globaler
  Prompt-Absatz, damit fremde Tenants die Meddent-Preise nie sehen.
- Regex-Wachen: `_ZAHNERSATZ_RE` matcht NICHT „am dritten Oktober" (nur
  „die Dritten"); Zwischenfragen halten die Bleaching-Frage offen (wie pzr).
- Tests: `tests/test_bleaching.py` (16, offline).

## Termin für Dritte (W-FUER-WEN 03.09.2026 — nicht rückbauen)

Chef (wörtlich): „wir haben noch nicht den fall trainiert wo der anrufer
nicht für sich sondern für jemand anderen den termin bucht. ‚Der Termin ist
für Sie selbst, richtig?' das fehlt ... korrigiere das rein"

Live-Fall (Anruf 03.09. 21:43): Der Vater (per Rufnummer erkannt) sagte
DREIMAL „für meinen Sohn" — Bianca buchte stur auf den Vater. Drei Löcher:

- **Erkennung** (`gehirn.fuer_wen_signal`): `_FUER_WEN_RE` matcht jetzt auch
  ohne „für" („Mein(en) Sohn braucht/möchte/hat Schmerzen …") plus
  `_NICHT_FUER_MICH_RE` („nicht für mich", „für jemand anderen", „für
  Herrn/Frau <Name>", „im Auftrag von" → Rolle "andere"). `_FUER_MICH_RE`
  löst „doch für mich" wieder auf. Wache: „Meine Frau hat gesagt…"/„Meine
  Tochter heiratet"/„für Frau Doktor Petsas" matchen NICHT.
- **Alle Rollen** (Chef-Nachtrag: „es muss nicht immer der sohn sein, es
  kann auch der nachbar der bruder oder die mutter sein. du musst alle
  möglichen Fälle verstehen"): `_ROLLEN` liefert die Grammatik für die
  bekannten Fälle (Familie, Nachbar(in), Bruder, Mutter, Freund,
  Kollege, Partner, Chef, Schwieger-, Betreuer, Pfleger …). `_FUER_WEN_RE`
  matcht aber **jede** Besitz-Konstruktion („für meinen X", „meine X
  braucht/möchte") — unbekanntes X (Betreuer, Peter) wird „andere" und
  Bianca fragt „Für wen ist der Termin denn — wie heißt er oder sie?".
  Stopwörter (Woche, Kontrolle, Donnerstag, Frau Doktor) sind kein Dritter.
  Extra-Netze: „für ihn", „ich rufe für Peter an", „im Auftrag/Namen von",
  „stellvertretend". Grammatik kommt NUR aus der Tabelle — nie geraten.
- **Die Chef-Frage:** der Anrufer-Check im BUCHEN-Fluss endet mit „Der
  Termin ist für Sie selbst, richtig?" (`anrufer_check_frage(sit,
  selbst=True)`); Verwaltung (Absage/Auskunft) behält „Stimmt das so?".
  Ein Nein ohne Rolle ⇒ fuerWen="andere" („Für wen ist der Termin denn —
  wie heißt er oder sie…"); „Nein, das bin ich nicht" (`_NICHT_ICH_RE`)
  bleibt der Identitäts-Fall (frisch aufnehmen wie bisher).
- **Identität lösen** (`gehirn.patient_von_kontakt_loesen`): kommt das
  Fuer-Wen-Signal, NACHDEM „ja" auf den Check die Kartei des Anrufers als
  Patient übernommen hat (auch im selben Satz: „Ja, aber für meinen Sohn"),
  werden Name/Akte/patientId/Geschlecht/Historie/Versicherung geleert,
  `warSchonMal=None`, `sit["patient"]/upcoming/past` verworfen. Die NUMMER
  des Anrufers bleibt als Kontakt (SMS an den Anrufer ist richtig), sein
  Name wandert nach `sammler["kontaktName"]` — der zugleich der
  Einmal-Riegel ist (Sohn heißt oft gleich ⇒ nie doppelt wischen).
- **Späte Korrektur:** „Nein, der ist für meinen Sohn" auf die
  Bestätigungsfrage lief vorher in „Was darf ich ändern…" ins Leere —
  `flow.zug` (phase bestaetigen, nein) prüft jetzt `fuer_wen_signal` und
  schreibt den Patienten um, OHNE Slot/Grund/Arzt zu verwerfen.
- **Fragen drehen sich um den Dritten:** „War Ihr Sohn schon einmal bei
  uns?", „bei welchem Behandler Ihr Sohn zuletzt war?", „Wie heißt Ihr
  Sohn? Bitte mit Vor- und Nachnamen.", „Und ist Ihr Sohn privat oder
  gesetzlich versichert?" (`fuer_wen_phrase`, Nominativ/Akkusativ). Häufige
  Rollen sind als feste Sätze vorgewärmt.
- **Termin-Notiz:** „Telefonisch gebucht von Angehörigem (Sohn-Termin):
  Kiriakos Tzannis, Kontakt-Nummer … gehört dem Anrufer." — die Praxis
  sieht, WER angerufen hat.
- Tests: `tests/test_fuer_wen.py` (offline).

## Anstand-Konter (W-ANSTAND 03.09.2026 — nicht rückbauen)

Chef (wörtlich): „wenn dich jemand beschimpft oder flucht sagst du nur....
boah... das war nicht nett... ich gebe mir echt mühe oder 4-5 Alternativen
in dieser Art. eine lustige nehmen wir auf wenn jemand sagt ach fick dich
oder ähnliches.. sagst du..... ähhhm selber!! sonst noch was?"

- **`bianca/anstand.py`:** deterministisch (0 ms, kein LLM). Drei Muster:
  `_SELBER_RE` (fick dich/verpiss dich/Arschloch …) → „Ähm — selber! Sonst
  noch was?"; `_SCHIMPF_RE` (blöde Kuh, halt die Klappe, Scheiß-KI …) →
  eine von 5 charmanten Antworten, rotierend pro Sitzung
  (`anstandZaehler`); `_FLUCH_RE` (purer Fluch) nur bei ≤ 6 Wörtern —
  Frust MIT Inhalt („Scheiße, ich hab den Termin verpennt") gehört dem
  Gespräch. `\bspasti?\b` trifft NICHT „Spastik" (Medizin-Kontext).
- **Einbau:** `agent.user_turn` fragt anstand NUR, wenn `flow.zug` None
  lieferte — ein Anliegen mit Schimpfwort im selben Satz („Verbinden Sie
  mich, Sie blöde Kuh!") gewinnt immer den Fach-Weg, der Konter entfällt.
  Nie zurückschimpfen, nie auflegen; der Frage-Anker holt die offene
  Pflichtfrage im nächsten Zug zurück.
- **Prompt-Leitplanke** (BESCHIMPFUNGEN in `bianca/prompt.py`): fängt
  Umschreibungen, die das Regex nicht kennt, im selben Ton ab.
- Tests: `tests/test_anstand.py` (7, offline — Agent-Test beweist, dass
  das LLM beim Konter nie läuft).

## Server-Deploy (pickadoc1) — die .env-Falle

- **`.env` ist im Git GETRACKT.** Jedes `git archive` enthält sie — ein
  `rsync` des Archivs auf `/home/cursor/telefonki/` ÜBERSCHREIBT die
  Live-`.env` und löscht live-only Werte: `CLOUDFLARE_TELEFONKI_TOKEN`
  (Tunnel `lisa-public` crash-loopt beim nächsten Recreate!) und Schalter
  wie `INTENT_NACHZUG=0`. Genau das ist am 03.09.2026 ZWEIMAL passiert.
- **Regel:** beim Deploy IMMER `rsync … --exclude=tenants/ --exclude=.env`.
  Nach jedem Deploy prüfen:
  `grep -c 'CLOUDFLARE_TELEFONKI_TOKEN\|INTENT_NACHZUG' .env` → muss 2 sein.
- Token-Notfall: lokal `cloudflared tunnel token pickadoc-telefonki`
  erzeugt ihn neu; per ssh-stdin an die Server-`.env` anhängen.
- Sauberer wäre: `.env` aus dem Git nehmen (`git rm --cached`) — Entscheidung
  des Chefs, weil GitHub-Historie und andere Checkouts dranhängen.

## Fernsteuerung

- Seite: `/fernsteuerung.html` (Handy braucht `#t=…` aus dem lokalen Link).
- Wächter: `tools/lisa_fernsteuerung_watch.ps1` — nur Grok, nur dieser Ordner.
- Kein MAS-Wächter, kein Workspace `F:\`.
