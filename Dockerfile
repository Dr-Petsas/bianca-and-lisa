# Lisa + Bianca Telefon-KI — EIN Image, zwei Services (siehe compose.yml).
# Kein GPU-Kram hier drin: LLM (vLLM) und TTS laufen als eigene Container,
# die App spricht beide nur ueber HTTP an.
FROM python:3.12-slim

WORKDIR /app

# ffmpeg nur fuer die SIP-Bruecke (MP3-Jingle -> PCM); haelt das Image klein
# genug und erspart einen zweiten Basis-Container.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY kern/ kern/
COPY lisa/ lisa/
COPY bianca/ bianca/
COPY sip_bridge/ sip_bridge/
COPY web/ web/
COPY bianca_web/ bianca_web/
# Basis-Mandanten liegen im Image; der Tenant-Mount in compose.yml legt sich
# darueber und macht neue Praxen ohne Rebuild moeglich.
COPY tenants/ tenants/

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    TZ=Europe/Berlin

EXPOSE 8095 8096
CMD ["python", "-m", "uvicorn", "lisa.server:app", "--host", "0.0.0.0", "--port", "8095"]
