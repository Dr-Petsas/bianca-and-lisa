# Chatterbox Multilingual V3 auf der RTX 5090 (Blackwell sm_120).
#
# Basis ist bewusst python:3.11-slim, NICHT pytorch/pytorch (conda):
# das conda-Image traegt eigene CUDA-Libs in /opt/conda/lib — nach dem
# torch-Reinstall passte libcupti nicht mehr zum Wheel
# ("undefined symbol: cuptiActivityEnableDriverApi", Vorfall 28.08.2026).
# Mit pip-only kommen ALLE nvidia-cu12-Libs konsistent aus dem cu128-Index.
#
# WICHTIG: chatterbox-tts pinnt torch 2.6 ohne Blackwell-Kernel — danach
# wird torch MIT Abhaengigkeiten (nvidia-cupti & Co.!) auf cu128
# zurueckgezwungen. Reihenfolge nicht umdrehen, --no-deps nicht ergaenzen.
FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends libsndfile1 curl && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir chatterbox-tts fastapi uvicorn && \
    pip install --no-cache-dir --force-reinstall \
      torch==2.7.1 torchaudio==2.7.1 \
      --index-url https://download.pytorch.org/whl/cu128

# Modell-Gewichte landen im Volume (/models), nicht im Image.
ENV HF_HOME=/models/hf \
    TTS_PORT=8100 \
    STIMMEN_DIR=/stimmen

WORKDIR /app
COPY server.py schnitt.py pegel.py ./

EXPOSE 8100
CMD ["python", "server.py"]
