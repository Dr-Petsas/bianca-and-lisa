# Produktionsstand V6.1 — Bianca-Terminverwaltung — 01.10.2026

Dieser Freeze erweitert ausschließlich Bianca um die abgesicherte
Terminverwaltung. Lisa, SIP-Brücken, TTS, STT, MAS und Clara wurden nicht
neu gestartet oder umgestellt.

## Autoritativer Stand

- Produktcode: `bf026b92a34eaf64ba0cee6339c150532e02ac1d`
- Git-Tag: `stabil-2026-10-01-bianca-terminverwaltung`
- Live-Image:
  `sha256:ed4e052dce5594fe3b40dfb55831e35d3f134e56b7f657574cace5c393d4b91b`
- Image-Tag:
  `telefonki:stabil-2026-10-01-bianca-terminverwaltung`
- Sofortiger Rollback:
  `telefonki:golden-live-20261001`
  (`sha256:80206fd424ea34c0426e5428d05be2e7832fe32b80eb6fb4de0d88b3ebf64366`)
- Privater Server-Snapshot vor dem Live-Tausch:
  `/home/cursor/telefonki-backups/pre-live-swap-20261001-174256`

## Konfigurations- und Code-Nachweis

Die Inhalte von `.env`, `secrets/`, Mandantenakten und Testdialogen sind
nicht Bestandteil dieses Commits. Zur unveränderten Zuordnung wurden nur
SHA-256-Werte festgehalten:

- `compose.yml`:
  `88abfb5f197aa487c91a67a7ad2e3d14fe5836027266f6aee8db2605dae89a32`
- `.env`:
  `4a6c1f0def2780e9d476f85dbd1136c34fd4a55ecbf5c9aafcc829f3de93da15`
- `tenants/meddent.json`:
  `090b5c605998af4bdb6bef51eb5b6a68e4a069fa85fe9bd158fc7623556241cc`
- Manifest der geänderten, im Image enthaltenen Dateien:
  `4315f84e7a05d82dabfa9dc6156a9f229a258c0a4a7f2e98a5a67267857c6340`

Live-Container, Kandidaten-Image und Serverquelle wurden für die geänderten
Laufzeitdateien bytegleich geprüft; unterschiedliche CRLF/LF-Zeilenenden
wurden dabei kanonisch als LF verglichen.

## Abnahme

- Lokale Gesamtsuite: **2709 bestanden, 2 übersprungen**.
  Die drei verbleibenden Fehler sind ausschließlich die bekannte lokale
  Python-3.14-Lücke `audioop`; Image und Produktion verwenden Python 3.12.
- Mandantenmatrix: **8/8 grün**, MedDent, Thaler, Blessing und Rüther,
  **0 Kalenderwrites**.
- Einmalige Namens-SMS an die freigegebene Testnummer:
  Versand bestätigt, Status `open`; Doppelversand durch Servermarke gesperrt.
- Kontrollierte Kalender-E2E:
  Buchung → exaktes Lesen → Verschieben → exaktes Lesen → Absagen →
  Abwesenheit bestätigt. Kein Testtermin blieb zurück.
- Asterisk vor dem Tausch: **0 aktive Kanäle**.
- Nur `telefonki-bianca-1` wurde neu erstellt; alle anderen Container-IDs
  blieben unverändert.
- Live: Image korrekt, Health `healthy`, `WRITE_LIVE=1`, beide
  `.env`-Wachen vorhanden.
- `tools/prod_smoke.py`: vollständig grün.
- No-Write-Live-Canary: 2 historische Anrufe, 37 Züge, 0 Fehler,
  p50 2 ms, p90 2532 ms.

## Rollback

Vor dem Rollback müssen die aktiven Asterisk-Kanäle erneut exakt null sein.
Danach wird nur Bianca zurückgesetzt:

```bash
cd /home/cursor/telefonki
docker tag telefonki:golden-live-20261001 telefonki:v1
docker compose up -d --no-deps --wait --wait-timeout 60 bianca
```

Anschließend Image-ID, Health, `WRITE_LIVE=1`, `.env`-Wachen und
`tools/prod_smoke.py` erneut prüfen. Die produktive `.env` und die
Mandantenverzeichnisse dürfen bei einem Rollback nicht überschrieben werden.
