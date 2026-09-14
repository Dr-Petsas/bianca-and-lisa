# Produktionsstand V2.6 — 14.09.2026, 12:10 Uhr (Einfrierpunkt VOR den Analyse-Fixes)

Dieser Stand ist der **Rückrollpunkt vor der Fix-Phase vom 14.09.2026**. Chef
(12:02 Uhr): „mach bitte vor den anstehenden Problemfixes eine vollständige
Sicherung, frier den stand der dinge ein mit allen dateien die sonst nicht auf
github landen und allen server einstellungen und snapshots. damit wir hier her
leicht zurückfinden anytime." Er ist V2.5 plus GENAU EIN Fix:
**W-TELEFON-ZULETZT** (Commit `f92951f` — Handynummer als letzter Schritt vor
der SMS, kein Eisbrecher vor dem Anliegen). Mechanik (vier Teile, Rückrollweg,
TTS/STT-Sonderfall, SIP-Brücken-Layer) unverändert, siehe
`docs/PRODUKTIONSSTAND-V2.md`; alles andere wie in `docs/PRODUKTIONSSTAND-V2.5.md`.

## Was auf diesem Stand LIVE ist (seit ~08:40 Uhr)

| Änderung gegenüber V2.5 | Commit |
| --- | --- |
| W-TELEFON-ZULETZT: `gehirn.telefon_frage` als EINE Stelle für Nummer/SMS-Ziel, `flow._telefon_tor` vor `_buchen`, `telefonPflicht`-Eskalation ohne Schleife, kein „wie geht es Ihnen?" wenn „Termin" im ersten Satz steht, Re-Greeting-Wache mit Wortstämmen, Frage-Gate kennt die Nebensatz-Zeitfrage | `f92951f` |
| Dock `bianca_web/app.js` Cache-Buster **b86**, Schaufenster-Eintrag | `f92951f` |
| Abnahme-Skript prüft zusätzlich Fach-Wache, Qwen-Korrektor, Standort-Zeiten, `motive.telefon_tauglich`, `_telefon_tor` | dieser Stand |

Abnahme nach dem Deploy (08:4x Uhr): Suite 1619/0, `prod_smoke` grün,
Nachstellung des Anrufs e7191c7e im Container grün, Feldprobe 70/70 live;
die 40 Testsitzungen wurden danach wieder entfernt.

## Warum jetzt eingefroren wird

Der Vormittag war reine Analyse (Chef 10:31: „wir werden den ganzen tag nur
analysieren, ohne code anzupacken"). Sieben Live-Anrufe sind ausgewertet
(`9dd61a59`, `3baead87`, `da746a65`, `48d3ac3f`, `5aa87268`, `984282e3`,
dazu `e7191c7e` vom Morgen). Die daraus folgenden Fixes (Suchfenster 6 Monate,
Verbinden nur auf echten Wunsch, Qwen-Korrektor ohne Namen/Job-Wörter,
Bestandsfrage „Termin vergessen", Fakten-Wache bei Teil-Negativaussagen,
„Oh."/„Puff." nicht als Stille, Rückruf-Notiz ohne Nummer, …) setzen auf
DIESEM Stand auf. Geht dabei etwas schief, ist V2.6 der Punkt, zu dem
zurückgerollt wird — nicht V2.5 (dann käme der Handynummer-Fehler zurück).

## Koordinaten dieses Stands

| Teil | Wo |
| --- | --- |
| Git | Tag **`telefonki-produktionsstand-v2.6-2026-09-14`** (annotiert) auf dem Handbuch-Commit; Code-Stand `f92951f` |
| App-Image | `telefonki:produktionsstand-v2.6-20260914` = **`c04b16aada71`** — bianca, lisa, bianca-test, studio (Abnahme: identisch mit der laufenden Bianca) |
| SIP-Brücke | `telefonki-sipbridge-1` / `-lisa-1` aus `060c28e7501a` (läuft als `telefonki:v1`, Layer nicht mehr taggbar) — deshalb **erstmals als Tar gesichert**: `image-sipbridge-telefonki-v1.tar` (238 MB) im Server-Schnappschuss; `sip_bridge/` seit `6a1f252` unverändert |
| TTS / STT / Tunnel | `tts-qwen3`, `stt-parakeet-de`, `cloudflare/cloudflared`, `alpine` jeweils `:produktionsstand-v2.6-20260914` — byte-identisch mit V2.4/V2.5 |
| Server-Schnappschuss | `/home/cursor/telefonki-backups/produktionsstand-v2.6-20260914/` (**552 MB**, `chmod 700`): Live-`.env`, `secrets.tgz`, `tenants.tgz`, `compose.yml` + aufgelöste Compose-Konfiguration, Compose von `tts_serve`/`stt_serve` (dort gibt es KEINE `.env`), drei Docker-Volumes (`data` 220 MB, `klang` 120 MB, `berichte`), `images.txt`, `inventar.txt`, `asterisk-live/` |
| Lokale Kopie | `F:\Bianca&Lisa TelefonKI\_snapshot-produktionsstand-v2.6\` (gitignoriert): kompletter Server-Schnappschuss + `bianca-lisa-produktionsstand-v2.6.bundle` (alle Refs) + `lokal/` (Dev-`.env`, komplettes `.data/`: Sitzungen, `praxis_notizen.jsonl`, Proben, TTS-Cache, Fernsteuerungs-Token) + `parakeet-qwen/` + `windows-netz.txt` |
| Parakeet-Qwen (3060-STT, `C:\Parakeet-Qwen`) | `parakeet-qwen.bundle` (alle Refs, HEAD `1961d08`), `uncommitted-tracked.patch` + `git-status.txt` (24 nicht committete Einträge!), `arbeitsbaum-ohne-modelle.zip` (auch die untracked Dateien), `docker-inspect.json` + `docker-images.txt` (laufend: `parakeet-qwen-final:clean-20260911` = `de4fbe1aa35a`, 42,9 GB — NICHT als Tar; Modell aus dem HF-Cache) |

Live-Schalter auf pickadoc1 (aus der gesicherten `.env`): `WRITE_LIVE=1`,
`HIRN_AUTO_RESUME=enforce`, `FAKTEN_WACHE=enforce`, `ANLIEGEN_ART=enforce`,
`INTENT_NACHZUG=0`, `TTS_STREAM=0`, `STT_WHISPER_BASE=` (leer),
`STT_QWEN_FINAL_BASE=http://192.168.0.173:8223,http://192.168.0.167:8223`,
`STT_QWEN_GRACE_S=0.25`, `STT_QWEN_WAIT_S=4.0`, `BRIDGE_LEAD_MS=400`,
`ASTERISK_SSH=root@212.132.104.205`.

## Asterisk — was gesichert werden konnte und was nicht

- Der **live** Asterisk ist `212.132.104.205` (Ziel des Tunnel-Containers und
  der Server-`.env`). Für ihn gibt es von pickadoc1 aus **keinen Shell-Zugang**:
  der Tunnel-Key ist auf `tunnel-only` beschnitten, der `asterisk-cli-key` aus
  `secrets/` wird dort nicht angenommen. Der Dialplan liegt deshalb NUR als
  Referenzkopie vor: `sip_bridge/extensions_bianca.conf` (Repo) bzw.
  `extensions_bianca.conf` im Schnappschuss. Wer den Live-Dialplan liest oder
  ändert, braucht den Zugang des Kollegen (Asterisk-Betrieb).
- Der **alte** Strato-Asterisk `87.106.34.137` ist mit dem `asterisk-cli-key`
  weiterhin erreichbar; sein `extensions_bianca.conf` ist byte-identisch mit
  der Repo-Kopie. Dessen Stand liegt unter
  `asterisk-live/87.106.34.137-alt/` (Dialplan, `extensions.conf`, Backup-
  Liste, `dialplan show`-Ausgabe, `pjsip show endpoints`).

## Rückweg

- **Auf V2.6 (dieser Stand):** `docker tag telefonki:produktionsstand-v2.6-20260914 telefonki:v1`
  + `docker compose up -d bianca lisa bianca-test studio`. Brücke bei Bedarf:
  `docker load -i image-sipbridge-telefonki-v1.tar` (liefert `060c28e7501a`).
  Code: `git checkout telefonki-produktionsstand-v2.6-2026-09-14`.
- **Volumes/Einstellungen:** wie in `docs/PRODUKTIONSSTAND-V2.md` (Tar in das
  Volume zurückspielen, `.env`/`tenants/`/`secrets/` aus dem Schnappschuss).
- **Auf V2.5:** nur wenn W-TELEFON-ZULETZT selbst Schaden anrichtet — dann kehrt
  die zu frühe Handynummer-Frage (Anruf e7191c7e) zurück.

## Offen geblieben (Stand der Analyse, wird ab jetzt bearbeitet)

- **Suchfenster:** die CF liefert je Abruf höchstens 20 Zeiten (`maxSlots`),
  Bianca ruft ohne Startdatum ab → faktisch nur die nächsten Tage; Wünsche
  „im Oktober/in drei Wochen" laufen ins Leere („kein freier Termin"). Chef:
  Fenster auf **6 Monate**.
- **Thaler `allowOnlineBooking=false`** für Kontrolle/Neupatient (Portal- bzw.
  CF-Entscheid, nicht in diesem Repo) — wie in V2.5.
- Die weiteren Cluster aus der Anruf-Analyse (siehe Fix-Commits nach diesem Tag).
