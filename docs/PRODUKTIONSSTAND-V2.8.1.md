# Produktionsstand V2.8.1 — 15.09.2026, 19:30 Uhr

V2.8.1 ist ein reiner Rollout-Nachzug zu V2.8. Die Blessing-Verbesserungen
bleiben unverändert. Korrigiert wurde eine ausgelassene, bereits in Git
enthaltene Datei des W-ERSATZ-MOTIV-Schutzes.

## Befund und Korrektur

Das erste V2.8-Image verhinderte bei Rüther bereits den gefährlichen
Ausweich auf `GYN Endometriose Erstberatung`. Wegen eines partiellen
Server-Syncs fehlte im Image jedoch der neuere Stand von `kern/calendar.py`:
Die Buchbarkeit aus dem vollständigen Sitzungs-Katalog
(`visitMotiveOnline=false`) wurde nicht ausgewertet. Ben sagte deshalb noch
fälschlich „Im Moment habe ich leider keinen freien Termin“.

V2.8.1 synchronisiert ausschließlich den bereits durch Commit `6d733c9`
versionierten Kalender-Nachzug und die zugehörige read-only Live-Probe.
Jetzt lautet die ehrliche Ansage „Diese Terminart darf ich telefonisch nicht
vergeben“; der echte Wunsch steht in der Rückruf-Notiz. Weder Endometriose
noch internes GYN-Kürzel oder das Wort „Krebs“ werden gesprochen.

## Live-Koordinaten

- Git-Tag: `telefonki-produktionsstand-v2.8.1-2026-09-15`
- App-Image: `telefonki:produktionsstand-v2.8.1-20260915`
- Image-ID:
  `574c2de2068d740bf333aebe8c5dc32452b26812cff32bf70a166b43e22cbb8d`
- Dieselbe Image-ID läuft in `bianca`, `lisa`, `bianca-test` und `studio`.
- Das ursprüngliche V2.8-Image bleibt zusätzlich als
  `telefonki:produktionsstand-v2.8-partial-20260915` erhalten.
- `WRITE_LIVE=1`; Live-`.env`, Tenants, SIP-Brücke, TTS, STT, Tunnel,
  Asterisk, Clara, Lena und MAS blieben unverändert.

## Abnahme

- Lokal: `tests/test_ersatz_motiv.py` — 31 bestanden.
- Vor dem Neustart: kein aktiver Echtanruf, keine SIP-Brückenaktivität.
- Health 8095/8096: grün, `writeLive=true`.
- `tools/prod_smoke.py`: `ALLE WACHEN GRUEN`.
- Read-only Live-Probe:
  `tools/_probe_ersatz_motiv_live.py` — alle Wachen grün:
  - Rüther bekommt keinen Endometriose-Ausweich.
  - `GYN Krebsvorsorge` wird als „telefonisch nicht vergeben“ markiert.
  - Der gesprochene Text nennt weder GYN, Krebs noch Endometriose.
  - MedDent behält seinen Kontroll-Ausweich.
- Die Produktionsabnahme prüft seit V2.8.1 den ausgelassenen
  `visitMotiveOnline=false`-Pfad ausdrücklich und bricht bei Fehlen ab.

## Sicherungen

- Server:
  `/home/cursor/telefonki-backups/produktionsstand-v2.8.1-20260915/`
- Enthalten: Live-`.env`, Secrets, Tenants, Compose-Konfigurationen,
  TTS-Stimmen, drei Docker-Volumes, Image- und Health-Inventar.
- Der unveränderte SIP-Brücken-Dateisystem-Tar ist ein Hardlink des
  byte-identischen V2.8-Exports.
- Lokale Kopie:
  `F:\Bianca&Lisa TelefonKI\_snapshot-produktionsstand-v2.8.1\`
  mit Server-Schnappschuss, Git-Bundle und Prüfsummen.

## Rückweg

V2.8 bleibt der unmittelbare Rückweg für das Blessing-Paket:

```bash
cd /home/cursor/telefonki
docker tag telefonki:produktionsstand-v2.8-partial-20260915 telefonki:v1
docker compose up -d lisa bianca bianca-test studio
```

Für den Stand vor allen Blessing-Änderungen weiter V2.7 verwenden:
`telefonki:produktionsstand-v2.7-20260915`.
