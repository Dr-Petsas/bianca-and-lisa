# Rollout auf der 5090 (pickadoc1, LAN 192.168.0.246 — SSH-Alias `pickadoc1`)

Vier getrennte Stacks, bewusst einzeln startbar:

| Stack | Compose | Ports | Zweck |
| --- | --- | --- | --- |
| vLLM | (laeuft schon) | 8000 | Qwen 3.6 — nicht anfassen |
| TTS | `tts_serve/compose.yml` | 8210 Chatterbox / 8211 CosyVoice | EIN Profil aktiv |
| STT | `stt_serve/compose.yml` | 8212 | deutscher Conformer statt Scribe (28.08.2026) |
| App | `compose.yml` (Repo-Wurzel) | 8095 Lisa / 8096 Bianca | Umschlag fuer SIP/Zaluma |

STT-Rollout (Details `stt_serve/api.md`):

```bash
cd /home/cursor/telefonki/stt_serve
docker compose up -d --build          # erster Start laedt ~0,5 GB Modell
curl -s http://127.0.0.1:8212/health
# App-Container umstellen: STT_BASE=http://host.docker.internal:8212 in die
# .env der App, dann docker compose up -d (Repo-Wurzel). KEIN Scribe-Rueckfall.
```

Voraussetzung auf der 5090: Docker + NVIDIA Container Toolkit
(`docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu22.04 nvidia-smi` muss die GPU zeigen).

## 1. Stimm-Referenzen erzeugen (einmalig, auf dem Dev-Rechner)

```powershell
cd "F:\Bianca&Lisa TelefonKI"
.\.venv\Scripts\python tts_serve\korpus_bauen.py      # Test-Korpus (54 Saetze)
.\.venv\Scripts\python tts_serve\bench.py --ref-erzeugen   # bianca/lisa.wav+.txt aus ElevenLabs
```

## 2. ElevenLabs-Baseline messen (Vergleichswerte fuers Ohr und die Stoppuhr)

```powershell
.\.venv\Scripts\python tts_serve\bench.py --engine eleven --voice bianca
.\.venv\Scripts\python tts_serve\bench.py --engine eleven --voice lisa
```

## 3. Repo auf die 5090 bringen und TTS-Container bauen

```bash
# auf der 5090, z. B. nach /srv/telefonki (git clone oder rsync/scp vom Dev-Rechner;
# tts_serve/stimmen/*.wav+.txt MITKOPIEREN — die sind bewusst nicht im Git)
cd /srv/telefonki/tts_serve
docker compose --profile chatterbox up -d --build     # erster Kandidat
docker logs -f tts_serve-chatterbox-1                 # warten bis "warm"
curl http://127.0.0.1:8210/health
```

Umschalten auf den zweiten Kandidaten (nie beide zugleich — eine GPU, vLLM daneben):

```bash
docker compose --profile chatterbox down
docker compose --profile cosyvoice up -d --build      # erster Start laedt ~5 GB
curl http://127.0.0.1:8211/health
```

## 4. Shootout gegen die Container (vom Dev-Rechner)

```powershell
.\.venv\Scripts\python tts_serve\bench.py --engine lokal --url http://192.168.0.246:8210 --voice bianca
.\.venv\Scripts\python tts_serve\bench.py --engine lokal --url http://192.168.0.246:8211 --voice bianca
```

WAVs zum Anhoeren + `ergebnis.csv` liegen unter `tts_serve/bench_out/<lauf>/`.
Entscheidend: Latenz p50/p95 gegen die ElevenLabs-Baseline und das Ohr des Chefs.

## 5. Lisa/Bianca mit dem Sieger verbinden

In der `.env` (Dev-Rechner oder App-Container) EINE Zeile:

```
TTS_BASE=http://192.168.0.246:8210     # bzw. :8211
```

Dienst neu starten — `/health` zeigt dann `"tts": "lokal"` und die URL unter
`ttsModel`. **In der Testphase gibt es KEINEN ElevenLabs-Rueckfall** (Chef
27.08.2026): faellt der Container aus, erscheint der Zug im Dock ohne Audio.
Zurueck zu ElevenLabs = Zeile leeren + Neustart.

## 6. App-Container (der stabile Umschlag fuer SIP/Zaluma)

```bash
cd /srv/telefonki
cp .env.example .env    # ELEVENLABS_API_KEY eintragen (kein F:\-Peek im Container),
                        # TTS_BASE=http://host.docker.internal:8210 fuer Lokal-TTS
docker compose up -d --build
curl http://127.0.0.1:8095/health     # Lisa
curl http://127.0.0.1:8096/health     # Bianca
```

- `tenants/` ist read-only in den Container gemountet: neue Praxis = JSON-Datei
  dazulegen, kein Rebuild.
- Sitzungsdaten liegen im Volume `telefonki-data` (`/app/.data`).
- vLLM/TTS erreichen die App-Container ueber `host.docker.internal`
  (host-gateway, in `compose.yml` verdrahtet).

## 7. Wenn beide Stimmen ueberzeugen

Demo-Clara und Clara V7 auf dieselben Container umziehen (gleicher
`/speak`-Vertrag, nur Referenz-WAVs dazulegen) — dann fliegt ElevenLabs raus.
Das passiert in DEREN Repos, nicht hier.

## Stolperfallen

- **Blackwell (RTX 5090 = sm_120):** Beide Dockerfiles zwingen torch nach der
  Modell-Installation auf cu128 zurueck. Meldung "no kernel image is available"
  = diese Zeile hat jemand entfernt.
- **CosyVoice-Build klemmt** an einer Trainings-Abhaengigkeit (deepspeed o. ae.):
  Zeile in der Repo-`requirements.txt` auskommentieren, fuer Inferenz unnoetig.
- **CosyVoice ohne `<stimme>.txt`** ueberspringt die Stimme (Zero-Shot braucht
  Audio UND Transkript) — steht dann im Container-Log.
- **VRAM:** vLLM (Qwen 35B) + ein 0.5B-TTS passt; zwei TTS-Container parallel
  sind unnoetig und riskant — darum die Compose-Profile.
