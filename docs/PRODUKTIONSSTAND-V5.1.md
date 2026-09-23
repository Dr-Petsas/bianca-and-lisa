# Produktionsstand V5.1 — 23.09.2026, 12:35 Uhr (MESZ)

V5.1 friert den **laufenden Live-Mund auf 8096** ein, bevor die Korrekturen
aus Anruf `9057eb03` in den Container kamen. Das ist der Rückweg, falls
diese Korrekturen zurückgenommen werden müssen.

Kein Container wurde für diesen Freeze gestoppt. Die Live-`.env` wurde
nur kopiert, nie überschrieben. Der Tag `telefonki:v5` bleibt auf dem
V5-Image `987fbaa5152d`.

## Was V5.1 ist

Live-Container `telefonki-bianca-1` (Port 8096) zum Zeitpunkt des
`docker commit` am 23.09.2026:

- Start-Image bleibt `telefonki:v1` = `364f53dd89c9`. Der Prozess lief
  weiter aus diesem Start-Image.
- Dateisystem im laufenden Container trägt die bis dahin nachgeladenen
  Patches. Deshalb `docker commit` → eigenes Image `c73476b7e3e8`.

Nicht Teil von V5.1 (bewusst unverändert im Freeze):

- Dialogkern bleibt **aus**. Im Container:
  `CONTROLLER_ENFORCE=0`, `CONTROLLER_SHADOW=0`, `INTENT_NACHZUG=0`
- Die vier Korrekturen aus Anruf `9057eb03` (Handynummer in die Akte,
  Vorlesen statt Slotwahl, Nein mit Uhrzeit, Frage „Wie lautet sie?“)
  liegen **nicht** in diesem Image. Sie kamen erst danach per docker-cp.
- V2.6-Canary `telefonki-bianca-v26-1` läuft weiter. Extra-Commit
  `telefonki:produktionsstand-v5.1-20260923-v26` = `98a53ca81611`
- Cloud Functions auf Firebase: unverändert.
- SIP-Brücken-Images ließen sich nicht taggen (Layer weg). Der
  Brücken-Quellstand liegt als `sip_bridge_server.py` im Schnappschuss.

## Live-Koordinaten

| Was | Wert |
| --- | --- |
| Live-8096 Container | `telefonki-bianca-1`, healthy |
| Start-Image (vor dem späteren Retag) | `364f53dd89c9` = `telefonki:v1` |
| V5.1-Commit (Dateisystem vor den 9057-Korrekturen) | **`c73476b7e3e8`** |
| Tags auf den Commit | `telefonki:produktionsstand-v5.1-20260923` · `telefonki:produktionsstand-v5.1` · `telefonki:v5.1` |
| Ladbares Tar | `image-bianca-v5.1.tar.gz` (229 MB) |
| V26-Canary-Commit | `98a53ca81611` |
| Lisa 8095 | `4a54f735f60b` |
| Studio / Bianca-Test | `9f69ba905f44` |
| V26-Start-Image | `c04b16aada71` |
| TTS Qwen3 8213 | `388900ee2436` |
| STT Parakeet 8212 | `8ff19deb7d74` |
| Tunnel | `d9e853e87e55` |
| Cloudflared | `51c9cefcb456` |
| `WRITE_LIVE` | `1` |
| Git-Tag | `telefonki-produktionsstand-v5.1-2026-09-23` (Doku-/Skript-Commit) |

`.env`-Wachen im Snapshot (Zähler, keine Werte):
`CLOUDFLARE_TELEFONKI_TOKEN=1`, `INTENT_NACHZUG=1`, `WRITE_LIVE=1`.

## Rückweg

Scharfer Rollback **genau auf diesen V5.1-Mund**:

```bash
cd /home/cursor/telefonki
docker tag telefonki:produktionsstand-v5.1-20260923 telefonki:v1
docker compose up -d --no-build bianca
```

Falls das Image-Tag fehlt, zuerst laden:

```bash
docker load -i /home/cursor/telefonki-backups/produktionsstand-v5.1-20260923/image-bianca-v5.1.tar.gz
```

Zurück auf **V5** (21.09., vor diesem Freeze):

```bash
docker tag telefonki:produktionsstand-v5-20260921 telefonki:v1
docker compose up -d --no-build bianca
```

## Sicherungen

- Server: `/home/cursor/telefonki-backups/produktionsstand-v5.1-20260923/`
  (3,7 GB).
- Enthalten: Live-`.env`, Secrets, Tenants, Compose, TTS-Stimmen, drei
  Docker-Volumes (`data` ~3,5 GB, `klang` ~120 MB, `berichte`),
  V5.1-Image-Tar, Container-Quellen `live-*` und `v26-*`, Inventar,
  Printenv-Stichprobe.
- Asterisk `212.132.104.205` war von pickadoc1 aus nicht erreichbar.
  Im Schnappschuss bleibt die Repo-Referenz `extensions_bianca.conf`.
  Eine Live-Kopie wird nur abgelegt, wenn der Dev-Rechner den Asterisk
  direkt erreicht.
- App-, Lisa-, Studio-, Test-, TTS-, STT-, Tunnel- und Cloudflared-Images
  tragen einen V5.1-Sicherungstag. Die SIP-Brücken nicht (Layer weg).
- Lokale Kopie (gitignoriert):
  `F:\Bianca&Lisa TelefonKI\_snapshot-produktionsstand-v5.1\`

Tokens, Service-Account-Key und Patientenmitschnitte liegen nur in
diesem Schnappschuss, nie auf GitHub.

## Skripte

- `tools/_produktionsstand_v51_server.sh` — Freeze auf pickadoc1
- `tools/_produktionsstand_v51_abnahme.sh` — read-only Gegenprobe
