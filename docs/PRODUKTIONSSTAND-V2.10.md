# Produktionsstand V2.10 — 15.09.2026, 19:55 Uhr

V2.10 verallgemeinert die ruhige Ein-Thema-/Ein-Frage-Regie über ALLE
Stimmen (Bianca/Ben, Patienten-Lisa, Kampagnen-Lisa) und baut die
deterministische Mehrfach-Absage („beide/alle absagen“) mit einer
Sammelbestätigung und schleifenfreiem Abschluss. Fachliche Antworten der
Mandanten bleiben byte-identisch — es fällt nur das Nachgeplauder hinter
einer Frage weg.

## Korrekturen

- Neue gemeinsame Ausgangswache `kern/gespraechsruhe.py` (W-RUHE): pro Zug
  höchstens EINE Frage, die Frage steht am Ende, danach folgt kein zweites
  Thema. Fail-safe wie fach_wache/zeiten_wache — hängt hinter der Frage ein
  Fakt (Ziffer, Datum, Wochentag, Uhrzeit, Notfall/112/116 117, SMS/Link,
  Euro), bleibt der ganze Text unangetastet.
- Eingehängt bei Bianca (`bianca/agent.py`, LLM- und Maschinen-Pfad),
  Patienten-Lisa (`lisa/agent.py`) und Kampagnen-Lisa (`lisa/bewerbung.py`).
  Notaus/Stufen `RUHE_WACHE=off|shadow|enforce` (Default enforce).
- Der LLM-Vorsatz während der semantischen Task-Auswahl entfällt jetzt bei
  ALLEN Mandanten, nicht mehr nur bei Blessing.
- Die dermatologische `_kompakt_fachfrage` ist ausdrücklich an
  `dermaMotivKlarheit` gebunden, nicht mehr an die allgemeine Ruhe-Regie.
- Lisas Stille-Verhalten angeglichen: erster Stups nur Presence, zweiter
  Stups nur die offene Frage — keine Wiederholung des ganzen Auftrags mehr.
- Neue deterministische Mehrfach-Absage (W-MEHRFACH-ABSAGE) in
  `bianca/verwalten.py`: „beide“, „alle“, „den ersten und den zweiten“
  werden VOR der Einzelauswahl erkannt, gemeinsam EINMAL rückbestätigt und
  erst nach klarem Ja nacheinander über `cancel-by-id` abgesagt. Teilfehler
  werden ehrlich benannt — nie „beide abgesagt“, wenn nur eines klappte.
- Prompt-Verträge von Bianca und Lisa tragen die Ein-Frage-/Ein-Thema-Regel
  explizit.

## Live-Koordinaten

- Code-Commit: `0e980aa`
- Git-Tag: `telefonki-produktionsstand-v2.10-2026-09-15`
- App-Image: `telefonki:produktionsstand-v2.10-20260915`
- Image-ID:
  `c4e36a417acbfd4cc55dc5b157a7f009da688dd860a3bde393928031981bf73c`
- Dieselbe Image-ID läuft in `bianca`, `lisa`, `bianca-test` und `studio`.
- `WRITE_LIVE=1`.
- SIP-Brücke, TTS, STT, Tunnel, Asterisk, Clara, Lena und MAS wurden nicht
  verändert oder neu gestartet.

## Abnahme

- Lokal: vollständige Suite — **2163 bestanden**, 0 fehlgeschlagen.
- Vor dem Neustart: keine SIP-Brückenaktivität und keine Bianca-/Lisa-
  Sitzung in den letzten Minuten; nur Health-Abfragen in den Logs.
- Health 8095/8096: grün.
- Live-`.env` unangetastet: `CLOUDFLARE_TELEFONKI_TOKEN`, `INTENT_NACHZUG`
  und `WRITE_LIVE=1` ausdrücklich geprüft.
- `tools/prod_smoke.py`: `ALLE WACHEN GRUEN` — lokal UND im deployten
  `bianca`-Container.
- Produktionsabnahme:
  `VERSION=v2.10 bash /tmp/ps_abnahme_lf.sh` — grün, einschließlich
  Blessing-Ruhe-V2.9-Schalter, Codeanker und Dock-Cache-Buster `b104`.

## Sicherungen

- Server:
  `/home/cursor/telefonki-backups/produktionsstand-v2.10-20260915/`
- Größe: rund 1,2 GB.
- Enthalten: Live-`.env`, Secrets, Tenants, aufgelöste Compose-
  Konfigurationen, Asterisk-Referenz-Dialplan, TTS-Stimmen, drei Docker-
  Volumes, Image- und Health-Inventar.
- App-, TTS-, STT-, Tunnel- und Cloudflared-Images tragen einen
  V2.10-Sicherungstag. Die unveränderten SIP-Brücken laufen aus ihren
  bisherigen, bereits gesicherten Dateisystemständen.
- Lokale Kopie:
  `F:\Bianca&Lisa TelefonKI\_snapshot-produktionsstand-v2.10\`
  mit Git-Bundle.

## Rückweg auf V2.9

```bash
cd /home/cursor/telefonki
docker tag telefonki:produktionsstand-v2.9-20260915 telefonki:v1
docker compose up -d lisa bianca bianca-test studio
```

Danach Health 8095/8096, `WRITE_LIVE=1` und `tools/prod_smoke.py` prüfen.
Wird zusätzlich der Blessing-Mandant von V2.9 gebraucht, den `tenants.tgz`
aus dem V2.9-Backup wie dort dokumentiert zurückspielen.
