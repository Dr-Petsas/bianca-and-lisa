# STT-Container (Parakeet, 5090) — Vertrag

Claras bewaehrte Telefon-Strecke als eigener Dienst fuer Lisa/Bianca
(Chef 28.08.2026: Parakeet statt ElevenLabs, "alle besten und bewaehrtesten
Entwicklungsstufen von Clara V7 und Demo Clara"):

- Engine: **primeline-parakeet** (deutsches TDT-Finetune, 2,95 % WER) als
  ONNX ueber `onnx-asr`, **CPU-only** (wie Claras Produktion; ~190 ms je Zug
  auf dem Dev-Rechner, der Server-CPU ist schneller). KEIN Torch, KEINE GPU —
  qwen-vLLM und TTS bleiben unberuehrt.
- Nachkorrektur: `postcorrect.py` = Kopie von Claras
  `services/stt_postcorrect.py` (Fuzzy-Hotwords, Anlaut-Gruppen P/B, T/D/Z,
  Token-Paare fuer zerhackte Namen, Namens-Zweifel fuer Buchungs-Wachen).
  Phrasen-Fixes (Heads-up/Teleskopkrone/Kons) sind Marker-gated — Lisa/Bianca
  senden keine Marker und bleiben davon unberuehrt (wie Claras Bianca).
- Stille-Trim (W-STT-TRIM 29.08.2026): Vor-/Nachlauf-Stille wird VOR der
  Inferenz energie-basiert abgeschnitten (20-ms-RMS-Fenster, Schwelle
  max(5 % vom Peak, 0.003), Rand 160 ms vorn / 320 ms hinten). Kurze
  Antworten ("Ja", "Nein") ueberleben so die Feature-Normalisierung des
  TDT-Modells (NeMo #15757); reine Stille-/Brumm-Blobs werden verworfen
  (`{"text": ""}`) statt halluziniert. Dazu ein Retry-Guard fuer onnx-asr
  #138 (AssertionError -> ein Wurf mit +40 ms Stille). Notaus: `STT_TRIM=0`
  (compose reicht die Variable durch) => Alt-Verhalten ohne Trim; `/health`
  zeigt `"trim"`. Abnahme: `tests/stt_kurz_probe.py`.

## Endpunkte

### POST /transcribe

Multipart:

| Feld | Pflicht | Bedeutung |
| --- | --- | --- |
| `file` | ja | Audio (WebM/Opus, M4A, WAV ... — ffmpeg wandelt nach 16 kHz mono) |
| `keywords` | nein | Komma-Liste Hotwords, z. B. `Petsas,Nikolaou,Patrikis` |

Antwort:

```json
{
  "text": "Ich moechte zu Doktor Petsas",
  "korrekturen": [["Betsas", "Petsas"]],
  "namenszweifel": {"unsicher": false, "wort": "", "grund": "", "kandidaten": []},
  "ms": 187.3
}
```

- `korrekturen`: was die Fuzzy-Nachkorrektur ersetzt hat (Diagnose).
- `namenszweifel`: Claras `assess_name_certainty` — `unsicher:true` mit
  `grund` `mehrdeutig`/`unbekannt` und `kandidaten`, gedacht als Wache VOR
  schreibenden Aktionen (buchen/absagen/verschieben).
- Fehler: `{"text": "", "error": "..."}` — der Client (kern/stt.py) wirft
  bei HTTP != 200; es gibt KEINEN ElevenLabs-Rueckfall.

### GET /health

```json
{"ok": true, "model": "parakeet-primeline-onnx", "device": "cpu", "loadSeconds": 9.1, "trim": true}
```

## Client (Lisa/Bianca)

- `.env`: `STT_BASE=http://192.168.0.246:8212` (Dev-Rechner) bzw.
  `http://host.docker.internal:8212` (App-Container auf der 5090).
- `kern/stt.py` schickt `keywords` = Behandler-Nachnamen des Tenants
  (`kern/tenants.py -> stt_keywords`).

## Deploy (5090)

```bash
cd /home/cursor/telefonki/stt_serve
# Modell liegt als Bind-Mount in ./modell (parakeet-primeline-onnx, 2,5 GB;
# Quelle: Claras Cache per scp ODER HF geier/deskscribe-parakeet-primeline-onnx)
docker compose up -d --build
curl -s http://127.0.0.1:8212/health
```

Port-Landkarte 5090: vLLM 8000, Lisa 8095, Bianca 8096, Chatterbox 8210,
CosyVoice 8211, **STT 8212**.
