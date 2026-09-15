# Produktionsstand V2.8 — 15.09.2026, 19:20 Uhr

> Abgelöst durch V2.8.1. Das Blessing-Paket ist vollständig, im Image fehlt
> jedoch der bereits in Git enthaltene Sitzungs-Katalog-Nachzug von
> W-ERSATZ-MOTIV. Rückfall nur über den erhaltenen Image-Tag
> `telefonki:produktionsstand-v2.8-partial-20260915`; Details:
> `docs/PRODUKTIONSSTAND-V2.8.1.md`.

V2.8 ist der erste Live-Stand des Blessing-Verbesserungspakets. Ziel ist,
die belegte Tagesbasis von **0 Prozent super / 6,7 Prozent super+gut** durch
weniger Leerlauf und mehr korrekt abgeschlossene Terminaufgaben anzuheben.
Der Zielwert bleibt 40 Prozent super und 80 Prozent super+gut ab mindestens
50 gewerteten Gesprächen.

## Live-Koordinaten

- Quell-Commit: `5360d0a` — „Blessing-Gespräche kürzen und
  Terminabschlüsse absichern“
- Git-Tag: `telefonki-produktionsstand-v2.8-2026-09-15`
- App-Image: `telefonki:produktionsstand-v2.8-20260915`
- Image-ID: `0f2a38889c0f26af7e636b350b3ae97590460827c8fdd55abe8eca35ecb24d89`
- Dieselbe Image-ID läuft in `bianca`, `lisa`, `bianca-test` und `studio`.
- Dock-Cache-Buster: `b103`
- `WRITE_LIVE=1`; die Live-`.env` blieb byte-identisch und trägt weiterhin
  `CLOUDFLARE_TELEFONKI_TOKEN` sowie `INTENT_NACHZUG=0`.
- SIP-Brücke, Lisa-Brücke, TTS, STT, Tunnel, Clara, MAS und Asterisk wurden
  weder neu gebaut noch neu gestartet.

## Was V2.8 bei Blessing ändert

- Unsichere Namen bleiben im Namensformular statt in der allgemeinen
  Unklar-Schleife.
- Buchstabiersegmente und „fertig“ werden sicher getrennt; der Nachname wird
  vor jeder Patienten- oder Terminsuche einmal rückbestätigt.
- Fragen nach einem bestehenden Termin bleiben Bestandsauskunft und kippen
  nicht in eine Neubuchung. Der Bächle-Verhörer trennt Bestandsdatum und
  Verschiebeziel.
- „Beratung“ wird konkretisiert; dermatologische Gründe werden auf den
  Blessing-Katalog gemappt. Ein einzelner Behandler wird nicht sinnlos
  erfragt.
- Abgelehnte Wochentage, Tageszeiten und Stunden bleiben über Folgeturns
  gesperrt und dürfen nicht als Ausweichslot zurückkehren.
- Nach einer Slot-Zusage kommt nur noch die erforderliche Handynummer vor dem
  Schreiben.
- Begrüßung, Menschenwunsch, Unklar-Antwort, Doktor-Notiz, „für Sie selbst?“,
  Presence und Notiz-Abschluss sind mandantenscharf gekürzt.
- MedDent, Thaler und Rüther tragen keinen dieser Opt-in-Schalter und bleiben
  im bisherigen Gesprächspfad.

## Abnahme

- Gesamtsuite lokal: `2137 passed`
- Blessing-Paket: `78 passed`
- Studio-/Task-Gates: `196 passed`
- Stille-/Hangup-Gates: `72 passed`
- `node --check bianca_web/app.js`: grün
- `tools/prod_smoke.py`: `ALLE WACHEN GRUEN`, lokal und im Live-Container
- Vier App-Container nach dem Rollout gesund; `writeLive=true`
- Live-Canary, schreibgeschützt:
  - Anrufer: „Hallo.“
  - Bianca: „Guten Tag. Geht es um einen Termin, eine Absage, eine
    Verschiebung oder eine Terminauskunft?“
  - Kein Wohlseins-Eisbrecher, kein freies LLM.
- Live-Code-Canary: Beratungsklärung, Bestandsauskunft und harte
  Slot-Ausschlüsse grün.

## Sicherungen

- Server:
  `/home/cursor/telefonki-backups/produktionsstand-v2.8-20260915/`
- Enthalten: Live-`.env`, `secrets.tgz`, `tenants.tgz`, Compose-Dateien,
  aufgelöste Compose-Konfiguration, TTS-Stimmreferenzen, drei Docker-Volumes,
  Image-Inventar, Health-Inventar und Asterisk-Hinweis.
- Die unverändert laufende SIP-Brücke hat aufgeräumte Image-Layer und lässt
  sich nicht taggen. Ihr 616-MB-Dateisystem-Tar ist deshalb als Hardlink des
  byte-identischen V2.7-Exports im V2.8-Schnappschuss enthalten.
- Lokale Kopie:
  `F:\Bianca&Lisa TelefonKI\_snapshot-produktionsstand-v2.8\`
  mit Server-Schnappschuss, Git-Bundle, lokaler `.env`/`.data` und
  Parakeet-Qwen-Arbeitsstand. Der Ordner bleibt gitignoriert.

## Messpunkt

Unmittelbar vor dem Rollout, nur echte Blessing-Anrufe vom 15.09.:

- 141 Gesamtanrufe
- 21 reine Aufleger
- 120 gewertete Gespräche
- 0 super
- 8 gut = 6,7 Prozent super+gut
- 40 fehlerhaft = 33,3 Prozent

Der Rollout verändert alte Manifeste nicht. Der erste belastbare
Nachher-Vergleich beginnt daher mit Anrufen nach **15.09.2026 19:20 Uhr**.
Auswertung:

`python tools/tages_scorer.py --seit 2026-09-15T19:20:00+02:00 --tenant blessing`

## Rückweg

V2.7 bleibt der direkte Rückrollpunkt vor allen Blessing-Fixes:

```bash
cd /home/cursor/telefonki
docker tag telefonki:produktionsstand-v2.7-20260915 telefonki:v1
docker compose up -d lisa bianca bianca-test studio
```

Danach Health 8095/8096 und `python tools/prod_smoke.py` prüfen. Einstellungen
und Volumes nur bei echter Datenkorruption aus dem V2.7-Schnappschuss
zurückspielen; ein Volume-Restore würde neuere Anrufe überschreiben.
