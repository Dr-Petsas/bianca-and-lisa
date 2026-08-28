# Fun-CosyVoice3-0.5B auf der RTX 5090 (Blackwell sm_120).
#
# Basis ist bewusst python:3.11-slim, NICHT pytorch/pytorch (conda) —
# gleiche cupti-Falle wie beim Chatterbox-Container (28.08.2026):
# conda-CUDA-Libs kollidieren mit den pip-Wheels. build-essential/cmake
# braucht pynini (WeTextProcessing) aus den CosyVoice-requirements.
#
# Das CosyVoice-Repo pinnt aeltere torch-Versionen ohne Blackwell-Kernel —
# nach den requirements wird torch MIT Abhaengigkeiten auf cu128
# zurueckgezwungen (--no-deps wuerde die nvidia-cu12-Libs alt lassen).
# Klemmt der Build an einer Trainings-Abhaengigkeit (z. B. deepspeed):
# Zeile in der requirements.txt auskommentieren, fuer Inferenz unnoetig.
FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      git sox libsox-dev libsndfile1 unzip curl build-essential cmake && \
    rm -rf /var/lib/apt/lists/*

ARG COSYVOICE_REF=main
RUN git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git /opt/CosyVoice && \
    cd /opt/CosyVoice && git checkout ${COSYVOICE_REF} && \
    git submodule update --init --recursive

# setuptools>=81 hat pkg_resources entfernt — mehrere CosyVoice-Deps
# importieren es aber noch in ihrem setup.py. PIP_CONSTRAINT wirkt auch in
# den isolierten Build-Umgebungen der Wheel-Builds (28.08.2026).
RUN printf 'setuptools<81\n' > /tmp/pip-constraints.txt
ENV PIP_CONSTRAINT=/tmp/pip-constraints.txt

RUN pip install --no-cache-dir "setuptools<81" wheel && \
    pip install --no-cache-dir -r /opt/CosyVoice/requirements.txt \
      fastapi uvicorn huggingface_hub && \
    pip install --no-cache-dir --force-reinstall \
      torch==2.7.1 torchaudio==2.7.1 \
      --index-url https://download.pytorch.org/whl/cu128

# deepspeed (Trainings-Dep aus den requirements) crasht beim Import ohne
# CUDA-Toolkit im Container (CUDA_HOME) — transformers zieht es an, sobald es
# installiert ist. Fuer Inferenz unnoetig, also raus (28.08.2026).
RUN pip uninstall -y deepspeed || true

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
