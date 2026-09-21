# Produktionsstand V5 — 21.09.2026, 13:03 Uhr (MESZ)

V5 friert den **laufenden Live-Mund auf 8096** ein, inklusive aller
nachgeladenen docker-cp-Patches (Anrede Herr/Frau, `erkannt_satz`,
Geschlecht in die Kartei, `ersatz.py`, `name_quittung`). Das ist der
Stand, von dem A/B/C (Candidate-API, Phonetik-Index, SMS-Link) ausgehen.

Kein Container wurde für diesen Freeze gestoppt. Die Live-`.env` wurde
nur kopiert, nie überschrieben.

## Was V5 ist

Live-Container `telefonki-bianca-1` (Port 8096) zum Zeitpunkt
`2026-09-21T11:03:04Z`:

- Start-Image bleibt `telefonki:v1` = `364f53dd89c9` (Recreate vom
  20.09. nach der Anrede-Runde). Der Prozess läuft weiter aus diesem
  Start-Image.
- Dateisystem im laufenden Container trägt die Patches. Deshalb
  `docker commit` → eigenes Image `987fbaa5152d`. Ohne diesen Commit
  wären die docker-cp-Dateien beim nächsten Recreate weg.

Im committed Image nachweislich:

- `bianca/gehirn.py`: `erkannt_satz`, Anrede nie nackter Nachname
- `kern/patients.py`: `geschlecht_aktualisieren`
- `bianca/verwalten.py`: `name_quittung` (2 Treffer)
- `kern/ersatz.py` vorhanden

Nicht Teil von V5 (bewusst unverändert):

- Dialogkern bleibt **aus**. Im Container:
  `CONTROLLER_ENFORCE=0`, `CONTROLLER_SHADOW=0`, `INTENT_NACHZUG=0`
- V2.6-Canary `telefonki-bianca-v26-1` (Port 8099, Testnummer
  `01776004600`) läuft weiter. Extra-Commit
  `telefonki:produktionsstand-v5-20260921-v26` = `7cca92804fff`
- Cloud Functions auf Firebase: unverändert der alte
  `agentFindPatientAppointments`-Vertrag (ein Treffer oder 404).
  Lokale WIP-Dateien in `pickadoc-live-base` gehören **nicht** zum
  Live-Stand.

## Live-Koordinaten

| Was | Wert |
| --- | --- |
| Live-8096 Container | `telefonki-bianca-1`, healthy |
| Start-Image (laufend) | `364f53dd89c9` = `telefonki:v1` |
| V5-Commit (Dateisystem) | **`987fbaa5152d`** |
| Tags auf den Commit | `telefonki:produktionsstand-v5-20260921` · `telefonki:produktionsstand-v5` · `telefonki:v5` |
| Ladbares Tar | `image-bianca-v5.tar.gz` (227 MB) |
| App-Code aus dem Container | `live-app-code.tgz` plus `live-bianca/` / `live-kern/` |
| V26-Canary | Start `c04b16aada71` (V2.6), Commit `7cca92804fff` |
| Lisa 8095 | `459f05c359b1` |
| Studio / SIP-Brücke | `364f53dd89c9` |
| SIP-Brücke Lisa | `60d2810e172c` |
| TTS Qwen3 8213 | `388900ee2436` |
| STT Parakeet 8212 | `8ff19deb7d74` |
| `WRITE_LIVE` | `1` |
| Git-Tag | `telefonki-produktionsstand-v5-2026-09-21` (Doku-/Skript-Commit) |

`.env`-Wachen im Snapshot (Zähler, keine Werte):
`CLOUDFLARE_TELEFONKI_TOKEN=1`, `INTENT_NACHZUG=1`, `WRITE_LIVE=1`.

## Rückweg

Scharfer Rollback **genau auf diesen V5-Mund** (nach späteren Recreates):

```bash
cd /home/cursor/telefonki
docker tag telefonki:produktionsstand-v5-20260921 telefonki:v1
docker compose up -d --no-build bianca
```

Falls das Image-Tag fehlt, zuerst laden:

```bash
docker load -i /home/cursor/telefonki-backups/produktionsstand-v5-20260921/image-bianca-v5.tar.gz
```

Zurück auf **V4** (V2.6-Canary-Mund, 20.09.):

```bash
docker tag telefonki:produktionsstand-v4-20260920 telefonki:v1
docker compose up -d --no-build bianca
```

Zurück auf **V3.2** (Dialogkern-Live vor den Abend-Reparaturen):

```bash
docker tag telefonki:produktionsstand-v3.2-20260920 telefonki:v1
docker compose up -d --no-build bianca
```

Nur die Canary, Live-8096 unberührt:

```bash
docker tag telefonki:produktionsstand-v5-20260921-v26 telefonki:produktionsstand-v2.6-20260914
docker compose --profile v26 up -d --no-deps --no-build bianca-v26
```

## Sicherungen

- Server: `/home/cursor/telefonki-backups/produktionsstand-v5-20260921/`
  (2,8 GB, `chmod 700`).
- Enthalten: Live-`.env`, Secrets, Tenants, Compose + aufgelöste
  Compose (App + Profil `v26` + TTS + STT), Asterisk-Referenz-Dialplan
  (`extensions_bianca.conf`), TTS-Stimmen, drei Docker-Volumes
  (`data` 2,5 GB / 20157 Einträge, `klang` 115 MB, `berichte`),
  V5-Image-Tar, Container-Quellen `live-*` und `v26-*`, Inventar,
  Printenv-Stichprobe.
- App-, SIP-, Lisa-, Studio-, TTS-, STT-, Tunnel- und Cloudflared-Images
  tragen einen V5-Sicherungstag.
- Lokale Kopie (gitignoriert):
  `F:\Bianca&Lisa TelefonKI\_snapshot-produktionsstand-v5\`
  mit Git-Bundle aller Refs, dem Server-Ordner und einer Kopie der
  lokalen Cloud-Function-Quellen zum Freeze-Zeitpunkt.

Tokens, Service-Account-Key und Patientenmitschnitte liegen nur in
diesem Schnappschuss, nie auf GitHub.

## Skripte

- `tools/_produktionsstand_v5_server.sh` — Freeze auf pickadoc1
- `tools/_produktionsstand_v5_abnahme.sh` — read-only Gegenprobe

Abnahme 21.09.2026 grün: Marker 1/1/2, `ersatz.py` da, Health 8096/8095
OK, `WRITE_LIVE=1`, `.env`-Wachen 1/1/1.
