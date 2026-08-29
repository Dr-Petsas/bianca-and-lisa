# Qwen3-TTS-12Hz-0.6B-Base auf der RTX 5090 (Blackwell sm_120).
#
# Hybrid (29.08.2026): qwen3-tts-triton + faster-qwen3-tts = Triton-Kerne
# plus CUDA-Graph, getestet vom Upstream auf 5090/cu128. Python 3.12 ist
# Pflicht (PyPI-Requires). flash-attn wird NICHT gebaut.
#
# Blackwell-Falle: nach den requirements torch MIT Abhaengigkeiten auf
# cu128 zurueckzwingen — qwen-tts/triton ziehen sonst gern cu124.
FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      libsndfile1 ffmpeg curl build-essential && \
    rm -rf /var/lib/apt/lists/*

# Torch zuerst (cu128), dann Hybrid-Deps, dann Torch nochmal festnageln.
RUN pip install --no-cache-dir \
      torch==2.7.1 torchaudio==2.7.1 \
      --index-url https://download.pytorch.org/whl/cu128 && \
    pip install --no-cache-dir \
      qwen-tts qwen3-tts-triton faster-qwen3-tts \
      fastapi uvicorn soundfile numpy && \
    pip install --no-cache-dir --force-reinstall \
      torch==2.7.1 torchaudio==2.7.1 \
      --index-url https://download.pytorch.org/whl/cu128

ENV HF_HOME=/models/hf \
    TTS_PORT=8100 \
    STIMMEN_DIR=/stimmen \
    QWEN_TTS_MODEL=Qwen/Qwen3-TTS-12Hz-0.6B-Base \
    TTS_SPRACHE=German \
    TTS_HYBRID=1

WORKDIR /app
COPY server.py ./

EXPOSE 8100
CMD ["python", "server.py"]
