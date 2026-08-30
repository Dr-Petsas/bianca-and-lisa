# TTS-Server-Vertrag (Chatterbox- und CosyVoice-Container, 27.08.2026)

Beide Container sprechen EXAKT dieselbe Schnittstelle. Lisa/Bianca kennen nur
`TTS_BASE` — welches Modell dahinter antwortet, entscheidet allein, welcher
Container laeuft. Nie beide gleichzeitig starten (eine GPU, vLLM laeuft daneben).

## GET /health

```json
{
  "ok": true,
  "engine": "chatterbox",          // oder "cosyvoice"
  "model": "Chatterbox-Multilingual-V3",
  "voices": ["bianca", "lisa"],    // gefundene Referenzen in /stimmen
  "device": "cuda",
  "warm": true                      // Warmlauf je Stimme abgeschlossen
}
```

`ok: false` + HTTP 503 solange das Modell noch laedt.

## POST /speak

Anfrage (JSON):

```json
{ "text": "Guten Tag, Praxis MedDent, hier ist Bianca.", "voice": "bianca" }
```

Antwort 200: **rohes PCM, 16 Bit signed little-endian, mono, 24000 Hz**
(`application/octet-stream`, Header `X-Sample-Rate: 24000`, `X-Engine: ...`).

Bewusst KEIN WAV: `kern/tts.py` legt auf das rohe PCM dieselbe
Demo-Clara-Pegel-Schicht (`pcm16_wav`) wie heute auf ElevenLabs-`pcm_24000` —
so klingen lokale und ElevenLabs-Zuege gleich laut.

Fehler:

- 400 `{"detail": "text fehlt"}` / `{"detail": "stimme unbekannt: x"}`
- 503 `{"detail": "modell laedt noch"}`
- 500 `{"detail": "<synthese-fehler>"}`

Der Client (`kern/tts.py`) macht daraus `RuntimeError` — in der Testphase gibt
es KEINEN ElevenLabs-Rueckfall (Chef 27.08.2026): ein kaputter Container ist
sofort hoerbar (Zug erscheint im Dock ohne Audio).

## POST /clone-speak

ClonR: beliebige Stimmprobe, kein vorregistrierter Name.

```json
{ "text": "Guten Tag, hier ist Dr. Petsas.", "ref_audio_url": "https://...", "language": "German" }
```

Optional: `ref_audio_b64` statt URL, `ref_text` (Transkript der Probe).
Ohne `ref_text` gilt `x_vector_only_mode`. Antwort wie `/speak`: PCM16 LE mono 24 kHz.

## Stimmen (/stimmen, read-only Volume)

- `<name>.wav` — Referenz fuers Klonen: 10-20 s, mono, sauber, >= 16 kHz.
- `<name>.txt` — wortgetreues Transkript der Referenz. **Pflicht fuer
  CosyVoice** (Zero-Shot braucht Audio UND Text), Chatterbox ignoriert es.

Dateiname = Stimmname im API-Aufruf (`bianca.wav` -> `"voice": "bianca"`).
