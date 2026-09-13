# Produktionsstand V2.2 — 13.09.2026

Dieser Stand ist der **aktuelle Rückrollpunkt**: Bianca und Lisa laufen damit
live auf pickadoc1, Health grün, `tools/prod_smoke.py` = ALLE WACHEN GRUEN.

Nachfolger von `telefonki-produktionsstand-v2.1-2026-09-13`. Die Mechanik
(vier Teile, Rückrollweg, TTS/STT-Sonderfall, SIP-Brücken-Layer) ist
unverändert und steht ausführlich in `docs/PRODUKTIONSSTAND-V2.md` — hier
steht nur, was V2.2 ANDERS macht, plus die Koordinaten dieses Schnappschusses.

## Was V2.2 gegenüber V2.1 mitbringt

Chef-Vorgabe zu V2.1 (wörtlich): „denk daran auch korrekturen einzubauen wenn
eine angabe nicht stimmt … dass das dann zunächst korrigiert wird und nicht
übergangen wird … genau dafür brauchen wir, dass auf das gesagte eingegangen
wird … weil dann würde es endlich ein Gespräch!!! und kein Monolog … es muss
jedoch sichergestellt sein, dass der Job … nicht unterbrochen wird, bzw. dass
sie immer wieder zurückfindet … manchmal strandet sie obwohl wir wächter
haben."

| Kürzel | Was |
| --- | --- |
| W-EINWAND | Widerspruch gegen einen belegten Wert (Nummer, Versichertenstatus, Behandler, Besuchsgrund, Name) wird ZUERST korrigiert — ausgesprochen („Entschuldigung — dann korrigiere ich den Behandler.") und **nur dieses Feld** geräumt. Erkennung `kern/einwand.py`, Wirkung `flow._einwand_zug`. Notaus `EINWAND=off`. |
| W-EINGEHEN | Eine Antwort, die nur aus Fragesätzen besteht, bekommt einen kurzen inhaltsfreien Bezug voran („Verstehe." / „Gerne." / bei Beschwerde „Das tut mir leid."). Nie doppelt, nie auf eine Frage des Anrufers, nie mit neuem Inhalt. `kern/eingehen.py`. Notaus `EINGEHEN=off`. |
| Auto-Resume scharf | `hirn.auto_resume_modus()` liefert `enforce` als **Code**-Default (nicht `.env` — die wird beim Deploy überschrieben). Nach Korrektur oder Abschweifer läuft die Job-Kette an derselben Stelle weiter. Rückweg `HIRN_AUTO_RESUME=off`. |
| vorname_check / versicherung_check | Ein Kartei-Wert wird HINTERFRAGT statt still verwendet: „Ihr Vorname ist Maximilian, richtig?" → „Prima, dann habe ich Sie gefunden."; „… gesetzlich versichert habe ich hier stehen. Ist das noch aktuell?". Ein Nein räumt NUR dieses Feld. |
| Live-Proben im Image | `.dockerignore`/`Dockerfile`: `tools/_probe_*.py` fahren mit ins Image. Vorher lag nur `prod_smoke.py` drin und jede Session musste die in `AGENTS.md` dokumentierten Proben erst per `docker cp` hineinschieben. |

Details und alle Gegenproben: `AGENTS.md`, Abschnitte „Widerspruch wird zuerst
korrigiert (W-EINWAND)" und „Jeder Zug geht auf das Gesagte ein (W-EINGEHEN)".

## Koordinaten dieses Stands

| Teil | Wo |
| --- | --- |
| Git | Tag **`telefonki-produktionsstand-v2.2-2026-09-13`** (annotiert, Commit `f08a47e`) |
| App-Image | `telefonki:produktionsstand-v2.2-20260913` (`7f127afed684`, 912 MB) — bianca, lisa, bianca-test, studio, sipbridge |
| TTS / STT | `tts-qwen3:produktionsstand-v2.2-20260913` (`388900ee2436`), `stt-parakeet-de:produktionsstand-v2.2-20260913` (`8ff19deb7d74`) — byte-identisch mit V2.1/V2.0, dort wurde nichts gebaut |
| Tunnel | `cloudflare/cloudflared:produktionsstand-v2.2-20260913`, `alpine:produktionsstand-v2.2-20260913` |
| Server-Schnappschuss | `/home/cursor/telefonki-backups/produktionsstand-v2.2-20260913/` (**169 MB**, `chmod 700`) |
| Lokale Kopie | `F:\Bianca&Lisa TelefonKI\_snapshot-produktionsstand-v2.2\` (gitignoriert), Git-Bundle `bianca-lisa-produktionsstand-v2.2.bundle` |

Der Schnappschuss ist diesmal klein (V2.1: 1,3 GB), weil vor den Feldtests
alle Gespräche und Ergebnisse geleert wurden — das `.data`-Volume trägt nur
noch 510 Einträge (56 MB). Der TTS-Platten-Cache (120 MB) ist der dicke Teil.

Neu geschrieben wird beides mit den bekannten Skripten; **LF-Zeilenenden
beachten** — PowerShell schreibt CRLF, und `ssh "bash -s"` bricht daran ab
(13.09.2026 erlebt, `set: -: invalid option`). Deshalb erst konvertieren:

```powershell
python -c "from pathlib import Path; p=Path('tools/_produktionsstand_v2_server.sh'); Path('_ps.sh').write_bytes(p.read_text(encoding='utf-8').replace(chr(13)+chr(10),chr(10)).encode())"
scp _ps.sh pickadoc1:/tmp/_ps.sh; ssh pickadoc1 "VERSION=v2.2 bash /tmp/_ps.sh"
```

`tools/_produktionsstand_v2_abnahme.sh` nimmt jetzt ebenfalls `VERSION` an
und prüft zusätzlich `einwand`, `eingehen` und `auto_resume` im Container.

## Zustand bei der Abnahme (13.09.2026, 17:30)

- Bianca 8096 `ok`, Lisa 8095 `ok`, `writeLive: true`, Mandant `meddent`
- Brücke: „bruecke bereit auf :40101 mode=inbound -> http://bianca:8096"
- `tools/prod_smoke.py`: ALLE WACHEN GRUEN
- Wächter im Container: `anrede_wache=enforce`, `abschied=True`,
  `einwand=enforce`, `eingehen=enforce`, `auto-resume=enforce`,
  Dock-Cache-Buster `app.js?v=b81`
- `.env` unversehrt: `CLOUDFLARE_TELEFONKI_TOKEN`, `INTENT_NACHZUG`,
  `WRITE_LIVE=1` je einmal vorhanden, Datei-Datum unverändert 12.09. 19:16
- Test-Suite: **1424 bestanden, 12 rot** (V2.1: 1324/12). Es sind DIESELBEN
  12 wie in V2.1 — gegengeprüft mit `EINWAND=off EINGEHEN=off
  HIRN_AUTO_RESUME=off`: identische Liste, die neuen Wächter verursachen
  also keinen davon. Warum sie offen sind, steht in
  `docs/PRODUKTIONSSTAND-V2.md` („Zustand bei der Abnahme").
- Live-Probe im Container: `tools/_probe_einwand_live.py` — Teil A
  (Nummer/Behandler/Versicherung bestritten: nur das bestrittene Feld weg,
  danach „Alles klar — privat versichert, notiert. Wann passt es Ihnen am
  besten …?"), Teil B über die echte Dock-API („Alles klar. Waren Sie denn
  schon einmal bei uns in der Praxis?" — und KEIN Vorsatz, wo die Antwort
  schon einen eigenen Bezug trägt).
- Die älteren Proben laufen unverändert: `_probe_abschied_live.py`,
  `_probe_langgespraech.py`, `_probe_hallo.py`.

## Achtung beim Rückrollen auf V2.1 oder früher

V2.2 hat `Dockerfile` und `.dockerignore` angefasst (`COPY tools/ tools/`).
Ein Rollback über die **Sicherungs-Images** ist davon unberührt — nur wer neu
BAUT, muss den passenden Quellstand auschecken, sonst fehlen die Proben im
Image (oder es landet mehr in `tools/` als gewollt).
