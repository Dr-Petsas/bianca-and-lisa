# Produktionsstand V2.5 — 14.09.2026, 06:50 Uhr (Hotfix auf V2.4)

Dieser Stand ist der **aktuelle Rückrollpunkt** für den Feldtest am
14.09.2026 (MedDent, Thaler, Blessing). Er ist V2.4 plus GENAU EIN Fix:
**W-MOTIV-KONSISTENT** (Commit `a0bc84b`). Mechanik (vier Teile, Rückrollweg,
TTS/STT-Sonderfall, SIP-Brücken-Layer) unverändert, siehe
`docs/PRODUKTIONSSTAND-V2.md`; alles andere wie in
`docs/PRODUKTIONSSTAND-V2.4.md`.

## Warum ein eigener Stand

Erster echter MedDent-Anruf des Morgens (06:0x, Chef: „die buchung klappt
nicht"): der Anrufer sagte „Ich hab Schmerzen", bekam Zeiten angeboten, sagte
Ja — und hörte nur „Termin ist gerade weg". Ursache im Werkzeug-Ledger:
`getFreeTimeSlots` lief mit **KCH Kontrolluntersuchung** (Ersatz-Motiv, weil
das gemappte Motiv keine Zeiten lieferte), `masBookAppointment` aber mit dem
**Terminal-Pseudo-Motiv `selfCheckinEmergencyVisitMotive`**
(`allowOnlineBooking=false`) → CF 400 „The slot is not available.". Gesucht
und gebucht wurde mit zwei verschiedenen Motiven; das Pseudo-Motiv gehört gar
nicht ans Telefon.

## Der Fix (a0bc84b)

| Baustein | Wo |
| --- | --- |
| Terminal-Pseudo-Motiv fliegt aus JEDEM Katalog (Live-Abruf, Sitzung, Mandanten-Liste) | `kern/motive.py` (`telefon_tauglich`, `_telefon_katalog`) |
| Buchbare Motive über die ganze Mapping-Kette zuerst (`allowOnlineBooking` ≠ false) | `bianca/gehirn.motiv_fuer_kalender`, `besuchsgrund.katalog_exakt` |
| Findet erst das Ersatz-Motiv Zeiten, wird GENAU damit gebucht (Pin im Sammler `motivFallback`, verfällt bei neuem Grund/Kalender) | `kern/calendar.find_slots_behandler` (`motivOriginal`), `gehirn.motiv_fallback_merken`, `flow._laden`, `hintergrund.vorrat_anstossen` |
| Wunsch des Anrufers landet als Terminnotiz („Gewünscht: … — eingetragen als …, bitte Besuchsgrund und Dauer prüfen") | `flow._buchen` |
| 12 Regressionen | `tests/test_motiv_konsistent.py` |

## Abnahme dieses Stands (14.09.2026, 06:30–06:50 Uhr)

| Prüfung | Ergebnis |
| --- | --- |
| Unit-Suite inkl. `tests/test_motiv_konsistent.py` | grün (12 neue) |
| `tools/prod_smoke.py` im Live-Container | ALLE WACHEN GRUEN |
| **Live-Nachstellung des Fehlanrufs** (Schmerzen → Petsas, Neupatient, `testNoWrite`) gegen den deployten Container | Suche UND Sammler auf `KCH akute Beschwerden/Notfall` (`6QHfsWALBRSyzBBbVCto`, 20 Zeiten), kein Pseudo-Motiv, kein Kontrolle-Fallback nötig, `book_slot` dryRun ok, Ansage „hätte ich jetzt eingetragen" — 8/8 grün |
| Feldprobe (20 Szenarien, 3 Praxen, Audio-Zug) nach dem Deploy wiederholt | **68/68 grün** (54 s) |
| Abnahme-Skript `VERSION=v2.5` | App-Tag = laufende Bianca (`00f8b9c73f87`), Dock-Cache-Buster `b85`, `.env` unangetastet, Brücke bereit |

## Koordinaten dieses Stands

| Teil | Wo |
| --- | --- |
| Git | Tag **`telefonki-produktionsstand-v2.5-2026-09-14`** (annotiert) auf dem Handbuch-Commit; Code-Stand `a0bc84b` |
| App-Image | `telefonki:produktionsstand-v2.5-20260914` = **`00f8b9c73f87`** — bianca, lisa, bianca-test, studio (gegen die laufende Bianca geprüft: identisch) |
| SIP-Brücke | unverändert V2.4: `telefonki-sipbridge-1` aus `060c28e7501a`; `sip_bridge/` seit `6a1f252` nicht angefasst |
| TTS / STT / Tunnel | `tts-qwen3`, `stt-parakeet-de`, `cloudflare/cloudflared`, `alpine` jeweils `:produktionsstand-v2.5-20260914` — byte-identisch mit V2.4 |
| Server-Schnappschuss | `/home/cursor/telefonki-backups/produktionsstand-v2.5-20260914/` (187 MB, `chmod 700`) |
| Lokale Kopie | `F:\Bianca&Lisa TelefonKI\_snapshot-produktionsstand-v2.5\` (gitignoriert; Bundle + Server-Schnappschuss) |

Live-Schalter auf pickadoc1 unverändert gegenüber V2.4 (`WRITE_LIVE=1`,
`HIRN_AUTO_RESUME=enforce`, `FAKTEN_WACHE=enforce`, `ANLIEGEN_ART=enforce`,
`INTENT_NACHZUG=0`, `STT_QWEN_FINAL_BASE=…173,…167`).

## Rückweg

- **Auf V2.5 (dieser Stand):** `docker tag telefonki:produktionsstand-v2.5-20260914 telefonki:v1`
  (bzw. den in `compose.yml` genutzten Tag) + `docker compose up -d bianca lisa bianca-test studio`.
- **Auf V2.4 (ohne Motiv-Fix):** dasselbe mit `telefonki:produktionsstand-v2.4-20260914` — dann
  kommt der 06:0x-Fehler zurück (Schmerzen-Buchung scheitert bei MedDent), also nur, wenn der
  Fix selbst Schaden anrichtet.

## Offen geblieben (nicht in diesem Stand lösbar)

- **Thaler:** „Kontrolle" und „Neupatient" stehen im Portal auf `allowOnlineBooking=false`; die CF
  (`getFreeTimeSlots`/`isSlotAvailable`) liefert dafür keine Zeiten — auch am Telefon. Folge:
  0 Zeiten → ehrliche Rückruf-Notiz statt Termin (kein falsches „gebucht", aber auch kein
  Termin). Lösung liegt im Portal (Online-Buchung für die sechs Telefon-Motive freischalten)
  oder in der CF (Telefon-Buchung vom Online-Schalter entkoppeln — eigener Entscheid).
