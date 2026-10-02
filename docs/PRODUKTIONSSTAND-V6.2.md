# Produktionsstand V6.2 — 03.10.2026

V6.2 ist ein vollständiger Rückrollpunkt des laufenden TelefonKI-Systems.
Er sichert nicht nur den Git-Code, sondern auch Images, Containerzustände,
Servereinstellungen, Live-Konfiguration, Geheimnisse, Mandanten, Stimmen,
Modelle und sämtliche TelefonKI-Laufzeitvolumes.

## Autoritative Kennungen

- Produktcode: Commit `366a3c630` („Restliche Audio-Turnarounds absichern“)
- Annotierter Git-Tag:
  `telefonki-produktionsstand-v6.2-2026-10-03`
- Server-Snapshot:
  `/home/cursor/telefonki-backups/produktionsstand-v6.2-20261003/`
- Lokale Offline-Kopie:
  `_snapshot-produktionsstand-v6.2-20261003/`
- Kanonisches App-Image:
  `telefonki:produktionsstand-v6.2-20261003`
- Bequeme Image-Aliasse:
  `telefonki:produktionsstand-v6.2` und `telefonki:v6.2`

Die unveränderlichen Image-IDs, Containerzustände, Dateigrößen und
Prüfsummen stehen in `inventar.txt`, `freeze-tags.txt` und `SHA256SUMS`
des Snapshots.

## Was vollständig gesichert ist

1. **Git und Quellstände**
   - annotierter Git-Tag,
   - portables `git bundle --all`,
   - kompletter Server-Arbeitsbaum einschließlich `.git`, `.env`,
     ignorierter Dateien und Diagnosewerkzeuge,
   - lokales Arbeitsbaumarchiv einschließlich aller nicht versionierten
     und ignorierten Daten, ausgenommen ältere Snapshotordner.

2. **Docker**
   - ladbares Gesamtarchiv `images-v6.2.tar.gz`,
   - exaktes Freeze-Image jedes vorhandenen TelefonKI-, TTS-, STT- und
     Enhance-Containers,
   - Container-, Image-, Netzwerk- und Compose-Inspects,
   - Start-/Stoppzustand jedes Containers sowie private Logauszüge,
   - Wiederherstellungsskripte für Image-Tags und die beim Freeze laufenden
     Compose-Dienste.

3. **Nicht in Git gespeicherte Konfiguration**
   - Live-`.env`, aufgelöste Compose-Konfiguration, Dockerfile und
     Requirements,
   - `secrets/`, `tenants/`, TTS-Stimmreferenzen und STT-Bind-Modell,
   - Cursor-SSH-Konfiguration und -Schlüssel,
   - relevante Host-Konfiguration unter `/etc`, Systemd-, Docker-,
     Netzwerk-, Tailscale-, Mount- und Cron-Inventar.

4. **Laufzeit- und Modelldaten**
   - alle Volumes mit Präfix `telefonki_`, `tts_serve_`, `stt_serve_`,
     `enhance_serve_` sowie das ältere `app_telefonki-data`,
   - damit insbesondere Sitzungen, Mitschnitte, Anrufmanifeste, Berichte,
     Dialog-Policies, Klang-Cache und lokale Modelle.

5. **Telefonie**
   - beide SIP-Brücken, SSH-Rücktunnel und öffentlicher Lisa-Tunnel als
     Image/Containerzustand,
   - Repo-Dialplan mit SHA-256,
   - der Live-Dialplan von `212.132.104.205`, falls der read-only SSH-Zugriff
     beim Freeze verfügbar ist; andernfalls wird der Zugriffsausfall
     ausdrücklich dokumentiert.

vLLM ist ein geschützter externer Dienst. Gemäß Produktionsregel wird es
weder gestartet, gestoppt noch exportiert; V6.2 sichert seinen vollständigen
Container-/Mount-/Argumente-Stand read-only. Das TelefonKI-System kann damit
auf denselben externen Modellendpunkt zurückgeschaltet werden.

## Sicherheitsgrenze

Der Snapshot enthält Tokens, Service-Account-Schlüssel, SSH-Schlüssel,
Stimmproben und Patientendaten. Deshalb:

- Snapshotverzeichnisse sind nur für den Serverbenutzer lesbar
  (`chmod go-rwx`).
- Diese Dateien werden **nie** committed, gepusht oder per E-Mail versandt.
- In Git liegen ausschließlich diese Dokumentation und die Freeze-/
  Abnahmeskripte.

## Abnahme

Server:

```bash
cd /home/cursor/telefonki
bash tools/_produktionsstand_v62_abnahme.sh
```

Die Abnahme prüft:

- alle SHA-256-Summen,
- Lesbarkeit sämtlicher Tar-/Gzip-Archive und des Git-Bundles,
- Live-Code gegen Freeze-Image,
- alle aufgezeichneten Volumes, Container, Netzwerke und Image-Tags,
- Health von Lisa/Bianca/Studio/Test und beiden SIP-Brücken,
- laufende Tunnel,
- `WRITE_LIVE=1`, `NAMENS_LINK=0` und die einmaligen Live-`.env`-Schlüssel,
- V6.2-Produktmarker und `python tools/prod_smoke.py`.

## Vollständiger Rollback

### 1. Snapshot und Images laden

```bash
S=/home/cursor/telefonki-backups/produktionsstand-v6.2-20261003
gunzip -c "$S/images-v6.2.tar.gz" | docker load
bash "$S/restore-image-tags.sh"
```

### 2. Server-Arbeitsbaum und private Konfiguration zurückspielen

Nur in einem freigegebenen Wartungsfenster:

```bash
cd /home/cursor
mv telefonki telefonki-vor-v62-rollback
mkdir telefonki
tar xzf "$S/server-source-tree.tgz" -C telefonki
cp -a "$S/.env" telefonki/.env
tar xzf "$S/secrets.tgz" -C telefonki
tar xzf "$S/tenants.tgz" -C telefonki
```

Alternativ stellt das Bundle die Git-Seite allein wieder her:

```bash
git clone "$S/telefonki-v6.2.bundle" telefonki-v62
cd telefonki-v62
git checkout telefonki-produktionsstand-v6.2-2026-10-03
```

### 3. Volumes zurückspielen

**Destruktiv; vorher die betroffenen Dienste stoppen.**

```bash
cd /home/cursor/telefonki
docker compose stop
CONFIRM_VOLUME_RESTORE=YES bash "$S/restore-volumes.sh"
```

### 4. Beim Freeze laufende Dienste exakt wieder starten

```bash
docker tag telefonki:produktionsstand-v6.2-20261003 telefonki:v1
bash "$S/restore-running-services.sh"
```

Das Wiederanlaufskript startet nur die Dienste, die beim Freeze tatsächlich
liefen. Bewusst gestoppte Alt-/Modellcontainer werden nicht versehentlich
aktiviert.

### 5. Asterisk

Wenn `extensions_bianca.live.conf` im Snapshot vorhanden ist, ist dies die
Live-Kopie. Andernfalls gilt `extensions_bianca.repo.conf` als dokumentierter
Rückfall. Ein echter Dialplan-Rollback erfolgt nur auf
`root@212.132.104.205` mit Backup und anschließendem
`asterisk -rx 'dialplan reload'`.

### 6. Pflichtabnahme nach Rollback

```bash
curl -sf http://127.0.0.1:8095/health
curl -sf http://127.0.0.1:8096/health
docker exec telefonki-bianca-1 printenv WRITE_LIVE
docker exec -w /app telefonki-bianca-1 python tools/prod_smoke.py
```

Vor jedem Rollback sind laufende Echtanrufe zu prüfen. Die Live-`.env` darf
niemals durch eine Git-Version oder einen unkontrollierten Deploy
überschrieben werden.
