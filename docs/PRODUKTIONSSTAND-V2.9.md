# Produktionsstand V2.9 — 15.09.2026, 20:53 Uhr

V2.9 macht Blessings Bianca nach dem Live-Anruf
`89daafaa50454560bff69c786a441296` ruhiger: pro Zug genau ein Thema,
relative Terminauswahlen bleiben erhalten und eine Nachricht für die Ärztin
wird als eigener, bestätigter Arbeitsschritt behandelt.

## Korrekturen

- Ein Task-Auswahl-Lauf spricht bei Blessing keinen freien LLM-Vorsatz mehr,
  bevor der sichere Aufgabenpfad feststeht.
- Ein Gruß mitten im Formular eröffnet kein zweites Thema, sondern hält nur
  die bereits offene Frage.
- „Hautkrebs-Screening“ wird am Telefon präzise als „Hautscreening“ statt
  als allgemeine „Kontrolle“ gesprochen.
- Korrigiert der Anrufer nur diese Ansage und bleibt die `motivId` gleich,
  bleiben der relativ gewählte früheste Slot, Kalender und Angebot erhalten.
  Ein echter Motivwechsel verwirft den Slot weiterhin.
- Die Vorbereitungsnachricht für die Ärztin ist wieder ein eigener Schritt
  vor der Buchung.
- Ein ausdrücklicher Notizwunsch nach der Buchung wird separat erfragt,
  einmal rückgelesen und erst nach einem klaren Ja per
  `masAppointmentNote` geschrieben.
- Der Blessing-Buchungsabschluss besteht nur noch aus Terminbestätigung,
  kurzer SMS-/Unterlageninformation und Verabschiedung. Es folgt keine
  offene „Sonst noch?“-Schleife.
- Alle verhaltensändernden Schalter sind mandantenscharf in
  `tenants/blessing.json`. Die Gegenprobe hält MedDent, Thaler und Rüther
  auf ihren bisherigen Pfaden.

## Live-Koordinaten

- Code-Commit: `7c0d0c3`
- Git-Tag: `telefonki-produktionsstand-v2.9-2026-09-15`
- App-Image: `telefonki:produktionsstand-v2.9-20260915`
- Image-ID:
  `ec64bbf0fb63bf3fa3ef3c1753fafa96d55f266848e723ea804cb4ad7693ad0a`
- Dieselbe Image-ID läuft in `bianca`, `lisa`, `bianca-test` und `studio`.
- `WRITE_LIVE=1`.
- SIP-Brücke, TTS, STT, Tunnel, Asterisk, Clara, Lena und MAS wurden nicht
  verändert oder neu gestartet.

## Abnahme

- Lokal: vollständige Suite — **2149 bestanden**, 0 fehlgeschlagen.
- Vor dem Neustart: in den letzten fünf Minuten keine SIP-Brückenaktivität
  und keine Bianca-/Lisa-Sitzung; nur Health-Abfragen in den Logs.
- Health 8095/8096: grün; alle vier App-Container `healthy`.
- Live-`.env` unangetastet:
  `CLOUDFLARE_TELEFONKI_TOKEN`, `INTENT_NACHZUG` und `WRITE_LIVE=1`
  ausdrücklich geprüft.
- `tools/prod_smoke.py`: `ALLE WACHEN GRUEN`.
- Abhängigkeitsfreie Probe im deployten `bianca-test`-Image:
  Frühestwahl, Hautscreening, Notiz-Rücklesen, Ja-vor-Schreiben und
  kompakter Abschluss — alle Wachen grün.
- `tools/_probe_ersatz_motiv_live.py`: alle Wachen grün; insbesondere bleibt
  Rüthers W-ERSATZ-MOTIV-Schutz unverändert.
- Produktionsabnahme:
  `VERSION=v2.9 STAMP=20260915 bash /tmp/v2-abnahme.sh` — grün,
  einschließlich V2.9-Schalter, Codeanker und Dock-Cache-Buster `b104`.

## Sicherungen

- Server:
  `/home/cursor/telefonki-backups/produktionsstand-v2.9-20260915/`
- Größe: rund 1,2 GB.
- Enthalten: Live-`.env`, Secrets, Tenants, aufgelöste
  Compose-Konfigurationen, Asterisk-Referenz-Dialplan, TTS-Stimmen, drei
  Docker-Volumes, Image- und Health-Inventar.
- App-, TTS-, STT-, Tunnel- und Cloudflared-Images tragen einen
  V2.9-Sicherungstag. Die unveränderten SIP-Brücken laufen aus ihren
  bisherigen, bereits gesicherten Dateisystemständen.
- Lokale Kopie:
  `F:\Bianca&Lisa TelefonKI\_snapshot-produktionsstand-v2.9\`
  mit Server-Schnappschuss, Git-Bundle und Prüfsummen.

## Rückweg auf V2.8.1

Für einen exakten Rückweg müssen App-Image **und** gemounteter
Blessing-Mandant gemeinsam zurück:

```bash
cd /home/cursor/telefonki
rm -rf /tmp/telefonki-v281-tenants
mkdir -p /tmp/telefonki-v281-tenants
tar xzf /home/cursor/telefonki-backups/produktionsstand-v2.8.1-20260915/tenants.tgz \
  -C /tmp/telefonki-v281-tenants
install -m 644 /tmp/telefonki-v281-tenants/tenants/blessing.json tenants/blessing.json
docker tag telefonki:produktionsstand-v2.8.1-20260915 telefonki:v1
docker compose up -d lisa bianca bianca-test studio
```

Danach Health 8095/8096, `WRITE_LIVE=1` und `tools/prod_smoke.py` prüfen.
