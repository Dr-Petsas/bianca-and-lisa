#!/bin/sh
# Wartet, bis Chatterbox (8210) warm ist (max. 8 min — Modell aus dem Volume).
i=0
while [ "$i" -lt 48 ]; do
  r=$(curl -s -m 3 http://127.0.0.1:8210/health 2>/dev/null)
  case "$r" in
    *'"ok":true'*) echo "TTS-BEREIT: $r"; exit 0 ;;
  esac
  i=$((i + 1))
  sleep 10
done
echo "TTS-TIMEOUT - letzte Logs:"
docker logs --tail 15 tts_serve-chatterbox-1 2>&1
exit 1
