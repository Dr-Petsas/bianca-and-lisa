# Produktionsstand V6.0 — 26.09.2026

V6.0 ist der erste vollständige Freeze der produktiven Telefon-KI: Git,
laufende Container-Dateisysteme, Images, Konfiguration, Geheimnisse,
Mandanten, Stimmen, Modelle und Laufzeitdaten sind gemeinsam gesichert.

## Autoritativer Stand

- Produktcode vor den Freeze-Werkzeugen:
  `0d8d136ba4e9a27519de4ea725669e52a0b67184`
- Annotierter Git-Tag:
  `telefonki-produktionsstand-v6.0-2026-09-26`
- Server-Snapshot:
  `/home/cursor/telefonki-backups/produktionsstand-v6.0-20260926/`
- Lokale Offline-Kopie:
  `_snapshot-produktionsstand-v6.0-20260926/`
- Live-Bianca vor dem Freeze: `telefonki:v1`,
  Image `80206fd424ea34c0426e5428d05be2e7832fe32b80eb6fb4de0d88b3ebf64366`.
- Freeze-Bianca:
  `547c17c0dc555ca89878a05c300027a324fc48321e919ba3953fdf31bcf81100`.
- Live-/Freeze-Code-Parität:
  `c4d455b3e043e42b3ec855e747b4baa93d667312e1dd72d3dee6a1306cd2c439`.
- Server-Snapshot: 34 GB; lokale Arbeitsbaum-Sicherung zusätzlich
  226.542.318 Byte.
- Gesamt-Imagearchiv `images-v6.0.tar.gz`:
  SHA-256 `fa482524b6c1d8918764c7ec1260d1e00384030dbc424e9c8fe4118aff11a121`.

Alle Einzelprüfsummen stehen unveränderlich in `SHA256SUMS` des Snapshots.

## Inhalt des Server-Snapshots

- Docker-Commit der laufenden Bianca als
  `telefonki:produktionsstand-v6.0-20260926`,
  `telefonki:produktionsstand-v6.0` und `telefonki:v6.0`.
- Ladbares Gesamtarchiv `images-v6.0.tar.gz` für Bianca, Lisa, Bianca-Test,
  Studio, beide SIP-Brücken, Tunnel, Cloudflared, Qwen3-TTS, Parakeet-STT
  und Enhance. Fehlende ursprüngliche Image-Layer werden per
  `docker commit --pause=false` aus dem laufenden Container erhalten.
- Container-, Image- und Volume-Inspects sowie private Logauszüge.
- Vollständiger Server-Arbeitsbaum einschließlich `.git`, `.env`,
  ignorierter Dateien, `secrets/`, `tenants/` und aller Compose-Dateien.
- TTS-Stimmen und das gebundene Parakeet-Modell.
- Volumes `telefonki-data`, `telefonki-berichte`, `telefonki-klang`,
  `tts-models`, `stt-models` und `enhance-hf`.
- vLLM ausschließlich als read-only Inventar. Der externe Modellprozess
  wurde weder verändert noch neu gestartet.
- Repo-Dialplan mit SHA-256. Der Live-Asterisk `212.132.104.205` war vom
  Entwicklungsrechner nicht per SSH autorisiert; dieser bekannte
  Zugriffsausfall ist im Snapshot dokumentiert und blockiert den
  freigegebenen Freeze nicht.

Der Snapshot entsteht zuerst in einem temporären Verzeichnis. Erst wenn
Archive lesbar, Live-/Image-Code bytegleich und alle Prüfsummen geschrieben
sind, wird er atomar auf den endgültigen Namen verschoben. Kein produktiver
Container wird dafür gestoppt oder neu gestartet.

## Lokale Offline-Kopie

Die lokale, gitignorierte Kopie enthält:

1. den kompletten Server-Snapshot,
2. ein `git bundle --all` samt Branches, Tags und Stash-Refs,
3. ein Archiv des lokalen Arbeitsbaums einschließlich `.env`, `.data`,
   `.run`, `.venv`, `_posteingang`, Audios, Berichte und Diagnoseartefakte,
4. Worktree-/Ref-Inventar und SHA-256-Prüfsummen.

`.git` und ältere Snapshotordner werden nur aus dem lokalen Baumarchiv
ausgeschlossen; die Git-Historie steckt vollständig im Bundle. Private
Artefakte, Patientendaten und Geheimnisse bleiben ausschließlich in den
Snapshots und gelangen nicht in den Git-Commit oder nach GitHub.

## Abnahme

Ausführung auf `pickadoc1`:

```bash
cd /home/cursor/telefonki
bash tools/_produktionsstand_v60_abnahme.sh
```

Die Abnahme am 26.09.2026 war vollständig grün. Sie prüft:

- alle SHA-256-Summen,
- Lesbarkeit sämtlicher Tar-/Gzip-Archive,
- Live-Code gegen Freeze-Image,
- drei Bianca-V6-Image-Tags,
- Container-/Image-/Volume-Inventar,
- Health 8095 und 8096,
- `WRITE_LIVE=1`,
- je genau eine Zeile für `CLOUDFLARE_TELEFONKI_TOKEN`,
  `INTENT_NACHZUG` und `WRITE_LIVE`,
- `python tools/prod_smoke.py` im Live-Container.

Die lokale Vollsuite war ebenfalls grün: **2668 Tests bestanden**. Der zuvor
einzige rote Test bildete den neuen Namenslink-Vertrag unvollständig nach;
seine externe Reservierungs-SMS- und Bindungs-Evidenz wurde im Test ergänzt,
ohne Produktivcode zu ändern.

## Rollback

Das App-Image kann ohne Build wiederhergestellt werden:

```bash
cd /home/cursor/telefonki
docker tag telefonki:produktionsstand-v6.0-20260926 telefonki:v1
docker compose up -d --no-build bianca lisa bianca-test studio
```

Falls lokale Image-Tags fehlen:

```bash
gunzip -c /home/cursor/telefonki-backups/produktionsstand-v6.0-20260926/images-v6.0.tar.gz | docker load
```

Volumes werden nur in einem ausdrücklich freigegebenen Wartungsfenster
zurückgespielt. Beispiel:

```bash
docker run --rm \
  -v telefonki_telefonki-data:/v \
  -v /home/cursor/telefonki-backups/produktionsstand-v6.0-20260926/volumes:/in:ro \
  alpine:3.20 sh -c 'rm -rf /v/* && tar xzf /in/telefonki_telefonki-data.tgz -C /v'
```

Vor jedem echten Rollback sind laufende Anrufe zu prüfen. Die Live-`.env`
darf nie durch eine Git-Version überschrieben werden.
