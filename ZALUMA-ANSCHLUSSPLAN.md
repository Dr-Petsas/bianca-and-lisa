# Zaluma-Anschlussplan Telefon-KI (Stand 30.08.2026)

Fuer: Kiriakos Tzannis (development@pickadoc.de)
Von: PickaDoc-Entwicklung (Praxis MedDent, Dr. Petsas)

Ziel: ElevenLabs ist raus. Alle Agenten (Clara, Lena, Bianca, Lisa) sprechen
seit heute ueber die eigene TTS-Strecke (Qwen3-Container auf der 5090).
Was fehlt, ist die Telefonie: Der eigene Stack in diesem Repo ist ein
HTTP-"Sitzungs-Umschlag" OHNE SIP-Schicht. Deine Aufgabe: Zaluma (SIP-Trunk)
anbinden und die drei Altpfade (MAS-2, Demo Akt 2, Live-Web) umstecken.
Dieses Dokument listet AUSNAHMSLOS alle Stellen mit Datei + Zeile.

Zeilennummern = Stand 30.08.2026 (Commits: siehe Abschnitt 9). Wenn dein
Cursor eine Stelle nicht findet: nach den genannten Funktions-/Markernamen
suchen, die sind stabil.

---

## 1. Ist-Zustand: Was schon fertig ist (NICHT anfassen)

| Strecke | Stand |
|---|---|
| Clara Betriebsstand (F:\Clara-Voice-dev, v7-dev, Port 8093) | TTS = `qwen3-container`, laeuft |
| Clara Rueckweg (F:\Clara-Voice, v5.4-speed, Port 8091) | TTS = `qwen3-container` (Commit `9f13aae`) |
| Demo-Clara (F:\Pickadoc-Demo\demo-clara) | TTS = `qwen3-container` |
| Lena | keine eigene TTS — spricht ueber Claras Coach-Pfad, Container-Klon `lena` |
| Bianca & Lisa (dieses Repo) | `kern/tts.py` spricht nativ `TTS_BASE` = Container |
| MAS-2 Tour-Narration (`backend/src/clara/tourNarrate.js`) | Qwen-Container `/speak` (30.08.) |
| ClonR (docgendaweb Functions) | Qwen ueber Tunnel `mas.pickadoc-tunnel.com/qwen-tts` |

TTS-Container: `http://192.168.0.246:8213` (`/health`, `/speak`, `/speak-stream`,
`/clone-speak`; Vertrag: `tts_serve/api.md`). Registrierte Stimmen (warm, cuda):
`bianca`, `clara`, `lena`, `lisa`, `quizmaster`, `mann`, u. a.
STT-Container: `http://192.168.0.246:8212` (`/transcribe`).

## 2. Ziel-Architektur (dein Anschlusspunkt)

Der Stack besteht aus zwei FastAPI-Diensten ("Umschlag"), die Gespraeche als
Sitzungen fuehren — Text/Audio rein, NDJSON + Audio raus. KEIN SIP, KEIN RTP,
KEINE Rufnummern im Repo. Genau davor setzt du die SIP-Schicht mit Zaluma.

| Dienst | Port | Rolle | Start einer Sitzung |
|---|---|---|---|
| Lisa (`lisa/server.py`) | 8095 | AUSGEHENDE Anrufe | `POST /api/start` `{tenant, auftrag, patient, ...}` |
| Bianca (`bianca/server.py`) | 8096 | EINGEHENDE Anrufe | `POST /api/start` `{tenant}` |

Wichtigste Sitzungs-Endpunkte (beide Dienste identisch):
- `POST /api/listen` (multipart: `sessionId`, `audio`, optional `bargeUrl`, `bargeMs`) — Audio-Zug, Antwort NDJSON
- `POST /api/turn` (`{sessionId, text, ...}`) — Text-Zug, Antwort NDJSON
- NDJSON-Events: `filler` | `transcript` | `warte` | `empty` | `reply`
  (`reply` traegt u. a. `text`, `audioUrl`, `hangup?`, `book`, `writeLive`)
- `GET /api/audio/{name}` bzw. `GET /api/audio-stream/{name}` — Audio abholen
- `POST /api/weiter` (Barge-in-Fortsetzung), `POST /api/stille` (Stups), `POST /api/hangup`
- `GET /api/gespraeche` + `GET /api/gespraeche/{session_id}` (nur Lisa) — Verlauf/Transkript
- `GET /health` — Bereitschaft

Audio-Formate: Der Umschlag liefert WAV (intern PCM16 mono 24 kHz vom
TTS-Container). Fuers Telefonnetz (G.711 aLaw 8 kHz) muss DEINE SIP-Bruecke
resamplen/transkodieren — in beide Richtungen.

## 3. Baustelle A — SIP-Schicht mit Zaluma bauen (existiert noch NICHT)

Das ist der neue Baustein. Empfehlung: eigener Container (z. B. Asterisk/
FreeSWITCH oder eine SIP-Lib wie pjsua2/drachtio) neben `lisa`/`bianca`.

Einzutragende/neue Stellen in DIESEM Repo (F:\Bianca&Lisa TelefonKI):

1. `compose.yml` — neuen Service `sip` ergaenzen (Netz zu `lisa`/`bianca`,
   `env_file: .env`). Aktuell definiert die Datei nur `lisa` (8095) und
   `bianca` (8096), Kommentar Zeile 1 nennt den Umschlag ausdruecklich
   "Umschlag fuer SIP/Zaluma".
2. `.env` + `.env.example` — es gibt dort noch KEINE SIP-Variablen. Neu
   anlegen (Namensvorschlag, damit wir beim Gegentesten dieselben Woerter
   benutzen):
   - `ZALUMA_SIP_REGISTRAR` (Domain/Registrar)
   - `ZALUMA_SIP_USER`, `ZALUMA_SIP_PASSWORT`
   - `ZALUMA_OUTBOUND_PROXY` (falls Zaluma einen vorgibt)
   - `ZALUMA_SIP_TRANSPORT` (udp|tcp|tls)
   - `ZALUMA_RTP_PORT_VON`, `ZALUMA_RTP_PORT_BIS`
   - `ZALUMA_DID_BIANCA` (eingehende Praxisnummer -> Bianca)
   - `ZALUMA_CALLER_ID_LISA` (ausgehende Anzeige-Nummer fuer Lisa)
3. Outbound-Bruecke (SIP -> Lisa): Bei Anruf-Auftrag waehlt die SIP-Schicht
   die Zielnummer und verbindet das RTP-Audio mit dem Umschlag:
   `POST http://lisa:8095/api/start` -> Begruessungs-Audio abspielen ->
   Anrufer-Audio gepuffert per `POST /api/listen` -> `reply.audioUrl`
   abspielen -> bei `reply.hangup` sauber aufhaengen (`POST /api/hangup`).
   Barge-in: waehrend der Wiedergabe weiter zuhoeren; bei Einwurf
   `bargeUrl`/`bargeMs` mitschicken bzw. `POST /api/weiter` nutzen.
4. Inbound-Bruecke (DID -> Bianca): Eingehender Ruf auf `ZALUMA_DID_BIANCA`
   annehmen -> `POST http://bianca:8096/api/start` `{tenant}` -> gleicher
   Zug-Zyklus wie oben.
5. Weiterleitung an einen Menschen: `bianca/weiterleiten.py`
   - Zeilen 17–19: Konstanten inkl. Marker **`ZALUMA_TRANSFER_PLATZHALTER`**
   - Zeilen 47–51: Ansage-Platzhalter
   - Zeilen 191–223: `zaluma_weiterleitung()` — heute Jingle + Ansage +
     `hangup`; hier kommt der echte SIP-Transfer hin (REFER oder Bridge zum
     Zielarzt; Kontext liegt in `sit` und `ziel_arzt`).
   - Tests dazu: `tests/test_weiterleiten.py`
6. Firewall/NAT auf dem SIP-Host: 5060 (bzw. TLS-Port) + RTP-Bereich
   freigeben. Im Repo gibt es dazu NULL Doku (`DEPLOY-5090.md` schweigt) —
   bitte dokumentieren, was du oeffnest.
7. Deployment: Stack laeuft per Docker auf der 5090 (`DEPLOY-5090.md`,
   Host `192.168.0.246`, SSH-Alias `pickadoc1`, User `cursor`); zusaetzlich
   laufen Lisa/Bianca aktuell auch lokal auf dem Praxis-Windows (uvicorn,
   Ports 8095/8096/8098). Sag uns, auf welchem Host deine SIP-Schicht
   laufen soll, dann richten wir die Erreichbarkeit ein.

## 4. Baustelle B — MAS-2 umstecken (F:\MAS-2\backend), "neue Lisa"

Heute ruft MAS-2 fuer echte Anrufe ElevenLabs ConvAI (`POST
https://api.elevenlabs.io/v1/convai/twilio/outbound_call`). Kuenftig ruft
MAS-2 den eigenen Stack. Lisas Verhalten ("unsere neue Lisa") lebt dann in
`lisa/`-Flows dieses Repos, nicht mehr im ConvAI-Agenten.

Alle Stellen:

1. `src/lisa/outbound.js`
   - Z. 22 + 231: `callConfigured()` prueft `ELEVENLABS_API_KEY`,
     `LISA_AGENT_ID`, `LISA_PHONE_NUMBER_ID` -> ersetzen durch neue Envs
     (Vorschlag: `LISA_STACK_BASE=http://<sip-host>:8095`)
   - Z. 410–434: `elevenOutboundCall()` -> `POST {LISA_STACK_BASE}/api/start`
     (Auftrag/Patient statt `dynamic_variables`; `task_id`, `client_id`,
     `task_prompt` uebergeben — heute Z. 521, 604, 618)
   - Z. 437–443: Transkript-Abruf ConvAI -> `GET /api/gespraeche/{sessionId}`
   - Z. 234 + 248–252: Absender-Nummer aus ConvAI-Phone-Numbers ->
     `ZALUMA_CALLER_ID_LISA`
   - Z. 990 + 1083–1097: Mitschnitt-Proxy (ConvAI-Audio) ->
     `GET /api/audio/{name}` des Stacks
2. `src/lisa/takeover.js` Z. 240–244: Voice-From aus ConvAI -> Zaluma-Nummer.
   Die Uebernahme-Konferenz selbst laeuft heute ueber Twilio — Umbau auf
   SIP-Transfer erst, wenn Baustelle A steht (bis dahin funktionsfaehig lassen).
3. `src/lisa/agentTools.js` Z. 4–20, 23, 32, 42, 48, 136–182: ConvAI-Webhook-
   Tools (`offer_slots`, `book_slot`) entfallen — der eigene Stack bucht
   direkt ueber MAS-APIs (`src/routes/lisaTools.js` Z. 9, 42 kann als
   HTTP-Schnittstelle weiterleben; Auth heute via `LISA_TOOL_SECRET`,
   Kommentar `src/auth.js` Z. 68).
4. `src/bianca/ingest.js` Z. 8–26, 41, 45–49, 53–54, 78–120: ConvAI-Polling
   -> `GET {BIANCA_STACK_BASE}/api/last-call` bzw. Gespraechsliste des Stacks.
5. `src/brain/aiDisclosure.js` Z. 18, 50, 102–121: KI-Hinweis (DSGVO) wird
   heute per Agent-PATCH gesetzt -> gehoert kuenftig in die Begruessung der
   Stack-Flows (Bianca: `bianca/flow.py`; Lisa: Auftrags-Preambel).
6. `src/clara/health.js` Z. 259–297 (`checkElevenLabs`) -> Health auf
   `GET :8095/health` + `:8096/health` umbiegen; Z. 358–377, 412, 467–475
   Konfig-Drift gegen `config-snapshots/elevenlabs-agent-*.json` ausmustern
   (`src/clara/konfigSnapshot.js`).
7. `src/server.js` Z. 305–311 (Boot: Tool-Sync zu ElevenLabs) entfaellt;
   Z. 427–432 (Ingest-Interval) auf neue Quelle.
8. `src/routes/misc.js` Z. 137 (Mitschnitt-Proxy-Kommentar) mitziehen.
9. Skripte (obsolet markieren oder auf Stack umbauen): `scripts/konfig-export.mjs`,
   `lisa-agent-praxis-fix.mjs`, `lisa-agent-prompt-fix.mjs`, `lisa-simulate.mjs`,
   `setup-lisa-agent-tools.mjs`, `demo-bucket-call.mjs` (Z. 48),
   `test-capability-ping.mjs` (Z. 6, 13, 46–47).
10. `.env`: raus `ELEVENLABS_API_KEY`, `LISA_AGENT_ID`, `LISA_PHONE_NUMBER_ID`;
    rein `LISA_STACK_BASE`, `BIANCA_STACK_BASE`. `config-snapshots/env-keys-mas.json`
    Z. 7 anpassen. BLEIBT: Twilio fuer SMS (`TWILIO_ACCOUNT_SID`,
    `TWILIO_AUTH_TOKEN`, `LISA_SMS_SENDER`) — SMS ist von Zaluma unabhaengig.

## 5. Baustelle C — Demo Akt 2 "echter Anruf" (F:\Pickadoc-Demo\demo-mas)

1. `src/demo/anruf.js`
   - Z. 1–10, 17–18: Config-Gate (gleiche drei ConvAI-Envs) -> Stack-Envs
   - Z. 36–54: `elevenOutboundCall()` -> `POST {LISA_STACK_BASE}/api/start`
   - Z. 63–99: `anrufStarten` (Pflicht-`task_id` -> Auftrags-Payload)
   - Z. 101–122: `biancaAgentId()` -> entfaellt (Bianca = Port, kein Agent)
   - Z. 109–118 + 134–184: `anrufTranskript` -> `GET /api/gespraeche/...`
2. `src/routes/demo.js` Z. 4, 335–393 (`POST /demo/anruf`), 401–441
   (`POST /demo/anruf-stand`) — Payload-Form beibehalten, nur Quelle tauschen.
3. `scripts/_liste-anrufe.mjs`, `scripts/_lies-transkript.mjs` — Dev-Helfer
   auf Stack-Endpunkte.
4. `demo-mas/.env`: `ELEVENLABS_API_KEY`, `LISA_AGENT_ID`,
   `LISA_PHONE_NUMBER_ID` raus; `LISA_STACK_BASE` rein.
   (`demo-clara`-Worker und `web/scripts/live.js` bleiben unveraendert —
   die reden nur mit demo-mas.)

## 6. Baustelle D — Live-Web / Cloud Functions (F:\pickadoc-live-base\docgendaweb)

ACHTUNG Grundsatz: Firebase Cloud Functions erreichen das LAN NICHT.
Muster fuer den Ausweg existiert schon: ClonR spricht Qwen-TTS ueber den
Tunnel `https://mas.pickadoc-tunnel.com/qwen-tts` (Proxy in MAS-2:
`backend/src/routes/qwenTtsProxy.js`; Konfig:
`functions/src/config/clonrConfig.ts` Z. 13–15). Fuer Telefonie analog einen
Tunnel-Pfad auf 8095/8096 bereitstellen (z. B. `/telefon-lisa`, `/telefon-bianca`).

1. `functions/src/services/elevenlabsService.ts` Z. 22: **hartcodierter
   API-Key `ELEVENLABS_KEY`** (!); Z. 104–498: Conversations, Audio,
   `startOutboundCall` (convai/twilio), Agent-PATCH, Phone-Number-CRUD ->
   komplette Abloesung durch Stack-Aufrufe ueber den Tunnel.
2. `functions/src/services/phoneCallsService.ts` Z. 5, 289–608: Inbound-
   Webhook (dynamic vars, Post-Call-Transkript/Audio) + Outbound-Start ->
   Inbound kommt kuenftig von der SIP-Schicht (Baustelle A), nicht mehr von
   ElevenLabs-Webhooks.
3. `functions/src/index.ts` Z. 64, 245–246, 542–553, 851, 906–920: Exporte
   `updateElevenLabsAgent`, `startOutboundCall`, `onInboundPhoneCall`,
   Legacy `handleCallFinished`. Hinweis: Der Parallelpfad
   `onPickadocPhoneCall` / `phoneCallWebhook` ("ohne Elevenlabs",
   `pickadocPhoneCall.ts`) existiert bereits als Vorlage.
4. `functions/src/controllers/elevenlabs.ts` Z. 1–20 (Callable) — entfaellt.
5. `functions/src/controllers/telephonyAdmin.ts` Z. 4–136: Rufnummern
   parken/importieren/freigeben in ConvAI -> kuenftig Zaluma-Nummernverwaltung.
6. `functions/src/controllers/campaigns.ts` + `campaignrTest.ts`: Kampagnen-
   Outbound laeuft ueber `PhoneCallsService.startOutboundCall` -> Stack.
7. `functions/src/services/clientCostsService.ts` Z. 6–284: Kostenrechnung
   aus ConvAI-Minuten -> neue Quelle (Stack-Gespraechsliste + Zaluma-Tarife).
8. Frontend (geht ueber Callables, kein eigener Key):
   `src/services/elevenlabsService.ts` Z. 6–22, `src/services/agentsService.ts`
   Z. 2–6, 28, 118–254, `src/services/telephonyAdminService.ts` Z. 6–25,
   `src/components/admin/customerPanels.tsx` Z. 3, 73, 128, 154–221.
9. **`src/components/agentVoiceSelectionCtrl.tsx` Z. 10–33, 54–64:** direkter
   Browser-Aufruf `api.elevenlabs.io/v1/text-to-speech` MIT hartcodiertem
   `xi-api-key` — Stimmvorschau auf Qwen-Tunnel (`/qwen-tts` `/speak`)
   umstellen und den Key aus dem Client entfernen.
10. `patient/src/components/pages/home/voicePlaygroundPage.tsx` Z. 22–24, 89,
    117 + `voicePlayback.tsx` Z. 18–19, 84, 121: hartcodierter `XI_API_KEY`
    im Patient-Frontend (Playground) — stilllegen oder auf Tunnel umstellen.
11. Modelle/Doku nachziehen: `shared/src/models/elevenlabsModels.ts`,
    `agent.ts` Z. 16–20 (`agentId`/`phoneNumberId` = ConvAI-IDs),
    `phoneCall.ts` Z. 23, 81; `docs/phone-agent.md`, `docs/api-endpoints.md`;
    `twilio-stream-server/handlers/voiceHandler.ts` Z. 38 (`ttsProvider`-Label).

## 7. Was wir von dir brauchen (Zaluma-Seite)

- Zugangsdaten des Trunks (Registrar, User, Passwort, ggf. Outbound-Proxy,
  Transport, RTP-Vorgaben) — bitte NICHT per Mail, sondern wie besprochen
  ueber den sicheren Kanal; in `.env` nur auf dem Zielhost.
- Rufnummern: Welche DID(s) liegen bei Zaluma? Soll die heutige
  Praxisnummer (aktuell bei Twilio/ConvAI geparkt) portiert werden?
- Host-Entscheidung: SIP-Schicht auf der 5090 (Empfehlung, dort laufen
  TTS/STT) oder auf dem Praxis-Windows?

## 8. Gegentesten (so nehmen wir ab)

Bitte in dieser Reihenfolge melden, wir testen jede Stufe von hier aus mit:

1. Trunk registriert (`sip`-Service laeuft, Registrierung OK)
2. Inbound: Anruf auf die DID -> Bianca meldet sich (Begruessung hoerbar,
   Transkript erscheint unter `GET :8096/api/last-call`)
3. Outbound: Lisa ruft eine Testnummer an (wir stellen `DEV_PHONE`)
4. Barge-in + Stille-Stups im echten Anruf
5. Weiterleitung (`zaluma_weiterleitung()` -> echter Transfer)
6. MAS-2-Integration (Baustelle B): Testauftrag aus Clara heraus
7. Demo Akt 2 (Baustelle C), danach Live-Web (Baustelle D)

## 9. Referenz-Staende (Commits von heute)

- Clara live: `Clara-Voice` Branch `v5.4-speed`, Commit `9f13aae`
- Clara v7-dev: Branch `v7-dev` (Container-TTS seit 30.08. vormittags)
- MAS-2: Tour-Narration auf Qwen-Container (Commit von heute Nachmittag)
- Dieses Repo: `tts_serve/` Stimmen inkl. `lisa.wav`/`bianca.wav` vorhanden;
  `aliase.json` leer (keine Alias-Umlenkungen mehr)

Bitte kurz per Rueckmail bestaetigen, dass der Plan so passt und wann du
anfaengst — dann halten wir hier das Zeitfenster fuers Gegentesten frei.
