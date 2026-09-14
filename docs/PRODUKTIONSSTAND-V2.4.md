# Produktionsstand V2.4 — 14.09.2026, 02:10 Uhr

Dieser Stand ist der **aktuelle Rückrollpunkt** für den Feldtest am
14.09.2026 in drei Praxen (MedDent, Thaler, Blessing). Er trägt die neun
Chef-Punkte vom Abend des 13.09. plus den Thaler-Kalender-Zusatzfund.
Nachfolger von `telefonki-produktionsstand-v2.3-2026-09-13`; Mechanik (vier
Teile, Rückrollweg, TTS/STT-Sonderfall, SIP-Brücken-Layer) unverändert, siehe
`docs/PRODUKTIONSSTAND-V2.md`. Der Vorgänger V2.3 bleibt der Rückweg, falls
die Nacht-Wächter im Feld Fehltreffer liefern.

## Abnahme dieses Stands (14.09.2026, 01:10–02:20 Uhr)

| Prüfung | Ergebnis |
| --- | --- |
| Unit-Suite (`python -m pytest tests -q --ignore=tests/baukasten`) | 1606 grün, 0 rot |
| `tools/prod_smoke.py` im Live-Container | ALLE WACHEN GRUEN |
| Feldprobe gegen den deployten Container (20 Szenarien, 3 Praxen, `testNoWrite`) | 68/68 grün |
| Audio-Zug (TTS-Render → `/api/listen`, echtes Ohr) | Parakeet gewinnt, Qwen 1,49 s später wortgleich, Anrufliste zeigt `stt.winner` je Zug |
| Kalender-Merge Thaler live (lesend) | `raeume pzr` → Prophylaxe (`xTz59…`), `raeume behandlung` → Eva Thaler |
| Health 8095 / 8096 | ok, `WRITE_LIVE=1`, STT „Parakeet (lokal) + Qwen3-ASR parallel (3060)“ |
| Daten | Anrufe / Sitzungen / Notizen auf 0 (Feldprobe-Testsitzungen wieder gelöscht) |

## Was V2.4 gegenüber V2.3 mitbringt

| Punkt | Was | Commit |
| --- | --- | --- |
| 1 | Behandler-Sperre je Mandant (`kern/behandler_sperre.py`, meddent: Nikolaou) — Buchung UND Verbinden mit ehrlicher Ansage; greift auch ohne DB-Kalender | `7af993a`, `296776d` |
| 2 + 9 | Verbinden-Whitelist (`verbindenErlaubt`, meddent: Petsas/Patrikis); Rezeption/Mitarbeiter nie durchstellen; Thaler/Blessing kein Durchstellen | `7af993a` |
| 9 | W-TRANSFER-RUECKKEHR: nach Verbinde-Versuch dieselbe Sitzung fortsetzen (Brücke + `/api/start`) | `6a1f252` |
| 3 | W-STANDORT: Öffnungszeiten aus den Standort-Einstellungen (Firestore) im Praxis-Prompt | `227117d` |
| 5 | W-QWEN-KORREKTOR: Qwen3-ASR als asynchrones Zweit-Ohr, `STT_QWEN_FINAL_BASE` mit zwei Karten (.173/.167), Engine-Anzeige je Zug im Manifest | `04224bb` |
| 6 | Notdienst-Wache: 116 117 nur mit Blessing-Notfallregel | `6ae9e78` |
| 8 | W-FACH-WACHE: kein Zahn-Inhalt beim Hautarzt (Eingang `fremdes_anliegen` + Ausgang) | `59f9f9a`, `296776d` |
| — | Suite auf 0 rot; Feldprobe-Fixes (Ja/Versicherungswort kein Vorname, M.Sc. kein Nachname, einzelner Vorname wird geerntet) | `d6dd941`, `296776d`, `2ccffec` |
| + | **Thaler-Kalender-Merge:** Firestore-Funktionsname „Prophylaxe“ schlägt den CF-Besitzernamen „Franziska Schmidt“ — sonst landete jede Zahnreinigung in Eva Thalers Kalender | `8c96ca8` |

## Koordinaten dieses Stands

| Teil | Wo |
| --- | --- |
| Git | Tag **`telefonki-produktionsstand-v2.4-2026-09-14`** (annotiert) und `stabil-2026-09-14`, beide auf `8c96ca8` |
| App-Image | `telefonki:produktionsstand-v2.4-20260914` = **`6305bd4450a7`** — bianca, lisa, bianca-test, studio (gegen die laufende Bianca geprüft: identisch) |
| SIP-Brücke | `telefonki-sipbridge-1` läuft aus `060c28e7501a` (Build 14.09. ~01:10 mit W-TRANSFER-RUECKKEHR; Layer nicht mehr taggbar). Rollback der Brücke = `docker compose build sipbridge` aus dem Git-Tag — `sip_bridge/` ist seit `6a1f252` unverändert |
| TTS / STT | `tts-qwen3:produktionsstand-v2.4-20260914` (`388900ee2436`), `stt-parakeet-de:produktionsstand-v2.4-20260914` (`8ff19deb7d74`) — byte-identisch mit V2.0–V2.3 |
| Tunnel | `cloudflare/cloudflared:produktionsstand-v2.4-20260914`, `alpine:produktionsstand-v2.4-20260914` |
| Server-Schnappschuss | `/home/cursor/telefonki-backups/produktionsstand-v2.4-20260914/` (169 MB, `chmod 700`) |
| Lokale Kopie | `F:\Bianca&Lisa TelefonKI\_snapshot-produktionsstand-v2.4\` (gitignoriert; Bundle + Server-Schnappschuss) |

## Live-Schalter auf pickadoc1 zum Zeitpunkt des Stands

`WRITE_LIVE=1`, `HIRN_AUTO_RESUME=enforce`, `FAKTEN_WACHE=enforce`,
`ANLIEGEN_ART=enforce`, `INTENT_NACHZUG=0`, `STT_WHISPER_BASE=` (leer),
`STT_QWEN_BASE=` (leer), `STT_QWEN_FINAL_BASE=http://192.168.0.173:8223,http://192.168.0.167:8223`.
Die Code-Defaults `EINWAND`, `EINGEHEN`, `FRAGE_GATE`, `ANREDE_WACHE` stehen
auf `enforce` (nicht in der `.env`). Schneller Teil-Rückweg je Wächter:
Schalter in die Server-`.env` (`…=off`) + `docker compose up -d bianca lisa`,
kein Build.

## Bekannte offene Risiken (Stand 02:30, aus dem Nachtbericht)

1. Eine GPU für vLLM 35B + TTS + STT (31,4/32,6 GB), TTS-Container mit EINEM
   Lock — drei gleichzeitige Anrufe warten aufeinander. Kein Lasttest.
2. Verhörer bei Namen: Qwen korrigiert nur den NÄCHSTEN Zug; ohne Dev-Rechner
   hört Parakeet allein.
3. Acht Wächter im enforce-Modus ohne Live-Stunde.
4. Thaler-PZR → Prophylaxe nur lesend bewiesen; erste echte Buchung prüfen.
