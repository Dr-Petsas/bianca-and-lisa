#!/bin/bash
set -e
echo "=== restart qwen3 TTS ==="
docker restart tts_serve-qwen3-1
for i in $(seq 1 40); do
  h=$(curl -sS -m 3 http://127.0.0.1:8213/health || echo '{}')
  echo "t+${i}s $h"
  echo "$h" | grep -q '"warm":true' && break
  sleep 2
done
echo "=== speak probe ==="
python3 /tmp/_probe_tts.py
echo "=== listen probe ==="
python3 /tmp/_probe_listen.py
