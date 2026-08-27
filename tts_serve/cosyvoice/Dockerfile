# Fun-CosyVoice3-0.5B auf der RTX 5090 (Blackwell sm_120).
# Das CosyVoice-Repo pinnt aeltere torch-Versionen ohne Blackwell-Kernel —
# nach den requirements wird torch auf cu128 zurueckgezwungen.
# Klemmt der Build an einer Trainings-Abhaengigkeit (z. B. deepspeed):
# Zeile in der requirements.txt auskommentieren, fuer Inferenz unnoetig.
FROM pytorch/pytorch:2.7.1-cuda12.8-cudnn9-runtime

RUN apt-get update && \
    apt-get install -y --no-install-recommends git sox libsox-dev unzip && \
    rm -rf /var/lib/apt/lists/*

ARG COSYVOICE_REF=main
RUN git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git /opt/CosyVoice && \
    cd /opt/CosyVoice && git checkout ${COSYVOICE_REF} && \
    git submodule update --init --recursive

RUN pip install --no-cache-dir -r /opt/CosyVoice/requirements.txt \
      fastapi uvicorn huggingface_hub && \
    pip install --no-cache-dir --force-reinstall --no-deps \
      torch==2.7.1 torchaudio==2.7.1 \
      --index-url https://download.pytorch.org/whl/cu128

# Modell (~5 GB) laedt der Server beim ERSTEN Start ins Volume /models —
# nicht ins Image backen.
ENV HF_HOME=/models/hf \
    MODEL_DIR=/models/cosyvoice/Fun-CosyVoice3-0.5B \
    COSYVOICE_REPO=/opt/CosyVoice \
    TTS_PORT=8100 \
    STIMMEN_DIR=/stimmen

WORKDIR /app
COPY server.py .

EXPOSE 8100
CMD ["python", "server.py"]
