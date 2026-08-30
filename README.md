# Bianca & Lisa Telefon-KI

Eigenständiger Dienst. **Rührt Clara, Clara-dev, DemoClara und MAS nicht an.**

- Port **8095**
- LLM: Qwen 3.6 über vLLM auf der 5090 (`http://100.77.30.98:8000/v1`)
- Stimme: ElevenLabs, austauschbar in `lisa/tts.py`
- Dev-Mandant: med dent, Anrufziel immer `0177 6004600`
- Schreiben am echten Kalender: aus (`WRITE_LIVE=0`)

```powershell
powershell -File .\start-protokoll.ps1
```

Startet Lisa 8095, Bianca 8096, Studio 8097, Test-Bianca 8098 und hebt Abgestürzte neu.
Clara/MAS/Lena bleiben unangetastet. Nur Stand: `-Status`.

Dann [http://127.0.0.1:8095](http://127.0.0.1:8095) / [8096](http://127.0.0.1:8096)

Zaluma hängt ein Kollege später an denselben Sitzungs-Umschlag.
Bianca kommt als zweite Rolle in denselben Kernel, nicht als zweites Repo.
