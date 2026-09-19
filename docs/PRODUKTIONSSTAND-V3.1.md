# Produktionsstand V3.1 — 19.09.2026, 20:45 Uhr

V3.1 bringt die drei fehlenden CALM-Bausteine an das ECHTE Telefon (V3.0
hatte sie nur im Dialogkern) und den Weg, wie eine Praxis ihren
Dialog-Layer selbst einstellt:

- **W-META-LIVE** (`bianca/metazug.py`, aufgerufen in
  `bianca/agent.user_turn` VOR Intent, Fluss und Modell): „Wie bitte?“,
  „Vergessen Sie's“, „Muss das sein?“ werden deterministisch beantwortet.
  Vorher ging „Wie bitte?“ ans Modell — live wurde daraus einmal ein
  Besuchsgrund. Stille ist seit dem 29.08.2026 unverändert live
  (`kern/stille.py`), damit sind 10 von 11 CALM-Befehlen abgedeckt.
- **W-BEFEHLSLISTE** (`verstehen.nachtraege` + `reducer.nachtragen`): „Termin
  absagen UND einen neuen ausmachen“ ist ein Satz mit zwei Aufträgen. Der
  erste läuft sofort, der zweite wartet geparkt und kommt über den
  bestehenden Auto-Resume zurück.
- **W-POLICY-ABLAGE** (`kern/policy_ablage.py`): der Veröffentlichen-Knopf
  der Studio-Maske schreibt `DialogPolicyV1` nach
  `.data/dialogpolicy/<mandant>.json`; `tenants.laden` und `agentprofil`
  legen ihn beim nächsten Anruf als `tenant["dialogPolicy"]` an.

## Was sich NICHT geändert hat

Die Praxis-Besonderheiten bleiben vollständig: MedDent, Thaler, Blessing und
Rüther laufen weiter aus ihren kuratierten `tenants/*.json` (read-only
gemountet) und der Pickadoc-DB. Die Ablage überschreibt eine vorhandene
Policy NIE — sie ist der Weg für Praxen, die keine tragen. Trägt kein
Mandant eine Datei, verhält sich jede Praxis byte-identisch wie unter V3.0.

Erkennung wird nicht verdoppelt: `metazug` nutzt `controller/meta.deute`,
also dieselbe Funktion wie der Kern, mit allen Gegenproben. Die Wortlaute
sind wortgleich mit `controller/renderer` — Studio-Probe und Telefon
klingen gleich.

## Die Gegenproben (der teurere Teil)

- Im Diktat (Nummer, Buchstabieren) greift keine Meta-Formel: „nochmal die
  Sieben“ ist eine Korrektur (`agent._diktat_offen`).
- Auf einer Rücklese, einer Slot-Auswahl oder einer destruktiven
  Bestätigung (`metazug.streng`) bleibt der Zug beim Fluss — dort eskaliert
  er seit Monaten selbst (Schreibweise frisch aufnehmen). Eine Kopie hier
  hieße, diese Eskalation zu verlieren.
- Liegt nur die Begrüßung vor, ist sie KEINE Vorlage: ein zweites Hallo
  streicht die Regreeting-Wache hinterher, der Zug bliebe stumm. Der Satz
  gehört dem normalen Unklar-Weg (Blessing-Gegenprobe „Wie bitte?“).
- Kein Nachtrag auf einer offenen Ja/Nein- oder Wahlfrage: dort gehört der
  Satz der Frage („ja, den früheren“), ein geparkter Auftrag wäre geraten.
- Abbrechen schreibt NICHTS und legt keine Rückrufnotiz an. Ist schon
  gebucht, sagt Bianca ehrlich, was steht, und nennt den Weg (absagen).

## Bekannte Decke

`Familie` ist ein geschlossenes Enum — jeder neue Anliegen-Typ kostet
Python im Reducer. Für die vier heutigen Praxen reicht das; sobald Abläufe
von außen kommen sollen (YAML-Flows wie bei CALM), ist das der Punkt.

## Live-Koordinaten

- Code-Commit (deployt): `5f59e47`
- Git-Tag: `telefonki-produktionsstand-v3.1-2026-09-19` — sitzt auf dem
  Doku-Commit direkt darüber (nur `AGENTS.md` + dieses Dokument, kein
  Code), damit der Tag seine eigene Anleitung mitbringt.
- App-Image: `telefonki:produktionsstand-v3.1-20260919`
- Image-ID:
  `2d760525b6127284b7601c06e5891a25ee37d3d02810078ec6e3b352dbee21b9`
- Dieselbe Image-ID läuft in `bianca`, `lisa`, `bianca-test` und `studio`.
- SIP-Brücke: `60d2810e172c` (unverändert, nur neu getaggt).
- `WRITE_LIVE=1`.
- TTS, STT, Tunnel, Asterisk, Clara, Lena und MAS wurden nicht verändert
  oder neu gestartet.

## Notaus

- `META_LIVE=0` => Meta-Bitten wie vor dem 19.09.2026.
- `DIALOG_POLICY_ABLAGE=0` => keine Policy-Datei wird gelesen.
- `CONTROLLER_SHADOW` bleibt wie unter V3.0 gesetzt.

## Abnahme

- Lokal: vollständige Suite — **2724 bestanden**, 0 fehlgeschlagen.
- `VERSION=v3.1 bash /tmp/_abn_lf.sh` auf pickadoc1: grün, einschließlich
  Blessing-V2.8-/V2.9-Schalter, W-ERSATZ-MOTIV, Codeanker und
  Dock-Cache-Buster `b106`.
- Health 8095/8096: grün. `WRITE_LIVE=1` im Container geprüft.
- `tools/prod_smoke.py` im deployten `bianca`-Container: `ALLE WACHEN
  GRUEN`.
- Live-`.env` unangetastet: `CLOUDFLARE_TELEFONKI_TOKEN` und
  `INTENT_NACHZUG` ausdrücklich gegengezählt.
- Brücke bereit auf `:40101` -> `http://bianca:8096`.
- Live-Probe gegen `bianca-test`: „Wie bitte?“ wiederholt die vorige
  Ansage, „Vergessen Sie's“ räumt das Anliegen und stellt die
  Abschlussfrage.
- Studio-Maske `/studio/dialogkern` erreichbar (durch die Live-Bianca
  gereicht, kein eigener Port).

## Sicherungen

- Server:
  `/home/cursor/telefonki-backups/produktionsstand-v3.1-20260919/`
- Enthalten: Live-`.env`, Secrets, Tenants, aufgelöste Compose-
  Konfigurationen (App + TTS + STT), Asterisk-Referenz-Dialplan,
  TTS-Stimmen, die drei Docker-Volumes (`telefonki-data`,
  `telefonki-klang`, `telefonki-berichte`), Image- und Health-Inventar.
- App-, SIP-Brücken-, Tunnel- und Cloudflared-Images tragen einen
  V3.1-Sicherungstag.
- Lokale Kopie:
  `F:\Bianca&Lisa TelefonKI\_snapshot-produktionsstand-v3.1\`
  mit Git-Bundle (`telefonki-repo.bundle`) und allen Volume-Archiven.

## Rückweg auf V3.0

```bash
cd /home/cursor/telefonki
docker tag telefonki:produktionsstand-v3.0-20260919 telefonki:v1
docker compose up -d lisa bianca bianca-test studio
```

Danach Health 8095/8096, `WRITE_LIVE=1` und `tools/prod_smoke.py` prüfen.
Ohne Container-Neustart genügt für die neuen Bausteine der Notaus-Weg:
`META_LIVE=0` und `DIALOG_POLICY_ABLAGE=0` in der Server-`.env`, dann
`docker compose up -d lisa bianca bianca-test studio` (recreate, kein
Build).
