# Produktionsstand V2.7 — 15.09.2026, 16:16 Uhr (Einfrierpunkt VOR den Blessing-Fixes)

Dieser Stand ist der **Rückrollpunkt vor der Blessing-Korrektur** (Namen halten,
Aufgaben treffen, erst danach knapper Mund). Chef: zuerst alles sichern,
einschließlich Server-Einstellungen, die nicht auf GitHub landen.

Er ist V2.6 plus der am 15.09. **bereits live** stehende Nachmittag:
Rüther/Ben, W-STIMME-MANDANT, W-AKTE-HANDY, W-BUCHUNG-BEWEIS, W-ZEITEN-WACHE.
Mechanik (vier Teile, Rückrollweg, TTS/STT-Sonderfall) unverändert, siehe
`docs/PRODUKTIONSSTAND-V2.md`.

## Zwei Ebenen — nicht verwechseln

| Ebene | Stand | Bedeutung |
| --- | --- | --- |
| **Live-Image** auf pickadoc1 | `telefonki:produktionsstand-v2.7-20260915` = **`cf97be2244d9`** | Das, was gerade Anrufe hält. Enthält W-ZEITEN-WACHE, Rüther, Handy-Akte, Buchungsbeweis. **Nicht** darin: W-ERSATZ-MOTIV (`a325401`/`6d733c9`). |
| **Git-Tag** | `telefonki-produktionsstand-v2.7-2026-09-15` | Lokaler Code inkl. der zwei noch nicht deployten Ersatz-Motiv-Commits und dem Blessing-Befund. Rollback der **Leitung** immer über das Image, nicht über ein frisches Build aus HEAD. |

Dock-Cache-Buster live: **b96**. `prod_smoke`: ALLE WACHEN GRUEN. `.env` unangetastet
(letzter Schreibzeitpunkt 13.09. 23:13). Kein Container wurde für diesen
Schnappschuss gestoppt.

## Was auf diesem Stand LIVE ist (gegenüber V2.6)

| Änderung | Commit |
| --- | --- |
| W-BUCHUNG-BEWEIS: Rücklese ohne Namensraten, zweiter Weg über `patientId` | `6f4c6d8` |
| W-AKTE-HANDY: bestätigte Handynummer in die Akte, sonst kein Termin | `343121b` |
| W-STIMME-MANDANT: Name/Genus/Stimme je Mandant (Ben bei Rüther) | `e619264` |
| DID +49 211 54244160 = Rüther an die Brücke | `4426841` |
| Agent-Name aus der DB durchreichen | `a8224a7` |
| W-ZEITEN-WACHE: keine erfundenen Öffnungszeiten | `c0cd9e8` + Nachzüge |
| Thaler-Weg aus belegter Adresse; Rüther-Portal-Befund | `c798486` / `6b04bd6` |
| Stimm-Referenzen im Produktionsschnappschuss (`tts-stimmen.tgz`) | `f462633` |

**Nur im Git, noch nicht im Live-Image:** W-ERSATZ-MOTIV (Buchbarkeit aus dem
Sitzungs-Katalog, Motivname nicht vorlesen). Blessing-Befund
`docs/BEFUND-BLESSING-GESCHWAETZ-2026-09-15.md`.

## Koordinaten dieses Stands

| Teil | Wo |
| --- | --- |
| Git | Tag **`telefonki-produktionsstand-v2.7-2026-09-15`** (annotiert) auf dem Handbuch-Commit |
| App-Image | `telefonki:produktionsstand-v2.7-20260915` = **`cf97be2244d9`** — bianca, lisa, bianca-test, studio (Abnahme: identisch mit der laufenden Bianca) |
| SIP-Brücke | `telefonki-sipbridge-1` aus `eb97b3d3e0e7` (Layer aufgeräumt: `docker tag`/`commit`/`save` scheitern). Deshalb **Dateisystem-Export** `container-sipbridge-filesystem.tar` (616 MB). Lisa-Brücke weiter `060c28e7501a`. Rollback der App-Brücke: Image-Tag der App **oder** Rebuild aus `sip_bridge/` + `extensions_bianca.conf` im Schnappschuss. |
| TTS / STT / Tunnel | `tts-qwen3`, `stt-parakeet-de`, `cloudflare/cloudflared`, `alpine` jeweils `:produktionsstand-v2.7-20260915` — byte-identisch mit V2.6 |
| Server-Schnappschuss | `/home/cursor/telefonki-backups/produktionsstand-v2.7-20260915/` (**1,6 GB**, `chmod 700`): Live-`.env`, `secrets.tgz`, `tenants.tgz`, Compose + aufgelöste Compose, TTS/STT-Compose, **`tts-stimmen.tgz`** (Bianca + Ben), drei Docker-Volumes (`data` 867 MB, `klang` 115 MB, `berichte`), SIP-Dateisystem-Tar, `images.txt`, `inventar.txt`, `asterisk-live/` |
| Lokale Kopie | `F:\Bianca&Lisa TelefonKI\_snapshot-produktionsstand-v2.7\` (gitignoriert): kompletter Server-Schnappschuss + Git-Bundle + `lokal/` (Dev-`.env`, komplettes `.data/`) + `parakeet-qwen/` + `windows-netz.txt` |
| Parakeet-Qwen (3060-STT, `C:\Parakeet-Qwen`) | Bundle + uncommitted Patch + Arbeitsbaum-Zip ohne Modelle. Laufend: `parakeet-qwen-final:clean-20260911`, Port 8223. 42-GB-Image **nicht** als Tar. |

Live-Schalter auf pickadoc1 (aus der gesicherten `.env`): `WRITE_LIVE=1`,
`HIRN_AUTO_RESUME=enforce`, `FAKTEN_WACHE=enforce`, `ANLIEGEN_ART=enforce`,
`INTENT_NACHZUG=0`, `TTS_STREAM=0`, `STT_WHISPER_BASE=` (leer),
`STT_QWEN_FINAL_BASE=http://192.168.0.173:8223,http://192.168.0.167:8223`,
`STT_QWEN_GRACE_S=0.25`, `STT_QWEN_WAIT_S=4.0`, `BRIDGE_LEAD_MS=400`,
`ASTERISK_SSH=root@212.132.104.205`.

## Asterisk

Unverändert zu V2.6: der **live** Asterisk `212.132.104.205` hat von pickadoc1
aus keinen Shell-Zugang. Dialplan nur als Referenzkopie
`extensions_bianca.conf` (im Schnappschuss; enthält DID 4160). Wer den
Live-Dialplan liest oder ändert, braucht den Zugang des Kollegen.

## Rückweg

- **Auf V2.7 (dieser Stand, Live-Image):** `docker tag telefonki:produktionsstand-v2.7-20260915 telefonki:v1`
  + `docker compose up -d bianca lisa bianca-test studio`. Brücke bei Bedarf
  aus `sip_bridge/` neu bauen (kein loadbares Image, Layer weg) oder den
  Dateisystem-Tar nur zur Inspektion öffnen.
- **Volumes/Einstellungen:** wie in `docs/PRODUKTIONSSTAND-V2.md` (Tar in das
  Volume zurückspielen, `.env`/`tenants/`/`secrets/` aus dem Schnappschuss).
  ACHTUNG: Volume-Restore überschreibt neuere Anrufe.
- **Auf V2.6:** nur wenn der 15.09.-Nachmittag selbst Schaden anrichtet —
  `docker tag telefonki:produktionsstand-v2.6-20260914 telefonki:v1`. Dann
  fehlen Ben/Rüther, Zeiten-Wache, Handy-Akte und Buchungsbeweis.

## Offen / als Nächstes

Blessing-Korrektur **nach** diesem Stand, einzeln, ohne Deploy bis der Chef
sagt: zuerst Namen halten (Unklar aus, Buchstabieren kleben, Readback), dann
Auskunft-vs-Buchung, dann Motive/Slots, erst danach knapper Mund.
MedDent/Thaler/Rüther bleiben byte-identisch außer mandantenscharfen Gates.
`WRITE_LIVE` bleibt 1.
