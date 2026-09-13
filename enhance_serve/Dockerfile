FROM pytorch/pytorch:2.4.1-cuda12.1-cudnn9-runtime

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
        git ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir --no-deps \
        git+https://github.com/resemble-ai/resemble-enhance.git

COPY patches ./patches
COPY apply_patches.py .
RUN python apply_patches.py

COPY server.py .
ENV ENHANCE_PORT=8214
EXPOSE 8214
CMD ["python", "server.py"]
