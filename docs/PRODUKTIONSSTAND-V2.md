# Produktionsstand V2.0 — 13.09.2026

Dieser Stand ist der **Rückrollpunkt**: Bianca und Lisa laufen damit live auf
pickadoc1, Health grün, `tools/prod_smoke.py` = ALLE WACHEN GRUEN.

Nachfolger von `telefonki-produktionsstand-v1.0-2026-09-10`.

## Was V2 gegenüber V1 mitbringt

| Kürzel | Was |
| --- | --- |
| W-ABSCHIED | Bianca legt bei klaren Schlusssätzen selbst auf („auf Wiederhören", „tschüss", „bis denn"); zweistufig, damit ein Hörfehler keinen laufenden Vorgang abwürgt. Umlaut-Varianten (ö/oe/o) inklusive. |
| W-HALLO-ANTWORT | Die Wohlsein-Frage entfällt, sobald ein Anliegen läuft oder es um Notfall/Beschwerde geht; wird sie doch gestellt, wird die Antwort AUFGENOMMEN statt verworfen. |
| W-STUPS-GESAMT | Presence-Stupse zählen über den ganzen Anruf; nach dem Deckel verabschiedet sich Bianca freundlich, sichert ein offenes Anliegen als Rückruf-Notiz und **legt auf** — durchgereicht über `/api/stille` → `sip_bridge._stups` → Dock. |
| W-FOKUS | Kein stummer Zug mehr; Drift-Bremse holt nach mehreren freien Zügen zur Pflichtfrage zurück; Wächter-Gedächtnis und LLM-Verlauf gedeckelt. |
| W-ANREDE | Eine Anrede mit Namen darf nur raus, wenn der Name belegt ist (Anrufer/Kartei/Mandant). „Gerne, Herr Meier" bei unbekanntem Anrufer wird gestrichen. |

Details und Notaus-Schalter stehen in `AGENTS.md` (Abschnitte „Auflegen,
Icebreaker, Fokus" und „Keine erfundene Anrede").

## Die vier Teile des Rückrollpunkts

### 1. Quellcode — Git

- Tag: **`telefonki-produktionsstand-v2.0-2026-09-13`** (annotiert)
- Remote: `origin` = `github.com/Dr-Petsas/bianca-and-lisa`
- Zurückrollen: `git checkout telefonki-produktionsstand-v2.0-2026-09-13`

### 2. Laufende Container — Docker-Image-Tags auf pickadoc1

Die Images, aus denen der Live-Stand läuft, sind zusätzlich unter
`produktionsstand-v2.0-20260913` getaggt — Rollback also **ohne Neubau**:

| Dienst | Live-Tag | Sicherungs-Tag |
| --- | --- | --- |
| bianca / lisa / bianca-test / studio / **sipbridge** / sipbridge-lisa | `telefonki:v1` (`8701a7003632`) | `telefonki:produktionsstand-v2.0-20260913` |
| TTS (Qwen3, 8213) | `tts-qwen3:v1` (`388900ee2436`) | `tts-qwen3:produktionsstand-v2.0-20260913` |
| STT (Parakeet, 8212) | `stt-parakeet-de:v1` (`8ff19deb7d74`) | `stt-parakeet-de:produktionsstand-v2.0-20260913` |
| Cloudflare-Tunnel | `cloudflare/cloudflared:latest` | `cloudflare/cloudflared:produktionsstand-v2.0-20260913` |
| SSH-Tunnel zum Asterisk | `alpine:3.20` | `alpine:produktionsstand-v2.0-20260913` |

Hinweis: die beiden SIP-Brücken-Container laufen historisch aus unbenannten
(inzwischen aufgeräumten) Layern. Ihr Code ist identisch mit
`telefonki:v1` — sie benutzen in `compose.yml` denselben `*app`-Block. Ein
Rollback startet sie also aus dem Sicherungs-Tag; `docker tag`/`docker commit`
auf die alten Layer ist nicht möglich und auch nicht nötig.

### 3. Einstellungen, Geheimnisse und Daten — Schnappschuss auf pickadoc1

`/home/cursor/telefonki-backups/produktionsstand-v2.0-20260913/` (1,1 GB, `chmod 700`):

| Datei | Inhalt |
| --- | --- |
| `.env` | die **Live-.env** mit allen Tokens (`CLOUDFLARE_TELEFONKI_TOKEN`, `PICKADOC_PHONE_CALL_API_TOKEN`, `STT_*_KEY`, `WRITE_LIVE=1`, `INTENT_NACHZUG=1`, Wächter-Stufen `FAKTEN_WACHE`/`ANLIEGEN_ART`/`HIRN_AUTO_RESUME`) |
| `secrets.tgz` | `secrets/` — u. a. das Service-Account-JSON für den Anruf-Audio-Upload |
| `tenants.tgz` | `tenants/` wie live (meddent, blessing, thaler, demo) |
| `compose.yml`, `compose-tts_serve.yml`, `compose-stt_serve.yml`, `env-tts_serve`, `env-stt_serve` | Stack-Definitionen der drei Compose-Projekte |
| `compose-aufgeloest.yml` | `docker compose config` — alle Variablen eingesetzt, so lief es wirklich |
| `extensions_bianca.conf` | Asterisk-Dialplan (Referenzkopie des Live-Stands) |
| `volume-telefonki_telefonki-data.tgz` | Sitzungen, Anruf-Mitschnitte, Praxis-Notizen (`.data`) — 1,0 GB |
| `volume-telefonki_telefonki-berichte.tgz` | Studio-Berichte + Testtermin-Autolösch-Schlange |
| `volume-telefonki_telefonki-klang.tgz` | TTS-Platten-Cache (gewärmte Sätze) |
| `images.txt`, `inventar.txt` | welches Image je Container lief, Health-Antworten, `.env`-Schlüsselnamen, Plattenbelegung |

**Diese Dateien kommen bewusst NICHT nach GitHub** (Tokens, Service-Account-Key,
Patientendaten in den Mitschnitten). Sie liegen doppelt: auf pickadoc1 im
Ordner oben und lokal in `_snapshot-produktionsstand-v2/` (gitignoriert).

### 4. Lokale Kopie — `_snapshot-produktionsstand-v2/`

Auf dem Dev-Rechner unter `F:\Bianca&Lisa TelefonKI\_snapshot-produktionsstand-v2\`:
Git-Bundle der **vollen Historie** (`bianca-lisa-produktionsstand-v2.bundle`,
läuft auch ohne GitHub), die Server-`.env`, `secrets.tgz`, `tenants.tgz`,
`inventar.txt`, `images.txt` und diese Anleitung.

Repo aus dem Bundle wiederherstellen:

```powershell
git clone bianca-lisa-produktionsstand-v2.bundle wiederhergestellt
cd wiederhergestellt
git checkout telefonki-produktionsstand-v2.0-2026-09-13
```

## Rückrollen in fünf Schritten

```bash
ssh pickadoc1
S=/home/cursor/telefonki-backups/produktionsstand-v2.0-20260913
cd /home/cursor/telefonki

# 1) Einstellungen und Geheimnisse zurück
cp $S/.env .env                       # Tokens, WRITE_LIVE, Wächter-Stufen
tar xzf $S/tenants.tgz                # tenants/
tar xzf $S/secrets.tgz                # secrets/
cp $S/compose.yml compose.yml

# 2) Quellcode zurück (vom Dev-Rechner, .env und tenants NIE mit-rsyncen)
#    lokal: git checkout telefonki-produktionsstand-v2.0-2026-09-13
#    dann zippen/scp wie in .cursor/rules/deploy-server.mdc beschrieben

# 3) Container aus den Sicherungs-Images starten (kein Neubau nötig)
docker tag telefonki:produktionsstand-v2.0-20260913 telefonki:v1
docker compose up -d lisa bianca bianca-test studio sipbridge sipbridge-lisa tunnel

# 4) Nur wenn Daten zurück sollen — ACHTUNG, überschreibt neuere Anrufe:
#    docker compose stop lisa bianca bianca-test studio
#    docker run --rm -v telefonki_telefonki-data:/v -v $S:/s alpine:3.20 \
#      sh -c 'rm -rf /v/* && tar xzf /s/volume-telefonki_telefonki-data.tgz -C /v'
#    docker compose up -d lisa bianca bianca-test studio

# 5) Abnahme
curl -sf http://127.0.0.1:8096/health; curl -sf http://127.0.0.1:8095/health
docker exec -w /app telefonki-bianca-1 python tools/prod_smoke.py
grep -c CLOUDFLARE_TELEFONKI_TOKEN .env   # muss 1 sein
grep -c INTENT_NACHZUG .env               # muss 1 sein
```

TTS/STT nur anfassen, wenn der Fehler dort liegt:

```bash
cd /home/cursor/telefonki/tts_serve
docker tag tts-qwen3:produktionsstand-v2.0-20260913 tts-qwen3:v1
docker compose --profile qwen3 up -d
cd ../stt_serve
docker tag stt-parakeet-de:produktionsstand-v2.0-20260913 stt-parakeet-de:v1
docker compose up -d
```

## Zustand bei der Abnahme (13.09.2026)

- Bianca 8096 `ok`, Lisa 8095 `ok`, `writeLive: true`, Mandant `meddent`
- `tools/prod_smoke.py`: ALLE WACHEN GRUEN
- Brücke: „bruecke bereit auf :40101", DID +4921154244110 → meddent
- Test-Suite: 1319 bestanden, 17 rot — dieselben 17 wie vor diesem Stand
  (fremde Arbeitskopien aus Parallel-Sitzungen: `test_funktionskalender`,
  `test_hirn`, `test_schleife`, `test_versicherung_geschlecht` u. a.).
  Kein Rückschritt durch V2, aber offen.
- Live-Proben im Container: `tools/_probe_abschied_live.py` (Abschied →
  `hangup: True`), `tools/_probe_langgespraech.py` (13 Züge, keine wortgleiche
  Wiederholung, Notleine legt auf), `tools/_probe_anrede_live.py`
  (erfundene Anrede fällt, belegte bleibt).
