# Deutscher Conformer-Transducer (NVIDIA NeMo) als STT-Dienst fuer die
# RTX 5090 (Blackwell sm_120) — ersetzt ElevenLabs Scribe fuer Lisa/Bianca
# (Chef 28.08.2026: "es geht nichts mehr zu elevenlabs").
#
# Bewusst NUR fuer dieses Repo: eigener Container, eigenes Modell-Volume.
# Claras Parakeet (F:\Clara-Voice) und Lena-Voice bleiben unberuehrt.
#
# Blackwell braucht torch cu128 — PIP_CONSTRAINT haelt torch/torchaudio fest,
# damit die NeMo-Abhaengigkeiten sie nicht auf alte CPU/cu12x-Wheels
# zurueckziehen (gleiche Falle wie bei den TTS-Containern, 28.08.2026).
FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ffmpeg libsndfile1 curl build-essential && \
    rm -rf /var/lib/apt/lists/*

RUN printf 'setuptools<81\ntorch==2.8.0\ntorchaudio==2.8.0\n' > /tmp/pip-constraints.txt
ENV PIP_CONSTRAINT=/tmp/pip-constraints.txt

RUN pip install --no-cache-dir "setuptools<81" wheel && \
    pip install --no-cache-dir torch==2.8.0 torchaudio==2.8.0 \
      --index-url https://download.pytorch.org/whl/cu128

# nemo_toolkit[asr] zieht lightning/hydra/librosa etc.; torch bleibt durch
# das Constraint auf cu128. fastapi/uvicorn fuer den Server-Umschlag.
RUN pip install --no-cache-dir "nemo_toolkit[asr]" fastapi uvicorn python-multipart

# Modell (~0,5 GB) laedt der Server beim ERSTEN Start ins Volume /models —
# nicht ins Image backen. XDG_CACHE_HOME deckt den NGC-Cache von NeMo ab,
# HF_HOME den HuggingFace-Weg.
ENV XDG_CACHE_HOME=/models/cache \
    HF_HOME=/models/hf \
    STT_MODEL=stt_de_conformer_transducer_large \
    STT_DEVICE=cuda \
    STT_PORT=8100

WORKDIR /app
COPY server.py .

EXPOSE 8100
CMD ["python", "server.py"]
