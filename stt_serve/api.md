# STT-Dienst (deutscher Conformer, 5090) — Vertrag

Ein Container, ein Vertrag — gleiches Muster wie `tts_serve/api.md`.
Ersetzt ElevenLabs Scribe fuer Lisa und Bianca (Chef 28.08.2026:
"es geht nichts mehr zu elevenlabs").

## Endpunkte

### `POST /transcribe`

Multipart-Upload, Feld `file` mit dem Aufnahme-Blob der Docks
(WebM/Opus vom MediaRecorder, M4A von iOS, WAV aus Tests — ffmpeg im
Container wandelt alles nach 16 kHz mono).

Antwort:

```json
{"text": "Ich haette gern einen Termin."}
```

Bei Fehlern kommt `{"text": "", "error": "..."}` mit HTTP 200 — der
Client behandelt leeren Text wie "nichts gehoert".

### `GET /health`

```json
{"ok": true, "model": "stt_de_conformer_transducer_large", "device": "cuda", "loadSeconds": 42.0}
```

## Client-Seite (dieses Repo)

- `kern/stt.py`: Ist `STT_BASE` in der `.env` gesetzt (z. B.
  `http://192.168.0.246:8212`), geht JEDE Transkription an den Container —
  **kein ElevenLabs-Rueckfall**. Leer = ElevenLabs Scribe wie vorher.
- Modell: `nvidia/stt_de_conformer_transducer_large` (NeMo, ~120M,
  deutsch-only — kein Sprachsprung-Risiko wie bei mehrsprachigen Modellen).
- Latenz-Ziel: unter 0,3 s je Zug (Scribe: 0,8-2,0 s gemessen 28.08.2026).

## Betrieb auf der 5090

```bash
cd /opt/telefonki/stt_serve
docker compose up -d --build
curl -s http://127.0.0.1:8212/health
```

- Erster Start laedt das Modell ins Volume `stt-models` (~0,5 GB, einmalig).
- VRAM ~1 GB FP32. Notaus bei Speichernot: `STT_DEVICE=cpu docker compose up -d`
  (Conformer-large dekodiert 5-s-Schnipsel auch auf CPU in ~0,3-0,5 s).
- Claras Parakeet und Lena-Voice sind NICHT beteiligt — eigener Container,
  eigenes Modell, eigenes Volume.
