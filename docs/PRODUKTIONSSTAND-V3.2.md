# Produktionsstand V3.2 — 20.09.2026, 05:52 Uhr

V3.2 ist ein **Freeze des laufenden Live-Stands**, bevor die vier
Gesprächsfehler aus Anruf `dc03a9ea` (05:26) einzeln repariert werden.
Kein Feature-Schnitt, kein Container-Neustart, kein `.env`-Schreiben.

Eingefroren ist der Stand **nach** V3.1 plus den danach ausgespielten
Commits bis `b5e7eb0`:

- Dialogkern spricht live, aber **nur** für die Testnummer
  `01776004600` (`CONTROLLER_ENFORCE`, `CONTROLLER_SHADOW=0`).
- Versicherungsfrage: „Wie sind Sie versichert?“ (`b5e7eb0`).
- MedDent-Desaster 34979221: Kern nicht mehr ins Modell schicken, keine
  SMS aus der Paraphrase, kein „unbekannt“ im Mund (`327b0c5`).
- Kern-Schalter liest die echte `callerPhone` (`2fba15f`).
- Anrufansicht wieder einspaltig (`4de0011`).

Die bekannten Fehler von `dc03a9ea` gehören **zu diesem Stand** und
werden erst danach einzeln behoben: Echo-Vorbezug, „mit Herr Petsas“,
„Ist egal“ als Wunsch, leerer Wochentag ohne nächstes Angebot.

## Was sich NICHT geändert hat

SIP-Brücke, TTS, STT, Tunnel, Asterisk, Clara, Lena und MAS sind
unberührt. Lisa, Studio und `bianca-test` laufen weiter aus dem älteren
Image `9703c41a444b` (Layer aufgeräumt — Dateisystem-Tar liegt bei).
Mandanten bleiben byte-identisch. `WRITE_LIVE=1`.

## Live-Koordinaten

- Code-Commit (deployte Bianca): `b5e7eb0`
- Git-Tag: `telefonki-produktionsstand-v3.2-2026-09-20` — sitzt auf dem
  Doku-Commit (nur `AGENTS.md` + dieses Dokument, kein Code), damit der
  Tag seine eigene Anleitung mitbringt.
- App-Image Bianca: `telefonki:produktionsstand-v3.2-20260920`
- Image-ID Bianca:
  `8fbf3727f483442762619ad7c44f620c011a1e97a5e9e56fdf97d6d312a9c16c`
- Lisa / Studio / bianca-test: `9703c41a444b` (Dateisystem-Tar
  `container-lisa.tar.gz`, Layer weg — `docker tag` und `docker commit`
  scheitern dort).
- SIP-Brücke: `60d2810e172c` als
  `telefonki:produktionsstand-v3.2-20260920-sipbridge` (unverändert seit
  V3.0).
- `WRITE_LIVE=1`.
- `CONTROLLER_ENFORCE=01776004600`, `CONTROLLER_SHADOW=0`.

## Notaus / Rückweg

Scharfer Rollback der Live-Bianca auf **genau diesen Freeze**:

```bash
cd /home/cursor/telefonki
docker tag telefonki:produktionsstand-v3.2-20260920 telefonki:v1
docker compose up -d bianca
```

Danach Health 8096, `WRITE_LIVE=1` und `printenv CONTROLLER_ENFORCE`
prüfen. Lisa/Studio/Test nicht mitziehen — die laufen aus einem anderen
Image.

Zurück auf **V3.1** (vor Dialogkern-Enforce und Versicherungs-Fix):

```bash
cd /home/cursor/telefonki
docker tag telefonki:produktionsstand-v3.1-20260919 telefonki:v1
docker compose up -d lisa bianca bianca-test studio
```

Ohne Image-Wechsel: Dialogkern aus für den nächsten Anruf durch
`CONTROLLER_ENFORCE=0` in der Server-`.env`, dann
`docker compose up -d bianca` (recreate, kein Build). `.env` nie
pauschal überschreiben.

## Abnahme

- `VERSION=v3.2 STAMP=20260920 bash /tmp/_abn_v32.sh` auf pickadoc1:
  grün. App-Tag zeigt auf die laufende Bianca (`8fbf3727f483`).
- Health 8095/8096: grün. `WRITE_LIVE=1` im Container.
- `tools/prod_smoke.py` im deployten `bianca`-Container: `ALLE WACHEN
  GRUEN`.
- Live-`.env` unangetastet: `CLOUDFLARE_TELEFONKI_TOKEN` und
  `INTENT_NACHZUG` ausdrücklich gegengezählt.
- Blessing-V2.8-/V2.9-Schalter, W-ERSATZ-MOTIV, Dock-Cache-Buster `b106`
  wie unter V3.1.
- Hinweis der Abnahme (kein Fehler des Freeze): Lisa, Studio,
  `bianca-test` und die SIP-Brücke laufen aus anderen Images als Bianca.
  Die Abnahme-Zeile `Blessing-Ein-Thema-Code` ist 0 — so stand es live.

## Sicherungen

- Server:
  `/home/cursor/telefonki-backups/produktionsstand-v3.2-20260920/`
  (2,2 GB).
- Enthalten: Live-`.env`, Secrets, Tenants, aufgelöste Compose-
  Konfigurationen (App + TTS + STT), Asterisk-Referenz-Dialplan,
  TTS-Stimmen, die drei Docker-Volumes (`telefonki-data`,
  `telefonki-klang`, `telefonki-berichte`), Image- und Health-Inventar,
  Dateisystem-Tar von Lisa (`container-lisa.tar.gz`, 244 MB).
- App-, SIP-Brücken-, Tunnel-, Cloudflared-, TTS- und STT-Images tragen
  einen V3.2-Sicherungstag.
- Lokale Kopie (gitignoriert):
  `F:\Bianca&Lisa TelefonKI\_snapshot-produktionsstand-v3.2\`
  mit Git-Bundle (`telefonki-repo.bundle`, alle Refs), dem kompletten
  Server-Ordner und `lokal/` (Dev-`.env` + `.data`).
