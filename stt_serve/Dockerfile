# Parakeet-STT (Claras bewaehrte Engine) fuer Lisa/Bianca — CPU-only.
# BEWUSST ohne Torch/CUDA: das Modell ist ONNX (onnx-asr + onnxruntime),
# laeuft wie bei Clara auf CPU und laesst die 5090-GPU (qwen-vLLM, TTS)
# komplett in Ruhe. Image ~600 MB statt ~12 GB.
FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg curl && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
      onnx-asr onnxruntime numpy fastapi uvicorn python-multipart

ENV STT_MODELL_PFAD=/modell \
    STT_PORT=8100

WORKDIR /app
COPY server.py postcorrect.py ./

EXPOSE 8100
CMD ["python", "server.py"]
