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
 `extensions_bianca.conf.bak-20260830-4120`), seit 15.09.2026
 **+49 211 54244160 = Rüther** (gynäkologische Praxis, Assistent **Ben**
 männlich — s. W-STIMME-MANDANT; clientId AWdFeDldR81P3jmiq869, Agent
 LtHkW6I1xSwDpWy5M3vy, dazu `tenants/ruether.json` für Sprechformen,
 Stimme und Hotwords). Der Map-Default steht im CODE
 (`sip_bridge/server.py`), nicht nur in der `.env` — eine beim Deploy
 überschriebene `.env` (s. „Die .env-Falle") würde die Praxis sonst auf
 dem Default-Mandanten landen lassen. Wache: `did_von_uuid`-Block in
 `tests/test_agentprofil.py` und `test_did_4160_fuehrt_zu_ben`
 (`tests/test_assistent.py`, prüft die ganze Kette UUID → DID → Mandant →
 Name/Stimme).
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
 `frage=anrufer_check` (`gehirn.anrufer_check_frage`): der
 ziffernfreie Hallo-Satz geht SOFORT als Vorab-Füller raus
 (`anrufer_hallo_jetzt` → `vorab`). **W-HALLO-PAUSE (10.09.2026):**
 Feststellungsvarianten („Schön, Sie wieder zu hören“) dürfen direkt in
 die Ja/Nein-Kontrolle übergehen. Fragt eine Variante wirklich „Wie geht
 es Ihnen?“, endet der Zug GENAU dort und Bianca hört zu; der ursprüngliche
 Termin-/Absage-/Auskunftswunsch bleibt in `anruferHalloOffenerText`
 geparkt und läuft nach der Wohlseinsantwort weiter. Nie wieder eine Frage
 stellen und im selben Atemzug selbst weiterreden. „Gut.“ oder „Ja, gut.“
 bestätigt dabei NIE die Identität; erst „Habe ich Sie richtig erkannt?“
 nimmt ein Ja an. Bei Buchungen folgt als EIGENER Schritt
 `frage=fuer_wen_check`: „Der Termin ist für Sie selbst, richtig?“.
 Identität und Terminempfänger dürfen nie wieder in eine doppeldeutige
 Ja/Nein-Frage zusammengezogen werden. Antwortet der Anrufer auf die
 Wohlseinsfrage stattdessen eindeutig „Ich bin nicht <Name>“, wird der
 falsche DB-Treffer sofort verworfen — keine überflüssige zweite
 Identitätsfrage.
 Fast-Pfad: der Hallo wartet NICHT auf
 letzten Besuch oder Behandler (`anrufer_hallo_jetzt` nur Name). Die
 Kartei startet schon zur Begrüßung (`hintergrund.kartei_von_anrufer`)
 und fliesst danach ein: „Sie waren zuletzt bei Doktor X, richtig?“
 (`arzt_check`), dann PZR.
 Ja (`einsammeln`): Name in Kartei-Schreibweise (buchstabiert=True,
 bekannt=True, patientId), Geschlecht als Quelle "akte", warSchonMal=True.
 Danach nur noch Pronomen („Sie“), nicht drei- bis viermal der volle Name.
 Die Rufnummer wird NICHT still als bestätigt übernommen: am normalen
 Nummernschritt fragt Bianca „Soll ich die Bestätigungs-SMS an die
 <hinterlegte Nummer> schicken?“. Ja übernimmt sie; Nein fragt eine neue
 Nummer ab. Nach deren Readback folgt `telefon_alt`: alte Nummer löschen
 und neue per `masUpdatePatientPhone` eintragen oder SMS doch an die alte
 Nummer. Ein erfolgreicher Wechsel wird am Termin als
 `Alte Nummer <alt> aktualisiert //Bianca` vermerkt. Identitäts-Nein
 verwirft den Treffer (anruferCheck="nein"), danach klassische Fragen.
- **Absage/Verschieben/Auskunft** (`verwalten._sammeln` bzw. Auskunfts-Zweig
 in `verwalten.zug`): dieselbe Frage ersetzt die Nachnamen-Frage; ein Ja
 sucht SOFORT mit Kartei-Name, patientId und Anrufernummer
 (`agentFindPatientAppointments` bekommt phone=callerPhone mit). Wurde der
 Name schon im schnellen Hallo genannt, lautet die spätere Kontrolle
 aufgabenscharf („Soll ich unter Ihren hinterlegten Daten den Termin suchen,
 den Sie
 absagen möchten?“) — nie mehr das zusammenhanglose „Stimmt das so?“.
- **Dritttermine + relative Nummer:** beim Lösen der erkannten Anruferakte
 vom Patienten bleiben `kontaktName` und `kontaktTelefon` erhalten. „Nehmen
 Sie meine Nummer“ bezieht sich dadurch sicher auf die Rufnummer des
 Anrufers/Elternteils, nie auf die frisch erfasste Kinderakte; Bianca liest
 sie als SMS-Ziel vor und verwendet sie erst nach Ja.
- **Deterministisch wie telefon_check:** Identität, Terminempfänger und
 SMS-Ziel bleiben feste Ja/Nein-Schritte. Zwei unklare Antworten verwerfen
 lieber den Identitätstreffer bzw. fragen die Nummer neu, statt etwas zu
 raten. Kurze Ruhe-Schwelle 350 ms (`_STILLE_KURZ`), Frage-Kerne in
 `agent._FRAGE_KERN["anrufer_check"|"fuer_wen_check"]`.
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
 **1,55-s-Latenzdeckel** (`STT_WHISPER_BUDGET_S`, seit 09.09.2026 spät)
 bezahlt. **W-STT-VORFALLBACK:** 300 ms vor diesem Deckel startet Parakeet
 bereits parallel. Ein noch rechtzeitig fertiges Whisper-Final gewinnt
 weiterhin; bei Timeout oder leerem Final ist der Rückfall schon fertig und
 kostet nicht nochmals seriell 0,2–0,3 s. Live-Messung vor dem Patch:
 1,714 s Whisper-Timeout + 0,210 s Parakeet = 1,883 s; Zielpfad danach
 höchstens etwa 1,55–1,60 s bis zum STT-Final. Leeres Whisper-Final pausiert
 Whisper nicht. NIE still auf ElevenLabs: ohne STT_BASE fliegt der
 RuntimeError hörbar. Leer = alles wie vor W-STT-WHISPER.
- **Gemessen 30.08.:** Whisper über Tailscale 1,4 s je Zug (Testsatz
  wortgenau inkl. "Petsas" per Hotword-Bias), Rückfall-Zug 2,75 s
  (einmalig, danach 0,33 s Parakeet-direkt), webm-Pfad grün.
  Parakeet bleibt die schnellere Engine — Whisper ist der Qualitäts-Test.
- Health-/Dock-Anzeige: `engine_anzeige()` zeigt "Whisper large-v3
  (Dev-GPU) + Parakeet-Rueckfall" bzw. "(…, Whisper pausiert)".
- Tests: `tests/test_stt_whisper.py` (offline: Vorrang, Rückfall+Pause,
  nie Scribe, WAV-Direktspur, Nachkorrektur); Live-Probe:
  `tests/stt_whisper_probe.py` (echter Container + echter Rückfall).

## Parakeet + Qwen parallel (W-STT-QWEN-PARALLEL 11.09.2026 — nicht rückbauen)

Live-Messung über den 3060-Hybrid-Gateway ergab 0,47–2,48 s STT statt
0,17–0,47 s mit lokalem Parakeet. Deshalb ist die Reihenfolge verbindlich:
**5090-Parakeet ist das sofortige Haupt-Ohr; Qwen3-ASR auf der separaten GPU
läuft parallel und ist nur der Qualitätsprüfer.**

- `STT_BASE` startet im aktuellen Thread; Qwen startet gleichzeitig in genau
  EINEM Hintergrundslot. Plausible Parakeet-Texte warten **0 ms**. Nur
  lexikalisch auffällige Ergebnisse warten maximal `STT_QWEN_GRACE_S`
  (Default 0,25 s). Ein noch laufender alter Qwen-Zug wird nie aufgestaut.
- `STT_QWEN_FINAL_BASE=http://192.168.0.167:8223` ist der schnelle direkte
  LAN-Weg zum gereinigten Qwen-only-Container. Dort läuft für Bianca KEIN
  zweites Parakeet. Der alte geschützte Hybrid-Gateway unter
  `STT_QWEN_BASE` bleibt nur kompatibler Test-/Rückweg; Cloudflare gehört
  nicht in Live-Biancas STT-Pfad.
- Qwen darf nur ein deutsches, nicht leeres, nicht aus dem Vokabular-Kontext
  nachgesprochenes Final übernehmen. Abweichende Ziffernfolgen bleiben aus
  Sicherheitsgründen bei Parakeet. Partials steuern Bianca nie.
- Qwen-Ausfall pausiert den Prüfpfad 30 s, beeinträchtigt Parakeets Antwort
  aber nicht. Bei gesetztem Qwen ruft `kern/stt.py` auch bei einem stale
  `STT_WHISPER_BASE` nie Whisper oder ElevenLabs auf.
- Der LAN-Qwen-Endpunkt ist nur an die 3060-LAN-IP gebunden und verlangt
  `STT_QWEN_KEY` als internen Token. Health zeigt
  `Parakeet (lokal) + Qwen3-ASR parallel (3060)`.
- Tests: `tests/test_stt_qwen.py`; vor Rollout zusätzlich direkte
  Qwen-WAV-Probe und `tools/prod_smoke.py`.

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

## Svetlana: Ohr offen, Echo nicht ans LLM (W-SVETLANA 04.09.2026 — nicht rückbauen)

Live-Transkript Svetlana 04.09.: Überschneidungen fehlten, Anrufer wurde
nach dem ersten Wort abgeschnitten, während Bianca sprach war die Brücke
taub (Barge-Schwelle 1100 / 280 ms). Vier Bausteine:

1. **Tempo verdrahtet** (`kern/tempo.py` → `bianca/server` `stille_fn`):
   unbekannt/langsam nie unter 800/1100 ms statt starrer 350 ms.
2. **Halbsatz** hält Fortsetzungsworte auch mit Punkt (`Also.`, `Ich.`).
3. **Stilles Ohr** in `sip_bridge/server.py` (`BRIDGE_OHR=1` Default):
   während Bianca spricht mit Zuhör-Schwelle puffern (6 s), sie nicht
   stoppen; nach Ansage-Ende wird der Puffer zum Zug (`ohrMit=1`).
   Wichtig: `stoppen()` greift erst wenn weder Ton noch wartende Posten
   (`aktiv`) — sonst werden Folgesätze in TTS-Lücken/Underruns verworfen.
   Notaus: `BRIDGE_OHR=0` = altes Halbduplex.
4. **Text-Echo** (`unterbrechung.ist_echo`, auch ohne Barge wenn `ohr=True`)
   gegen die Satzkarte — Freisprech-Echo startet kein LLM; Ja/Nein/Stopp
   nie als Echo. Echter Einwand bekommt den Floor (kein „Also, wo war ich“).
5. **Barge-Fenster statt Lebenszeit-Summe (W-OHR-FENSTER 09.09.2026):**
   Kiriakos meldete Audioaussetzer, die bei langen Antworten zunahmen.
   Ursache: `_ohr_frames` summierte kurze Echo-/Rauschbursts über die GANZE
   Ansage; nach insgesamt 400 ms wurde der laufende Audio-Posten gekappt,
   auch wenn zwischen den Bursts lange Ruhe lag. Die Stopp-Schwelle gilt
   jetzt nur noch in einem rollenden 600-ms-Fenster (mindestens 400 ms
   Sprachanteil). Echte längere Einwände stoppen unverändert schnell,
   verteilte Leitungsstörungen nie. Repro/Wache:
   `test_ohr_stoerimpulse_summieren_sich_nicht_ueber_lange_ansage`.
6. **Interne Ohr-Pause vor Parakeet kürzen (W-STT-OHR-KOMPAKT
   10.09.2026):** Im Thaler-Livezug lagen zwischen zwei Sprachinseln
   5,18 Sekunden Leere (8,76 s Segment, nur 19 % Sprache). Parakeet machte
   daraus „Mm-hmm. Mitte mir jetzt.“; nach reinem Entfernen der inneren
   Leere wurde derselbe Ton zu „Aha, mit dem März.“. `sip_bridge.stimme.
   ohr_kompakt` greift deshalb NUR bei Ohr-Zügen ab 4 s, höchstens 25 %
   Sprache, GENAU einer internen Pause ab 1,2 s. Es entfernt nur
   Pausensamples; Sprache, normale Züge, kurze Antworten und mehrteilige
   Abschiede bleiben byte-identisch. Notaus: `STT_OHR_KOMPAKT=0`.

Tests: `tests/test_tempo.py`, Ohr-Block in `test_sip_vad.py`,
`test_ist_echo_ohr_gegen_satzkarte`, `tests/test_sip_stimme.py`,
Halbsatz-Punkt-Fälle.

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
Termin-Notiz. **W-PZR-KASSEN (08.09.2026):** jeder vergebene Termin
bekommt die PZR-Frage (`pzr_noch_fragen`, auch ohne Kartei; vor dem
Buchen holt `_nach_ok_buchen` nach). Auf Preisfrage: ungefähr 120 Euro
(nie „grob“), plus dass bei uns die Zahnärzte die Reinigung selbst
machen, nicht Prophylaxehelferinnen. Dann die Krankenkasse —
Zuschuss nur aus `kern/pzr_kassen.py` (Tabelle), immer
„Im Einzelfall kann das abweichen.“ Zahlen nie schätzen.
**W-KARTEI-FUELLER (08.09.2026):** liegt der letzte Besuch
schon in der Kartei, füllt die Totzeit nur eine Feststellung ohne Frage
(„Letztes Mal die Kontrolle — einen Moment.“ — `gehirn.kartei_fueller_satz`
→ `sit["karteiFillerText"]` → `filler.kartei_satz`). Nie in Confirm/Slot/
Nummern-Readback, nie ohne Fakt, nie als Frage. Die Verlaufsfrage kommt
später im `_einschub` (dann ohne Vorsatz); die Antwort steht als
`rueckblickAntwort` im Terminpopup. Tests: `tests/test_rueckblick_pzr.py`,
`tests/test_pzr_kassen.py`, `test_kartei_satz_*` in `tests/test_filler.py`.
**W-PZR-REIHENFOLGE (09.09.2026):** Das Zusatzangebot darf die primäre
Terminaufnahme nicht überholen. Bei Neupatienten kommt nach „noch nie da“
zuerst die Behandlerwahl; erst wenn der Behandler feststeht, fragt Bianca
nach der Zahnreinigung. Das Angebot bleibt Pflicht vor dem Eintragen.
Technisch ist das EIN Eintrag: `"arzt"` in der Einschub-Sperre von
`flow.zug`. Der ist am 12.09.2026 aus einem fremden Arbeitsstand heraus
verlorengegangen und lief zwei Tage falsch live (13.09. zurückgeholt) —
wer diese Zeile anfasst, prüft `tests/test_pzr_kassen.py::
test_neupatient_klaert_erst_behandler_dann_pzr` UND
`tests/test_datenerfassung_pausen.py` (voller Neupatientenfluss).

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
- **Sprachband-EQ vor dem STT (W-STIMME-EQ 04.09.2026 — nicht rückbauen):**
  Chef nach dem Flughafen-Testanruf (Session 55f9b05a, 04.09. 00:44):
  „noise filter, kompressoren mit verstärkung der stimmfrequenzen und
  unterdrückung des rests mit eq". `sip_bridge.stimme_filtern` läuft auf
  dem 16-kHz-PCM **nach** dem Resample, **bevor** das WAV an
  `/api/listen` geht (`sip_bridge/stimme.py`) — STT/TTS/Ports unangetastet.
  Kette (ffmpeg, schon im Image fürs Jingle): Hochpass 160 Hz + Tiefpass
  4,5 kHz, `afftdn` (Rauschen), EQ senkt 250 Hz / hebt 900+1800 Hz
  (Formanten) / senkt 3,5 kHz, Kompressor (Makeup +8 dB), Gate −40 dB. Aus:
  `BRIDGE_STIMME=0`. Docks hören den Rohweg weiter (nur Telefon).
  Tests: `tests/test_sip_stimme.py` (offline, skip ohne ffmpeg).
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
- **Auslassungspunkte (Paket 7 / Punkt 8, 09.09.2026):** ein Zug-Ende mit
 `...` (ASCII, >=2 Punkte) ODER `…` (Unicode) gilt IMMER als unfertig
 (`_ELLIPSE_RE`) — der Anrufer ist mitten im Gedanken verstummt. ASCII `...`
 endete vorher auf `.` und galt als fertiger Satz, so wurde „Ich hätte gern
 einen Termin für…“ nicht gehalten. Einzelner Punkt unverändert.
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
2c. **False-404-Fallback (W-ABSAGE-STALLONE 10.09.2026 — nicht
 rückbauen):** Live war „Stallone, S-T-A-L-L-O-N-E“ korrekt erkannt,
 `agentFindPatientAppointments` lieferte aber `not_found`, weil zusätzlich
 die Rufnummer des ANRUFERS (Michael Petsas) mitging und nicht zur Akte des
 Bruders passte. `kern/calendar.find_patient_appointments` prüft einen
 solchen 404 jetzt sicher über zwei unabhängige Lesewege:
 `masSearchPatients` (exakter Nachname, bei mehreren Treffern weiter
 Vornamen-Frage — nie raten) → eindeutige patientId →
 `masPatientLastDoctor.nextAppointment`. Der so gefundene Termin wird mit
 echter appointmentId/Kalender/Motiv normal bestätigt und anschließend
 punktgenau über `agentCancelAppointmentById` abgesagt bzw. verschoben.
 Kein Fallback bei echtem `no_upcoming`. Regression:
 `test_absage_stallone_fallback_trotz_fremder_anrufernummer`.
 **Nachlauf W-ABSAGE-SPURWECHSEL:** Nennt der Anrufer während eines neuen
 Slotangebots ausdrücklich einen BESTANDstermin („Termin von Sylvester
 Stallone absagen“, „meinen bereits gebuchten Termin löschen“), gewinnt die
 Absage und parkt den neuen Buchungsfaden. Nur ein nacktes „den absagen, der
 passt nicht“ lehnt weiter den angebotenen Slot ab. Regression:
 `test_bestandsabsage_ueberstimmt_laufendes_slotangebot`.
 **SIP-Sitzungssicherung:** Laufzeitobjekte mit `_`-Präfix
 (`_anruferReady`/`threading.Event`, offene TTS-Jobs) werden bewusst nicht
 nach JSON geschrieben. Fachzustand, erkannter Anrufer und CF-Tenant bleiben
 vollständig erhalten; ein Event darf nie wieder die gesamte Sicherung still
 verhindern. Regression: `test_session_persistenz.py`.
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

## Dossier + Lücken-Talk (W-DOSSIER 08.09.2026 — nicht rückbauen)

Chef: Parallelität und schnelle Spurwechsel, damit Wartezeiten überbrückt
werden — kein zweites Gesprächssystem. Job bleibt die Stimme für Termine,
Namen, Nummern. Talk ist eine Schlange fester Takte, die Job nur in einer
Lücke zieht.

- **Drei Zeiten:** FAST (Name/Hallo, kein Warten auf Akte/MAS) → HINTERGRUND
  (`kern/dossier.py`, gefüllt aus `anruferKartei` + Sammler + MAS-Kontext) →
  MUND in der Lücke (höchstens EIN Takt: Verlauf, dann PZR).
- **Lücke:** Hintergrund/Vorrat läuft oder Job hat geerntet und die nächste
  Pflicht kann warten. **Keine Lücke:** Ziffern-Readback, Slotwahl,
  „Soll ich so eintragen?“, Transfer. Fragen nie in die Totzeit
  (Kartei-Füller bleibt Feststellung).
- **Spurwechsel:** „Kontrolle“ schon gesetzt, Anrufer sagt „brauch noch ein
  Implantat“ → Job wechselt auf Implantat-Besprechung, Slot-Vorrat weg.
  „Letztes Mal Implantat, alles gut“ wechselt nicht. Talk bucht nie.
- **MAS:** Lesen wie bisher (`caller-context` / `karteikarte`) landet im
  Dossier, nicht nur im Prompt. Schreiben: Hangup-Report bleibt; dazu
  `gedaechtnis.fakt_senden` im Hintergrund bei festem Verlauf, PZR-Ja und
  Spurwechsel (eigene Event-Id `telefonki:fakt:<sid>:<n>`). Mund wartet nie.
- Tests: `tests/test_dossier.py`.

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

## Stille-Garantie (W-STILLE 29.08.2026 / W-FUELLER-EINER 08.09.2026 — nicht rückbauen)

Chef 29.08.: "es darf NIE zum Schweigen kommen". Chef 08.09.: erster Ton
unter 2 s — und NIE drei Entschuldigungen hintereinander („ich schaue
nach" / „einen Moment" / „kurzen Augenblick").
Zwei Verteidigungslinien, beide Stimmen:

- **Server-Füller nur bei Kalender/Werkzeug** (29.08. abends, Chef: auf
  „wie heißt du" kam „einen Moment, ich schaue eben nach"): geratene
  SUCHEN/AKTE-Füller nur wenn `filler.vermutet()` trifft. `_ALLGEMEIN`
  behauptet kein Nachschauen. Identität/Smalltalk (`_RE_PLAUSCH`) nie
  Kalender-Füller. Hängt die schnelle Phase (Buchung/Readback), kommt
  nach `FILLER_SPAET_S` (0,8 s) EIN neutraler Satz — sonst 7–32 s
  Totenstille (Live 06.09.).
- **Genau EIN Warte-Satz** (`FILLER_MAX=1`, 08.09.): kein Nachschub-
  Sermon. Sätze kurz (`MAX_VORAB` 28 Zeichen, ~1,4 s), damit sie die
  echte Antwort nicht hinter die 2-s-Grenze schieben. Inhalt (Vorab-Satz,
  `sag:`-Ansage, festes Audio) beendet die Kette. Die Brücke wirft
  ungehörte Warte-WAVs weg, sobald das Reply da ist.
- **Kartei-Füller statt Neutral** (W-KARTEI-FUELLER, 08.09.): liegt
  `sit["karteiFillerText"]` (kein `?`, nur Buchung, nicht Confirm/Slot/
  Nummer), spielt `_filler_url` diesen Satz einmal — sonst „Einen Moment.“
- **Dock-Watchdog (zweite Linie, greift auch bei totem Server/Netz):**
  beide Docks laden beim Boot `GET /api/notfall`
  (`dienst.NOTFALL_SAETZE`, 3 Stufen — Live spielt max. EINE, `WACHT_MAX=1`,
  und nur wenn 2 s kein Server-Ton kam; ein Füller stoppt den Wächter)
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

### Anmeldung als globales Anliegen (W-ANMELDUNG 09.09.2026 — nicht rückbauen)

„Anmeldung“, „Empfang“, „Buchhaltung“ oder „Mitarbeiter“ bedeutet nicht
automatisch, dass Bianca zu einem zufälligen Arzt weiterleiten soll. Beim
ersten Wunsch erklärt sie ihre Produktrolle: Sie ist die Telefonassistentin,
entlastet die Anmeldung und kann das konkrete Anliegen direkt übernehmen.
Danach hört sie auf das Anliegen. Steht es schon im ersten Satz
(`Anmeldung, ich möchte meinen Termin absagen`), gewinnt sofort der passende
sichere Task.

Besteht der Anrufer ein zweites Mal auf einem Menschen, darf Bianca nur ein
DB-Forwarding verbinden, dessen Name/Hinweis EXAKT zur verlangten Rolle passt.
Die Ein-Ziel-Rückfallregel für Ärzte gilt hier ausdrücklich nicht. Ohne
Rollenziel bietet Bianca jetzt — und nur nach diesem ausdrücklichen Bestehen —
einen echten Rückrufwunsch über den ABGEBEN-Fluss an. Direkte namentliche
Arztwünsche, Jingle und echte Transfers bleiben unverändert. Eine geparkte
Buchung wird auf „Dann machen wir mit dem Termin weiter“ wieder aufgenommen.
Das zweite Bestehen bleibt über dazwischenliegende Anliegen-Sätze hinweg
erkennbar: Nach „Mitarbeiter“ → Anliegen erklären → „Verbinde mich mit dem
Personal“ beginnt die Rollen-Erklärung nicht wieder von vorn.
Tests: W-ANMELDUNG-Blöcke in `tests/test_weiterleiten.py`.

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

## Servicebeschwerde vs. Notfall, Upsell-Sperre (W-ANLIEGEN-ART 09.09.2026 — nicht rückbauen)

Zusatzangebote (PZR-Mitbuchung, Bleaching) dürfen NICHT kommen, während sich
jemand beschwert oder einen Notfall hat — das wirkt taktlos.

- **Klassifikation** (`kern/anliegen_art.py`, bianca-frei): `art(text)` trennt
  notfall (starke Schmerzen, Blutung, dicke Backe, ausgeschlagener Zahn) >
  beschwerde (Wartezeit, Unfreundlichkeit, Reklamation, Ärger) > klinisch
  (Schmerz/empfindlich ohne Notfallmarker). `merken(sit, text)` hält die
  höchste gesehene Lage sticky in `sit["anliegenArt"]`.
- **Upsell-Sperre**: `flow.zug` ruft `anliegen_art.merken`, `flow._einschub`
  fragt `upsell_gesperrt(sit)` — bei aktiver Beschwerde/Notfall entfallen die
  PZR-/Bleaching-Angebote (Spur `anliegen-art`). Notfall-Routing der Buchung
  (Akut-Motive) bleibt unverändert; der Rückblick (Verlaufsfrage) ist kein
  Zusatzangebot und bleibt erlaubt.
- **Notaus/Stufen** `ANLIEGEN_ART=off|shadow|enforce` (Default **off** =
  byte-identisch). shadow loggt `anliegen-art-shadow`, ändert nichts; enforce
  sperrt.
- Tests: `tests/test_anliegen_art.py` (offline). Rollout: erst shadow, dann
  enforce. **Live seit 09.09.2026 auf `enforce`** (pickadoc1) — sehr
  konservativ (`upsell_gesperrt` greift NUR bei beschwerde/notfall, nie bei
  klinisch/Schmerz; schlimmstenfalls ein ausgelassenes Zusatzangebot).

## Evidenzbasierter Fakten-/Erledigt-Wächter (W-FAKTEN-WACHE 09.09.2026 — nicht rückbauen)

Wie Claras UNVERIFIED_ACTION_FALLBACK: eine gesprochene Erledigt-Behauptung
(„Ihr Termin ist gebucht/abgesagt/verschoben", „ich habe eine Notiz gemacht",
„in die Kartei aufgenommen", „ich stelle Sie jetzt durch") darf nur raus, wenn das passende Werkzeug
ERFOLGREICH lief. Wahrheit ist das Tool-Ledger (`sit["tools"]` bzw. die Marken
lastBook/lastCancel/lastMove/lastNote/lastCreate aus `kern/sitzung.merke_tool`
oder ein echtes nummeriertes `weiterleitungZiel`),
NIE der LLM-Text.

- **Erkennung** (`kern/fakten_wache.py`, bianca-frei): `unbelegte_behauptung`
  prüft je Satz gegen `AKTIONEN` (buchen/absagen/verschieben/transfer/notiz/anlegen) und
  das jeweilige Evidenz-Prädikat. Reine Fragen („soll ich eintragen?")
  zählen nicht als Behauptung; ein konkretes Slotangebot oder eine
  vorausgehende Tatsachenbehauptung wird durch ein angehängtes „passt Ihnen?"
  aber nicht mehr entschärft. Kurze Gesprächsbestätigungen
  („notiert", „Ihre Angaben aufgenommen") zählen ohne ausdrücklichen
  Notiz-/Aktenbezug ebenfalls nicht — sonst würde `enforce` legitime
  Datenerfassung unterbrechen.
- **Nur LLM-Pfad** (`bianca/agent._fakten_wache_anwenden`, direkt nach
  `_nachbessern`): der deterministische Fluss ist ohnehin evidenzbasiert. shadow
  loggt nur `fakten-wache-shadow`; enforce ersetzt die unbelegte Behauptung
  durch eine ehrliche Absicherung + die offene Pflichtfrage (durch den
  Wiederholungs-Wächter).
- **Notaus/Stufen** `FAKTEN_WACHE=off|shadow|enforce` (Default **off** =
  byte-identisch, der bestehende `_ERLEDIGT_RE`-Guard bleibt unberührt).
- Tests: `tests/test_fakten_wache.py` (offline). Rollout: erst shadow gegen
  Replays, dann enforce. **Live seit 09.09.2026 auf `enforce`** (pickadoc1):
  insbesondere darf „Ich habe Ihre Akte angelegt“ nach einem Nummernfragment
  nie ohne erfolgreiche `lastCreate`-/`lastBook`-Evidenz gesprochen werden.
  Ebenso werden Thaler-Sätze wie „Ich leite die Verbindung jetzt ein“ ohne
  echte Zielnummer ersetzt, statt den Anrufer in einer Phantom-Weiterleitung
  warten zu lassen. Eine erfolgreiche `praxis_notiz` zählt wie
  `note_appointment` als Notiz-Evidenz; fehlgeschlagene Notizwerkzeuge nie.

### P0-Schreib- und Kalenderbeweis (10.09.2026 — nicht rückbauen)

- **Name und `patientId` sind eine untrennbare Bindung:** `kern/patients.py`
  merkt am Buchungskontext `patientIdBound` plus Karteinamen. Jede
  Namenskorrektur räumt sofort Akte, Termine und alte Schreibziele.
  `calendar.book_slot` und `note_appointment` brechen vor jedem Write ab,
  wenn gesprochener Name und gebundene ID auseinanderlaufen. Repro:
  Session `2ec59b80` („Killnir“ durfte nie auf die Kellner-Akte buchen).
- **HTTP 200 reicht nicht:** `calendar.book_slot` liest jede
  `masBookAppointment`-Antwort unabhängig über die Patienten-Terminliste
  zurück. Patient, Startminute, Kalender und echte Termin-ID müssen gemeinsam
  passen. Bei Abweichung: kein Buchungs-/SMS-Erfolg, kein Notiz-Write auf die
  Antwort-ID, kein zweiter Buchungsversuch; stattdessen echter
  Prüf-/Rückrufvorgang (`verwalten.buchung_pruefen_notiz`). Repro:
  Tom Schumann, Antwort-ID zeigte später auf einen anderen Slot.
- **Kalenderfakten sind ebenfalls evidenzpflichtig:** freie/volle Slots,
  bestehende/nicht bestehende Termine, SMS, Rückruf und Transfer sind in
  `kern/fakten_wache.py` abgedeckt. Slot- und Termin-Aussagen brauchen den
  passenden erfolgreichen Lese-Tool-Eintrag; Transfer zusätzlich einen
  ausdrücklichen Wunsch im aktuellen Nutzersatz. Die P5-Vorab-Ausgabe wird
  schon satzweise geprüft, damit die Halluzination nicht vor der finalen
  Antwortwache hörbar wird.
- Deterministische Zusatznotizen werden erst als geschrieben angesagt, wenn
  `masAppointmentNote` erfolgreich war und im Tool-Ledger steht. Bei Fehler
  entsteht ein echter Rückrufvermerk statt einer leeren Zusage.
- Regressionen: `tests/test_patients.py`, `tests/test_notiz.py`,
  `tests/test_fakten_wache.py`.

## Task-Grenze vor dem Flow-Monolithen (W-TASK-GRENZE 09.09.2026 — nicht rückbauen)

Erster Schritt zur Entkopplung des ~2.000-Zeilen-`bianca/flow.py`, OHNE
Fachlogik zu verschieben: `bianca/tasks.py` setzt eine typisierte Task-Grenze
davor.

- **Registry** (`tasks.REGISTRY`/`TASK_TYPEN`): die fachfreien Aufgaben
  buchen/absagen/verschieben/auskunft/anmeldung/rueckruf, jeweils mit dem
  bewährten Eintrittspunkt (flow/verwalten/weiterleiten). `flow.zug` bündelt
  diese Wege bereits — die Registry ist Introspektion/Doku.
- **Transparenter Adapter** (`tasks.zug`): ruft `flow.zug` UNVERÄNDERT auf und
  gibt dessen Ergebnis Byte für Byte zurück (gleiche Antwort, gleiche
  Werkzeugaufrufe). Zusätzlich nur ein inertes Ledger `sit["taskLedger"]`
  (Typ + Lifecycle active/done/parked/failed via `tasks.lifecycle`).
  `bianca/agent.user_turn` ruft den Fluss jetzt über `tasks.zug` statt direkt
  `flow.zug`.
- **Notaus** `TASK_ADAPTERS=0` => `tasks.zug` ist exakt `flow.zug` (kein
  Ledger). Default an — der Adapter ist bewiesenermaßen pass-through
  (`test_adapter_ist_transparent`).
- Tests: `tests/test_tasks.py` (offline, inkl. Paritätsbeweis mit/ohne Adapter).

## Eingeschobene Anliegen fortsetzen (W-HIRN-AUTORESUME 09.09.2026 — nicht rückbauen)

Wird mitten in einer Buchung ein zweites Anliegen eingeschoben (schnelle
Auskunft, kurze Absage), soll Bianca danach von selbst zur Buchung
zurückkehren — ohne Datenverlust und ohne Schleife.

- **Tasklokaler Checkpoint** (`kern/hirn.py`): beim Parken eines aktiven
  Anliegens (`_anhaengen`/`zurueck`) sichert das Hirn einen Schnappschuss des
  Sammlers plus Suchzustand (`_CP_SIT_KEYS`: offered, gefundenKey,
  verschiebRichtung, slotVorrat, vorratFuer, upcoming, past, patient,
  flussFrage, slotGesperrt) in `anliegen["checkpoint"]`. So überschreiben sich
  Patienten-/Slotzustände verschiedener Anliegen nicht.
- **LIFO-Rücksprung nach Abschluss**: erreicht die aktive Aufgabe
  `phase=fertig`, reaktiviert `_nach_abschluss_ruecken`/
  `abschluss_ruecksprung_live` das ZULETZT geparkte Anliegen (vor dem nächsten
  offenen) und spielt dessen Checkpoint zurück. `phase=gebucht` bleibt
  ausgenommen (die Maschine fragt dort selbst weiter).
- **Genau eine Rückkehrbrücke** (`bianca/agent._auto_resume_anhaengen`, im
  `_maschinen_antwort`-Pfad): `hirn.rueckkehr_bruecke` + die gespeicherte
  Pflichtfrage werden EINMAL an die Maschinen-Antwort gehängt; nie mitten in
  Buchung/Transfer/Diktat (book/hangup/transfer/warte).
- **Notaus dreistufig** `HIRN_AUTO_RESUME=off|shadow|enforce` — seit
  13.09.2026 ist **enforce** der Default (im CODE, s. W-EINGEHEN). `off` ist
  das byte-identische Alt-Verhalten (nächstes OFFENES Anliegen wie bisher,
  kein Checkpoint, kein Rücksprung), `shadow` schreibt nur die Wächterspur
  (`auto-resume-shadow`) und ändert kein Verhalten.
- Tests: `tests/test_auto_resume.py` (offline). Rollout: erst `shadow` gegen
  Replays, dann `enforce`.

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

## Thaler: sechs buchbare Besuchsgründe (W-THALER-MOTIVE 09.09.2026 — nicht rückbauen)

Chef: Thaler möchte telefonisch NUR Neupatient, Kontrolle, Schmerzen,
Besprechung Zahnersatz, Besprechung Implantate und PZR buchbar haben.
Andere Katalogtermine dürfen nicht angeboten oder still auf Kontrolle
zurückfallen.

- `kern/zimmer_map.buchbarer_katalog` filtert den pro Anruf frisch aus der
  DB geholten Katalog auf exakt diese sechs stabilen Motiv-IDs/-Namen. Die
  lokale Tenant-Datei ist nicht die Wahrheit.
- `mapping_text` ordnet Eingriffswünsche sicher der erlaubten Erstberatung
  zu: Füllung/Krone/Prothese -> ZE Besprechung; Implantat-Eingriffe ->
  IMP Besprechung. Der Originalwortlaut bleibt für die Terminnotiz erhalten.
- Klare andere Wünsche (z. B. Wurzelbehandlung/KFO/Bleaching) setzen kein
  Motiv und starten keine Slot-Suche. Bianca nennt ausschließlich die sechs
  freigegebenen Gruppen und bleibt bei der Besuchsgrundfrage.
- Die Grenze greift nur bei aktivem Thaler-`zimmerMap`/Thaler-Mandant.
  MedDent und Blessing bleiben byte-identisch.
- Tests: `tests/test_thaler_motivgrenze.py`, dazu
  `tests/test_funktionskalender.py`/`tests/test_zimmer_map.py`.

## Thaler: sichere Buchungs-/Verschiebebestätigung (W-TERMIN-BESTÄTIGUNG 09.09.2026 — nicht rückbauen)

Live Helmich/Donaubauer 09.09.: Eine Bitte, die Termindaten zu wiederholen,
löste nach zwei unklaren Antworten ohne Ja eine echte Buchung aus. Beim
Verschieben wurde „Freitag, den 23.“ relativ zu heute als September statt
zum Bestandstermin am 21. Oktober gelesen; ein 30-Minuten-Motiv-Fallback bot
einen für den 60-Minuten-Bestandstermin ungültigen Slot, und nach dessen
Ablehnung sprang die Alternative wieder in den September.

- `flow._termin_nochmal`: Wiederholen/Abgleichen bleibt in `bestaetigen`;
  falsche Uhrzeit wird gegen `slotIso` korrigiert. Ohne ausdrückliches Ja
  niemals `book_slot`, auch nicht nach mehreren unklaren Antworten.
- Explizit verlangte Termindaten dürfen den allgemeinen Wiederholungs-Wächter
  passieren — sonst blieb nur „Soll ich eintragen?“ übrig.
- Monatlose Verschiebe-Zieltage werden am bekannten Bestandstermin aufgelöst.
- Verschiebe-Slots nutzen exakt Kalender + Motiv des Bestandstermins, ohne
  kürzeren Kontroll-Fallback. Ein belegter Zielslot liefert Alternativen ab
  dessen Datum und hält den deterministischen `verschieb_angebot`-Zustand;
  das LLM darf keinen Erfolg erfinden.
- Regressionen: Live-Sätze in `tests/test_thaler_rebrovic.py` und
  `tests/test_slot_behandler.py`.

## Thaler: New-York-Formularfaden (W-THALER-FORMULAR 09.09.2026 — nicht rückbauen)

Live New-York/Andrejevic 08./09.09.: „noch keinen Termin, aber nicht neu“
wurde als Neupatient und teils als Name „Nicht Neu“ geerntet; die Frage
„Soll ich meinen Namen buchstabieren?“ fiel ans freie LLM, ein Reiseort
verdrängte die offene Zeitfrage, und nach einer erfolglosen Slotsuche wurde
dieselbe Rückrufmeldung bei jedem Folgesatz erneut gesprochen.

- „nicht neu“ gewinnt auf der Schonmal-Frage deterministisch als
  Bestandspatient; die Floskel ist für die Namens-Ernte gesperrt.
- Ein ausdrücklicher Behandlungswunsch ohne das Wort „Termin“ („Ich brauche
  eine Füllung“) öffnet auch während des parallelen Katalog-Ladefensters
  sofort den sicheren Buchungsflow. Thaler merkt dabei den normalisierten
  Grund (Füllung → Zahnersatz-Besprechung) zunächst ohne Motiv-ID; die ID wird
  nach dem Katalog-Lauf regulär behandlerscharf aufgelöst. Kostenfragen und
  verneinte Wünsche starten keine Buchung.
- Meta-Fragen zum Buchstabieren bleiben im Formular und führen gezielt in
  die sichere mehrzügige Nachnamenaufnahme.
- Ein Reiseort ist weder Datenbestätigung noch Zeitwunsch: offene Nummern-
  Readbacks bleiben offen; auf der Zeitfrage fragt Bianca nach den Tagen vor
  Ort und der Tageszeit.
- Nach leerer Slotsuche + echter Rückrufnotiz ist der Vorgang beendet.
  Dank/Abschied startet keine erneute Suche; ein ausdrücklicher weiterer
  Termin öffnet den Flow bewusst neu.
- `buchstaben.deute` verlangt bei „also <Name>“ ohne echte Buchstabenkette
  einen ähnlichen gesprochenen Namensanker. Normale Prosa wie „aus dem
  Kalender, also entfernen“ wird nicht mehr als Nachname gespeichert.
- Regressionen: `tests/test_thaler_new_york.py` plus
  `test_absage_varianten_erkannt`.

## Blessing: Notfall + Dokument-Vorsprache (W-BLESSING-AKUT 09.09.2026 — nicht rückbauen)

- Der Live-DB-Agent (DID 4120) trägt kompakte Marker in den von der
  `onPickadocPhoneCall`-CF tatsächlich gelieferten Promptfeldern:
  `NOTFALL-SOFORTREGEL` und `DOKUMENT-VORSPRACHEREGEL`. Nicht in eine lokale
  Tenant-Datei verschieben — DB bleibt die Wahrheit.
- `kern/praxisregeln.py` aktiviert den festen Weg nur bei diesen DB-Markern.
  Andere Hautarztpraxen bleiben unverändert.
- Akut/Notfall während der aus dem DB-Prompt gelesenen Sprechzeit: kein
  normaler Termin, jetzt kommen, keine feste Uhrzeit, Wartezeit, garantiert
  schnellstmöglich gesehen/versorgt. Außerhalb ohne Lebensgefahr: 116 117.
  Atemnot/Zungen-/Mund-/Halsschwellung, Kollaps/Bewusstlosigkeit oder schwere
  Arzneimittelreaktion: 112, nicht in die Praxis schicken.
- Rezepte/Überweisungen/Krankmeldungen werden telefonisch nicht bestellt oder
  zur Abholung zugesagt: persönliche Vorsprache, gegebenenfalls kurze
  ärztliche Kontrolle. Der Flow fragt dafür weder Name noch Rückrufnummer ab.
- Tests: `tests/test_blessing_praxisregeln.py` plus
  `tests/test_blessing_derma.py`/`tests/test_zahn_katalog.py`.

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
- **W-ARZT-TITEL (09.09.2026):** CF-Kalender heißen ausgeschrieben
  „Doktor Michael Petsas“ / „Doktor Theodosios Patrikis“. `arzt_sprechname`
  erkennt „Doktor“ genauso wie „Dr.“ und spricht die Auswahl als
  „Doktor Petsas oder Doktor Patrikis“ — nie titellos. Die reine
  Mund-Umschrift für Patrikis ist `Pattriekis`: kurzes deutsches „Pat“,
  nur leicht betontes „rie“. `Pat-ri-kis` klang englisch wie „Patrick“,
  `Pa-tri-kis` dehnte zuvor das „Pa“ zu stark. Live-Gegenprobe mit Bianca:
  fünf von fünf Würfen wurden ohne Keyword-Hilfe als „Patrikis“ erkannt.
- Tests: `tests/test_arzt_default.py` (9, offline);
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
  fragt) → bei Ja direkt `"beratung"` + `bleachingInfo="unverbindlich"`:
  „Der Doktor entscheidet … besonders bei Zahnersatz im Frontbereich. Ich
  buche das unverbindlich als Besprechung mit ein." Keine zusätzliche
  Zahnersatz-Verhörfrage. Die alten `"check"`-Zustände bleiben nur für
  laufende Sitzungen während eines Deploys kompatibel. Explizit genannter
  Zahnersatz/Unsicherheit führt ebenfalls zur Berate-Notiz.
- **Tenant-Wache** (`gehirn.bleaching_faellig`): nur wenn der NEUE Termin
  selbst eine Zahnreinigung ist (`ist_pzr_grund`) UND der Motiv-Katalog der
  Praxis eine Aufhellung führt (`_BLEACH_RE` gegen Namen). Derma-Praxen
  (Blessing) sehen die Frage nie. Preis (350 €) und Dauer (+1 Std.) sind die
  Chef-Ansage für SEINE Praxis — führt ein anderer Zahn-Tenant Bleaching,
  vorher Preis/Dauer klären!
- **Gebucht wird IMMER die Zahnreinigung** (kein zweiter Slot, kein
  Motiv-Wechsel — Meddent hat kein Kombi-Motiv): nach Ja bekommt der Termin
  die unverbindliche Bleaching-Besprechung als Popup-Notiz; der Doktor prüft
  die Machbarkeit, besonders bei Zahnersatz im Frontbereich.
- **Bianca berät NIE selbst medizinisch:** bei Unsicherheit/Zahnersatz sagt
  sie den Chef-Satz (Notiz gemacht, der Doktor schaut es sich in Ruhe an
  und berät). Faktenwissen fürs LLM (Nachfragen wie „Was kostet das?")
  hängt `flow.status_zeile` an, solange die Frage offen ist — kein globaler
  Prompt-Absatz, damit fremde Tenants die Meddent-Preise nie sehen.
- Regex-Wachen: `_ZAHNERSATZ_RE` matcht NICHT „am dritten Oktober" (nur
  „die Dritten"); Zwischenfragen halten die Bleaching-Frage offen (wie pzr).
- Tests: `tests/test_bleaching.py` (17, offline).

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
  Kollege, Partner, Chef, Schwieger-, Betreuer, Pfleger …). Unbekannte
  Substantive nach mein/ein werden bewusst NICHT automatisch zur Person:
  „Besprechung für eine (neue) Prothese", „für meine Krone" und „für ein
  Implantat" sind Behandlungsgründe, keine Dritten (Live 08.09.2026).
  Stopwörter (Woche, Kontrolle, Donnerstag, Frau Doktor) sind ebenfalls kein Dritter.
  Extra-Netze: „für ihn", „ich rufe für Peter an", „im Auftrag/Namen von",
  „stellvertretend". Rollen kommen aus der Tabelle, unbekannte Personen
  brauchen ein solches eindeutiges Personensignal — nie aufgrund eines
  beliebigen Hauptworts raten.
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
  uns?", „bei welchem Behandler Ihr Sohn zuletzt war?", „Damit ich Ihren
  Sohn in der Kartei finde: Wie lautet der Nachname?", danach nur der
  Vorname, „Und ist Ihr Sohn privat oder
  gesetzlich versichert?" (`fuer_wen_phrase`, Nominativ/Akkusativ). Häufige
  Rollen sind als feste Sätze vorgewärmt.
- **Termin-Notiz:** „Telefonisch gebucht von Angehörigem (Sohn-Termin):
  Kiriakos Tzannis, Kontakt-Nummer … gehört dem Anrufer." — die Praxis
  sieht, WER angerufen hat.
- Tests: `tests/test_fuer_wen.py` (offline).

## Keine Doppelschleifen nach der Bestätigung (W-SCHLEIFE 04.09.2026 — nicht rückbauen)

Live-Anruf 03.09. ~22:44 UTC (Kiriakos Tzannis, Flughafen): drei
Inhalts-Schleifen hintereinander — „schon mal bei uns?", Behandler, dann
viermal „Soll ich das so eintragen?" trotz „Nein" / „Der Name." /
„Ändere den Namen auf Levi".

- **Anlauf „Uh"** (`gehirn._ANLAUF_RE`): „Uh ja." ist Ja, „Uh Dr. Petter"
  verliert das Füllwort. Englisches „Correct" zählt als Ja (`_JA_RE`).
- **Kein Namensdiebstahl vom Behandler:** auf die Arzt-Frage und bei
  „Dr./Doktor …" ohne „ich heiße" wird kein Patientenname geerntet
  (`_name_aufnehmen`). „Uh Dr. Petter" darf nie als „Udrpetter" landen.
- **Änderungs-Zweig** (`flow._aenderung_zug`): Nein auf die Readback-
  Frage lässt Slot und Angebot stehen und setzt `frage=aenderung`.
  „Der Name." / „Ändere den Namen auf Levi" leert nur die Patienten-
  Identität (`name_fuer_aenderung_leeren`) und fragt „Wie heißt Ihr
  Sohn?" — nie wieder die Bestätigung, solange der Name fehlt.
  Nummer → Telefonfrage, Zeitpunkt → Wunschzeit (dann Slot weg).
- **Unbekannter Behandler:** „Keine Ahnung, wie der Zahnarzt heißt"
  quittiert „Kein Problem, das finden wir schon." und stellt im
  selben Zug die nächste Pflichtfrage (Name), statt nur zu plaudern.
- Tests: `tests/test_schleife.py` (offline).

## MedDent-Härte: Nonsense, Dokumente, Floor (W-MEDDENT 04.09.2026 — nicht rückbauen)

Nach Auswertung der Live-Anrufe 04.09.2026 (STT-Müll → Plaudern, Rezept-
Zusagen, Boah auf Hörfehler, PZR mitten in Wunschzeit, „Wem kann ich“):

- **Talk-Unklar:** `kern/gespraech.wirkt_unklar` — 1–2 Tokens ohne Job/
  Kurz-OK/Ziffern starten kein Thema (`unklar=True`). `agent.user_turn`
  antwortet mit `UNKLAR_ANTWORT` („Das habe ich nicht verstanden…“), kein
  LLM. Anstand greift bei Unklar nicht.
- **Rezept/Überweisung:** Prompt-Harte + `_abgeben_zug` sagt klar „kann ich
  nicht ausstellen“; Hirn-`stand_block` verstärkt die Regel.
- **Barge-Floor:** echter Einwand (`gesagt` nicht leer/Echo) → kein Rest
  („wo war ich“); nur leerer/Echo-Einwurf setzt fort (W-SVETLANA).
- **Weiterleitung:** bei `frage=anbieten` auch erneutes `erkannt()` wie Ja.
- **PZR/Einschub:** nicht im selben Zug wie frische `wunsch`-Ernte.
- **Anrufer-Check:** bei Termin/Öffnungszeiten im Satz kurzer Vorsatz
  „Gerne helfe ich Ihnen weiter.“ vor der Erkennung.
- **Begrüßung:** `Wem kann ich` → `Was kann ich` (DB + `gruss_saeubern`).
- Tests: `test_gespraech` (unklar), `test_hirn` (Rezept), `test_unterbrechung`
  (Floor), `test_greeting_bianca`, `test_anstand` (STT-Müll).

## Öffnungszeiten + Wegbeschreibung aus Fakten (W-PRAXISAUSKUNFT 09.09.2026 — nicht rückbauen)

Session `dda01bf3b329461aac70aeb0d4a8e2b6` (technische Audio-Probe):
Der beim Transport beschädigte Testsatz wurde als „Pflungszeiten“ und „wie ich
die praktisch erreiche“ transkribiert. Die Talk-Schicht machte daraus einen
Gärtnerei-Witz, obwohl Öffnungszeiten und Weg im Mandantenprofil standen.

- `kern/wissen.praxis_antwort` erkennt Öffnungszeiten eng fuzzy (lange Wörter,
  hohe Schwelle) und Anfahrtsfragen auch bei diesem STT-Verhörer.
- Die Antwort ist deterministisch: zuerst Fakten aus `tenant["dbPrompt"]`,
  danach `tenant["wissen"]` als lokaler Rückfall. Das LLM formuliert und rät
  auf diesem Weg nicht.
- Werden beide Dinge gefragt, nennt Bianca in EINEM Zug die echten Zeiten und
  die vollständige Wegbeschreibung. In einer laufenden Aufgabe hängt sie
  danach die offene Pflichtfrage wieder an.
- MedDent trägt die aktuellen Zeiten zusätzlich im lokalen Rückfall:
  Montag bis Donnerstag acht bis achtzehn Uhr, Freitag acht bis sechzehn Uhr,
  außerdem nach Vereinbarung. Die DB gewinnt weiterhin, wenn sie erreichbar ist.
- Regressionswachen: `tests/test_wissen.py` (Live-Verhörer, DB-Vorrang,
  LLM-Bypass und Wegabschnitt).

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

## Semantischer Task-Router + sichere Werkzeuge (08.09.2026 — nicht rückbauen)

Das Haupt-LLM erkennt natürliche Anliegen über `kern/task_router.py` und
übergibt sie an `kern/hirn.py`; es führt keine Kalenderaktion selbst aus.
Auch während einer laufenden Aufgabe bekommt das freie Gespräch nur
`select_task` (nach einer echten Buchung zusätzlich `note_appointment`),
nie `book_slot`, `cancel_appointment`, `move_appointment`, `offer_slots`,
`list_appointments` oder `create_patient`. Ein klar anderes Anliegen parkt
die laufende Aufgabe; Smalltalk beantwortet das Modell ohne Task-Wechsel.
**W-NAMEN-SCHLEIFE (08.09.2026, Live-Anruf 0c78ca65):** Das Modell darf im
freien Gespräch NIE selbst nach Name, Nummer, Behandler, Grund, Wunschzeit
oder Versicherung fragen — diese Fragen gehören dem FlowManager. Ein frisch
gegen den Praxiskatalog geernteter Besuchsgrund plus ausdrücklicher Wunsch
startet die sichere Buchungsaufgabe sofort, auch wenn Intent/LLM das
`select_task` versäumen („Ich möchte eine Besprechung für eine neue Prothese“).
Zwei unverständliche Antworten hintereinander wiederholen nie dieselbe
Aufforderung: bei vorhandenem Grund zieht Bianca in den echten Flow zurück,
sonst fordert sie einmal zum Neustart des Anliegens auf.
Notaus: `TASK_ROUTER=0` stellt die alte Werkzeugliste wieder her. Tests:
`tests/test_task_router.py`.
**W-MISCHZUG (09.09.2026):** Bei „Ja/Nein, aber …“ gehen weder die Antwort
auf den laufenden Dialogschritt noch das neue Anliegen verloren. Nur bei
nicht-destruktiven Fragen (`anrufer_check`, `schonmal`, `arzt_check`) erntet
der alte Flow zuerst den kurzen Präfix; anschließend deutet Intent/Task-Router
den Zusatz und kann die bisherige Aufgabe parken. Nummern-Readback, Slotwahl,
Buchungsbestätigung und Datendiktat bleiben unteilbar. Nach einem
Presence-Stups bestätigt das führende Ja ausschließlich „noch dran“ und
niemals die Patientenidentität. Tests: Mischzug-Blöcke in `test_hirn.py`,
`test_task_router.py` und `test_fuer_wen.py`.

## Frage nach bestehenden Terminen mitten in der Buchung (W-BESTANDSFRAGE 09.09.2026 — nicht rückbauen)

Live Petsas 08.09.2026 (Anruf a1d77850): der Anrufer fragte VIERMAL nach
seinen schon gebuchten Terminen („Habe ich noch einen anderen Termin diese
Woche?“, „Wann ist denn der andere Termin?“, „Ich glaube, ich hatte noch
einen anderen Termin gebucht.“) — Bianca hing im Buchungs-Slotangebot fest,
das Frei-LLM ERFAND jedes Mal „keine weiteren Termine im System“, OHNE je den
Kalender zu lesen (kein `agentFindPatientAppointments`). Ursache:
`kern/intent.py` behandelte „Termin“ im laufenden ANLEGEN/AENDERN als
Alltags-Erntewort (`_wechsel_verdacht` sprang nicht an), und `_FB_AUSKUNFT_RE`
kannte nur „einen Termin“, nicht „einen ANDEREN Termin“/„andere Termine“.

- **`_BESTANDSFRAGE_RE`** (eng gehalten) erkennt die Frage nach BESTEHENDEN
  Terminen: „habe ich (noch/andere/weitere/schon/überhaupt/eigentlich/
  bereits) … Termin(e)“, „wann ist/war (mein/der) (andere) Termin“, „welche
  Termine habe ich“, „ich hatte … Termin … gebucht/vereinbart/ausgemacht“,
  „mein/der/einen andere(r/n) Termin“ und die Nebensatz-Wortstellung
  „ich möchte wissen, ob ich noch einen Termin habe“. Ein blosser
  Terminwunsch („ich hätte gern einen Termin“, „ich möchte einen Termin
  vereinbaren“) fällt bewusst NICHT darunter.
- **Freie Termine sauber getrennt:** „Haben SIE noch einen Termin diese
  Woche?“ / „Welche Termine sind frei?“ ist eine Neubuchungsfrage
  (`_FREIER_TERMIN_RE`). Sie startet sofort den sicheren Formularfaden; das
  freie LLM darf weder Verfügbarkeit noch Patientennamen behaupten.
- **Einbau:** `_wechsel_verdacht` wertet einen Treffer auch mitten in der
  Buchung als Wechsel-Verdacht; `_fallback` und `_eindeutig` deuten ihn als
  WISSEN × VORGANG. Das Hirn parkt die Buchung (mit Checkpoint), schaltet auf
  `auskunft`, `verwalten` liest die Termine WIRKLICH und sagt sie an — danach
  führt Auto-Resume (enforce) zur Buchung zurück („So, zurück zu Ihrem
  Termin.“). Der bekannte Anrufer wird nicht neu nach dem Namen gefragt (der
  Nachname aus der Buchung bleibt im Sammler stehen).
- **Notaus:** `INTENT_SCHICHT=0` (Regex-Modus, wie vor W-HIRN). Tests:
  `tests/test_bestandsfrage.py` (Regex, Intent-Deutung, Hirn-Parken,
  verwalten-Lookup, Agent Ende-zu-Ende OHNE LLM).
- **Abschluss-Hörfehler (Live 09.09.2026):** Nach einer erledigten Aufgabe
  gelten kurze STT-Formen, die auf „Danke/Dank“ enden, als Abschied. So werden
  „Vielen Dank“ → „Seid Danke“ / „Dein Danke“ nicht mehr mit „nicht
  verstanden“ und anschließend der Schleifenbremse beantwortet.

## Name/Nummer mit langen Pausen (08.09.2026 — nicht rückbauen)

Erkannte Rufnummern überspringen die schwierige Datenerfassung; deshalb muss
der unbekannte Anrufer eigener Pflichtfall bleiben. `buchstabenTeil` sammelt
eindeutige Buchstabierfragmente über mehrere Züge. Nach einem fragmentierten
Namen sagt der Anrufer am Ende „fertig“; ein zusammenhängend buchstabierter
Name bleibt unverändert der schnelle Weg. „Ich kann nicht buchstabieren“
wechselt deterministisch auf langsames Nachsprechen. `telefonTeil` nimmt auch
Einzelziffern; eine fragmentierte Mobilnummer wird nicht schon nach zehn
Ziffern abgeschlossen, kürzere Sonderfälle enden ausdrücklich mit „fertig“.
Jede vollständige Nummer wird weiter Ziffer für Ziffer rückbestätigt.
**W-DATEN-FLOOR (08.09.2026 spät):** Teilstücke sind stille `warte`-Züge —
Bianca sagt nach einer Denkpause nicht mehr „Den Anfang habe ich“ und fällt
dem Anrufer dadurch nicht ins Wort; die Talk-Schicht bekommt Fragmente nie.
Die Namensfrage verlangt nicht mehr erst Vor- und Nachnamen und danach den
Nachnamen ein zweites Mal: Nachname einmal (sprechen oder direkt
buchstabieren), danach nur noch der Vorname. Gemischte Ketten wie
„P A P A wie Anton G R“ behalten auch die Buchstaben neben dem Tafelwort.
**W-VORNAME-FLOOR (08.09.2026, Live-Anruf Ramanujan):** beginnt der Anrufer
nach dem gesprochenen Vornamen zu buchstabieren („Srinivasa, S, R, I …“),
gilt das Wort noch NICHT als Turn-Ende. Bianca bleibt über die folgenden
Sprechpausen still; die Buchstaben korrigieren einen verhörten Wortanfang
und schließen bei passender Länge/Ähnlichkeit auch ohne „fertig“ ab. Ein
Vorname am Stück bleibt der sofortige Schnellweg.
Tests:
`tests/test_datenerfassung_pausen.py`.

## Auflegen, Icebreaker, Fokus (12.09.2026 — nicht rückbauen)

Chef 12.09.2026 nach mehreren Testanrufen (wörtlich): „sie fragt manchmal
immer noch wie geht es Ihnen, was unklug ist, da fragen vom job ablenken …
diese antwort ignoriert bianca komplett … bei mehreren turns wenn die
gespräche sehr lang sind verliert sich bianca in stille oder schleifen …
und Bianca soll lernen aufzulegen bei eindeutigen sätzen die ein gespräch
beenden wie tschüss auf wiederhören wiedersehen bis denn etc."

**W-ABSCHIED** — `kern/abschied.py` ist die EINE Stelle, die einen
Schlusssatz erkennt. Zwei Stufen, damit ein Hörfehler keinen laufenden
Vorgang abwürgt: unmissverständliche Kerne („auf Wiederhören", „tschüss")
gelten allein, Kurzformen („bis denn", „ciao", „schönen Tag noch") nur wenn
der Satz nach Abzug der Floskeln nichts anderes mehr trägt (höchstens
`MAX_KERN_WOERTER`). Umlaute kommen je nach Quelle als ö/oe/o an — die
Muster decken beides ab (live 12.09. rutschte „Auf Wiederhoeren!" durch und
das Modell bettelte „bitte nicht auflegen"). Eingehängt in
`bianca/agent.user_turn` VOR Intent/Fluss (`streng=True`, solange der
Anrufer Ziffern oder Buchstaben diktiert) und an den drei Abschieds-Returns
in `bianca/flow.py`, die den Satz vorher sprachen OHNE `hangup` zu setzen.
Notaus: `ABSCHIED_AUFLEGEN=0`.

**W-HALLO-ANTWORT** — `gehirn.hallo_frage_unpassend` unterdrückt die
Wohlsein-Frage, sobald ein Anliegen läuft (`hirn.aktiv`, `sammler["modus"]`)
oder der Satz nach `anliegen_art` Notfall/Beschwerde ist; `_hallo_form`
liefert dann eine Feststellung statt einer Frage. Stellt Bianca sie doch
(W-HALLO-PAUSE parkt den Wunsch in `anruferHalloOffenerText`), wird die
Antwort nicht mehr verworfen: trägt sie Inhalt (`ist_nur_wohlsein` ist
False), geht sie MIT dem geparkten Original in den Folgezug
(Spur `hallo-antwort-aufgenommen`).

**W-STUPS-GESAMT** — `stupse` wird bei jedem Anrufer-Satz genullt, `MAX_STUPSE`
greift also nur INNERHALB einer Stillephase. Live 11.09. (Session 9395e2ce,
109 Züge / 23 Minuten) wechselten sich deshalb 15-mal „Sind Sie noch dran?"
und dieselbe Frage ab. `kern/stille.py` zählt zusätzlich über den GANZEN
Anruf (`gesamt`): ab `PRESENCE_BIS` entfällt die Presence-Floskel, ab
`GESAMT_MAX` verabschiedet `agent._notleine` freundlich und legt auf — ein
offenes Anliegen wird vorher als echte Rückruf-Notiz gesichert. Presence
kommt nur beim ERSTEN Stups des Anrufs (dreimal „Sind Sie noch dran?" war
selbst die Schleife), das Talk-Thema nur ohne offene Pflichtfrage und nie
aus einer Beschimpfung (`anstand.unfein`). Der Schlusssatz fällt genau
einmal (`notleineGesagt`).
**Die Durchreiche gehört dazu:** `POST /api/stille` MUSS `hangup` melden,
`sip_bridge._stups` es beantworten (`_ausklingen_und_auflegen`) und
`bianca_web/app.js` den Anruf beenden — ohne diese drei Stellen sprach die
Notleine ihren Abschied und die Leitung blieb offen (live-Probe 12.09.:
derselbe Satz kam beim nächsten Stups erneut).

**W-FOKUS** — kein stummer Zug mehr: liefert das Modell nichts, antwortet
`agent._nie_stumm` mit der offenen Pflichtfrage; streichen alle Wächter den
Stups, gewinnt die Frage (Spur `stups-nie-stumm`); sind alle Frage-Varianten
verbrannt, kommt die Frage mit Präfix statt Presence. Nach `_FOKUS_MAX`
freien Zügen holt die Drift-Bremse zur Pflichtfrage zurück und räumt den
Talk-Stapel. Gegen den Ballast langer Gespräche: `wiederholung`-Gedächtnis
ist ein Fenster (`GEDAECHTNIS_SAETZE`), der LLM-Verlauf gedeckelt
(`llm.VERLAUF_MAX`, System-Kopf bleibt).

Tests: `tests/test_abschied.py`, `tests/test_fokus.py`, `tests/test_stille.py`,
Stups-Block in `tests/test_sip_vad.py`. Live-Proben (read-only, im Container):
`tools/_probe_abschied_live.py`, `tools/_probe_langgespraech.py`.

## Keine erfundene Anrede (W-ANREDE 13.09.2026 — nicht rückbauen)

Live-Probe 12.09.2026 mit UNBEKANNTEM Anrufer (keine übermittelte Nummer):
Bianca antwortete im ersten Zug „Einen Moment. Gerne, **Herr Meier**. Ich
buche Ihnen einen Termin zur Kontrolle." — den Namen hat niemand gesagt, das
Modell hat ihn erfunden. Bei erkannter Rufnummer fällt das nicht auf (dann
steht der echte Name in der Akte), einem fremden Anrufer wird so der Name
eines anderen Menschen vorgelesen.

`kern/anrede_wache.py` behandelt die Anrede deshalb wie jede andere Tatsache
(W-FAKTEN-WACHE): raus darf sie nur, wenn der Name BELEGT ist. Belegt sind
Sammler-Namen (nachname/vorname/name, `kontaktName` bei Dritt-Terminen),
der per Cloud-Function erkannte Anrufer, Kartei-/Patientenfelder sowie
Behandler- und Praxisnamen des Mandanten (`tenants.stt_keywords`,
`tenant["calendars"]`) — die kommen aus der DB, nie aus dem Modell. Titel
ohne Namen („Herr Doktor") und ein blosses „Herr oder Frau?" bleiben
unberührt. Alles andere wird samt trennendem Komma gestrichen, der Satz
bleibt stehen („Gerne. Ich buche Ihnen einen Termin").

- Eingehängt NUR im LLM-Pfad (`bianca/agent._anrede_wache_anwenden`): nach
  `_nachbessern`/Fakten-Wache **und** am P5-Streaming-Ausgang
  (`sicherer_vorab`). Beide Stellen säubern identisch — sonst fände
  `llm.rest_nach_vorab` den Rest nicht mehr und der Satz käme zweimal.
- Die deterministische Maschine ist nicht betroffen: `gehirn.anrede()` baut
  die Anrede aus dem Sammler, ist also immer belegt. Damit das Modell sie
  nicht selbst zusammenreimen muss, trägt `flow.status_zeile` die belegte
  Form als `Anrede=…` mit, und `flow._ctx_bauen` legt ein fehlendes
  Geschlecht aus dem Vornamen nach (gleiche Regel wie beim Einsammeln —
  greift, wenn ein anderer Weg den Vornamen direkt gesetzt hat).
- Stufen/Notaus `ANREDE_WACHE=off|shadow|enforce`, Default **enforce**
  (ein erfundener Name ist nie besser als kein Name). Spur:
  `anrede-wache` bzw. `anrede-wache-shadow`.
- Tests: `tests/test_anrede_wache.py` — die Gegenprobe (belegte Anrede bleibt
  unangetastet) ist der teurere Fehler und deshalb breiter abgedeckt.

## Auf das Gesagte eingehen (Anruf e5c25e25, 13.09.2026 — nicht rückbauen)

Chef zum Live-Anruf e5c25e25 (wörtlich): „da gab es eine 100prozentige
wiederholung, warum? […] der Nachname wurde nicht richtig erkannt und sie
springt trotzdem vor der klärung zum vornamen weiter … der einwand des
anrufers wird überhört!! das ist ein NO GO … Bianca MUSS auf das gesagte
eingehen!!! in jedem ZUG! […] es ist von einem SOHN die rede, wieso sagt
Bianca dann dass es sich um den Termin bei FRAU tzannis handelt […] 'der
frühere' wurde nicht in seinem relativen bezug verstanden."

Vier Befunde, vier Wachen. Regressionen: `tests/test_anruf_tzannis.py`,
`tests/test_unterbrechung.py`; Live-Probe im Container:
`tools/_probe_e5c25e_live.py`.

- **W-BARGE-FASTFERTIG** (`kern/unterbrechung.py`): Die Brücke meldete
  `bruecke-ohr-barge ms=4020` bei einer **4570 ms** langen Ansage („Gut. Ich
  will nichts falsch schreiben: Buchstabieren Sie mir den Nachnamen bitte
  einmal kurz?"). Der Fragesatz endete erst bei 4570, galt damit als
  ungesprochen — der Anrufer hatte **86 %** davon gehört und bekam die Frage
  WORTGLEICH noch einmal. `_fast_fertig` zählt einen Satz als gehört, wenn
  mindestens `_FAST_FERTIG_ANTEIL` (80 %) gespielt waren UND der fehlende
  Schwanz unter `_FAST_FERTIG_REST_MS` (1 s) liegt. Bewusst ZWEI Bedingungen:
  ein Knacks in der Satzmitte und ein langer Restschwanz bleiben Rest wie
  bisher — echten Inhalt zu verschlucken wäre der teurere Fehler. Notaus:
  `BARGE_FAST_FERTIG=0`.
- **W-NAME-EINWAND** (`bianca/gehirn.py`, `bianca/flow.py`): Auf „Thomas."
  kam „Nein, nein, nicht Thomas, Thannes ist mein Nachname." — die Korrektur
  landete still im Sammler, gesagt wurde nur „Danke. Wie ist Ihr Vorname?".
  Drei Stellen: (1) `_korrektur_merken` merkt den verhörten Wert vor,
  `flow._quittung` spricht ihn GENAU EINMAL aus („Entschuldigung — ich hatte
  Thomas gehört. Dann korrigiere ich auf Thannes.") und geht dabei VOR jede
  andere Quittung; (2) `nachnameKlaeren` zieht die Buchstabier-Frage sofort
  vor, statt erst nach Grund und Wunschzeit zu klären (live sechs Züge
  später) — der zweite Verhörer in Folge ist die häufigste Fehlsuchen-Ursache;
  (3) eine AUSDRÜCKLICHE Zuweisung („Mein Nachname ist Thannes") ist niemals
  eine Buchstabier-Kette: `buchstaben.teil` zog daraus das Fragment „h" und
  die Angabe verschwand ungehört („Den Anfang habe ich. Bitte mit den
  restlichen Buchstaben weiter"). Die Erst-Erfassung ist KEINE Korrektur —
  sonst quittiert Bianca jeden Namen mit „ich hatte … gehört".
- **W-ROLLE-GESCHLECHT** (`bianca/gehirn.py`): Die ausgesprochene Rolle ist
  eine HARTE Angabe, der Vornamen-Wächter rät dagegen nur (und landet bei
  unklarem Vornamen nach Chef-Default auf weiblich — live „Levy" ⇒ „Frau
  Tzannis", während der Anrufer vom SOHN sprach). Rangfolge der Quellen:
  **akte > rolle > rate** (`geschlecht_aus_rolle`, aufgerufen in
  `einsammeln` nach der Vornamen-Schätzung). Bewusst NUR eindeutige Rollen:
  Kind/Enkelkind/Patenkind/Partner sagen nichts über das Geschlecht — dort
  wird weiter nicht geraten.
- **W-SLOT-RELATIV** (`bianca/flow.py`): „Der frühere." landete als unklar
  bei der Talk-Schicht („Ich habe „Der frühere" verstanden. Was meinen Sie
  damit?"). Komparativ UND Superlativ (früher/früheste/eher/vorne bzw.
  später/späteste/hinten) greifen auf die ANGEBOTENE Liste zu (`min`/`max`
  nach ISO) — aber nur, wenn der Satz keine eigene Zeitangabe trägt: „Geht
  es später, gegen vierzehn Uhr?" ist ein neuer Wunsch, keine Wahl.

## Abwegige Bitten ernst nehmen (W-ABSCHWEIFEN 13.09.2026 — nicht rückbauen)

Chef zum Anruf 48673eca: „ausserdem bist du nicht auf den anrufer eingegangen
als der verlangte: zähl mal von 1 bis 4 oder buchstabiere meinen namen
Abdullah … die ki muss dann schon gezielter auf solche abwägigen themen
eingehen können. das ist ja unser talk floor eigentlich … ein abschweifen …
das wurde nicht gut genug bearbeitet."

Live lief genau das schief: „Wiederhol mal die Zahlen 1, 2, 3, 4." landete als
RÜCKRUF-NOTIZ im Abgeben-Zweig („die Praxis prüft Ihren Wunsch"),
„buchstabiere meinen Namen Abdullah" beantwortete das Modell mit „Danke für
Ihren Namen.". Solche Bitten sind harmlos, sofort erfüllbar und eine Probe, ob
die Assistentin wirklich zuhört.

- `kern/abschweifen.py` antwortet deterministisch (0 ms, kein Modell):
  zählen (von/bis, Zahlwörter, rückwärts, gedeckelt auf `_MAX_ZAEHLEN` = 20),
  Ziffern nachsprechen, Namen buchstabieren (Tafel aus `bianca/buchstaben`).
  Nichts davon berührt Kalender, Kartei oder Sammler — es wird NUR gesprochen.
- Einhängung in `bianca/agent.user_turn` VOR dem Fluss; die offene
  Pflichtfrage (`_offene_frage`) hängt im SELBEN Zug hinterher, damit der
  Faden nicht reißt. Spur: `abschweifen`.
- **Die Gegenproben sind der wichtigere Teil:** während eines Diktats
  (`_diktat_offen`: Nummer, Buchstabieren) schlägt der Baustein NIE zu, und
  eine Bitte muss AN Bianca gerichtet sein (`_an_bianca`: Imperativ am
  Satzanfang oder Anrede). „Ich buchstabiere: Tzannis" und „T-Z-A-N-N-I-S."
  gehören der Namens-Ernte — eine gekaperte Datenerfassung wäre teurer als
  eine verpasste Spielerei. Ohne belegten Namen wird bei „buchstabiere meinen
  Namen" nie geraten.
- Notaus: `ABSCHWEIFEN=0`. Tests: `tests/test_abschweifen.py`.

## „Rezeption" ist kein „Rezept" (W-REZEPTION 13.09.2026)

`\brezept\w*` traf auch **Rezeption**: auf den Wunsch nach der ANMELDUNG
antwortete Bianca „Rezept und Überweisung kann ich am Telefon nicht
ausstellen" (Anruf 48673eca), und im Intent landete der Satz im Rückruf-Zweig.
Alle drei Stellen tragen jetzt `\brezept(?!ion)\w*`: `bianca/flow._DOKUMENT_RE`,
`kern/hirn._DOKUMENT_SPIEGEL_RE`, `kern/intent` (`_WECHSEL_RE`,
`_FB_RUECKRUF_RE`). Gegenprobe mit im Test: das echte Rezept greift weiter
(`test_rezeption_ist_kein_rezept` in `tests/test_weiterleiten.py`).

## Vor jeder Frage ins Session-Hirn schauen (W-FRAGE-GATE / W-HIRN-GATE 13.09.2026 — nicht rückbauen)

Chef zum Anruf 1fbda5db (wörtlich): „das session hirn braucht deutlich mehr
sicherheit in dem aufnehmen und ausstreuen von daten […] es darf keine frage
gestellt werden, zu der es bereits einen wert gibt […] die frage nach der
zhanreinigung kommt doppelt!!!!! warum ???!!!" Und zur Form (später, wörtlich):
„der datensatz muss hinterfragt werden mit data xy ist richtig, oder? z.b.
Privat versichert habe ich hier stehen. ist das noch aktuell? oder: vorname
Michael, ja? dann habe ich Sie gefunden."

Ein belegter Wert wird also **nicht verschwiegen und nicht neu erfragt, sondern
hinterfragt**. Drei Wachen, drei Ursachen:

- **W-FRAGE-GATE** (`kern/frage_gate.py`, Default `enforce`, Notaus
  `FRAGE_GATE=off`): Datenfragen gehören der MASCHINE. Live bot das MODELL in
  Zug 8 die Zahnreinigung an — der Sammler wusste davon nichts, also fragte die
  Maschine in Zug 13 erneut. Eine Job-Frage des Modells wird deshalb gestrichen
  (`saeubern`), die Maschine stellt sie danach selbst. Zwei Ausnahmen, damit das
  Gate nichts kaputt macht: die GERADE offene Maschinenfrage bleibt stehen (das
  Modell spricht dann nur aus, worauf die Maschine wartet), und eine Rückfrage
  gegen einen bekannten Wert („…, richtig?", `_RUECKFRAGE_RE`) ist genau die
  gewünschte Form. Eingehängt am LLM-Ausgang (`agent._frage_gate_anwenden`)
  UND im P5-Strom (`sicherer_vorab`) — sonst wäre die Frage gesprochen, bevor
  die Wache am Zugende sie streichen kann.
- **W-HIRN-GATE** (`bianca/gehirn.py`): `vornameQuelle` sagt, WOHER ein Wert
  kommt — „gesagt", „akte" oder „check" (Identität war schon Thema). Ein
  Vorname aus der KARTEI wird einmal bestätigt (`vorname_check`,
  `vorname_check_frage`), statt still verwendet zu werden; so fällt auch ein
  falscher Kartei-Treffer auf, bevor er in den Termin wandert. Die Markierung
  „gesagt" setzt `einsammeln` an EINER Stelle (Vergleich gegen den Stand vor
  der Ernte) — so kann kein neuer Schreibweg sie vergessen. Ein Nein räumt NUR
  den Vornamen; Nachname, Nummer, Grund und Slot bleiben stehen. Nach zwei
  unklaren Antworten gilt der Kartei-Wert (`flow._eskalieren`) — die
  Bestätigung ist eine Vergewisserung, keine Pflichterhebung.
- **W-JA-NACHGESTELLT** (`gehirn._ja_nachgestellt`): „Haben wir doch schon
  gesagt, ja." fiel durch, weil `_JA_RE` am Satzanfang verankert ist — die
  PZR-Zusage war verloren, im Hirn stand `pzr="gefragt"`. Bewusst eng: kein
  Fragezeichen (eine Vergewisserung „…, ja?" ist keine Zusage, daran hängt
  auch das Buchungs-Okay), kein Nein am Anfang, letztes Teilstück ein blankes
  Ja-Wort.

Dass die MASCHINE keine Frage zu einem belegten Feld stellt, ist Bauart:
`gehirn.naechste_frage` ist eine if-Kette, in der jeder Zweig genau das Feld
prüft, nach dem er fragt. `tests/test_frage_inventar.py` nagelt das Feld für
Feld fest, damit eine künftige Frage ohne Wächter dort auffliegt und nicht
erst im Feldtest. Weitere Regressionen: `tests/test_frage_gate.py`,
`tests/test_anruf_rateike.py`.

Dazu aus demselben Anruf, weil Zustands-Verfall dieselbe Doppelfrage erzeugt:

- **W-DIKTAT-FERTIG** (`bianca/buchstaben.py`): das Schlusswort gehört nie zum
  Namen („R-A-T-E-I-K-E, fertig" → Rateike), Füllwörter werden nicht in
  Buchstaben zerlegt („es das" machte „Sdasrateike"), und ein vollständig
  gesprochener Name am Ende der Buchstabenkette schlägt zwei Streu-Buchstaben
  davor.
- **W-NAME-EINWAND-2** (`gehirn.name_korrektur_versuch`,
  `flow._aenderung_namensteil`): trägt der Einwand die Korrektur schon in sich
  („Ich heiße nicht Rateike fertig, sondern Rateike"), wird NICHTS geleert;
  sonst nur der bestrittene Teil (`name_fuer_aenderung_leeren(teil)`). Live
  begann die Datenaufnahme von vorn und der nie beanstandete Vorname wurde
  erneut abgefragt (Chef: „das ist eine Katastrophe").
- **Hörfehler im Zahn-Kontext** (`besuchsgrund._zahn_hoerfehler`): „schiefe
  Zehen" ist in einer Zahnarztpraxis „schiefe Zähne" → KFO-Besprechung statt
  Kontrolle. NUR für die Motiv-Zuordnung; Sammler und Terminnotiz behalten den
  echten Wortlaut, beim Hautarzt bleiben Zehen Zehen.

## Widerspruch wird zuerst korrigiert (W-EINWAND 13.09.2026 — nicht rückbauen)

Chef (wörtlich): „denk daran auch korrekturen einzubauen wenn eine angabe nicht
stimmt. telefon oder vorname oder was auch immer und der patient da
widerspricht, dass das dann zunächst korrigiert wird und nicht übergangen wird
[…] dann würde bianca nie wieder einwände einfach übergehen."

Die Korrektur gab es nur an der Readback-Frage („Soll ich das so eintragen?" →
Nein → `_aenderung_zug`), beim Namen (W-NAME-EINWAND) und bei der Nummer
(`_TEL_FALSCH_RE` in `einsammeln`). Mitten im Fragenfaden lief ein Einwand
gegen Versichertenstatus, Behandler oder Besuchsgrund ins Leere: die Maschine
stellte einfach ihre offene Frage weiter.

- **Erkennung** `kern/einwand.py` (pur, bianca-frei): `feld(text)` braucht im
  SELBEN Teilsatz einen Widerspruchs-Marker (nein/falsch/stimmt nicht/nicht
  mehr/geändert) UND ein Feldwort. Bewusst eng — ein falscher Treffer wirft
  einen feststehenden Wert weg (genau die Katastrophe aus Anruf 1fbda5db).
  Deshalb fallen Fragen des Anrufers („Stimmt meine Nummer nicht?"), Bitten um
  Wiederholung und Marker im ANDEREN Teilsatz („Nein, zur Kontrolle bei Doktor
  Petsas") heraus.
- **Wirkung** `flow._einwand_zug` (vor dem Fragenfaden, nach `verwalten.zug`):
  ruft `_aenderung_zug(feld=…, streng=True)` und stellt die ausgesprochene
  Korrektur voran („Entschuldigung — dann korrigiere ich den Behandler."). Neu
  im `_aenderung_zug`: `versicherung` (Status wird neu erhoben) und `arzt` (mit
  ihm ist der Slot-Vorrat wertlos — er kam aus dem falschen Kalender, also
  `_vorrat_leeren`). **Geräumt wird NUR das bestrittene Feld**, die Kette läuft
  danach an derselben Stelle weiter (`naechste_frage` liest ja den Sammler).
- **`streng`**: der Widerspruch nennt oft nur den ALTEN Wert („gesetzlich
  stimmt nicht mehr"). Ohne die Sperre hätte die Ernte im selben Satz denselben
  Wert gleich wieder festgeschrieben und Bianca hätte den bestrittenen Stand
  bestätigt.
- **Wer schon korrigiert hat, gewinnt:** hat `einsammeln` den Einwand bereits
  verarbeitet (jeder Ernte-Schlüssel des Feldes steht in `_EINWAND_ERNTE` —
  inkl. `telefonOffen`/`telefonKorrektur`) oder ist die eigene Ja/Nein-Frage
  des Feldes offen (`_EINWAND_EIGENE_FRAGE`: telefon_check, versicherung_check,
  arzt_check, vorname_check), hält W-EINWAND sich heraus. Absage/Verschieben
  bleiben bei W-NAMESKORREKTUR.
- Notaus `EINWAND=off|shadow|enforce` (Default **enforce**). Tests:
  `tests/test_einwand.py` — hinter jedem Positiv-Fall steht ein Negativ-Fall.
  Live-Probe im Container (kein Kalender-Write):
  `docker exec -w /app telefonki-bianca-1 python tools/_probe_einwand_live.py`
  — Teil A zeigt Nummer/Behandler/Versicherung samt weiterlaufender Kette,
  Teil B den Bezug in echten Dock-Zügen (13.09.2026 grün).

## Jeder Zug geht auf das Gesagte ein (W-EINGEHEN 13.09.2026 — nicht rückbauen)

Chef (wörtlich): „genau dafür brauchen wir, dass auf das gesagte eingegangen
wird […] weil dann würde es endlich ein Gespräch!!! und kein Monolog […] es
gibt keinen Wächter, der pro Zug erzwingt, dass die Antwort erkennbar auf den
letzten Satz eingeht. Das muss deshalb angepasst werden … nur so entsteht
KONVERSATION."

Die Maschine quittiert jede ERNTE längst (`flow._quittung`). Der Monolog
entsteht in den Zügen DAZWISCHEN: der Anrufer sagt etwas, das kein Feld füllt,
und die Antwort ist eine nackte Frage („Und der Vorname?").

- **Regel** (`kern/eingehen.py`, pur): eine Antwort, die NUR aus Fragesätzen
  besteht, bekommt einen kurzen, inhaltsfreien Bezug voran — rotierend
  („Verstehe." / „Alles klar." / „Mhm, verstehe." / „In Ordnung."), bei einem
  Wunsch „Gerne.", bei Beschwerde/Notfall (`anliegenArt`) „Das tut mir leid.".
  Kein neuer Inhalt, keine Tatsache — die Fakten-Wache bleibt unberührt.
- **Nie angefasst:** Antworten mit Aussagesatz (Quittung, Readback, Angebot),
  Antworten die schon mit einem Bezug beginnen (`_SCHON_BEZUG_RE` — doppelt
  klingt schlimmer als keiner), Presence-Stupse, Züge ohne substanzielle
  Äußerung („Ja.", „Hm.") und eine **Frage des Anrufers**: ein „Verstehe."
  davor wäre eine Scheinantwort (nur Spur `eingehen-frage-offen`; dort gehört
  die Talk-Schicht hin).
- **Einbau** `bianca/agent.py`: im Maschinen-Zug NACH dem Wiederholungs-
  Wächter (der vergleicht also weiter den reinen Fragesatz) und im LLM-Zug nur,
  wenn noch NICHTS gesprochen wurde (`vorab_gesagt`) — sonst fände
  `llm.rest_nach_vorab` den Rest nicht und der Satz käme zweimal (dieselbe
  Falle wie bei der Anrede-Wache). Kein nacktes „Gut."/„Okay." als Vorsatz:
  das sind die Quittungen der Maschine und würden im Gedächtnis des
  Wiederholungs-Wächters eine echte Quittung als „schon gesagt" streichen.
- Notaus `EINGEHEN=off|shadow|enforce` (Default **enforce**). Tests:
  `tests/test_eingehen.py`; Live-Probe Teil B in
  `tools/_probe_einwand_live.py` (13.09.2026: „Alles klar. Waren Sie denn
  schon einmal bei uns?" — und KEIN Vorsatz, wo die Antwort schon einen
  eigenen Bezug trägt).

**Auto-Resume ist seit heute scharf.** Chef: „manchmal strandet sie obwohl wir
wächter haben". `hirn.auto_resume_modus()` liefert jetzt `enforce` als Default
— und zwar im CODE, nicht in der Server-`.env` (die wird beim Deploy
überschrieben, s. `.env`-Falle unten). Rückweg unverändert
`HIRN_AUTO_RESUME=off`. Wache: `test_default_ist_enforce`.

## Fünf Feldtest-Fixes (13.09.2026 abends — nicht rückbauen)

Vor den Feldtests in drei Praxen (Chef: „1-4 dürfen NIEMALS Probleme
machen") wurden die groben Befunde der Analyse EINZELN korrigiert — je ein
Commit, je eigene Tests, die Opus-Wächter (W-EINWAND, W-EINGEHEN,
W-FRAGE-GATE, W-HIRN-GATE, Anrufe Tzannis/Rateike) blieben in jedem Schritt
grün. Voll-Suite 14 → 11 Altfehler (9 bekannte + 2 `audioop`), kein neuer.

1. **Dokument-Hook mandanten- und kontextscharf** (`kern/praxisregeln.
   unterlagen_antwort`, Einhängung in `flow.zug`). Vorher lief der feste
   Blessing-Text („Rezepte nur persönlich") bei JEDEM Mandanten und räumte
   mitten in der Buchung `s["frage"]` — die Kette strandete. Jetzt: der
   Vorsprache-Text nur mit DB-Marker UND echter ANFORDERUNG
   (`dokument_anforderung`); „ich habe eine Überweisung" ist Besitz
   (`hat_ueberweisung`) = Buchungsgrund; „Befundbesprechung"/„Röntgentermin"
   sind Termine (`_TERMIN_KONTEXT_RE`). Läuft eine Aufgabe, gibt Bianca die
   Auskunft und stellt die offene Frage (`flussFrage`) im SELBEN Zug erneut.
   Tests: `tests/test_dokument_hook.py`.
2. **Überweisung ≠ Rückruf** (`kern/intent.py`): `_FB_RUECKRUF_RE` ist
   geteilt in Kern (Rückruf-Wörter) und Dokument; `_rueckruf()` schweigt,
   wenn das Dokument ein Buchungsgrund ist, `_ueberwiesen()` öffnet ANLEGEN.
   „Ich brauche ein Rezept" bleibt ABGEBEN. Tests:
   `tests/test_intent_ueberweisung.py`.
3. **Dringlichkeit ≠ Notfall** (Blessing, `praxisregeln.akut`): „dringend",
   „sofort", „heute unbedingt" sind aus `_AKUT_RE` raus; Notfall nur bei
   `_DRINGLICHKEIT_RE` PLUS `_BESCHWERDE_RE` (Haut/Ausschlag/brennt/
   geschwollen …) oder echtem Akut-/Lebensgefahr-Wort. `haut\w*` matcht
   bewusst nicht „Hautarzt". Tests in `tests/test_blessing_praxisregeln.py`.
4. **W-EINWAND ohne Fehltreffer** (`kern/einwand.py`,
   `_teil_ist_kein_einwand`): „keine Beschwerden/Schmerzen", „keine
   andere/neue Nummer", „keinen anderen Arzt", Bestätigung mit
   vorangestelltem Nein ohne harten Marker („Nein die Nummer stimmt"),
   Unwissen des Anrufers („ich weiß den Namen nicht", „ich habe die Nummer
   nicht verstanden" — „SIE haben … falsch verstanden" bleibt Einwand),
   Alter, Neupatient, Rückblick/Bewertung. `beschwerden` ist kein
   Grund-Feldwort mehr; `arzt` steht vor `name` („Der Arzt heißt nicht
   Petsas"). Jeder Negativ-Fall hat seine Positiv-Gegenprobe in
   `tests/test_einwand.py`.
5. **Notleine 6 → 8 Stupse** (`kern/stille.GESAMT_MAX`): vier Stille-Phasen
   statt drei, die 15er-Schleife aus 9395e2ce wird weiter gefangen; die
   Opus-Tests leiten die Phasenzahl aus den Konstanten ab. Dazu wärmt
   `gehirn.feste_saetze` die W-EINGEHEN-Bezüge (`eingehen.ALLE_BEZUEGE`),
   die `_EINWAND_VORSATZ`-Sätze und die W-HIRN-GATE-Quittungen vor — der
   Dienst spricht satzweise aus dem Cache, ein ungewärmter Vorsatz kostete
   sonst eine eigene Synthese vor der gewärmten Frage.

## Chef-Vorgaben für den Feldtest (13.09.2026 spät — nicht rückbauen)

Neun Punkte des Chefs vor dem Volllast-Start in drei Praxen; die
Code-Punkte in Kürze, jeder mit eigenem Modul, Notaus und Tests:

1. **Behandler-Sperre** (`kern/behandler_sperre.py`, Chef: „Dr. Nikolaou
   soll vorerst raus aus der telefonischen Buchung"): `telefonGesperrteBehandler`
   im Mandanten (meddent: `["Nikolaou"]`) nimmt den Kalender aus Wahl, Suche
   und Buchung (`anwenden` in `agentprofil.fuer_did/fuer_tenant`, gesperrte
   Kalender liegen unter `_gesperrteKalender`). Nennt der Anrufer den Namen
   (`arzt.deute` → `typ=gesperrt`) oder war er zuletzt dort
   (`arzt.letzter_behandler` → `gesperrt=True`, `anruferKartei`), sagt
   Bianca es EHRLICH (`behandler_sperre.hinweis`, vorgewärmt) und bietet
   die übrigen Behandler an — vorher buchte sie still bei Petsas oder in
   Nikolaous Kalender. Der Name bleibt STT-Hotword (sonst Verhörer).
   Tests: `tests/test_behandler_sperre.py`.
2. **Verbinden-Whitelist** (`bianca/weiterleiten.verbinden_erlaubt`,
   Punkte 2 + 9): weitergeleitet wird NUR an Ziele aus `verbindenErlaubt`
   (meddent: Petsas, Patrikis; Env-Ergänzung `VERBINDEN_ERLAUBT`). Thaler
   und Blessing haben kein Ziel — kein Durchstellen. Kein Transfer an
   Rezeption/Mitarbeiter/Buchhaltung bei irgendeinem Mandanten (die
   Rollen-Weiterleitung ist gelöscht). Die alte Regel „ein einziger
   `weiterleitungen`-Eintrag gilt für alle Ärzte" ist gestrichen — sie
   hätte Nikolaou-Wünsche auf die Praxisnummer gelegt. Gesperrter
   Behandler am Telefon verlangt → `_gesperrt_antwort` (ehrlich, Termin
   oder Notiz), kein Jingle.
3. **Rückkehr nach fehlgeschlagenem Verbinden** (`bianca/rueckkehr.py`,
   Brücke `_RUECKKEHR`-Store; Chef: „darf nicht auf 0 zurückgefallen
   werden"): der Dialplan landet nach Besetzt/keine Antwort per
   `Goto(bianca)` in `/api/start` — die Brücke gibt `resumeSessionId`,
   `resumeSchnell` (< `BRIDGE_RUECKKEHR_SCHNELL_S` 55 s = Verbindung kam
   nicht zustande), `resumeSeitS`, `resumeZiel` mit; `rueckkehr.aufnehmen`
   prüft DID/Anrufer (`passt`) und Alter (`TRANSFER_RUECKKEHR_MAX_S` 1800),
   `vorbereiten` räumt Barge-/Halbsatz-Reste, `hirn.nach_transfer_ruecken`
   erledigt das ERREICHEN-Anliegen und holt das geparkte zurück;
   `agent._rueckkehr_reply` spricht „Da bin ich wieder — die Verbindung zu
   Doktor X ist leider nicht zustande gekommen" + offene Frage. Kein
   zweites `call_erfassen` (ein PhoneCall), Report mit Phasen-Suffix
   (`gedaechtnis._event_id` `:rN`) statt Dedupe-Verlust. Notaus:
   `TRANSFER_RUECKKEHR=0` bzw. `BRIDGE_RUECKKEHR=0`. Tests:
   `tests/test_transfer_rueckkehr.py`, Rückkehr-Block in `test_sip_vad.py`.
4. **Öffnungszeiten aus den Standorteinstellungen** (`kern/standort.py`,
   Punkt 3): Bianca liest `clients/{clientId}/locations/{locationId}`
   per Firestore-REST (Service-Account-JWT, Scope-Cache in
   `anrufaudio._access_token`), parst `openingHours`, hängt
   `tenant["standort"]` an und schreibt den Block „ÖFFNUNGSZEITEN
   (Standorteinstellungen)" in den `dbPrompt` — NUR wenn der Agent-Prompt
   keine eigene Zeile trägt (MedDent behält seine; die Standort-Zeiten
   dort stimmen nicht mit dem Prompt überein — Chef informiert).
   `wissen.praxis_antwort` und `praxisregeln.praxis_offen` lesen dieselbe
   Quelle. Stale-while-revalidate (`STANDORT_TTL_S` 600, `STANDORT_WARTE_S`
   2,5, Vorwärmen im `_warm_start`) — kein Firestore-Warten im Anruf.
   Notaus: `STANDORT_ZEITEN=0`. Tests: `tests/test_standort.py`.
5. **W-QWEN-KORREKTOR** (`kern/qwen_korrektor.py`, Punkt 5 — Chef: „qwen
   muss erreichbar sein und asynchron korrigieren dürfen"): Parakeet
   bleibt das Live-Ohr; Qwens Ergebnis, das den Zug verpasst oder
   abgelehnt wurde, wird nicht mehr weggeworfen (`stt._nachtrag_anmelden`
   → Callback `nachtrag`), sondern je Zug gemerkt (`qwenSpaet`), als
   Wörterbuch Verhörer→Qwen-Wort gelernt (`qwenWoerter`, Quell-Zug in
   `qwenWoerterZug`) und als Hotwords an Parakeet gegeben
   (`qwenHotwords`). `anwenden` läuft VOR Fluss/LLM des nächsten Zugs
   (0 ms, kein Netz): Wörterbuch ersetzt („Rentenbild" → „Röntgenbild");
   bei Wiederholung oder Widerspruch („Nein, Röntgenbild!") gilt Qwens
   Fassung des VORIGEN Zugs — der Anrufer-Satz im LLM-Verlauf wird
   umgeschrieben und ein einmaliger Prompt-Hinweis (`prompt_hinweis`,
   zug-gebunden) nennt die Korrektur. NIE: Ziffernfolgen, Mandanten-
   Vokabular (Behandlernamen), Strukturwörter, ohne Signal in den Verlauf,
   den EIGENEN Zug (kommt Qwen vor dem Korrektor an, bleibt die
   Live-Entscheidung stehen). Qwen-Pool jetzt `STT_QWEN_PARALLEL` (2)
   statt 1; `STT_QWEN_FINAL_BASE` nimmt eine Komma-Liste (Rotation bei
   Verbindungsfehler — die Dev-Box wechselte die LAN-IP .167 → .173, Qwen
   war deshalb seit Tagen stumm). Anzeige: Manifest `zuege[].stt`
   (Gewinner, beide Texte, spätes Qwen, Korrektur) → `/anrufe` zeigt je
   Zug „Parakeet STT"/„Qwen STT", „Qwen (spät) anders", „Qwen-Korrektur"
   samt Vergleichszeile; Studio (`ergebnisse.js`/`app.js`) dieselben Tags.
   Notaus: `QWEN_KORREKTOR=0`. Tests: `tests/test_qwen_korrektor.py`,
   `tests/test_stt_qwen.py` (Nachtrag-Fälle), `tests/test_mitschnitt.py`.
6. **W-FACH-WACHE** (`kern/fach_wache.py`, Punkt 8 — Chef: „bei blessing
   darf auf gar keinen Fall ein zahnmedizinischer Einfluss oder
   gesprächsverlauf entstehen"): Die MASCHINE war schon dicht — PZR,
   Bleaching, Zahn-Regeln im Prompt, Zahnarzt-Verweis hängen alle am
   Katalog (`motive.ist_zahn`/`fuehrt_pzr`, `tests/test_zahn_katalog.py`,
   Audit 13.09. ohne Befund). Offen war der LLM-Ausgang: sagt ein
   Anrufer beim Hautarzt „Zahnschmerzen", darf das Modell keinen
   Zahnarzt-Rat und kein Zahn-Angebot sprechen. Die Wache streicht am
   Endtext UND im P5-Streaming-Satz (`agent._fach_wache_anwenden`, gleiche
   Doppel-Einhängung wie Anrede-Wache) jeden Satz mit Zahn-Vokabular
   (`\w*zähn\w*`, PZR, Bleaching, Karies, Implantat, Krone, Prothese,
   Wurzelbehandlung, KFO, dental …); bleibt nichts, kommt „Das gehört
   nicht zu unserer Praxis — wir sind eine Hautarztpraxis." Scharf NUR
   bei bekanntem Nicht-Zahn-Fach (`fachprofil.fach_id` ≠ allgemein/
   zahnmedizin — Blessing trägt `fachgebiet=dermatologie` in der lokalen
   Datei, also ab dem ERSTEN Zug); „allgemein" (leerer Katalog) = AUS,
   damit MedDent vor dem Katalog-Lauf nie verstummt. Bewusst NICHT im
   Vokabular: Prophylaxe (Hautkrebs-Prophylaxe), Brücke, Mund, Kiefer,
   Füllung (= Filler beim Hautarzt) — ein gestrichener legitimer Satz
   wäre der teurere Fehler. Stufen `FACH_WACHE=off|shadow|enforce`
   (Default enforce). Tests: `tests/test_fach_wache.py`.

7. **Notdienst-Wache** (`praxisregeln.notdienst_saeubern`, Punkt 6 —
   Chef: „kein Verweis auf 116/117"): die feste Notfallantwort mit 116 117
   hängt am Blessing-DB-Marker (`notfall_sofort_aktiv`) und fällt in den
   Zahnpraxen nie. Damit auch das MODELL sie dort nicht nennt, streicht
   `agent._notdienst_wache_anwenden` (Endtext + P5-Satz) jeden Satz mit
   „116 117"/„116117"/„1 1 6 1 1 7", wenn der Mandant den Marker nicht
   trägt; bleibt nichts, kommt „Bei akuten Beschwerden helfen wir Ihnen
   hier in der Praxis weiter." Blessing unverändert. Tests: Punkt-6-Block
   in `tests/test_fach_wache.py`.

Reine Betriebs-Punkte ohne Code: Clara/Lena bleiben bis zum Hardware-
Upgrade aus (4); Telefon-Notizen laufen ins MAS-Gedächtnis, das Praxisteam
sichtet CallR (7 — Schreibweg für alle drei Mandanten am 13.09. live
geprüft: `/brain/events` + `/brain/caller-context` 200, `bianca_call`-
Reports vorhanden).

Dabei entfernt: die Debug-Instrumentierung der Sitzung a62ee2 vom
12.09. (`kern/dbg_a62ee2.py`, `#region agent log`-Blöcke in Brücke,
`agent.py`, `weiterleiten.py` — NDJSON nach `/tmp/debug-a62ee2.log`); sie
war zur Fehlersuche gedacht und hatte in V2.3 nichts mehr zu tun.

## Gesucht = gebucht (W-MOTIV-KONSISTENT 14.09.2026 — nicht rückbauen)

Chef 14.09.2026 06:1x: „hör dir das letzte gespräch an med dent — die buchung
klappt nicht." Der Anrufer sagte auf das Angebot „Ja" und hörte nur „Termin
ist gerade weg". Im Tool-Ledger: `getFreeTimeSlots` mit „KCH
Kontrolluntersuchung" (Zeiten da), `masBookAppointment` mit
`selfCheckinEmergencyVisitMotive` → 400 „The slot is not available.".

Drei Ursachen, drei Wachen (`kern/motive.py`, `bianca/gehirn.py`,
`kern/calendar.py`, `bianca/flow.py`, `bianca/hintergrund.py`):

1. **Terminal-Pseudo-Motiv nie am Telefon** (`motive.telefon_tauglich`):
   Die Plattform führt „Notfall (Selbst-Check-in)" mit fester Id
   (docgendaweb `SELF_CHECKIN_EMERGENCY_VISIT_MOTIVE_ID`) für die
   Check-in-Terminals, `allowOnlineBooking=false` — die CF liefert dafür nie
   Zeiten und lehnt jede Buchung ab. `motive.holen` und `motive.katalog`
   filtern es (auch aus persistierten Sitzungen und der Mandanten-Liste).
2. **Buchbar zuerst — über die GANZE Kette** (`gehirn.motiv_fuer_kalender`):
   die Buchbar-Bevorzugung galt nur innerhalb einer Mapping-Stufe; „Ich hab
   Schmerzen" gewann exakt/Konzept/Fuzzy jeweils ein unbuchbares Motiv,
   obwohl „KCH akute Beschwerden/Notfall" buchbar im Katalog stand. Jetzt
   läuft exakt → Konzept → Fuzzy erst über die buchbaren Motive, dann über
   den vollen Katalog (unbuchbarer Wunsch wird NICHT still zu Kontrolle —
   die Slotsuche sagt ehrlich, dass telefonisch nichts geht, bzw. fällt
   sichtbar zurück, s. 3). Live-Gegenprobe gegen den echten MedDent-Katalog
   (133 Motive, 122 nicht online-buchbar): Schmerzen → 6QHf… „KCH akute
   Beschwerden/Notfall" (buchbar).
3. **Ersatz-Motiv wird gebucht** (`find_slots_behandler` → `motivFallback`
   + `motivOriginal`; `gehirn.motiv_fallback_merken` pinnt es in
   `sammler["motivFallback"]`, `_motiv_fallback_pin` hält es in
   `motiv_fuer_kalender`, solange Kalender UND Grund gleich bleiben):
   `masBookAppointment` prüft die Verfügbarkeit JE MOTIV (`isSlotAvailable`
   → `getFreeTimeSlots`); wer mit Kontrolle sucht und mit dem Original bucht,
   scheitert IMMER — die Lülf-Regel vom 08.09. („gebucht wird weiter mit dem
   Original-Motiv") konnte nie funktionieren. Der Wunsch bleibt im Sammler
   (`grund`/`grundWortlaut`) und landet als Notiz am Termin: „Gewünscht:
   „Füllung" (KCH Füllung klein) — dafür war telefonisch nichts buchbar,
   eingetragen als KCH Kontrolluntersuchung. Bitte Besuchsgrund und Dauer
   prüfen." Der Hintergrund-Vorrat pinnt ebenso und stempelt `vorratFuer`
   auf das Ersatz-Motiv um (sonst lud `_angebot` eine CF-Runde umsonst nach).

Offen und NICHT in Biancas Hand: `allowOnlineBooking=false` sperrt in der
CF auch Telefon-Buchungen. Bei **Thaler** sind „KCH Kontrolluntersuchung"
und „KCH Erstuntersuchung/Neupatient" (zwei der sechs freigegebenen
Gruppen) so markiert → 0 Zeiten, Rückruf-Notiz statt Termin. Lösung: im
Portal Online-Buchung für diese Motive freischalten ODER in der CF den
Telefon-Agenten (source pickadoc-bianca) von dem Gate ausnehmen — beides
Entscheidung des Chefs, nicht dieses Repos. Tests:
`tests/test_motiv_konsistent.py` (12).

## Handynummer als letzter Schritt + kein Eisbrecher vor dem Anliegen (W-TELEFON-ZULETZT 14.09.2026 — nicht rückbauen)

Chef 14.09.2026 07:00 zum MedDent-Anruf e7191c7e (wörtlich): „es gab bei der
Erkennung des Patienten dopplungen die überflüssig sind / biancas reihenfolge
der datenabfrage ist schlecht . sie fragt zu früh nach der handy nummer, bevor
der termin überhaupt steht! die handynummer sollte das letzte vor Versand der
sms sein, das abgefragt wird."

Live (Anrufer per Rufnummer als Michael Petsas erkannt): „Hallo, ich habe gerne
einen Termin." → „Ah, Herr Petsas, wie geht es Ihnen?" → „Danke, gut." → „Das
freut mich. Guten Tag, hier ist Bianca von den Zahnärzten … Wie kann ich Ihnen
helfen?" → erst in Zug 4 der Identitätscheck; in Zug 7/8 die Zeitfrage doppelt
(Modell im Nebensatz, Maschine danach); in Zug 9 — direkt nach dem Zeitwunsch,
VOR jedem Slot — „Soll ich die Bestätigungs-SMS an die 0177 … schicken?".

**Reihenfolge (Buchung):** Anliegen → Identität (`anrufer_check`) → „für Sie
selbst?" → Behandler → Grund → Wunschzeit → Name → Versicherung → Slots →
Readback + Ja → PZR/Doktor-Notiz → **Handynummer / SMS-Ziel** → `book_slot`
(= SMS). Nachstellung des Anrufs gegen den Code (offline, LLM gestubbt):
`python tools/_probe_e7191c7e.py` — 14.09.2026 ALLE GRUEN.

- **`gehirn.telefon_frage(sit)`** ist die EINE Stelle für Nummer und SMS-Ziel
  (Reihenfolge: gehörte Nummer rückbestätigen → Dritttermin „an den Patienten
  oder an Sie?" → hinterlegte Nummer „SMS an die … schicken?" → Nummer
  erfragen). `gehirn.naechste_frage` erfragt die Nummer NICHT mehr; es führt
  sie nur zu Ende, wenn sie schon läuft (`telefonTeil`, offene `telefon`-/
  `sms_empfaenger`-Frage) — damit Frage-Anker, Wiederholungs-Wächter und
  Eskalation dieselbe Frage sehen wie das Tor.
- **`flow._telefon_tor`** sitzt am Anfang von `flow._buchen`: Slot gewählt,
  Ja gesagt, Zusatzfragen durch → JETZT die Nummernfrage (`phase=""`,
  `frage=telefon|telefon_check|sms_empfaenger`, `buchIntent=True`). Nach der
  Antwort läuft der Fragenfaden weiter (`telefon_check` → ggf. `telefon_alt`),
  und `_angebot` bucht bei `buchIntent + slotIso` DIREKT (Guard oben in
  `_angebot`) — nie wieder „Welcher passt Ihnen?" nach der Nummer.
  `_einschub` (Rückblick/Bleaching) schiebt sich nicht mehr zwischen Nummer
  und Eintragen.
- **`telefonPflicht`**: „Meine Nummer haben Sie" (`telefonAkte`) wird EINMAL
  geglaubt und gebucht; sagt die Plattform „Handynummer" (Akte ohne Handy),
  setzt `_buchen` die Pflicht. Nennt der Anrufer sie dann zweimal nicht,
  schließt `_eskalieren` den Vorgang EHRLICH ab (Rückruf-Notiz, `phase=
  fertig`) — vorher lief Eskalation → `_buchen` → Fehler → Eskalation im Kreis.
- **Kein Eisbrecher vor dem Anliegen:** steht „Termin" im ersten Satz, gibt
  es keine Wohlseinsfrage (`gehirn.hallo_frage_unpassend`), sondern die
  Feststellungs-Variante und sofort den Identitätscheck. `kern/intent.
  _FB_NEU_RE` kennt Parakeets Hörfehler-/Konjunktivformen („hab(e) gern",
  „bräuchte", „wollte", „würde gern", „Termin bekommen/kriegen").
- **Re-Greeting-Wache** (`kern/antwort_wache.strip_repeated_greeting`):
  Wortstämme statt Wörter („Zahnärzte" = „Zahnärzten"), Selbstvorstellung +
  Grußwort mitten im Gespräch zählt immer, die Eröffnungsfrage („Wie kann ich
  Ihnen helfen?") fällt mit. Referenz ist die WIRKLICH gesprochene Begrüßung
  (`sit["begruessungText"]`, gesetzt in `agent.start_reply`); ist die
  Referenz selbst keine Begrüßung, wird nichts gestrichen — sonst fiele eine
  legitime Wiederholung der Nummernfrage. Eingehängt am Zugende UND im P5-
  Strom (`agent.user_turn` → `antwort_wache.regreeting_raus`), sonst ist der
  Satz gesprochen, bevor die Wache greift. Spur: `regreeting`/`regreeting-vorab`.
- **Frage-Gate** kennt die Nebensatz-Zeitfrage („Vorstellung, wann es Ihnen
  passt?", „vormittags oder nachmittags?") — Rückblick-Fragen („Wann waren
  Sie zuletzt bei uns?") bleiben.
- Tests: `test_fluss_fragenkette_bis_angebot` (ganze Kette bis `book_slot`),
  `test_anrufer_hallo_frage_ist_eigener_zug_und_job_geht_danach_weiter`,
  `test_modell_fragt_die_zeit_im_nebensatz_…` (frage_gate), angepasste
  Fixtures (`telefonOk`/`smsEmpfaenger` vor `_buchen`) in
  `test_fuer_wen`/`test_rueckblick_pzr`/`test_thaler_rebrovic`/
  `test_versicherung_geschlecht`/`test_datenerfassung_pausen`.

## Suchfenster sechs Monate (W-SUCHFENSTER 14.09.2026 — nicht rückbauen)

Chef 14.09.2026 12:05 (wörtlich): „bianca macht nur im laufenden monat
termine...das fenster muss auf 6 monate erweitert werden." Live-Belege:
Anruf `5aa87268` (MedDent, „heute um halb zwei/zwei") — die CF lieferte 20
Zeiten ab morgen, `pick_slots` warf ALLE weg, weil keine auf heute passte,
Bianca sagte „keinen freien Termin" und schrieb eine Rückruf-Notiz. Anruf
`da746a65` (Thaler, „Schmerzen") — Akut-Kalender Eva Thaler hatte im
120-Tage-Fenster genau EINEN Slot, keine Ausweichzeit, kein Angebot.

Die Cloud Function `getFreeTimeSlots` liefert je Aufruf höchstens
`maxSlots=20` Zeiten ab `startDate` (30 Tage, ohne Treffer automatisch
+90 Tage) — bei zwei Kalendern mit je zehn Zeiten pro Tag ist die Seite nach
EINEM Tag voll, und alles „im Oktober" lag jenseits der Seite. Deshalb vier
Bausteine, alle an der bestehenden Kette (kein CF-Deploy nötig):

1. **Wunsch liest Monate und Zeiträume** (`kern/slots.parse_slot_wish` →
   `zeitraum_aus_text`): „im Oktober", „Anfang/Mitte/Ende November", „ab
   Dezember", „bis Oktober", „nächsten/übernächsten Monat", „noch in diesem
   Monat", „in drei Wochen/zwei Monaten/vierzehn Tagen" werden zu
   `von`/`bis` (ISO) bzw. `minDaysAhead`; Wochentag im Monat („ein Dienstag
   im Oktober") kombiniert beides. Uhrzeiten OHNE „Uhr" („halb zwei", „um
   zwei") zählen jetzt — „um zwei Termine" bleibt keine Uhrzeit. Ein
   Monatsname in der Vergangenheit meint das nächste Jahr.
2. **Suche startet beim Wunsch** (`gehirn.start_datum`): frühestes Datum aus
   `von`, `minDaysAhead` und Wochentag — nie in der Vergangenheit. „heute"/
   „morgen" räumt einen alten Monatsbereich (`_relatives_datum`), ein neuer
   Bereich räumt ein altes Einzeldatum (`_wunsch_mischen`); Monatswünsche
   sind „gehaltvoll" (`_wunsch_deuten`), sonst hätte die Wunschfrage sie
   ignoriert. `vorrat_schluessel` trägt das Startdatum — ein Vorrat von vor
   dem Wunsch wird umgeschlüsselt und gezielt nachgeladen.
3. **Vorwärts-Blättern über die CF** (`kern/calendar.find_slots`, Helfer
   `_naechste_seite`/`slots_der_seite`): deckt die erste Seite den Wunsch
   nicht (`_wunsch_gedeckt`: Datum, `von`..`bis`, Wochentag), holt Bianca
   bis `SEITEN_MAX` (`.env` `SLOT_SEITEN`, Default 3) weitere Seiten —
   innerhalb `FENSTER_TAGE` (183 = sechs Monate ab heute). Volle Seite (20)
   → weiter am Tag des letzten Slots (Dubletten filtert der Aufrufer; lag
   alles auf dem Starttag: +1 Tag); kurze Seite → CF-Fenster ausgeschöpft,
   +30 Tage bzw. +120, wenn der 90-Tage-Rückfall der Plattform schon lief;
   leere Seite → Schluss (die Plattform hat 120 Tage gesehen). Bei `egal`
   (schnellster Arzt) bleiben die
   Folgeseiten im Kalender des Gewinners der ersten Seite; Dubletten werden
   gemerged, ein Fehler auf einer Folgeseite verwirft nicht die schon
   gefundenen Zeiten. `dispatch.seiten` protokolliert die Kette; `/anrufe`
   zeigt sie als „Suchfenster: N Seiten — …" an der Tool-Karte.
   `find_slots_behandler`/`find_slots_raeume` reichen `wish` durch;
   `find_slots_raeume` kennt jetzt denselben Kontroll-Ersatz wie
   `find_slots_behandler` (`_kontrolle_ersatz`/`_mit_motiv_fallback`,
   `motivFallback`+`motivOriginal`) — Thaler-Akut ohne Zeiten fällt sichtbar
   auf Kontrolle zurück statt in die Rückruf-Notiz. Der Hintergrund-Vorrat
   (`hintergrund.vorrat_anstossen`) setzt den Gewinner-Kalender in den Kontext,
   BEVOR er den Ersatz pinnt.
4. **Nächstbestes statt „kein Termin"** (`slots.pick_slots` →
   `_naechstbestes`): passt keine Zeit exakt auf den Wunsch, kommen die drei
   Zeiten, die dem Wunschzeitpunkt am nächsten liegen (Zeitanker aus Datum,
   Wochentag, `von`), gesprochen als „Genau dann ist leider nichts frei. Frei
   wäre …" (`spoken_offer(wish_matched=False)`). NICHT bei `schieben`
   (Verschiebe-Richtung) und nicht bei harter Uhrzeit-Untergrenze
   (`minutenMin`) — dort bleibt die strenge Filterung. Die Rückruf-Notiz
   („die Praxis meldet sich") gibt es nur noch, wenn die CF WIRKLICH nichts
   im Fenster hat.

Rückweg ohne Deploy: `SLOT_SEITEN=0` = keine Folgeseiten (Parser,
Startdatum und Nächstbestes bleiben — sie sind reine Verbesserungen der
schon geladenen Seite). Tests: `tests/test_suchfenster.py` (37: Parser,
Mischen, Startdatum, pick_slots, Paging, Zimmer-Ersatz, Angebot Ende-zu-
Ende, Bestandstermin „im Oktober"). Live-Gegenprobe 14.09. (read-only,
MedDent): CF akzeptiert `startDate` in der Zukunft (Oktober → 20 Zeiten ab
01.10.), Parser/Mischen/Startdatum wortgleich mit den Live-Sätzen.

Offen (Praxis-Konfiguration, nicht Code): Eva Thalers Akut-Kalender hat im
Sechs-Monats-Fenster praktisch keine freien Akut-Zeiten — der Ersatz bucht
Kontrolle mit Notiz; die Praxis sollte Akut-Fenster freigeben.

## Verbinden nur auf echten Anrufer-Wunsch (W-VERBINDEN-BEWEIS / W-ARZT-JANEIN 14.09.2026 — nicht rückbauen)

Chef zum MedDent-Anruf 984282e303cb414ab6c32125877473c2: „hier wurde
durchgestellt, obwohl der patient sagt er wolle einen termin." Kette live:
Buchung lief, Maschine fragte „Wissen Sie noch, bei welchem Behandler Sie
zuletzt waren?" → Anrufer „Ja." → die Maschine erntete NICHTS (die Frage
ist grammatisch Ja/Nein, es gab keinen Ja-Zweig) → erster Leerlauf-Zug
fiel ans Modell → das Modell bot aus „Behandler + Ja" ein DURCHSTELLEN zu
„Doktor Petsas, Patrikis oder Nikolaou" an (Namen aus dem PRAXIS-PROFIL —
Sperre und Whitelist kannte es nicht) → Anrufer „Patrikis" → `weiterleiten.
zug` Pfad (b) nahm die Modell-Rückfrage als Beweis (`_RUECKFRAGE_RE`) und
verband: Jingle, Transfer, Buchung weg. Vier Wachen:

1. **Ja/Nein auf die Bestands-Behandlerfrage sind deterministisch**
   (`gehirn.einsammeln`, `_arzt_janein_kurz`): das erste „Ja" setzt
   `arztJa` und `naechste_frage` stellt `arzt_nachfrage` — die Namen zur
   Wahl („Bei wem denn — Doktor Petsas oder Doktor Patrikis?"), aus
   `_behandler_sprechnamen` (Sperr-Liste gegengeprüft, Nikolaou nie).
   „Nein" und ein zweites „Ja" ohne Namen gelten wie „weiß nicht"
   (`typ=unbekannt` → Standard-Behandler, Kette läuft). NUR kurze Antworten
   (≤ 5 Wörter) und NIE ein Widerspruch (`einwand.feld` ≠ "") — „Nein, bei
   dem Behandler war ich nicht" gehört W-EINWAND. Nur Bestand
   (`warSchonMal`), nicht Thaler-Zimmerkarte, nicht die Neupatienten-Wahl
   (die nennt die Namen selbst).
2. **Modell-Rückfrage ist kein Beweis, wenn die Maschine arbeitet**
   (`weiterleiten.maschine_beschaeftigt`): Pfad (b) verbindet auf „Zu
   welchem unserer Ärzte …?" + Name NUR, wenn keine Maschinen-Frage offen
   ist, kein Angebot/Readback läuft, kein `buchIntent` steht und das
   Session-Hirn kein aktives Nicht-ERREICHEN-Anliegen führt. Der freie
   Rückweg der Prompt-Leitplanke (Maschine wirklich frei) bleibt.
3. **Erfundene Verbinde-Angebote fallen** (`weiterleiten.angebot_saeubern`,
   `agent._verbinden_wache_anwenden` — am Zugende UND im P5-Strom, sonst
   ist der Satz gesprochen, bevor die Wache greift): „Darf/Soll/Kann ich
   Sie … durchstellen/verbinden/weiterleiten?" und „Ich kann/könnte Sie
   … verbinden." werden gestrichen, wenn der Anrufer keinen Verbinde-Wunsch
   geäußert hat (`erkannt(gesagt)` leer, kein `hirnVerbinden`) und die
   Maschine beschäftigt ist. Verneinungen („kann Sie leider nicht
   verbinden") und Sachtext bleiben. Spur: `verbinden-wache`.
4. **Der Prompt weiß, wohin überhaupt** (`weiterleiten.verbinden_zeile` →
   `prompt.system_prompt(verbinden_zeile=…)`): „Durchgestellt werden kann
   NUR zu: Doktor Petsas, Doktor Patrikis." aus `verbindenErlaubt` ×
   Kalender, plus „Telefonisch weder erreichbar noch buchbar: Doktor
   Nikolaou — nenne diesen Namen nie als Möglichkeit." aus
   `behandler_sperre.gesperrte_kalender`. Ohne Whitelist (Thaler,
   Blessing): „In dieser Praxis wird telefonisch NICHT durchgestellt —
   biete es nie an." Die WEITERLEITEN-Leitplanke sagt außerdem: nur der
   Anrufer äußert den Wunsch; ein „Ja", ein Behandlername oder eine
   Antwort auf eine Terminfrage ist KEIN Verbinde-Wunsch; nie von sich aus
   anbieten, schon gar nicht mitten in der Buchung.

Tests: `tests/test_anruf_984282e3.py` (19 — Ja/Nein/zweites Ja/Name,
Widerspruch-Gegenprobe, Maschine frei vs. beschäftigt, Angebots-Wache mit
Verneinungs- und Sachtext-Gegenprobe, Prompt-Zeile, Nachstellung des
Anrufs mit dem Modell als Täter: wortgleiches Live-Angebot samt Nikolaou →
kein Ton, „Patrikis" danach = Behandler der Buchung, kein Jingle). Die
bestehenden Verbinde-Tests (echter Wunsch → Jingle/Transfer, Whitelist,
Sperre) bleiben unverändert grün.

## Zweit-Ohr kennt die offene Frage (W-QWEN-SICHER 14.09.2026 — nicht rückbauen)

Chef: „schaue, ob du für das Verhören Qwen besser als jetzt einspannen
kannst, beschränke dich auf die bisher erkannten Probleme OHNE eine
Verschlechterung zu riskieren." Befund aus den Anrufen 3baead87 / 48d3ac3f /
9dd61a59: der Korrektor (W-QWEN-KORREKTOR) lernte aus Verhörern UNSINN —
„Terminabfrage" → „Termin Absage", „interessiert" → „versichert" (Qwens Text
war hier der falsche; Parakeets „Gesetze versichert" war für den Fluss
richtig) — und bei der Nachnamen-Frage übernahm Qwen LIVE eine
Halluzination („Casacop." → „Da sagt Gott."), weil Parakeet den Namen als
auffällig markiert hatte. Namen haben kein Vokabular, gegen das ein
Zweit-Ohr „richtiger" sein könnte.

Der Korrektor weiß jetzt je Zug, WELCHE Frage offen ist (`sammler["frage"]`
+ laufendes Diktat `buchstabenTeil`/`telefonTeil`; `_kontext_merken` legt
das je Zug-Nummer ab, damit ein SPÄTES Qwen nach dem Kontext des
Quell-Zugs behandelt wird, nicht nach der inzwischen nächsten Frage):

- **Live-Sperre** (`qwen_korrektor.live_sperre(sit, lokal)` → Grund oder
 `""`): bei Namensfrage (`_NAMENSFRAGEN`: name/nachname/vorname/
 buchstabieren/nachname_korr/vorname_check/aenderung), laufendem Diktat und
 Nummern-Frage übernimmt Qwen NIE live; trägt Parakeets Text die erwartete
 Antwort der offenen Frage (`_ERWARTUNG`: „privat/gesetzlich/…" auf
 versicherung, „ja/nein/…" auf Ja/Nein-Fragen, „erste/neu/…" auf schonmal,
 „frühere/zweite/…" auf slotwahl, Wochentage/Tageszeiten auf wunsch),
 ebenfalls nicht — und das Ohr WARTET dann auch nicht die Grace-Zeit auf
 Qwen. Verdrahtet als `qwen_sperre`-Callable durch `stt.transcribe` /
 `stt_spur.transcribe` (`kern/dienst.py`, Closure mit der Sitzung) UND im
 Dock-Vorab-Ohr `/api/hoeren` (sonst käme der Zug als TEXT mit Qwens
 Lesart). Ohne Grund ist alles byte-identisch wie vorher.
- **Nie Lernstoff** (`_NIE_LERNEN` = Struktur + Zahlwörter + `_JOB`
 (termin, absage, buchen, verschieben, kontrolle, …) + `_ANTWORT` (privat,
 gesetzlich, versichert, egal, jawohl, …) + `_ZEIT` (Wochentage,
 Tageszeiten, woche/monat)); `_lernen` überspringt außerdem Phrasen, in
 denen Parakeet ein erwartetes Wort der offenen Frage hatte, und den
 ganzen Zug bei Namens-/Diktat-Kontext (`gesperrt=<grund>` am
 `qwenSpaet`-Eintrag — der Vorzug bei Wiederholung/Widerspruch entfällt
 für diesen Zug).
- **Wörterbuch schont Geschütztes** (`_woerterbuch_anwenden(…, geschuetzt)`):
 unscharfe Treffer gegen `_NIE_LERNEN` oder das Erwartungs-Vokabular der
 offenen Frage werden nicht ersetzt („versichert" bleibt, auch wenn
 „versickert→Verschickt" gelernt wäre); `anwenden` pausiert komplett bei
 Namensfrage/Diktat (`{"pause": grund}`, Spur `qwen-korrektor-pause`).
- **Sichtbar**: Manifest `stt.qwen.sperre` (live) und `stt.qwen.spaet.gesperrt`
 (spät) → `/anrufe` Tooltip „Qwen live gesperrt: namensfrage:nachname" /
 „kein Lernen/Vorzug (…)", Studio-Ergebnisse dieselbe Zeile; Spur
 `qwen-live-sperre`.
- Notaus nur für die Live-Sperre: `QWEN_LIVE_SPERRE=0` (Lernsperren und
 Wörterbuch-Schutz bleiben — sie sind reine Verschlechterungs-Bremsen).
 `QWEN_KORREKTOR=0` schaltet wie bisher alles ab.

BEWUSST NICHT gebaut: ein Kartei-Abgleich für Namen („Dideritch" vs. Kartei
„Vidovic", Anruf 48d3ac3f) — das ist keine STT-Frage, sondern gehört in die
Patientensuche (eigenes Arbeitspaket). Tests: `tests/test_qwen_korrektor.py`
(Job-/Antwortwörter nie gelernt, erwartete Antwort kein Verhörer, Namens-Zug
keine Lernquelle, anwenden pausiert, Wörterbuch-Schutz, live_sperre je
Kontext, Dienst und `/api/hoeren` Ende-zu-Ende), `tests/test_stt_qwen.py`
(rechtzeitiges Qwen gewinnt trotz Sperre nicht, kein Grace-Warten, Sperre
ohne Grund/mit Exception ändert nichts).

## Bestandsauskunft mit Folgefrage (W-BESTAND-ANSAGE 14.09.2026 — nicht rückbauen)

Anruf 9dd61a59 (MedDent): „Ich habe meinen Termin vergessen … habe ich da
einen Termin?" wurde erst nach dem dritten Anlauf als Frage nach dem
BESTEHENDEN Termin erkannt; die Ansage nannte den Grund nicht, endete ohne
Frage (`frage=""`), und „Alles gut, alles gut." fiel ans Modell. Auf „im
Oktober" (kein Treffer, Termin im Dezember) strich die Fakten-Wache den
ehrlichen Satz „Im Oktober sehe ich keinen Termin" als unbelegt.

- **Erkennung:** `kern/intent._BESTANDSFRAGE_RE` und `gehirn._AUSKUNFT_RE`
 kennen „Termin vergessen/verschwitzt/verpennt" (nicht: „vergessen, einen
 Termin zu machen") und „habe ich (da/denn/überhaupt/bei Ihnen) einen
 Termin" am Satz-/Teilsatzanfang. „Dann habe ich einen Termin" bleibt
 bewusst draußen (Terminwunsch-Formulierung).
- **Ansage** (`verwalten._ansagen`): nennt den Besuchsgrund
 (`grund_am_telefon`), stellt danach eine DETERMINISTISCHE Folgefrage —
 `termin_ok` („Passt der so, oder möchten Sie ihn verschieben oder
 absagen?") bzw. `sonst_noch` — und trägt bei einem Zeitraum-Hinweis
 (`verwHinweis` aus dem Einstiegssatz, relativ geparst) den ehrlichen
 Vorsatz („Im Oktober sehe ich keinen Termin für Sie — Ihr nächster Termin
 ist …"). Ist eine Buchung geparkt (`hirn.hat_geparktes`), gibt es keine
 Folgefrage: Auto-Resume bringt die Buchung zurück.
- **Folgezug** (`verwalten._termin_ok_zug`, VOR dem restlichen `zug`):
 `_ist_passt` versteht „alles gut", „passt", „so lassen", „der bleibt" —
 auch mit Datum („Alles gut, 21. Dezember.": das Datum ist der BESTAND,
 `einsammeln` hat es eben als Neubuchungs-Wunsch geerntet — `wunsch` wird
 geräumt, sonst vergiftet es eine spätere Verschiebe-Suche). Reihenfolge:
 Änderungswunsch (verschieben/absagen → `_umschalten`, kein Modell) →
 klarer Abschied → Zustimmung → kurzes Nein (`termin_aendern`: „verschieben
 oder absagen?") → Abschied. „Nein danke." auf `termin_ok` = nichts ändern.
 `termin_ok`/`termin_aendern`/`sonst_noch` sind Formular-Fragen
 (`intent._FORMULAR_FRAGEN`, `_STILLE_KURZ`, `FRAGE_VARIANTEN`,
 `agent._FRAGE_KERN`/`_kanonische_frage`).
- **Fakten-Wache** (`kern/fakten_wache`): eine verneinte Bestandsaussage
 mit Zeitraum („Im Oktober haben Sie keinen Termin", „sehe ich keinen
 Termin") ist BELEGT, wenn `agentFindPatientAppointments` lief und KEINER
 der gefundenen Termine in diesem Zeitraum liegt (`_zeitraum_negativ_belegt`
 über `parse_slot_wish`: Monat/Wochentag/Datum/von–bis). Ihr „keinen Termin"
 zählt danach nicht mehr als Slot-Claim (`st_slot`: die belegte Aussage
 wird vor der Slot-Wache aus dem Satz entfernt) — sonst schlug die
 Slot-Wache ohne Slotsuche zu. Inversionen („haben Sie keinen", „sehe ich
 keinen") sind in `_CLAIM_BESTAND_NEGATIV`.
- Tests: `tests/test_anruf_9dd61a59.py` (Regex-Gegenproben, `_ist_passt`,
 Ansage mit Grund und Vorsatz, Live-Nachstellung Ende-zu-Ende ohne Modell,
 geparkte Buchung, Fakten-Wache belegt/unbelegt).

## Warteschleifen-Wache (W-WARTESCHLEIFE 14.09.2026 — nicht rückbauen)

Chef zu Thaler-Anruf e2badc4c: „da kommen so sachen vor plötzlich: Übrigens,
online finden Sie uns rund um die Uhr … unter www.zahnarztpraxis-mainburg.de
… ich weiss nicht woher das kommt". Befund: die Sätze kommen NICHT von
Bianca — sie HÖRT sie. Es sind die Ansagen der Praxis-Telefonanlage
(„Einen kleinen Augenblick noch bitte, wir sind gleich persönlich für Sie
da."), die den Anrufer in ihre Warteschleife zurückgeholt hat; am anderen
Ende spricht kein Mensch mehr. Sweep über alle 583 Live-Anrufer-Züge
(14.09.): 11 reine Ansage-Züge in vier Thaler-Anrufen (08f4995c, 14d91fb9,
9311a9e2, e2badc4c) plus ein gemischter Zug — und KEIN menschlicher Satz
darunter. Live bedankte sich das Modell für den „Hinweis", die
Buchungsmaschine startete auf eine Ansage (anrufer_check), der Anruf lief
141 s bzw. 331 s mit „Sind Sie noch dran?" gegen die Schleife, bis die
Notleine griff. Die Konfiguration der Anlage ist Sache der Praxis (Mail an
Frau Thaler vom 14.09., `docs/mails/thaler-warteschleife-…`); Bianca
verhält sich seitdem so:

- **Erkennung** (`kern/warteschleife.ist_ansage`, deterministisch, 0 ms):
 Anlagen-Sätze sprechen aus PRAXIS-Perspektive ZUM Anrufer („wir sind
 gleich für Sie da", „Sie werden gleich verbunden", „alle Leitungen sind
 besetzt", „Ihr Anruf ist uns wichtig", „bleiben Sie in der Leitung",
 „online finden Sie uns", „unter www.…", „dort haben Sie die Möglichkeit",
 „Danke für Ihren Anruf", „hinterlassen Sie eine Nachricht"). Ein „Einen
 Moment bitte, ich hole den Kalender" des Anrufers trägt diese Perspektive
 nicht — Gegenproben (15 Anrufersätze) sind der größere Teil der Tests.
- **Zerlegen** (`zerlegen`): Ansage-Sätze vom echten Anrufer-Rest trennen
 (e2badc4c Zug 4: „Ja, ich wurde angerufen, von wem? Keine Ahnung." + Ansage
 → nur der Anfang wird verarbeitet). Ein Rest OHNE Sprecher-Marker (ich/
 mir/ja/nein/Termin …) neben einer erkannten Ansage gilt als unbekannter
 Ansagesatz („Herzlich willkommen bei …"); „wir/uns" ist bewusst KEIN
 Sprecher-Marker (so sprechen Anlagen).
- **Aktion** (`bewerten`, eingehängt in `agent.user_turn` VOR
 `stille.reset`, Verlauf, Intent und Fluss): reine Ansage → `warte` (kein
 Ton, kein Modell, nichts im Verlauf, Stille-Zähler und Maschinenzustand
 unberührt; `stilleMs` 1500); gemischt → nur der Rest läuft normal weiter;
 ab der ZWEITEN reinen Ansage (Anrufer hatte im Anruf schon gesprochen)
 bzw. der DRITTEN (noch kein Anrufer-Wort — eine Begrüßungsansage vor dem
 Durchstellen darf einen echten Anruf nie beenden) → `auflegen` ohne
 Abschiedssatz (spricht ja niemand). Aufgelegt wird NIE in einem Zug mit
 Anrufer-Sprache. Brücke und Dock kennen `warte`/`hangup` mit leerem Text
 bereits (`_spielen` leer → `_ausklingen_und_auflegen`).
- **Sichtbar:** Manifest `warteschleife` {n, aufgelegt, texte} →
 `/anrufe` zeigt die Marke „Warteschleife (N Ansagen, aufgelegt)" und die
 gehörten Ansagen im Kopf; Gedächtnis-Report/CallR bekommt die Zeile
 „Anruf endete in der Warteschleife der Praxis-Telefonanlage (…)"; Spuren
 `warteschleife` / `warteschleife-rest` / `warteschleife-auflegen`.
- Notaus: `WARTESCHLEIFE=0`. Tests: `tests/test_warteschleife.py` (37:
 Live-Wortlaute inkl. Verhörer „meinburg", weitere Anlagen-Phrasen, 15
 Anrufer-Gegenproben, Zerlegen, Schwellen mit/ohne Anrufer-Sprache,
 gemischter Zug legt nie auf, Agent Ende-zu-Ende: still/auflegen/Report/
 Manifest, echter Anrufersatz unverändert).

## Luftholen, doppelte Verneinung, Rückrufnummer (W-KURZLAUT / W-SCHONMAL-DOPPELT / W-RUECKRUF-NUMMER 14.09.2026 — nicht rückbauen)

Drei Kleinbefunde aus den Anrufen 9dd61a59 (MedDent), 5aa87268 und da746a65
(Thaler), jeder für sich harmlos, zusammen der Grund, warum sich ein Anruf
„nicht wie ein Gespräch" anfühlte:

- **W-KURZLAUT** (`bianca/agent.py`, `_NUR_LAUT_RE` + `kurzlautSerie`):
 „Oh." (9dd61a59 z02/z07) holte SOFORT „Sind Sie noch dran?", „Puff."
 (5aa87268 z02) fiel ans Modell. Ein Ausruf heißt „ich bin dran und hole
 Luft" — kein Schweigen. Die ersten `_KURZLAUT_SERIE` (2) Ausrufe in Folge
 sind jetzt ein stiller `warte`-Zug (900 ms Ruhe-Schwelle; die Brücke hält
 den Stups über `_diktat_weiterhoeren` 8 s zurück, das Dock stoppt den
 Watchdog). Erst die SERIE ohne Inhalt („Hm. Hm. Hm." = Leitungs-Artefakt)
 läuft wie seit dem 29.08. auf den gedeckelten Stille-Stups — bewusst VOR
 `stille.reset`, damit `MAX_STUPSE` die Serie beendet. Jeder echte Satz
 nullt die Serie. Die Liste kennt jetzt auch puff/uff/oha/ups/hoppla/huch/
 boah/„ach so"/aha; Ja/Nein/Okay/Stopp stehen bewusst NICHT drin.
 `test_kurzlaut_stupst_statt_llm` (test_stille) bildet den neuen Vertrag ab:
 zwei Warte-Züge, dann Presence, kurze Frage, Schweigen — nie das LLM.
- **W-SCHONMAL-DOPPELT** (`gehirn._SCHONMAL_BESTAND_TROTZ_KEIN_TERMIN_RE`):
 „Nein, noch nicht das erste Mal." (5aa87268 z04) heißt BESTAND — die
 Nein-Regel sah nur „das erste Mal" und machte einen Neupatienten daraus
 (Behandler-Wahl statt Karteisuche). „nicht das/zum/mein erste(n) Mal" und
 „kein(e) Neupatient(in)" werden VOR `_SCHONMAL_NEIN_RE` geprüft; ein
 einfaches „Nein, das erste Mal" bleibt Neupatient (Gegenprobe im Test).
- **W-RUECKRUF-NUMMER** (`flow._rueckruf_nummer_start/_zug/_abschluss`,
 `verwalten.rueckruf_nummer/_fehlt/_nachtragen`): fand die Suche nichts
 (5aa87268, da746a65), versprach Bianca „die Praxis meldet sich" — die
 JSONL-Notiz trug KEINE Nummer: seit W-TELEFON-ZULETZT kommt die Nummer
 erst nach dem Slot, die Suche scheiterte davor, der Anrufer hatte keine
 Rufnummer übermittelt. Die Praxis konnte gar nicht zurückrufen.
 `verwalten.rueckruf_nummer(sit)` ist die EINE Quelle (bestätigte Nummer >
 Akte > Kontakt-Nummer bei Dritt-Terminen > übermittelte Anrufernummer,
 normalisiert und plausibel); `_notiz_schreiben` nutzt sie und hängt
 „Tel: …" an den Dock-/Report-Text. Fehlt sie, setzt `_rueckruf_nummer_start`
 nach der Notiz die Nummernfrage (`sit["rueckrufNummer"] = {offen: True}`,
 `frage=telefon`; eine gehörte, unbestätigte Nummer geht erst ins Readback).
 `flow.zug` reicht Folgezüge an `_rueckruf_nummer_zug` — deterministisch
 wie `telefon_check`, KEIN Modell auf diesem Pfad (es wüsste auch nicht,
 WANN die Praxis anruft): Ziffern → Readback Ziffer für Ziffer → Ja →
 `rueckruf_nummer_nachtragen` (zweite JSONL-Zeile, `praxisNotiz` + Dock
 mit Nummer); Nein/„die letzte war eine neun" → Korrektur schlägt Fragment
 (sonst stünde ein einsames „9" als Diktat-Anfang und Bianca schwiege) →
 einmal neu erfragen; „Meine Nummer haben Sie doch" ohne Anrufer-ID →
 ehrlich „In der Leitung wird mir leider keine Nummer angezeigt";
 Ablehnung/„das war's" oder ZWEI unklare Antworten → ehrlich ohne Nummer
 abschließen (Notiz bleibt, der Anrufer hört, dass er die Praxis direkt
 erreichen kann) — nie eine Schleife; Zwischenfrage („Wie lange dauert
 das?") wird deterministisch beantwortet und die Nummer erneut erfragt.
 Ein ANDERES Anliegen (Hirn-Wechsel, Task-Handoff, `_NOCH_EIN_TERMIN_RE`)
 gewinnt: die Nummernfrage wird abgebrochen (Spur
 `rueckruf-nummer abgebrochen:anliegen`), die Notiz bleibt wie sie ist.
 Gilt an beiden Notiz-Stellen: `_angebot` (leere Suche) und `_buchen`
 (`slotTaken` ≥ 2).
- Tests: `tests/test_kurzlaut_bestand.py` (Ausruf-Liste, Serie → Stups,
 Doppelverneinung mit Gegenprobe), `tests/test_rueckruf_nummer.py` (alle
 Zweige inkl. `_buchen`-Fehlpfad und Abbruch durch anderes Anliegen);
 die Live-Wortlaute der drei Anrufe stehen dort wortgleich drin.

## Rechnungsthemen nur persönlich — oder Rückruf (W-RECHNUNG 14.09.2026 — nicht rückbauen)

Chef zum Thaler-Anruf 3ad3b6d3 (wörtlich): „Rechnungsreklamation., Fehlerhafte
Rechnung., Fehler, abrechnungsfehler, Buchhaltung...Rechnung... diese und
ähnliche Worte/Sätze müssen wir nachschärfen dadurch, dass Bianca sagt, dass
Rechnungsthemen nur persönlich in der Praxis besprochen werden können, oder
sie einen Rückruf anbietet und einrichtet auf Wunsch. Sie selbst hat keine
Autorisation über Rechnungen zu reden." Live kam auf „Rechnungsreklamation."
und „Fehlerhafte Rechnung." zweimal der Unklar-Satz — zwei verschenkte Züge.

- **Erkennung** (`kern/rechnung.py`, deterministisch, 0 ms): harte Wörter
  (Rechnung + Komposita, Reklamation, Mahnung, Abrechnung/Abrechnungsfehler,
  Honorar, Zahlungserinnerung, Inkasso, zu viel bezahlt, doppelt abgebucht,
  „keine Rechnung bekommen") immer; weiche (Betrag, Kosten, bezahlt …) nur mit
  Beschwerde-Marker und ohne Termin-/Kassen-Kontext; **„Buchhaltung" ist ein
  Rechnungsthema**, kein Durchstell-Wunsch (die Rollen-Erklärung der
  Weiterleitung kommt nicht mehr). Gegenproben sind der größere Teil der
  Tests: Preisfragen („Was kostet die PZR?"), Kassenfragen, Termine, ein
  NAMENTLICH verlangter Behandler („mit Doktor Petsas über die Rechnung
  sprechen" → Weiterleitung), Nachnamen („Rechnungshofer") und Verneinungen
  („es geht nicht um die Rechnung"). **Im Diktat nie** (`diktat_laeuft`:
  Nummer/Buchstabieren offen oder Fragment) — auch die Intent-Schicht
  (`kern/intent.py`: `_eindeutig`, `_fallback`, `_wechsel_verdacht`) fragt
  `rechnung.erkannt(text, sit)`, sonst räumte ein Wechsel-Verdacht die
  Nummern-Frage und parkte die Buchung.
- **Zug** (`bianca/flow._rechnung_zug`, VOR `weiterleiten.zug`, nach dem
  Dokument-Hook): Erklärung + „Soll ich Ihnen dafür einen Rückruf
  einrichten?" (`frage=rechnung_rueckruf`, Formular-Frage, kurze Ruhe-
  Schwelle). Ja → der bewährte ABGEBEN-Weg (`_abgeben_zug`: Name, Nummer,
  `verwalten.abgeben_notiz` — die JSONL-Zeile trägt jetzt `was` = worum es
  geht). „Rufen Sie mich wegen der Rechnung zurück" überspringt die Frage.
  **Nummer wie W-RUECKRUF-NUMMER** (`_rechnung_nummer_zug`; Live-Probe im
  Container nach dem ersten Deploy: die diktierte Nummer wurde sofort
  geglaubt, im Schlusssatz vorgelesen und die Notiz geschrieben — „Ja,
  richtig." darauf fiel ans Modell („Was meinen Sie damit?"), eine Korrektur
  hätte die Notiz nicht mehr geändert): `_abgeben_kontakt(sofort=False)`
  lässt die gehörte Nummer in `telefonOffen`, Bianca liest sie Ziffer für
  Ziffer vor (`telefon_check`), erst das Ja macht sie fest und schreibt die
  Notiz; Nein/„die letzte war eine neun" → einmal neu erfragen (Korrektur
  schlägt Fragment); Zwischenfrage/Unklares auf die Nummern-Frage →
  deterministische Erinnerung, beim zweiten Mal bzw. nach drei Vorlesern
  ehrlich OHNE sichere Nummer abschließen (Notiz mit Namen + „bitte
  Kartei", `NUMMER_UNSICHER`). Leitungs-/Akten-Nummer gilt weiter ohne
  Rückfrage. Der Schlusssatz liest eine eben bestätigte Nummer nicht noch
  einmal vor. Danach bleibt „Kann ich sonst noch etwas für Sie tun?" als
  OFFENE Frage (`frage=sonst_noch`, nur wenn kein anderes Anliegen läuft):
  Nein/Danke/Abschied → freundlich auflegen, kurzes Ja → „Gerne — was kann
  ich noch für Sie tun?", alles andere (Termin, erneutes Rechnungswort) →
  normaler Fluss (`_rechnung_sonst_noch`) — nie „Was meinen Sie damit?".
  Nein / „ich komme vorbei" →
  ehrlich abschließen (`ABGELEHNT`); unklar → EINE Nachfrage, dann gilt
  Nein (kein Verhör). „Nein, aber ich brauche einen Termin" eröffnet die
  Buchung; „Nein, verbinden Sie mich mit Doktor X" verbindet; ein bloßer
  Behandlername auf die Frage verbindet NUR, wenn der Einstieg ein
  Sprech-Wunsch war („Kann ich mit der Buchhaltung sprechen?" →
  `rechnungStand.sprechwunsch`) — sonst unklar, nie raten. Abschied auf die
  Frage = Nein + Auflegen.
- **Mitten in der Buchung** wird sie geparkt (Hirn: ABGEBEN mit
  `rechnung=True`, Checkpoint) und kommt nach Nein/Notiz zurück („Alles
  klar. So, zurück zu Ihrem Termin. Zu welchem Behandler …?") — beim
  Rückruf diktierte Kontaktdaten stehen dann schon im Sammler der Buchung
  (`hirn.checkpoint_ergaenzen`: Name nur als Gruppe, Nummer als
  `telefonBekannt` → SMS-Frage statt Diktat). Wird die Frage OHNE Nachfolger
  verneint, holt `hirn.geparktes_zurueckholen` die Buchung sofort (sonst
  strandete sie einen Zug). Stale-Sammler-Falle: nach `rechnung_abbrechen`
  ist `sit["sammler"]` ein neues Dict (Checkpoint) — `zug()` holt `s` neu.
- **Stand** `sit["rechnungStand"]` (offen/rueckruf/notiert/abgelehnt/
  persoenlich, `was`, `gefragt`, `unklar`): nach Ablehnung fragt ein
  erneutes Rechnungswort kürzer (`ERKLAERUNG_WIEDERHOLT`), nach der Notiz
  gibt es keine zweite Sammelei („schon notiert — die Praxis meldet sich").
  `kern/gedaechtnis.zusammenfassung` hängt `rechnung.zusammenfassung_zeile`
  an — das Thema steht im Report AUCH ohne Rückruf.
- **LLM-Ausgang** (`agent._rechnung_wache_anwenden`, Endtext UND P5-Satz):
  ein Modell-Satz mit hartem Rechnungs-Vokabular, der weder auf die Praxis
  verweist noch die eigene Grenze nennt, fällt (Betrag, Zahlungsstand, „ich
  kümmere mich"); bleibt nichts, kommt die feste Erklärung. Preise (PZR,
  Bleaching) sind kein Rechnungs-Vokabular. Prompt-Block RECHNUNGEN in
  `bianca/prompt.py`.
- Notaus: `RECHNUNG=0` (Erkennung aus — Verhalten wie vor dem 14.09.),
  `RECHNUNG_WACHE=off|shadow|enforce` (Default enforce). Tests:
  `tests/test_rechnung.py` (62), Buchhaltung-Fälle in
  `tests/test_weiterleiten.py`.

## Rücklese ohne Namensraten (W-BUCHUNG-BEWEIS 15.09.2026 — nicht rückbauen)

Chef zum Thaler-Anruf `831c8b6bd9044569962d20abdc9a5885`: „das war ein
perfektes gespräch aber die buchungsfunktion failte. warum" — der Termin
(16.09. 13:00, IMP Besprechung, Kalender Eva Thaler) stand danach sauber im
Kalender, die Anruferin hörte aber „Die Buchungsantwort ist nicht eindeutig
im Kalender angekommen".

Der Schreibweg war grün: `masBookAppointment` → HTTP 200, `appointmentId
5JCHiVjknQCuVJDYj2l8`, Akte `npZu3ptUmDODjsNkuzRE`. Gestolpert ist die
Read-after-write-Prüfung (`_buchung_verifizieren`, 10.09.), und zwar am
Plattform-Vertrag: `agentFindPatientAppointments` löst den Patienten über
**Namens-Ähnlichkeit** auf und liest eine mitgeschickte `patientId` NICHT
(`functions/src/controllers/agentAppointments.ts`). In der Praxis liegen
DREI Akten „Eva Thaler" — die Rücklese traf `3DsgqaItzZCbkPDI9wfd` samt
deren PZR am 21.10., `found_pid != patient_id` schlug zu. Die Prüfung ist
also richtig streng, sie hatte nur keinen Weg, die gebuchte Akte überhaupt
zu adressieren.

- **Zweiter, namensfreier Beweisweg** (`_buchung_beweis_ueber_akte`):
  `masPatientLastDoctor` NIMMT die `patientId` (`masAgent.ts`). Derselbe
  Vierfach-Beweis (Akte, Startminute, Kalender, echte Termin-ID) läuft damit
  ohne Namensraten. Bewusst nur `nextAppointment`: liegt ein früherer Termin
  der Akte davor, beweist dieser Weg nichts und der Termin bleibt
  unbestätigt — lieber ehrlich als geraten.
- **Nur bei fehlender Evidenz, nie gegen einen Widerspruch:**
  `namenspfad_traf_akte` merkt, ob die Namensliste die RICHTIGE Akte
  überhaupt erreicht hat. Nur wenn nicht (fremder Treffer, notFound,
  mehrdeutig, CF-Fehler) darf der Akten-Weg ran. Traf sie die Akte und der
  Termin passte trotzdem nicht, bleibt es unbestätigt — das ist die
  Tom-Schumann-Klasse vom 11.09. (fremde/recycelte ID) und wird NICHT
  überstimmt. Auf dem guten Pfad kostet der Beweis keinen Aufruf.
- **`callerPhone` geht mit** (`verify_ctx["phone"]`): live fehlte die Nummer
  im Verify-Body. Mit ihr kandidiert die CF ZUERST über das Telefon und
  nimmt sie sonst als Stichentscheid (`patientsService.findClientLocation
  PatientUserBySimilarity`) — findet die Nummer nichts, fällt sie selbst auf
  die Namenssuche zurück. Die Angabe kann also nur helfen.
- Sichtbar in der Gesprächsansicht: `dispatch.verification.beweis` ist
  `namensliste` oder `akte`, im zweiten Fall steht der Grund der Namensliste
  in `namenslisteFehler`. Log: `buchung-beweis akte pid=… aid=… iso=…`.
- Notaus: `BOOK_VERIFY_AKTE=0` => byte-identisches Verhalten von vor dem
  15.09.2026 (nur Namensliste). Tests: `tests/test_buchung_beweis.py` (9,
  mit den echten Live-Payloads des Anrufs) — die Gegenproben (Widerspruch,
  falsche Startminute, falscher Kalender, kein kommender Termin, Notaus)
  sind der wichtigere Teil.

**Nicht Biancas Baustelle, aber der Grund für die Dublette:** die Akte
`npZu3ptUmDODjsNkuzRE` wurde am 14.09.2026 per Import angelegt und trägt die
kaputte Nummer `+015167807647` (E.164 kennt keine führende Null nach der
Ländervorwahl) — deshalb kam auch keine Bestätigungs-SMS. Biancas eigener
Weg (`patients.handy_e164`) hätte das nie erzeugt. Sauber wird das nur im
Portal: Dubletten zusammenführen, Nummer korrigieren.

## Handynummer in die Akte, sonst kein Termin (W-AKTE-HANDY 15.09.2026 — nicht rückbauen)

Blessing-Anruf `a8fcbcb43aad496aa2a1451447a1d50f` (15.09., 07:40, 6:36 min):
Bestandspatientin, Kontrolltermin am 3. Dezember 14:40 bei Doktor Blessing.
In der Akte stand NUR eine Festnetznummer. Sie diktierte ihr Handy und
bestätigte es Ziffer für Ziffer — die Plattform lehnte die Buchung trotzdem
VIERMAL mit `needs_phone` ab, weil niemand die Nummer in die Kartei schrieb.
Bianca fragte dieselbe Nummer wieder und wieder ab, sagte dann „Alles klar,
die Nummer ist gespeichert. Dann ist alles für Sie eingetragen." — im
Kalender stand nichts — und beendete mit 13× „Kann ich sonst noch etwas für
Sie tun?". Vier Ursachen, vier Wachen:

1. **Selbstheilung bei `needs_phone`** (`kern/calendar._handy_nachtragen`, in
   `book_slot`): kommt `needs_phone`, schreibt Bianca die RÜCKBESTÄTIGTE
   Handynummer per `masUpdatePatientPhone` in die Akte und bucht GENAU EINMAL
   neu. Geschrieben wird nur `ctx["phoneConfirmed"]` (aus `telefon` +
   `telefonOk`, gesetzt in `flow._ctx_bauen` — `ctx["phone"]` trägt notfalls
   die Akten-Nummer und taugt dafür nicht) und nur eine echte deutsche
   MOBILnummer (`patients.ist_handy_de`; `handy_ok` prüft bloß die Länge, ein
   Festnetz käme da durch und die SMS liefe erneut ins Leere). Der Weg liegt
   HINTER dem Trockenlauf-Tor (`WRITE_LIVE`/`_testNoWrite`), schreibt also im
   Test nie. Sichtbar in der Gesprächsansicht: `dispatch.phoneFix`,
   `phoneFixDispatch`, `needsPhoneVorher`. Notaus: `BOOK_FIX_PHONE=0`.
2. **`telefon_alt` nie gegen ein Festnetz** (`gehirn.naechste_frage`,
   `telefon.ist_handy`): die Wahlfrage „alte Nummer löschen oder SMS an die
   alte" setzt voraus, dass an der alten Nummer überhaupt eine SMS ankommt.
   Live wählte die Anruferin folgerichtig „die Bestätigung an die alte
   Nummer" — und damit war die Buchung unmöglich (`telefonAlt="akte"` → kein
   Update → `needs_phone` für immer). Gegen eine Festnetz-/Dummy-Nummer wird
   nicht mehr gefragt; `flow._buchen` trägt die bestätigte Handynummer still
   nach (dieselbe Stelle wie das Eskalations-Sicherheitsnetz), der Termin
   bekommt den Vermerk „Alte Nummer … aktualisiert //Bianca". Gegen ein altes
   HANDY bleibt die Frage wie am 29.08. beschlossen.
3. **Die Sonst-noch-Frage ist eine echte Formular-Frage**
   (`flow._sonst_noch_frage`/`_sonst_noch_antwort`): wer sie stellt,
   REGISTRIERT sie (`frage="sonst_noch"`) — sonst fällt jede Antwort in den
   Rückruf-Zweig und bekommt denselben Satz. „Nein."/„Danke."/Abschied legen
   auf, kurzes „Ja." lädt ein, alles andere gehört der Talk-Schicht (Frage
   geräumt, nie wortgleich wiederholt); war sie schon gestellt, kommt sie nie
   ein zweites Mal (`sonstNochGefragt`).
4. **Fakten-Wache kennt den Satz und die Nummer** (`kern/fakten_wache.py`):
   `_CLAIM_BUCHEN` deckt jetzt die Füllwort-Formen ab („ist alles/damit/
   somit/dann (für Sie) eingetragen") — die Füllwörter stehen einzeln da,
   damit eine ehrliche VERNEINUNG („ist noch nicht eingetragen") nie als
   Behauptung gilt. Neu `_CLAIM_NUMMER` + `_ev_nummer`: „die Nummer ist
   gespeichert/hinterlegt/aktualisiert" braucht einen gelaufenen
   Schreibvorgang (`update_phone`, neue Akte, geglückte Buchung) ODER den
   Kartei-Stand (die Akte trägt genau diese Nummer — Bianca fragt selbst nach
   der „hinterlegten Nummer", das darf die Wache nicht überschreiben). Hedge:
   „Ihre Nummer steht noch nicht in der Akte."

Tests: `tests/test_anruf_a8fcbcb4.py` (40, mit den Live-Wortlauten:
Selbstheilung samt Update-Fehler, fehlendem bestätigtem Handy und Notaus,
Sammler-Nachzug, Gegenproben der Wache), Abschlussfrage-Block in
`tests/test_rueckruf_nummer.py`; die `telefon_alt`-Fixtures in
`tests/test_bianca_bausteine.py` tragen jetzt ein altes HANDY — gegen ein
Festnetz gibt es dort nichts mehr zu fragen. Abnahme am DEPLOYTEN Stand
(read-only, kein Kalender-Write): `docker exec -w /app telefonki-bianca-test-1
python tools/_probe_a8fcbcb4_live.py` — 15.09.2026 grün.

## Ein Prozess, mehrere Stimmen und Namen (W-STIMME-MANDANT 15.09.2026 — nicht rückbauen)

Neue Praxis Fr. Dr. Denise Rüther (Gynäkologie, DID +49 211 54244160): Chef
15.09.2026 — „ich brauche für Frau Rüthers telefonKi eine männliche Stimme und
der Assistent soll Ben heissen." Bis dahin war beides PROZESS-weit fest: eine
Stimme (`tts.set_voice` beim Start, `_VOICE_NAME="bianca"`) und der Name
„Bianca" hart im Code, samt weiblicher Grammatik („Empfangsassistentin",
„Ich bin die Neue!", „Sie sprechen mit Bianca, der Telefonassistentin").
Ein zweiter Prozess pro Praxis war keine Option — die Sitzungen, der
Mitschnitt und die SIP-Brücke hängen an EINEM Dienst auf 8096.

Wer spricht, entscheidet jetzt der Mandant. Alles läuft über `kern/assistent.py`
(`name`, `genus`, `maennlich`, `stimme`, `formen`) und ist so gebaut, dass
MedDent, Thaler und Blessing **byte-identisch** bleiben:

- **Name** (`assistentName` in `tenants/*.json`) gewinnt immer; sonst der
  Agent-Name aus der Pickadoc-DB, aber NUR wenn er wie ein einzelner Vorname
  aussieht (die DB führt dort teils den PRAXIS-Namen, `'"Med Dent" Zahnklinik
  Duesseldorf - Robert'` — den darf sich die Assistenz nie selbst sagen);
  sonst „Bianca".
- **Genus** aus `assistentGenus` (m/f), sonst aus einer kleinen Namenstabelle,
  im Zweifel weiblich. Bewusst NICHT über `kern/vornamen.py`: das ist der
  Wächter für PATIENTEN-Namen (dort gilt „unklar ⇒ weiblich + Notiz") und
  kennt „Ben" nicht.
- **`formen(text, tenant)`** dreht die SELBSTbezeichnung. Bei weiblicher
  Assistenz kommt der Text unverändert zurück — kein Zeichen bewegt sich.
  Die Tabelle `_MAENNLICH` steht absichtlich von lang nach kurz: „Bianca, **der
  Telefonassistentin** der Praxis" muss zu „**dem Telefonassistenten**" werden;
  ein blindes Ersetzen von „Telefonassistentin" ließe den falschen Kasus
  („der Telefonassistent") stehen. „Frau Doktor", „Ihre Kollegin" (die
  ANRUFERIN!) und Behandlerinnen-Namen stehen bewusst NICHT in der Tabelle.
  Eingehängt in `bianca/prompt.system_prompt`, `bianca/greeting.begruessung`
  (nimmt jetzt den Mandanten) und `gehirn._hallo_wahl`.

**Die Stimme ist eine Contextvar, kein Parameter** (`tts._STIMME_JETZT`,
gesetzt über `dienst.stimme_aus_sitzung(sit)`): TTS wird aus rund 40 Stellen
gerufen — Füller, Vorab-Sätze, Readbacks, Warm-Lauf — und die meisten kennen
den Mandanten nicht. Drei Fallen, alle eingebaut:

1. **Fäden verlieren den Kontext.** Ein frischer `threading.Thread` startet mit
   LEEREM Contextvar-Kontext; Bens Füller und der Stream-Feeder hätten mit
   Biancas Stimme geantwortet. Deshalb laufen alle sprechenden Fäden in
   `kern/dienst.py` über `faden()` (`contextvars.copy_context().run`) — und
   `test_alle_faeden_in_dienst_nehmen_den_kontext_mit` lässt genau eine
   Ausnahme zu: `faden()` selbst.
2. **Vorgerenderte Sätze lagen nach Text geschlüsselt.** Füller, Barge-
   Quittungen und Notfall-Ansagen werden beim Start gerendert — jetzt je
   Stimme (`vorab_ablegen`/`vorab_url` mit Schlüssel `"<stimme>|<text>"`,
   `quittung_urls`/`notfall_urls` als Dict je Stimme, `stimmen_im_haus()`
   liefert Prozess-Default + jede Mandanten-Stimme). `quittungen_fuer(sit)` /
   `notfall_fuer(sit)` fallen auf die Prozess-Stimme zurück, wenn eine Praxis
   noch nicht vorgerendert ist — lieber fremde Stimme als Stille. Die Brücke
   holt die Quittungen deshalb MIT `?sessionId=`.
3. **Der Stille-Stups spricht am `json_antwort`-Pfad vorbei**
   (`/api/stille` → `DIENST.stimme()` direkt). Ohne `stimme_aus_sitzung(sit)`
   dort stupst Biancas Stimme mitten in Bens Anruf; die Wache
   `test_stups_pfad_setzt_die_anruf_stimme` prüft sogar die Reihenfolge.

Auch der **Warm-Lauf** setzt die Stimme je Mandant, bevor er Begrüßung und
`feste_saetze` wärmt — der Cache-Schlüssel trägt sie, ein Warm-Lauf in Biancas
Stimme wäre für Ben wertlos (und er zahlte live die Synthese). `feste_saetze`
gibt für einen männlichen Assistenten die männlichen Formen zurück, damit
genau die Sätze im Cache liegen, die der Mund spricht.

**Statische Audio-Altlaster (16.09.2026):** Ist ein Füller trotz richtigem
Mandantenkontext einmal mit der falschen Referenz im Platten-Cache gelandet,
reicht ein normaler Warm-Lauf nicht — Dauer-Audios werden absichtlich
wiederverwendet. `tools/rerender_statische_stimme.py --tenant ruether
--schreiben` löscht und rendert ausschließlich die 19 kurzen Füller-,
Barge- und Notfall-Audios unter dem Stimmenschlüssel `ben`; danach lädt ein
Bianca-Neustart sie neu in die URL-Ablage. Der Lauf vom 16.09. hat alle
19 Dateien nachweislich neu mit `voice=ben` geschrieben.

**Herkunft in Notizen und Berichten:** `sit["stimme"]` bleibt intern
absichtlich `"Bianca"` — Prozess-Gates und Mitschnitt-Ordner hängen daran.
`kern.notes.stimme_von(sit)` löst für sichtbare Herkunftsstempel dagegen
`assistent.name(tenant)` auf. Deshalb schreibt Rüther `// Ben` und
„Laut Anruf (Ben)“, während MedDent, Thaler und Blessing weiterhin
`// Bianca` schreiben. Praxisnotiz-JSONL nutzt dieselbe Quelle.

Der Stimmklon `ben` liegt als `tts_serve/stimmen/ben.wav` + `ben.txt` (Referenz
vom Chef, ElevenLabs-Export „Mark", 4,9 s) und ist im Container über
`TTS_STIMMEN_EXTRA` registriert — kein Rebuild, aber ein Neustart des
TTS-Containers (der 15.09. eine laufende Blessing-Leitung 9 s gekostet hat:
das nächste Mal in einer Anrufpause).

**Der Agent-Name aus der DB wird durchgereicht** (`agentprofil.tenant_von_pre`
setzt `t["agentName"]`). Ohne diese eine Zeile hieße jede Praxis OHNE lokale
`tenants/*.json` für immer „Bianca", egal was im Portal steht — der DB-Weg
(Chef 30.08.2026: „die Konfig MUSS aus der DB kommen") wäre für den Namen tot.
Gefahrlos, weil `assistent._aus_db` streng prüft und ALLE heutigen Live-Agenten
in der DB „Bianca" heißen (17 Datensätze am 15.09. gegengelesen; die übrigen
tragen Praxis-Namen und fallen durch den Vorname-Filter). Das Genus bleibt für
einen unbekannten Namen weiblich — wer einen männlichen Assistenten will, setzt
`assistentGenus` (oder trägt den Namen in `_GENUS_NAMEN` ein).

- **Notaus:** `assistentName`/`assistentGenus`/`stimme` aus `tenants/ruether.json`
  entfernen ⇒ Ben ist wieder Bianca, alles byte-identisch wie vor dem
  15.09.2026. Es gibt bewusst keinen Env-Schalter: die Mandanten-Datei IST der
  Schalter.
- Tests: `tests/test_assistent.py` (35) — hinter jedem Ben-Fall steht die
  Gegenprobe, dass MedDent/Bianca sich nicht rührt. Live-Probe im Container:
  `docker exec -w /app telefonki-bianca-1 python tools/_probe_stimme_mandant_live.py`
  (mit `--hoeren` rendert sie Bens Begrüßung im echten TTS-Container und liest
  sie per STT gegen — 15.09. grün: „…mit dem digitalen Telefonassistenten Ben").

**Noch offen bei Rüther** — Befunde gebündelt in
`docs/BEFUND-RUETHER-PORTAL.md` (15.09.2026 read-only gegen die Live-Daten
geprüft). Kurz:

1. Auf der Nummer liegen ZWEI aktive inbound-Agenten — `LtHkW6I1xSwDpWy5M3vy`
   („Ben", Buchungs-Tools an) und `jeLZftpLKZdQaDUwVml6` („Bianca", alle Tools
   aus, leere Begrüßung). Derzeit gewinnt Ben; das ist Zufall der
   Dokument-ID-Sortierung. Der Bianca-Datensatz muss weg.
2. Der Agent-Prompt ist LEER (nur `systemPrompt`, 462 Zeichen Datum/Zeitzone/
   Anrede) — Text liegt fertig in `docs/prompt-ruether.md`.
3. 20 der 31 Telefon-Besuchsgründe stehen auf `allowOnlineBooking=false`
   (32 Motive in Firestore, eines filtert `motive.telefon_tauglich`) — darunter
   Krebsvorsorge, PAP/HPV, Schwangerschaftsvorsorge, Spirale. Die Zuordnung
   trifft live korrekt („Krebsvorsorge" → `GYN Krebsvorsorge`), die CF liefert
   dafür aber 0 Zeiten. Seit W-ERSATZ-MOTIV/V2.8.1 wird dafür niemals mehr
   eine Endometriose-Erstberatung angeboten: Ben sagt ehrlich, dass diese
   Terminart telefonisch nicht vergeben werden darf, und schreibt eine
   Rückruf-Notiz. Für echte Telefonbuchungen muss die Praxis die gewünschten
   Motive im Portal trotzdem freischalten. `GYN Schwangerschaft Ersttermin`
   wurde am 16.09. online freigeschaltet; die echte Slotsuche lieferte danach
   bei beiden Ärztinnen weiter 0 Zeiten, bis die zugehörigen Sprechzeiten
   eingerichtet sind. Bewusste Entscheidung des Chefs: echte Motive und
   Sprechzeiten einzeln freigeben, keinen medizinisch falschen allgemeinen
   Kontroll-Fallback erfinden.
4. Die Öffnungszeiten stehen auf dem Portal-Default (alle sieben Tage
   08:00–18:00). `standort.zeiten_von` verwirft genau dieses Muster absichtlich
   („nie raten") — damit hat Ben zu den Zeiten KEINE Quelle. Er verwies
   deshalb aber nicht auf die Praxis, sondern erfand sie (s. W-ZEITEN-WACHE);
   seit dem 15.09.2026 fällt die Erfindung. Die Zeiten gehören ins Portal.
5. Der Dialplan-Eintrag für 4160 liegt als Referenzkopie in
   `sip_bridge/extensions_bianca.conf`; der Live-Asterisk braucht ihn noch
   (kein Shell-Zugang von hier).

## Nur echte Kontroll-Motive als Ausweich (W-ERSATZ-MOTIV 15.09.2026 — nicht rückbauen)

Rüther führt kein generisches Kontroll-Motiv. Der alte Rückfall
`tenants._sicheres_default` lieferte deshalb für „Krebsvorsorge“ die
`GYN Endometriose Erstberatung` — andere Leistung, andere Dauer.

- `tenants.taugt_als_ersatz` und `calendar._kontrolle_ersatz` erlauben nur
  echte Kontroll-, Vorsorge-, Nachsorge-, Recall- oder Check-up-Motive.
- Ist das gewünschte Motiv im frischen Sitzungs-Katalog ausdrücklich
  `allowOnlineBooking=false` und existiert kein sicherer Ersatz, trägt die
  Slotsuche `motivNichtTelefonisch`. `flow._angebot` nennt weder internes
  GYN-Kürzel noch das Wort „Krebs“, sondern sagt ehrlich „Diese Terminart darf
  ich telefonisch nicht vergeben“ und legt eine echte Rückruf-Notiz an.
- MedDent, Thaler und Blessing behalten ihre echten Kontroll-Ausweichmotive.
  Notaus `MOTIV_ERSATZ_STRENG=0` stellt nur die alte Ersatz-Auswahl wieder her.
- Das erste V2.8-Image enthielt zwar die strenge Auswahl, aber wegen eines
  partiellen Server-Syncs nicht die Übergabe `visitMotiveOnline` in
  `calendar._nicht_telefonisch`; dadurch blieb der gesprochene Satz noch
  fälschlich bei „kein freier Termin“. V2.8.1 synchronisiert genau diese
  fehlende Datei. Die Produktionsabnahme prüft den Marker seitdem hart.

Tests: `tests/test_ersatz_motiv.py` (31). Live-Probe, vollständig read-only
bis auf eine Rückruf-Notiz im temporären Verzeichnis:
`docker exec -w /app telefonki-bianca-1 python
tools/_probe_ersatz_motiv_live.py`.

## Rüther: Motivkorrektur + Nachnamensschreibweise (W-RUETHER-KORREKTUR 16.09.2026 — nicht rückbauen)

Live-Anruf `008a9f2cd375432e8b18fc41d31ef3aa`: „Vorsorge“ kam als
„Forsabe“ und wurde auf Hormonstatus gemappt. Der klare Einwand „keine
Hormonstatus-Besprechung, einfach eine Vorsorge“ wurde nicht angewendet;
„Besuchsgrund“ bestätigte danach zweimal den alten Grund. Außerdem schnitt
die Ruhe-Wache den Buchstabierhinweis hinter „Wie lautet der Nachname?“ ab,
und „Tannis“ galt fälschlich sofort als gesicherte Schreibweise.

- `flow._grund_korrektur_text` löst den neuen Grund nach „sondern“,
  „stattdessen“ oder „einfach“ aus dem Einwand. Eine reine Feldwahl
  („Besuchsgrund“) leert den alten Grund und fragt konkret neu; sie darf nie
  als Motivwert gemappt werden. Ein echter Motivwechsel verwirft Slot und
  Vorrat, dieselbe Motiv-ID behält weiter die relative Slotwahl.
- Der marker-gated STT-Fix `Forsabe` → `Vorsorge` greift nur, wenn der
  Mandant „Vorsorge“ als Hotword führt. Rüther führt zusätzlich
  `Hormonstatus` und `Schwangerschaft`.
- Nur Rüther trägt `nachnameDirektBuchstabieren=true`: Die Aufforderung steht
  vor der einzigen Frage und überlebt dadurch W-RUHE. Ein nur gesprochener
  Nachname führt noch nicht zum Vornamen; erst Buchstabierung plus
  `nachnameReadbackNachBuchstabieren` sichern die Schreibweise. Bekannte,
  per Rufnummer identifizierte und bestätigte Patienten werden nicht erneut
  verhört.

Regressionen mit den wortgleichen Live-Sätzen und Gegenproben für MedDent,
Thaler und Blessing: `tests/test_ruether_korrekturen.py`.

## Keine erfundenen Öffnungszeiten (W-ZEITEN-WACHE 15.09.2026 — nicht rückbauen)

Live-Probe gegen den ECHTEN Prompt der neuen Praxis Rüther (Ben, DID …4160).
Der Agent-Prompt aus dem Portal trägt dort keine einzige Praxis-Tatsache
(nur Datum/Zeitzone/Anrede), die Standorteinstellungen stehen auf dem
Portal-Default. Drei Fragen, drei frei erfundene Zeitpläne:

| Frage | Antwort des Modells |
| --- | --- |
| „Wann haben Sie geöffnet?" | „Wir sind heute von 8 bis 12 Uhr und von 14 bis 16 Uhr für Sie da." |
| „Wann habt ihr auf?" | „montags, mittwochs und freitags von 8 bis 12 Uhr, dienstags und donnerstags von 14 bis 18 Uhr" |
| „Haben Sie am Freitag offen?" | „Ja, wir sind freitags von 8 bis 12 Uhr für Sie da." |

Wer das glaubt, steht vor verschlossener Tür — und merkt es erst dort. Zwei
Ursachen, zwei Stellen:

- **Die Frage erreichte das Modell überhaupt** (`wissen._oeffnungszeiten_thema`):
  erkannt wurden nur „Öffnungszeiten/Sprechzeiten" und „wann … offen/geöffnet".
  „Wann habt ihr auf?" und „Haben Sie am Freitag offen?" fielen durch und
  landeten als freies Talk-Thema beim LLM. `offen`/`auf` zählt jetzt hinter
  einem Praxis-Subjekt („haben Sie/habt ihr/ist die Praxis"), aber NIE mit
  Termin-Bezug — „Haben Sie den Termin noch offen?" bleibt draußen.
- **Der LLM-Ausgang war unbewacht** (`kern/zeiten_wache.py`, eingehängt in
  `agent._zeiten_wache_anwenden` am Zugende UND im P5-Strom — sonst ist der
  Satz gesprochen, bevor die Wache greift; dieselbe Doppel-Einhängung wie
  W-ANREDE/W-FACH-WACHE). Eine Zeit-Auskunft darf nur raus, wenn die Zeiten
  BELEGT sind: `standort["text"]` (W-STANDORT), eine ausdrückliche Zeile im
  Agent-Prompt („Öffnungszeiten: …" bei MedDent, der „SPRECHZEITEN"-Block bei
  Thaler/Blessing) oder lokales `wissen.oeffnungszeiten`. Sonst fällt der
  Satz; bleibt nichts, kommt „Die genauen Öffnungszeiten habe ich hier leider
  nicht vorliegen — einen Termin kann ich Ihnen aber gern direkt geben."

Die **Belegt-Seite ist bewusst großzügig** (Öffnungs-Vokabular plus Zeitangabe
irgendwo im Praxis-Prompt genügt) und ohne Mandant ist die Wache AUS: eine
gestrichene ECHTE Auskunft wäre der teurere Fehler — dann könnte die Praxis
ihre eigenen Zeiten nicht mehr sagen. Ebenso unangetastet bleiben Sätze mit
Termin-/Buchungs-Bezug: „Am Montag um neun Uhr hätte ich einen Termin frei"
ist eine Kalender-Aussage und hat ihre eigene Wache (W-FAKTEN-WACHE,
Slot-Claim).

Auf eine **gestellte** Zeiten-Frage kommt die ehrliche Auskunft VORAN: nach dem
Streichen blieb live nur der Folgesatz übrig („Möchten Sie sich zur Kontrolle
vorstellen?") — eine Rückfrage, die an der gerade gestellten Frage vorbeigeht.
Fing das Modell von selbst mit Zeiten an, genügt das Streichen. Der Ersatz
kommt pro Zug **genau einmal** (`_zeitenErsatz`, Schlüssel Zug-Nummer +
gehörter Satz): im P5-Strom läuft jeder Satz einzeln durch die Wache, zwei
erfundene Zeit-Sätze hätten ihn sonst zweimal gesprochen. Ist er verbraucht,
bleibt der zweite Satz LEER — kein `neu or text`, die Erfindung darf nie als
Rückfall zurückkommen; am Zugende hängt `_nie_stumm` die offene Pflichtfrage
an, im P5-Strom wird ein leerer Satz nicht gesprochen.

Zwei Löcher, die die Live-Gegenprobe danach noch zeigte:

- **Die knappe Antwort ohne Öffnungs-Wort.** „Heute von 8 bis 12 Uhr und von
  14 bis 16 Uhr." trägt kein Öffnungs-Vokabular und blieb stehen. Auf eine
  GESTELLTE Zeiten-Frage genügt darum die Zeitangabe allein
  (`ist_zeit_auskunft(satz, streng=True)`); ohne Frage bleibt es bei
  Vokabular PLUS Zeit — sonst fiele „Dann sehen wir uns um 14 Uhr."
- **Die Fortsetzung des gestrichenen Plans.** „Danach schließen wir." /
  „An den anderen Tagen nachmittags von 14 bis 18 Uhr." bezieht sich auf
  einen Satz, den es nicht mehr gibt. `ist_fortsetzung` streicht solche
  Rückbezüge (danach/ansonsten/an den anderen Tagen + Schließ- oder
  Zeitwort) — aber NUR, wenn in diesem Text oder Zug schon ein Zeitplan
  gefallen ist (`_zeitenWeg`, gleicher Zug-Schlüssel wie `_zeitenErsatz`;
  im P5-Strom kommt der Rückbezug in einem eigenen Aufruf). Allein stehend
  bleibt der Satz unangetastet, „sonst noch etwas?" und „Danach hätte ich
  einen Termin frei" ebenfalls.

- Stufen/Notaus: `ZEITEN_WACHE=off|shadow|enforce` (Default **enforce**).
  Spur: `zeiten-wache` / `zeiten-wache-shadow`.
- Tests: `tests/test_zeiten_wache.py` (33) — die Gegenproben (belegte Praxis
  spricht weiter, Termin-Sätze mit Uhrzeit bleiben, Rückbezug ohne
  Vorgänger bleibt, Frage-Erkennung greift nicht bei Terminfragen) sind der
  größere Teil. Live-Gegenprobe im Container: `docker exec -w /app
  telefonki-bianca-test-1 python tools/_probe_zeiten_live.py` — lädt die
  Mandanten über `agentprofil.fuer_did` (NICHT `tenants.laden`: die lokale
  Datei kennt weder `dbPrompt` noch `standort`, dann sieht die Probe alle
  vier als „unbelegt"), ruft `start_reply` vor dem ersten Zug und stellt
  allen vier Mandanten dieselben drei Fragen.

## Blessing-Namensfrage ohne Unklar-Doppelschleife (W-BLESSING-NAME-UNKLAR 15.09.2026 — nicht rückbauen)

Blessing-Livefälle: Nach einer offenen Namensfrage bekamen leicht verhörte
oder kurze Namen wie „Mülhausen“, „Said“, „Aqu“ und „Manuela“ den allgemeinen
Zwei-Fragen-Satz „Was meinen Sie damit? Meinen Sie vielleicht etwas anderes?“.
Das half der Erfassung nicht, spiegelte möglicherweise einen echten Namen als
Fehler zurück und startete parallel die allgemeine Unklar-Schleife.

- `bianca/agent._namens_unklar_antwort` hält Name, Nachname, Vorname,
  Buchstabierung und Namenskorrektur deterministisch im Formular. Der
  unsichere STT-Text wird nicht wiederholt und erreicht das LLM nicht.
- Die Namensfrage bleibt offen; `flow.frageLeer` behält seinen vorhandenen
  Ausstieg beim nächsten Fehlversuch. Der allgemeine `unklarFolge`-Zähler
  wird auf diesem Weg nicht gesetzt.
- Strikt mandantenscharf: nur `tenants/blessing.json` trägt
  `namensUnklarOhneEcho=true`. Ohne den Schalter läuft der bisherige Weg
  byte-identisch — Gegenproben für MedDent, Thaler und Rüther.
- Tests: `tests/test_blessing_namen.py`. Seit Produktionsstand V2.8 live.

## Blessing-Buchstabiersegmente nicht zusammenkleben (W-BLESSING-BUCHSTABIER-SEGMENTE 15.09.2026 — nicht rückbauen)

Zwei Live-Anrufe zeigten drei verschiedene Verluste im selben Parser:
`a97bc81a` machte aus „L-O-U-R-E-N-C wie Cäsar O“ je nach Parakeet-Zug
`Lourencbcsao` bzw. `Lourencvcsao`, las `R-EN-C-O` als `R-N-C-O` und entfernte
bei „neues Wort“ alle Wortgrenzen. `c7470b98` klebte den erfragten Nachnamen
Hallwachs und den danach genannten Kindesnamen Tamia zu
`Hallwachstmiatamia`. Das Zweit-Ohr hatte „Hallwachs. Tamia. T-A-M-I-A“
korrekt getrennt, durfte eine Namensfrage nach W-QWEN-SICHER aber bewusst
nicht live überschreiben.

- `bianca/buchstaben.deute_feldsegment` ist ein opt-in Parser VOR dem
  bewährten `deute`: Großbuchstaben-Cluster in Hyphen-Ketten werden entfaltet
  (`R-EN-C-O` -> `R-E-N-C-O`), die beiden beobachteten Parakeet-Formen von
  „C wie Cäsar“ werden auf C reduziert, und ausdrücklich gesagtes „neues Wort“
  bleibt als Leerzeichen in zusammengesetzten Nachnamen erhalten.
- Ohne „neues Wort“ endet das gerade erfragte Feld an einer bereits
  vollständigen ersten Buchstabierkette, wenn danach eine zweite vollständige
  Kette folgt. Kommas zwischen Einzelbuchstaben und geteilte Ketten
  (`L-O-U, R-EN-C-O`) bleiben dagegen EIN Name.
- Ein gesprochenes Schlusswort wird auch im Nachsprech-Rückfall abgeschnitten:
  „Gavranides, fertig“ speichert `Gavranides`, nie `Gavranidesfertig`.
- Strikt mandantenscharf: nur Blessing trägt
  `buchstabierSegmenteTrennen=true`. `buchstaben.deute` und der
  `_nachgesprochen`-Standardweg bleiben ohne den Schalter byte-identisch für
  MedDent, Thaler und Rüther.
- Regressionen mit den wortgleichen Live-Transkripten:
  `tests/test_blessing_namen.py`; seit V2.8 live.

## Blessing-Nachnamen vor der Suche rückbestätigen (W-BLESSING-NACHNAME-READBACK 15.09.2026 — nicht rückbauen)

Nach A1/A2 konnte Bianca die Buchstabierung sicherer verstehen, verwendete das
Ergebnis aber weiterhin SOFORT für Patienten- und Termin-Suchen. Ein einzelner
Rest-Verhörer („Pusch“ statt „Busch“) traf damit eine falsche oder gar keine
Akte, bevor der Anrufer die gespeicherte Schreibweise überhaupt gehört hatte.

- Nur Blessing trägt `nachnameReadbackNachBuchstabieren=true`. Erkennt
  `gehirn.einsammeln` in einer Namensfrage eine echte Buchstabierkette, setzt
  es `nachnameCheck="offen"` und `frage="nachname_check"`.
- `gehirn.nachname_check_frage` liest den Namen einmal samt Buchstabiertafel
  vor. `flow._nachname_check_vorbereiten` lässt Patienten-/Bestandssuche erst
  nach einem klaren Ja weiterlaufen. Nein oder eine neue Buchstabierkette
  löscht nur den Nachnamen und die daran gebundene Akte; Vorname, Grund,
  Wunschzeit und Slot bleiben erhalten.
- Eine direkt gesprochene Korrektur wird ebenfalls noch einmal vorgelesen.
  Zwei unklare Antworten starten die Buchstabierung frisch, statt das LLM oder
  eine Endlosschleife zu öffnen. Qwen bleibt während `nachname_check` wie bei
  jeder Namensfrage gesperrt.
- MedDent, Thaler und Rüther tragen den Schalter nicht und bleiben ohne
  zusätzlichen Gesprächszug. Regressionen und Suchsperren:
  `tests/test_blessing_namen.py`; seit V2.8 live.

## Blessing-Terminauskunft bleibt Terminauskunft (W-BLESSING-BESTANDSAUSKUNFT 15.09.2026 — nicht rückbauen)

Drei Gescheidle-Anrufe fragten nach einem bereits vereinbarten Termin
(„Meinen Termin nächste Woche, wann ist der?“, „ich habe einen Termin … und
weiß den Tag nicht mehr“). Die bisherige Bestandsfrage erkannte nur Formen mit
„wann“ VOR „Termin“ oder einem Abschlussverb wie „gebucht“. Die Live-Sätze
liefen dadurch als unklarer Zug oder kippten nach einer Fehlsuche in die
Neubuchung mit Versicherungs- und Besuchsgrundfragen.

- Nur Blessing trägt `bestandsauskunftErweitert=true`.
  `kern.intent.ist_bestandsfrage` ergänzt dort die beobachteten
  Termin-vor-Wann-, Vergessen-/Uhrzeit- und Statusformen. Auch die echten
  STT-Varianten „Charmin“/„Salmin“ gelten ausschließlich mit Besitzbezug und
  Zeitfrage als Termin.
- Der Treffer ist synchron `WISSEN × VORGANG`, auch mitten in einer bereits
  angelaufenen Neubuchung. Das Session-Hirn parkt diese und schaltet zurück in
  die echte Bestandskalender-Auskunft; weder freies LLM noch Katalog-/
  Versicherungsfrage dürfen übernehmen.
- „Wann kann ich einen Termin bekommen?“ und freie Termine bleiben
  Neubuchung. „Ist der Termin eingetragen?“ startet während eines noch
  ungeschriebenen Slot-/Bestätigungsschritts keine zweite Bestandssuche.
- Der Regex-Rückfall ohne Session-Hirn nutzt denselben mandantenscharfen
  Wächter. MedDent, Thaler und Rüther behalten ihre bisherige Deutung.
- Die Auskunft endet nicht bei der Intent-Erkennung: ein bekannter Anrufer
  bekommt nach dem Identitäts-Ja den gefundenen Termin samt Datum, Uhrzeit,
  Grund und Behandler direkt angesagt. Ein unbekannter Anrufer buchstabiert
  den Nachnamen, bestätigt zuerst den W-BLESSING-NACHNAME-READBACK und erst
  dann startet die Suche. Das Diktat-Schlusswort „fertig“ bleibt in diesem
  Blessing-Namensformular eine Formularantwort — es darf die Auskunft nicht
  mehr als allgemeines `WISSEN × REGEL` parken und ans freie LLM abgeben.
  Die Suche läuft nachweislich nie vor dem Namens-Ja; nach einem Treffer
  bleibt `modus=auskunft` und die feste `termin_ok`-Folgefrage offen.
  Regressionen: `tests/test_blessing_abschluss.py`; seit V2.8 live.

## Evidenzbasierter Tages-Scorer (W-QUALITAET-40-80 15.09.2026)

`tools/tages_scorer.py` bewertet die read-only `anruf.json`-Manifeste mit
einer festen Rubrik: super, gut, durchwachsen, unvollständig, fehlerhaft.
Aufleger sind ausschließlich Anrufe ohne substanziellen Anrufersatz; ein
genanntes Anliegen bleibt auch bei frühem Abbruch in der Wertung. Super
verlangt einen belegten Write/Transfer ohne Reibung. Echte Praxisnotizen
erreichen höchstens gut. Fehlgeschriebene Writes, Erfolgsaussagen ohne
Ledger-Beweis sowie Unklar-/Presence-/Frageschleifen sind harte Fehler.

Der Bericht weist Sessions, Praxen und lokale Stunden getrennt aus und zieht
deterministisch zehn Prozent der automatisch als super bewerteten Gespräche
zur manuellen Gegenhör-Stichprobe. Ziel gilt erst ab 50 gewerteten Gesprächen:
super mindestens 40 Prozent und super plus gut mindestens 80 Prozent.
Testanrufe sind standardmäßig ausgeschlossen. Das Werkzeug verändert nie
Manifeste oder Kalender; nur ein ausdrücklich gesetztes `--json`-Ziel wird
geschrieben. Regression: `tests/test_tages_scorer.py`.

## Blessing-Gründe konkret statt Notfall/Absage (W-BLESSING-MOTIVKLARHEIT 15.09.2026 — nicht rückbauen)

Blessing bot am Telefon selbst „eine Beratung oder etwas anderes“ an und
antwortete auf genau diese Auswahl anschließend „Diese Leistung wird nicht
angeboten“. Außerdem traf das alte Zahn-Konzept `eiter` als Teilwort in
„WEITERbehandlung“ und „WEITERE Medikamentenkontrolle“: beide wurden zum
Notfall-Motiv. Echte Hautgründe wie Rosacea, Wunden, Atherom/„Atterom“ und
Grützbeutel liefen dadurch falsch oder blieben ohne Motiv.

- Nur Blessing trägt `dermaMotivKlarheit=true`. Reines „Beratung“ wird
  deterministisch über die tatsächlich buchbaren Beratungs-Motive
  konkretisiert; „etwas anderes“ fragt offen nach, was die Ärztin ansehen
  soll. Es wird noch kein Motiv geraten und keine Slotsuche gestartet.
- Der Dermatologiepfad läuft vor den alten Zahn-Konzepten. Er bindet
  Erkrankungen und Sprechgründe an den echten Blessing-Katalog; Weiter- und
  Medikamentenkontrolle gehen auf `Kontrolle`, allgemeine Haut-/Nagel-/
  Fußbeschwerden auf `Sprechstunde`, Atherom/Grützbeutel auf die
  Entfernung-Beratung. Ein echtes Akut-Signal braucht eine Wortgrenze:
  `eiter` trifft nie wieder `weiter`.
- Zahnwünsche bleiben bei Blessing fachfremd und werden weiter abgelehnt.
  MedDent, Thaler und Rüther tragen den Schalter nicht; der Gegenbeweis hält
  dort den bisherigen Mapper byte-identisch.
- Nur Blessing trägt zusätzlich `einArztOhneBehandlerfrage=true`: solange die
  Praxis genau einen Behandlerkalender führt, bindet auch der Bestandsweg
  diesen direkt. Die inhaltslose Frage „Bei welchem Behandler waren Sie
  zuletzt?“ entfällt; käme ein zweiter Kalender hinzu, erscheint die Frage
  wieder.

Regressionen: `tests/test_blessing_motive.py`; seit V2.8 live.

## Blessing kurz und aufgabenbezogen (W-BLESSING-KNAPP 15.09.2026 — nicht rückbauen)

Der Geschwätz-Befund vom 15.09. zeigte vor allem zwei Fragen in einem
Unklar-Satz, „Ich bin die Neue“, Wohlseins-/Behandlerfragen,
den langen KI-Erklärtext bei einem Menschenwunsch und offene
„Sonst noch?“-Nachläufe ohne Ergebnis.

- Nur Blessing trägt die Schalter `gespraechKompakt`, `halloKompakt`,
  `anmeldungKurz`, `selbstCheckNurBeiSignal`,
  `sonstNochNurNachErfolg` und `presenceEinmal`.
- Unklare Schnipsel bekommen genau EINE kurze offene Jobfrage; ein echtes
  Hautfachwort bekommt die gezielte Terminfrage. Ein reiner Gruß führt ohne
  LLM direkt zum Auftrag. Freies Talk-Gerede wird durch die offene
  Maschinenfrage ersetzt.
- Ein bestätigter Anrufer ohne Drittperson-Signal wird nicht zusätzlich
  gefragt, ob der Termin für ihn selbst ist. „Für meinen Sohn“ gewinnt
  weiterhin jederzeit über die bestehende Dritttermin-Wache.
- Rückruf-/Praxisnotizen ohne Buchung enden kurz und legen auf. „Sonst noch?“
  kommt höchstens einmal und nur nach einem belegten Erfolg.
- Bei Stille: einmal Presence, einmal offene Jobfrage, danach sauberer
  Abschluss. Ein noch offenes Anliegen wird dabei über die bestehende
  Notleine als echte Rückrufnotiz gesichert.

Regressionen: `tests/test_blessing_knapp.py`. Andere Mandanten tragen keinen
dieser Schalter und bleiben im bisherigen Pfad.

## Blessing ruhig, relativ und ohne Endschleife (W-BLESSING-RUHE 15.09.2026 — nicht rückbauen)

Live-Anruf `89daafaa50454560bff69c786a441296`: Der Anrufer wählte aus drei
Terminen „den frühestmöglichen“. Intern war bereits das richtige
Hautkrebs-Screening-Motiv gewählt, die Sprechschicht nannte es jedoch
„Kontrolle“. Auf den berechtigten Einwand löschte der Änderungszweig den
ausgewählten frühen Termin und fragte erneut nach einem Slot. Nach der
erfolgreichen Buchung kamen Termin, SMS, Link, Unterlagen und „Sonst noch?“
in einem rund 16 Sekunden langen Block. Vier Bitten, noch eine Notiz für die
Ärztin einzutragen, wurden mit derselben Sonst-noch-Frage beantwortet.

- `sprech.ohne_krebs` sagt weiter nie das Wort „Krebs“, unterscheidet aber
  jetzt `Hautscreening`/`Hautvorsorge` von einer allgemeinen Kontrolle.
- Korrigiert der Anrufer nur diese Ansage und die erneut ermittelte
  `motivId` ist identisch, bleiben `slotIso`, Angebot, Kalender und die
  relative Wahl erhalten. Ein echter Motivwechsel leert den Slot weiter.
- Blessing fragt vor dem Schreiben in EINEM eigenen Zug:
  „Möchten Sie der Ärztin für den Termin noch eine Nachricht zur Vorbereitung
  mitgeben?“ (`arztNotizFrageText`; kein `arztNotizAutomatisch` mehr).
- Ein ausdrücklicher Notizwunsch nach einer Buchung läuft über den
  mandantenscharfen Mini-Flow `terminNotizNachBuchung`: Inhalt erfragen,
  einmal rücklesen, erst nach Ja `masAppointmentNote`; bei Schreibfehler
  echter Rückrufvermerk, niemals wieder „Sonst noch?“.
- `buchungAbschlussKompakt` spricht nach einem Erfolg nur Terminbestätigung,
  die kurze SMS-/Unterlagen-Info und den Abschied; keine neue offene Frage.
- Ein Task-Auswahl-LLM darf keinen P5-Vorsatz mehr sprechen, bevor feststeht,
  was der sichere Jobpfad antwortet. Ein Gruß mitten in einem Formular
  wiederholt nur die offene Frage, ohne neue Begrüßung. So kommt pro Zug nur
  ein Thema aus dem Mund.
- Die Meldeansage lautet in Pickadoc-DB und lokalem Rückfall exakt:
  „Hallo, Hautarztpraxis Doktor Blessing, Sie sprechen mit der digitalen
  Assistentin Bianca ...Wie kann ich helfen?“ (Chef 16.09.2026). Zuvor stand
  dort „Ki“/„Ka-ih“ — das sprach der TTS-Container als „Kie“; „digitalen
  Assistentin“ umgeht das Problem ganz. Die DB bleibt die Wahrheit; nach einer
  Portaländerung den Mandanten-Cache leeren.
- Die neuen Verhaltensschalter und Texte stehen nur in `tenants/blessing.json`;
  MedDent, Thaler und Rüther behalten ihren bisherigen Pfad.

Regressionen: `tests/test_anruf_89daafaa.py`, `tests/test_blessing_knapp.py`,
`tests/test_sprech.py`, `tests/test_zahn_katalog.py`.

## Blessing hält Slot-Ablehnungen fest (W-BLESSING-SLOTPRÄFERENZ 15.09.2026 — nicht rückbauen)

Live-Anruf `50563be8`: „kein Donnerstag“ wurde mehrfach verstanden, dennoch
erneut als Donnerstag angeboten; „elf Uhr ist Vormittag, bitte Nachmittag“
wurde sogar als Wahl von 11:15 Uhr behandelt.

- Nur Blessing trägt `slotPraeferenzenFesthalten=true`.
- Im laufenden Angebot werden erlaubte/ausgeschlossene Wochentage,
  Tageszeiten, Stunden und Bereiche kumulativ im Wunsch gespeichert.
- `pick_slots` behandelt diese Grenzen hart: weder Nächstbestes noch
  Streu-Auswahl oder Verschiebe-Fallback darf ausgeschlossene Slots
  zurückholen. Ohne passenden Slot fragt Bianca neu.
- Das alte Angebot wird vor der Neusuche vollständig geräumt; bei
  Kalenderfehler oder leerer Verschiebesuche bleiben keine stale Slots
  auswählbar.

Regressionen: `tests/test_blessing_slotpraeferenzen.py`.

## Blessing-Bestandsdatum und Verschiebeziel (W-BLESSING-BÄCHLE 15.09.2026 — nicht rückbauen)

Im Bächle-Live-Satz „Termin am 21. Oktober … bis Mitte November enthalten“
beendete `_ALT_REF_RE` die Alt-Referenz fälschlich am Punkt nach „21.“.
Dadurch blieb Oktober als Zielwunsch stehen. Blessing trägt jetzt
`bestandsVerschiebenErweitert=true`: nur der beobachtete Satztyp mit
Bestandstermin, Zielbezug und STT-Wort „enthalten“ öffnet die
Verschiebe-Maschine. Die Alt-Referenz umfasst „21. Oktober“, der Zielparser
bekommt ausschließlich „Mitte November“. Ein alleinstehendes „enthalten“ und
alle anderen Mandanten bleiben unverändert. Regressionen:
`tests/test_blessing_abschluss.py`.

## Ruhige Gesprächsführung für ALLE Stimmen (W-RUHE 15.09.2026 — nicht rückbauen)

Chef: „bianca ist hektisch. es werden wieder mehrere sachen direkt
hintereinander abgefeuert … sie soll ruhiger sein und ein thema nach dem
anderen abarbeiten.“ Die Ruhe war bis dahin eine Blessing-Sonderwirkung
(`gespraechKompakt`). Jetzt gilt sie mandantenübergreifend für Bianca/Ben,
Patienten-Lisa UND Kampagnen-Lisa — MedDent/Thaler/Rüther/Blessing ändern
inhaltlich nichts, nur das Nachgeplauder hinter einer Frage fällt.

- **Eine gemeinsame Ausgangswache** `kern/gespraechsruhe.py`
 (`saeubern(text) -> (neu, weg)`): pro gesprochenem Zug höchstens EINE Frage,
 die Frage steht am ENDE, danach kein zweites Thema. Fail-safe wie
 `fach_wache`/`zeiten_wache` — im Zweifel BEHALTEN: es wird NUR gestrichen,
 wenn eine Frage NICHT am Ende steht UND hinter ihr KEIN Fakt hängt (Ziffer,
 Datum, Wochentag, Uhrzeit, Notfall/112/116 117, SMS/Link/E-Mail, Euro).
 Angebotene Alternativ-Slots und Sicherheits-/Terminfakten fallen so nie
 blind weg; reine Aussage-Züge (Termin-/SMS-Bestätigung ohne Frage) bleiben
 unangetastet. Stufen/Notaus `RUHE_WACHE=off|shadow|enforce` (Default
 enforce).
- **Einhängung Bianca** (`bianca/agent._ruhe_wache_anwenden`): am LLM-Ausgang
 nach `regreeting_raus` UND im Maschinen-Pfad nach `_eingehen_anwenden`
 (dieselbe Doppel-Stelle wie die anderen Ausgangswachen, damit
 `rest_nach_vorab` den gekürzten Text sieht). Zusätzlich gilt die
 Vorsatz-Sperre während der semantischen Task-Auswahl (`darf_vorab`) jetzt
 für JEDEN Mandanten, nicht nur die kompakten — das Modell darf vor einer
 deterministischen Jobfrage keinen Streaming-Vorsatz mehr sprechen. Die
 dermatologische `_kompakt_fachfrage` hängt jetzt ausdrücklich an
 `dermaMotivKlarheit`, nicht mehr an der allgemeinen Ruhe-Regie.
- **Einhängung Lisa** (`lisa/agent.py`, `lisa/bewerbung.py`): dieselbe
 `gespraechsruhe.saeubern`-Ausgangswache am LLM-Ausgang. Lisas Stille-Regie
 ist an Biancas Muster angeglichen: erster Stups NUR Presence, zweiter NUR
 die offene Frage (`_offene_lisa_frage` aus `idCheck`/letzter wirklich
 gestellter Frage, Presence-Echo herausgefiltert) — die frühere Wiederholung
 des GANZEN Auftrags bei jedem Stups entfällt.
- **Prompt-Vertrag** in `bianca/prompt.py` und `lisa/prompt.py`: „Die Frage
 steht IMMER am Ende — danach kein zweites Thema, keine zweite Frage.“
- Tests: `tests/test_gespraechsruhe.py` (Fakt-hinter-Frage-Gegenproben sind
 der wichtigere Teil), Stups-Block in `tests/test_stille.py`,
 Task-Auswahl-Gegenprobe in `tests/test_anruf_89daafaa.py`.

## Mehrfach-Absage (W-MEHRFACH-ABSAGE 15.09.2026 — nicht rückbauen)

Chef: „wenn ich beide absagen möchte … oder am ende komme ich wieder in eine
schleife.“ Bislang wählte die Termin-Wahl bei „beide/alle“ still nur den
ersten Treffer.

- **Erkennung + Auswahl** (`bianca/verwalten._mehrfach_auswahl`, VOR der
 Einzelauswahl in der `wahl`-Phase): „beide“, „alle“, „den ersten und den
 zweiten“ wählen mehrere vorgelesene Termine; ein einzelnes „den ersten“
 bleibt der bewährte Einzelweg.
- **Eine Sammelbestätigung** (`_mehrfach_absage_start` → Phase
 `mehrfach_bestaetigen`): erst nach einem klaren Ja werden die konkreten
 Termin-IDs NACHEINANDER über den vorhandenen `cancel-by-id`-Weg abgesagt
 (`_mehrfach_absagen`). Teilfehler werden ehrlich einzeln benannt — nie
 „beide abgesagt“, wenn nur ein Werkzeug erfolgreich war. „Nein“ lässt alle
 Termine bestehen.
- **Schleifenfreier Abschluss**: nach der Absage genau EINE registrierte
  „Sonst noch?“-Frage. Eine Neubuchung beginnt nur auf ausdrücklichen Wunsch,
  nie automatisch aus der Absage heraus.
- Tests: `tests/test_mehrfach_absage.py` (Erfolg, Teilfehler, klares Nein,
 Einzelwahl bleibt Einzelweg).

## Verwaltung sucht den Termin, nicht nur den Namen (W-VERWALTUNG-TERMIN-ZUERST 16.09.2026 — nicht rückbauen)

Chef nach den Blessing-Feldgesprächen: Absagen und Verschieben dürfen nicht
mehr von einer nahezu perfekten Namens-STT abhängen. Patienten nennen häufig
schon Datum, Uhrzeit und Behandler; außerdem liegt bei übermittelter
Rufnummer oft eine bestätigte Akte vor. Gegenfall: Wer anruft, weil er den
Termin vergessen hat, darf selbstverständlich NICHT nach dem vergessenen
Datum gefragt werden.

- **Verwaltung mit bekanntem Termin:** `bianca.verwalten` sammelt bei
  Absage/Verschieben sowie bei einer Auskunft mit genanntem Termin
  Datum/Uhrzeit und gegebenenfalls den Behandler zuerst.
  `kern.calendar.find_appointments_by_date` liest den Praxistag direkt und
  ausschließlich lesend aus Firestore. Kandidaten werden in dieser
  Reihenfolge eingegrenzt: bestätigte `patientId`, bestätigte Rufnummer,
  dann Name ab 60 Prozent Ähnlichkeit. Ein unscharfer Name ist nur Kandidat;
  gesprochen werden Patient, Termin und Behandler zur Rückversicherung.
  Ein praktisch identischer Name überspringt nur diesen zusätzlichen
  Identitätszug, niemals die konkrete Terminbestätigung.
  Kontakt-Rufnummern bei Drittterminen und noch nicht rückbestätigte Nummern
  werden nie als Patientenbeweis an die Terminsuche geschickt.
  Erst ein ausdrückliches Ja gibt die konkrete Termin-ID zum Absagen oder
  Verschieben frei. Ohne Identitätsbeweis werden nie fremde Patientennamen
  aus einer Tagesliste vorgelesen.
- **Terminzeit vergessen / Terminauskunft:** `verwZeitUnbekannt` schaltet
  strikt auf Behandler + bestätigte Akte/Rufnummer + Nachname. Die
  Wann-Frage ist auf diesem Weg verboten. Bei nur einem Behandler wird
  dieser automatisch gebunden; bei mehreren wird er zuerst erfragt.
- **Namensschutz:** Monats-, Datums-, Uhrzeit- und Terminparaphrasen werden
  aus frei gehörten Namen entfernt. Strukturierte Angaben wie
  „Mai, Anna, der Termin …“ bleiben geschützt. Eine bestätigte Rufnummer
  oder `patientId` gewinnt immer gegen einen verhörten Namen.
- **Kalenderschutz:** Die Tageslese blendet vergangene, abgesagte,
  virtuelle, reservierte und nicht bestätigte Termine aus. Geloggt werden
  nur Tag, Trefferzahl und Filterentscheidung, nie die Patientenliste.
  `VERWALTUNG_TERMIN_DETAILS=0` schaltet nur diesen neuen Leseweg aus.
- **Kein Abschluss-Loop:** Nach erfolgreichem Verschieben bleibt
  „Kann ich sonst noch etwas für Sie tun?“ als echte Formularfrage
  registriert. „Nein/Danke“ legt freundlich auf und räumt den
  Verwaltungsmodus; die Antwort fällt nie ans freie LLM.
- **Kein Halluzinations-Fallthrough:** Solange Absage oder Verschieben aktiv
  ist, beantwortet ausschließlich `verwalten.sicherer_fortsetzungsanker`
  einen unklaren Zug. Das freie LLM darf weder Terminwahl noch Bestätigung
  oder Erfolg übernehmen. Technische Schreibfehler erzeugen eine echte
  Rückrufnotiz statt einer erfundenen Erledigt-Aussage.
- **60 Prozent sind nie ein Beweis:** Ein unscharfer Name bekommt vor
  Terminauskunft, Verschiebung oder Absage einen eigenen Ja/Nein-Abgleich.
  Bei einer Absage folgt danach getrennt die destruktive Bestätigung.
- **Kein Buchungs-Drift:** Erfolgreiche Einzel- und Mehrfach-Absagen sowie
  fehlgeschlagene Terminauskünfte bieten nicht mehr von selbst eine
  Neubuchung an. Ein neuer Termin beginnt nur auf ausdrücklichen Wunsch.
- **Buchungsweg unverändert:** Die Tageslese wird ausschließlich aus
  der Verwaltung aufgerufen. Neubuchung und ihre Reihenfolge benutzen
  weiterhin die bewährte Slotsuche.
- Tests: `tests/test_verwaltung_termin_zuerst.py` (einschließlich aller vier
  Mandanten, 60-Prozent-Rückversicherung, Identitätsvorrang, Datenschutz,
  Termin-vergessen ohne Wann-Frage und Buchungs-Gegenprobe).

## Rückrollpunkte (Produktionsstände)

| Stand | Tag | Anleitung |
| --- | --- | --- |
| **V2.10, 15.09.2026 19:55 (aktuell — ruhige Ein-Thema-Regie für ALLE Stimmen + Mehrfach-Absage)** | `telefonki-produktionsstand-v2.10-2026-09-15` | `docs/PRODUKTIONSSTAND-V2.10.md` — Live-Image `c4e36a417acb`; W-RUHE (`kern/gespraechsruhe.py`) über Bianca/Ben + beide Lisa-Pfade, W-MEHRFACH-ABSAGE („beide/alle absagen“) mit Sammelbestätigung und Tool-Evidenz; Mandanten byte-identisch |
| V2.9, 15.09.2026 20:53 (Blessing ruhig, relative Auswahl und Terminnotiz ohne Endschleife) | `telefonki-produktionsstand-v2.9-2026-09-15` | `docs/PRODUKTIONSSTAND-V2.9.md` — Live-Image `ec64bbf0fb63`; ein Thema pro Zug, Frühestwahl bleibt erhalten, Nachricht für die Ärztin als eigener bestätigter Schritt |
| V2.8.1, 15.09.2026 19:30 (V2.8 plus vollständiger W-ERSATZ-MOTIV-Nachzug) | `telefonki-produktionsstand-v2.8.1-2026-09-15` | `docs/PRODUKTIONSSTAND-V2.8.1.md` — Live-Image `574c2de2068d`; Rüther hört bei gesperrtem Motiv ehrlich „telefonisch nicht vergeben“, niemals Endometriose-Ausweich |
| V2.8, 15.09.2026 19:20 (Blessing Namen, Aufgaben, Motive, Slots und knapper Mund; partieller W-ERSATZ-MOTIV-Rollout) | `telefonki-produktionsstand-v2.8-2026-09-15` | `docs/PRODUKTIONSSTAND-V2.8.md` — Image `0f2a38889c0f`; Blessing-Paket vollständig, aber `kern/calendar.py` ohne Sitzungs-Katalog-Nachzug; nur über `produktionsstand-v2.8-partial-20260915` zurückrollen |
| V2.7, 15.09.2026 16:16 (Rückrollpunkt VOR den Blessing-Fixes) | `telefonki-produktionsstand-v2.7-2026-09-15` | `docs/PRODUKTIONSSTAND-V2.7.md` — Live-Image `cf97be2244d9` (Rüther/Ben, Handy-Akte, Buchungsbeweis, Zeiten-Wache); SIP-Brücke als Dateisystem-Tar (`eb97b3d3e0e7`, Layer weg); `tts-stimmen.tgz` (Bianca+Ben) |
| V2.6, 14.09.2026 12:10 | `telefonki-produktionsstand-v2.6-2026-09-14` | `docs/PRODUKTIONSSTAND-V2.6.md` — App-Image `c04b16aada71`; V2.5 + W-TELEFON-ZULETZT (`f92951f`); erstmals SIP-Brücken-Image als Tar, Parakeet-Qwen-Repo (Bundle + 24 uncommittete Einträge), komplettes lokales `.data/`; Live-Asterisk 212.132.104.205 ohne Shell-Zugang → Dialplan nur als Referenzkopie |
| V2.5, 14.09.2026 06:50 | `telefonki-produktionsstand-v2.5-2026-09-14` | `docs/PRODUKTIONSSTAND-V2.5.md` — App-Image `00f8b9c73f87`; V2.4 + W-MOTIV-KONSISTENT (MedDent-Schmerz-Buchung 06:0x); Abnahme Live-Nachstellung 8/8, prod_smoke, Feldprobe 68/68 nach dem Deploy |
| V2.4, 14.09.2026 02:10 | `telefonki-produktionsstand-v2.4-2026-09-14` | `docs/PRODUKTIONSSTAND-V2.4.md` — App-Image `6305bd4450a7`; neun Chef-Punkte vom 13.09. abends + Thaler-Kalender-Merge; Abnahme Suite 1606/0, prod_smoke, Feldprobe 68/68 live. Ohne Motiv-Fix: Schmerz-Buchung bei MedDent scheitert |
| V2.3, 13.09.2026 | `telefonki-produktionsstand-v2.3-2026-09-13` | `docs/PRODUKTIONSSTAND-V2.3.md` — App-Image `9bb32ed3a5c9`; Sicherungsskript-Falle (Tag zeigte erst auf das V2.2-Image) dort dokumentiert |
| V2.2, 13.09.2026 | `telefonki-produktionsstand-v2.2-2026-09-13` | `docs/PRODUKTIONSSTAND-V2.2.md` |
| V2.1, 13.09.2026 | `telefonki-produktionsstand-v2.1-2026-09-13` | `docs/PRODUKTIONSSTAND-V2.md` |
| V2.0, 13.09.2026 — NICHT benutzen | `telefonki-produktionsstand-v2.0-2026-09-13` | trägt die fehlende Behandlerwahl vor dem PZR-Angebot und die kaputte Dock-Kodierung (siehe Handbuch) |
| V1.0, 10.09.2026 | `telefonki-produktionsstand-v1.0-2026-09-10` | nur Git-/Image-Tags |

Ein Produktionsstand besteht aus VIER Teilen — Code allein reicht nicht:
annotierter Git-Tag, Docker-Image-Tags `produktionsstand-vX-JJJJMMTT` der
laufenden Container auf pickadoc1, ein Schnappschuss von Live-`.env`,
`secrets/`, `tenants/`, Compose-Konfiguration, Asterisk-Dialplan und den
Docker-Volumes unter `/home/cursor/telefonki-backups/produktionsstand-…`
sowie eine lokale Kopie samt Git-Bundle in `_snapshot-produktionsstand-…`
(gitignoriert). Tokens, Service-Account-Key und Patientendaten aus den
Mitschnitten gehen NIE nach GitHub. Skripte:
`tools/_produktionsstand_v2_server.sh` (Schnappschuss + Image-Tags) und
`tools/_produktionsstand_v2_abnahme.sh` (Abnahme), beide mit `VERSION=vX.Y`.
**LF-Zeilenenden**: PowerShell schreibt CRLF, `ssh "bash -s"` bricht daran ab
(`set: -: invalid option`) — Datei vorher konvertieren und per scp schicken.

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
