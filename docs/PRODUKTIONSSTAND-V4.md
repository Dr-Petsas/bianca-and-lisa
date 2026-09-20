# Produktionsstand V4 — 20.09.2026, 20:44 Uhr

V4 ist der **beste bisherige Gesprächsstand**. Chef: V2.6 ist
tausendmal runder als der Dialogkern. Dieser Freeze hält genau die
V2.6-Canary fest, die unter `01776004600` gesprochen hat — inklusive
aller nach dem Image nachgezogenen Patches.

Kein Live-8096-Wechsel, kein `.env`-Schreiben, kein Container-Stopp.

## Was V4 ist

Basis: Image `telefonki:produktionsstand-v2.6-20260914` (`c04b16aada71`)
plus die im laufenden Container `telefonki-bianca-v26-1` nachgeladenen
Dateien:

- Wunschzeit: letzte Uhr im Satz gewinnt (`13.30` nach `um 12 Uhr`)
- Abgelehnte Slot-Angebote werden gesperrt, Neusuche am Wunsch
- Verschieben spricht denselben SMS-/Link-Abschluss wie eine Buchung
- Rezept, Überweisung, Befund, Rechnung, Akte, Plan, Unterlagen,
  Krankmeldung: nur persönlich, kein Rückruf

Der laufende Container wurde per `docker commit` zum eigenen Image.
Ohne diesen Commit wären die docker-cp-Patches beim Recreate weg.

## Live-Koordinaten

- V4-Mund (Canary `01776004600`): Container `telefonki-bianca-v26-1`,
  Image-ID **`738c820782fc`**
- Tags (alle drei zeigen auf dasselbe Image):
  `telefonki:produktionsstand-v4-20260920`
  `telefonki:produktionsstand-v4`
  `telefonki:v4`
- Ladbares Tar: `image-bianca-v4.tar.gz` (227 MB) im Server-Schnappschuss
- App-Code aus dem Container: `v26-app-code.tgz` plus Ordner
  `v26-bianca/` / `v26-kern/`
- Git-Tag: `telefonki-produktionsstand-v4-2026-09-20` auf dem
  Doku-/Quellen-Commit (nicht der Dialogkern-WIP)
- Lokale Quellen der Patches: `_v26patch/`
- Live-8096 (Dialogkern, andere Anrufer): unverändert
  `telefonki:v1` = `459f05c359b1`, extra getaggt als
  `telefonki:produktionsstand-v4-20260920-live8096`
- SIP-Brücke live: `459f05c359b1` als
  `telefonki:produktionsstand-v4-20260920-sipbridge`
  (ALT-Routing `01776004600` → v26:8099 bleibt im Snapshot-`compose.yml`)
- Lisa / Studio / bianca-test: `459f05c359b1`
- `WRITE_LIVE=1`. Live-`.env` unangetastet
  (`CLOUDFLARE_TELEFONKI_TOKEN`, `INTENT_NACHZUG`, `WRITE_LIVE` gezählt).

## Rückweg

Scharfer Rollback **genau auf diesen V4-Mund** (alle Anrufer, nicht nur
die Testnummer):

```bash
cd /home/cursor/telefonki
docker tag telefonki:produktionsstand-v4-20260920 telefonki:v1
docker compose up -d bianca
```

Falls das Image-Tag fehlt, zuerst laden:

```bash
docker load -i /home/cursor/telefonki-backups/produktionsstand-v4-20260920/image-bianca-v4.tar.gz
```

Nur die Canary weiter, Live-8096 unberührt:

```bash
docker tag telefonki:produktionsstand-v4-20260920 telefonki:produktionsstand-v2.6-20260914
docker compose --profile v26 up -d --no-deps --no-build bianca-v26
```

Zurück auf **V3.2** (Dialogkern-Live vor den Abend-Reparaturen):

```bash
docker tag telefonki:produktionsstand-v3.2-20260920 telefonki:v1
docker compose up -d bianca
```

## Sicherungen

- Server: `/home/cursor/telefonki-backups/produktionsstand-v4-20260920/`
  (2,5 GB, `chmod 700`).
- Enthalten: Live-`.env`, Secrets, Tenants, Compose + aufgelöste
  Compose (App + Profil `v26` + TTS + STT), Asterisk-Referenz-Dialplan,
  TTS-Stimmen, drei Docker-Volumes (`data` 2,2 GB, `klang` 120 MB,
  `berichte`), V4-Image-Tar, Container-Quellen `v26-*`, Inventar.
- App-, SIP-, Lisa-, Studio-, TTS-, STT-, Tunnel- und Cloudflared-Images
  tragen einen V4-Sicherungstag.
- Lokale Kopie (gitignoriert):
  `F:\Bianca&Lisa TelefonKI\_snapshot-produktionsstand-v4\`
  mit Git-Bundle aller Refs, dem Server-Ordner und `_v26patch/`.

Tokens, Service-Account-Key und Patientenmitschnitte liegen nur in
diesem Schnappschuss, nie auf GitHub.
