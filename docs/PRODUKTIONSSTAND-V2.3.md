# Produktionsstand V2.3 — 13.09.2026

Dieser Stand ist der **aktuelle Rückrollpunkt** für den Feldtest am
14.09.2026 in drei Praxen (MedDent, Thaler, Blessing). Bianca und Lisa laufen
damit live auf pickadoc1, Health grün, `tools/prod_smoke.py` = ALLE WACHEN
GRUEN.

Nachfolger von `telefonki-produktionsstand-v2.2-2026-09-13`. Mechanik (vier
Teile, Rückrollweg, TTS/STT-Sonderfall, SIP-Brücken-Layer) unverändert, siehe
`docs/PRODUKTIONSSTAND-V2.md`; was V2.2 mitbrachte, steht in
`docs/PRODUKTIONSSTAND-V2.2.md`. Hier nur: was V2.3 anders macht, die
Koordinaten, und **eine Falle im Sicherungsskript, die hier aufgefallen ist**.

## Was V2.3 gegenüber V2.2 mitbringt

Fünf Fixes aus der Feldtest-Analyse vom 13.09.2026 (Details je Fix in
`AGENTS.md`, Abschnitt „Fünf Feldtest-Fixes"):

| Nr. | Was | Commit |
| --- | --- | --- |
| 1 | Dokument-Hook (Rezept/Überweisung/AU) mandanten- und kontextscharf: bei laufender Buchung reißt die Job-Kette nicht mehr; Zahnpraxen bekommen die Zahn-Antwort, Blessing die Vorsprache-Regel | `220fb46` |
| 2 | Intent: „Ich habe eine Überweisung" = Terminwunsch (ANLEGEN), nur der ausdrückliche Dokument-WUNSCH bleibt ABGEBEN/Rückruf | `072f478` |
| 3 | Blessing: Dringlichkeit („schnell", „dringend") allein ist kein Notfall — erst mit Beschwerde greift die Sofortregel | `452b0f8` |
| 4 | W-EINWAND Fehltreffer eng gemacht (`_teil_ist_kein_einwand`, `arzt` vor `name`): kein Wert fliegt ohne echten Widerspruch | `7d8af31` |
| 5 | Notleine 6 → 8 Stupse; W-EINGEHEN-Bezüge und Einwand-Vorsätze werden beim Start vorgewärmt (kein TTS-Render im Zug) | `213aa36` |

Dazu `46aefe6` (Doku + Schaufenster) und dieses Handbuch.

## Koordinaten dieses Stands

| Teil | Wo |
| --- | --- |
| Git | Tag **`telefonki-produktionsstand-v2.3-2026-09-13`** (annotiert, sitzt auf `46aefe6`; Code-Stand der Fixes ist `213aa36` — der Tagname ist die Wahrheit, nicht der Hash) |
| App-Image | `telefonki:produktionsstand-v2.3-20260913` = **`9bb32ed3a5c9`** (912 MB, gebaut 13.09. 18:55 UTC) — bianca, lisa, bianca-test, studio |
| SIP-Brücke | `telefonki-sipbridge-1` läuft aus **`7f127afed684`** (= V2.2-App-Image; `sip_bridge/`, `Dockerfile`, `compose.yml` seit V2.2 unverändert, deshalb nicht neu gebaut) — gesichert als `telefonki:produktionsstand-v2.3-20260913-sipbridge` |
| TTS / STT | `tts-qwen3:produktionsstand-v2.3-20260913` (`388900ee2436`), `stt-parakeet-de:produktionsstand-v2.3-20260913` (`8ff19deb7d74`) — byte-identisch mit V2.0–V2.2 |
| Tunnel | `cloudflare/cloudflared:produktionsstand-v2.3-20260913`, `alpine:produktionsstand-v2.3-20260913` |
| Server-Schnappschuss | `/home/cursor/telefonki-backups/produktionsstand-v2.3-20260913/` (170 MB, `chmod 700`; `images.txt` trägt die Korrektur von 19:22 UTC, s. u.) |
| Lokale Kopie | `F:\Bianca&Lisa TelefonKI\_snapshot-produktionsstand-v2.3\` (gitignoriert) |

## Falle im Sicherungsskript (13.09.2026, 21:20 — behoben)

Beim Gegenprüfen der Koordinaten zeigte `telefonki:produktionsstand-v2.3-20260913`
auf **`7f127afed684` — das V2.2-Image**, nicht auf das Image mit den fünf
Fixes. Ursache: `tools/_produktionsstand_v2_server.sh` taggt je Container
`<repo>:<MARKE>`; die sipbridge (nicht neu gebaut) war der LETZTE Container
der Liste und überschrieb den Tag, den bianca zuvor korrekt gesetzt hatte.
Bei V2.0–V2.2 liefen alle App-Container aus demselben Image, darum fiel es
nie auf. **Ein „Rollback auf V2.3" hätte den Vor-Fix-Stand zurückgeholt.**

Behoben in drei Teilen:

1. Server: Tag von Hand auf `9bb32ed3a5c9` gesetzt, sipbridge-Image als
   `…-sipbridge` gesichert, Korrekturvermerk in `images.txt`.
2. `_produktionsstand_v2_server.sh`: zeigt `<repo>:<MARKE>` schon auf ein
   ANDERES Image, wird nicht überschrieben — der Abweichler bekommt
   `<repo>:<MARKE>-<container>` und eine ACHTUNG-Zeile. Der erste Container
   der Liste (bianca) ist der maßgebliche.
3. `_produktionsstand_v2_abnahme.sh`: harter Vergleich „App-Tag == Image der
   laufenden Bianca" (FEHLER-Zeile mit dem passenden `docker tag`-Befehl) plus
   HINWEIS für jeden App-Container, der aus einem anderen Image läuft.

## Zustand bei der Abnahme (13.09.2026, 20:56 Deploy / 21:25 Nachabnahme)

- Bianca 8096 `ok`, Lisa 8095 `ok`, `writeLive: true`, Mandant `meddent`
- Wächter im Container: `anrede_wache=enforce`, `abschied=True`,
  `einwand=enforce`, `eingehen=enforce`, `auto-resume=enforce`,
  Fix-Code verifiziert (`GESAMT_MAX = 8`, `_teil_ist_kein_einwand`,
  `ALLE_BEZUEGE` vorgewärmt), Dock-Cache-Buster `app.js?v=b82`
- `.env` unversehrt (`CLOUDFLARE_TELEFONKI_TOKEN`, `INTENT_NACHZUG`,
  `WRITE_LIVE=1` je einmal, Datei-Datum 12.09. 19:16)
- `tools/prod_smoke.py`: ALLE WACHEN GRUEN
- Test-Suite: **1433 bestanden, 11 rot** (V2.2: 1424/12) — Fix 1 hat einen
  Altfehler geschlossen; die 11 sind veraltete Erwartungen oder Umgebung
  (`audioop` unter Python 3.14), keiner anruferrelevant.
- Live-Proben im Container (kein Kalender-Write, `testNoWrite`): Buchung
  MedDent, Absage, Weiterleitung Petsas/Patrikis, Blessing-Rezeptwunsch,
  Thaler-Überweisung — grün. Zwei echte Befunde daraus stehen in der
  Analyse-Mail vom 13.09. an den Chef und sind **nicht** Teil von V2.3:
  - MedDent Doktor Nikolaou ist weder online buchbar noch verbindbar
    (Portal-Konfiguration, kein Code) — Bianca verspricht sonst „ich buche
    bei Doktor Nikolaou" und der Slot landet bei Petsas.
  - Öffnungszeiten Thaler/Blessing kommen aus dem LLM, weil
    `wissen._prompt_oeffnungszeiten` nur die Einzeiler-Form kennt
    (Portal-Fix: eine Zeile „Öffnungszeiten: …" im Standort-Prompt; Code-Fix
    ~30 Min, offen bis zum Go des Chefs).

## Rückweg

Wie in `docs/PRODUKTIONSSTAND-V2.md` beschrieben, mit `VERSION=v2.3`. Für die
Brücke gilt: `docker compose up -d sipbridge` startet sie aus `telefonki:v1`
(= `9bb32ed3a5c9`) — Code der Brücke identisch, das ist gewollt.
