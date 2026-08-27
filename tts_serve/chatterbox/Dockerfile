# Chatterbox Multilingual V3 auf der RTX 5090 (Blackwell sm_120).
# WICHTIG: chatterbox-tts pinnt eine aeltere torch-Version ohne
# Blackwell-Kernel — nach der Installation wird torch auf cu128
# zurueckgezwungen. Diese Reihenfolge nicht umdrehen, sonst
# "no kernel image is available for execution on the device".
FROM pytorch/pytorch:2.7.1-cuda12.8-cudnn9-runtime

RUN pip install --no-cache-dir chatterbox-tts fastapi uvicorn && \
    pip install --no-cache-dir --force-reinstall --no-deps \
      torch==2.7.1 torchaudio==2.7.1 \
      --index-url https://download.pytorch.org/whl/cu128

# Modell-Gewichte landen im Volume (/models), nicht im Image.
ENV HF_HOME=/models/hf \
    TTS_PORT=8100 \
    STIMMEN_DIR=/stimmen

WORKDIR /app
COPY server.py .

EXPOSE 8100
CMD ["python", "server.py"]
