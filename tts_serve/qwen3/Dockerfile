# Qwen3-TTS-12Hz-0.6B-Base auf der RTX 5090 (Blackwell sm_120).
#
# Gleiches Rezept wie Chatterbox: python:3.11-slim + pip-only, danach
# torch MIT Abhaengigkeiten auf cu128 zurueckzwingen. qwen-tts zieht sonst
# gern ein CPU- oder cu124-Torch, und Blackwell hat dafuer keine Kernel.
# flash-attn wird NICHT gebaut (Compile auf slim = Stunden + oft rot);
# der Server faellt auf sdpa zurueck — 0.6B ist damit schnell genug.
FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends libsndfile1 ffmpeg curl && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir qwen-tts fastapi uvicorn soundfile numpy && \
    pip install --no-cache-dir --force-reinstall \
      torch==2.7.1 torchaudio==2.7.1 \
      --index-url https://download.pytorch.org/whl/cu128

ENV HF_HOME=/models/hf \
    TTS_PORT=8100 \
    STIMMEN_DIR=/stimmen \
    QWEN_TTS_MODEL=Qwen/Qwen3-TTS-12Hz-0.6B-Base \
    TTS_SPRACHE=German

WORKDIR /app
COPY server.py ./

EXPOSE 8100
CMD ["python", "server.py"]
