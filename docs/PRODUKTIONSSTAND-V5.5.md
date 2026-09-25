# Produktionsstand V5.5 — 25.09.2026

Eingefrorener **laufender Live-Stand** von `telefonki-bianca-1` (Port 8096) auf
pickadoc1. Dies ist der Stand VOR den Konsolidierungs-Arbeiten
(„souveräne Bianca", 25.09.2026). Er ist der Rollback-Anker, auf den jederzeit
zurückgerollt werden kann, ohne einen Anruf zu verlieren.

## Was live läuft (Stand des Freeze)

- **Mund/Code:** bewährte V2.6/V4-Mundlinie mit allen bis zum Freeze
 nachgezogenen V5-/docker-cp-Patches im Dateisystem (Anrede Herr/Frau,
 `erkannt_satz`, Geschlecht-Kartei, `ersatz.py`, `name_quittung`,
 Verwaltungs-Quittung …). Die live vorhandenen Wächter
 (`anrede_wache`, `fach_wache`, `auto-resume`) laufen auf `enforce`;
 `_telefon_tor` ist aktiv.
- **Ohr:** ElevenLabs **Scribe v2** — `STT_BASE=""` (leer) über
 `compose.scribe-heute.yml`. Parakeet/Qwen/Whisper-Basen sind für Bianca
 bewusst leer. Authoritativ geprüft: `docker exec telefonki-bianca-1
 printenv STT_BASE` → leer.
- **Dialogkern nicht enthalten:** `CONTROLLER_ENFORCE=0`,
 `CONTROLLER_SHADOW=0`, `INTENT_NACHZUG=0`. Der verworfene
 V3.x-Dialogkern (`bianca/controller/`) liegt nicht im eingefrorenen
 Live-Dateibaum und wird im produktiven Stamm nicht wieder aufgenommen.
- **Schreiben live:** `WRITE_LIVE=1`.
- **Start-Image des Containers:** `telefonki:bianca-scribe-20260925`
 (`24e5dced66a2`).

## Vier Säulen des Freeze

1. **Annotierter Git-Tag:** `telefonki-produktionsstand-v5.5-2026-09-25`.
2. **Docker-Image (docker commit des LIVE-Containers):**
 `telefonki:produktionsstand-v5.5-20260925` = `8bc6cdb6b3f3`, zusätzlich
 getaggt `telefonki:produktionsstand-v5.5` und `telefonki:v5.5`.
 **Byte-identisch** zur laufenden Bianca (Code-Paritätshash
 `82c74fad91d42b82` in Freeze-Image und Live-Container — in der Abnahme
 hart geprüft). `telefonki:v1` bleibt UNANGETASTET (`a951a7c881ab`).
 Ladbar ohne Registry: `image-bianca-v5.5.tar.gz` (230 MB).
 Mitgetaggt: lisa, bianca-test, studio, bianca-v26, tts-qwen3,
 stt-parakeet-de, enhance, tunnel, lisa-public (sipbridge: Layer weg,
 als Dateibaum in `live-sip_bridge/` gesichert).
3. **Server-Schnappschuss** unter
 `/home/cursor/telefonki-backups/produktionsstand-v5.5-20260925/` (4.3 GB):
 `.env` (Kopie), `compose.yml` + `compose.scribe-heute.yml` +
 `compose.parakeet-zurueck.yml` + `compose.qwen-test.yml`,
 aufgelöste Compose-Konfig (`compose-aufgeloest-scribe.yml`),
 `tenants.tgz`, `secrets.tgz`, `tts-stimmen.tgz`,
 `compose-tts_serve.yml`/`compose-stt_serve.yml`/`compose-enhance.yml`,
 `extensions_bianca.conf` (Referenzkopie — Live-Asterisk 212.132.104.205
 von pickadoc1 nicht per SSH erreichbar), `sip_bridge_server.py`,
 Live-Quellbäume `live-bianca/`, `live-kern/`, `live-lisa/`,
 `live-sip_bridge/`, der kleine Kern-Tar `live-app-code.tgz` und
 `live-app-full-code.tgz` mit allen im Freeze-Image liegenden App-Quellen,
 sowie die drei Docker-Volumes
 `volume-telefonki_telefonki-data.tgz` (4.1 GB, 33 048 Einträge),
 `-berichte.tgz`, `-klang.tgz` (2 605 Einträge).
4. **Lokale Kopie + Git-Bundle:** Vollständiger Live-Quellbaum, Bundle aller
 Git-Refs, Binär-Patch der getrackten WIP-Dateien und separates Archiv der
 ungetrackten Quell-WIP unter
 `_snapshot-produktionsstand-v5.5-20260925/` (gitignoriert; keine
 Secrets/Patientendaten oder Audios).

Skripte: `tools/_produktionsstand_v55_server.sh` (Schnappschuss + Image-Tags)
und `tools/_produktionsstand_v55_abnahme.sh` (Abnahme, harter Paritäts-Check).
**LF-Zeilenenden Pflicht** (PowerShell schreibt CRLF → `sed -i 's/\r$//'`).

## Abnahme (25.09.2026 — grün)

- Freeze-Image byte-identisch zur laufenden Bianca (`82c74fad91d42b82`).
- `telefonki:v1` unverändert (`a951a7c881ab`).
- Archive lesbar; 3 Volumes gesichert; Image-Tar 230 MB.
- Ohr = Scribe (`STT_BASE` leer), Overlay gesichert.
- Wächter `enforce`, `_telefon_tor`=2 Treffer, `ersatz.py` da.
- Health 8096/8095 `ok:true, writeLive:true`; `prod_smoke: ALLE WACHEN GRUEN`.
- `.env` unangetastet (`CLOUDFLARE_TELEFONKI_TOKEN`, `INTENT_NACHZUG`,
 `WRITE_LIVE=1` je 1 Zeile).

## Rollback auf V5.5 (kein Container-Verlust nötig)

Das Freeze-Image ist byte-identisch zum laufenden Stand. Rollback aus einem
späteren, schlechteren Stand:

```bash
cd /home/cursor/telefonki
# Freeze-Image wieder unter den Namen legen, den das Scribe-Overlay referenziert
docker tag telefonki:produktionsstand-v5.5-20260925 telefonki:bianca-scribe-20260925
# Bianca aus dem eingefrorenen Stand neu erzeugen (Scribe-Ohr)
docker compose -f compose.yml -f compose.scribe-heute.yml up -d --no-build bianca
# Abnahme
bash tools/_produktionsstand_v55_abnahme.sh
```

Image von außen laden (falls der lokale Tag fehlt):

```bash
gunzip -c /home/cursor/telefonki-backups/produktionsstand-v5.5-20260925/image-bianca-v5.5.tar.gz | docker load
```

**Nicht** `telefonki:v1` überschreiben und beim Deploy IMMER
`--exclude=.env --exclude=tenants/` (die `.env`-Falle).
