#!/bin/sh
# Wartet, bis der STT-Container das Modell geladen hat (max. 10 min).
i=0
while [ "$i" -lt 60 ]; do
  r=$(curl -s -m 3 http://127.0.0.1:8212/health 2>/dev/null)
  case "$r" in
    *'"ok":true'*) echo "BEREIT: $r"; exit 0 ;;
  esac
  i=$((i + 1))
  sleep 10
done
echo "TIMEOUT nach 10 min - letzte Container-Logs:"
docker logs --tail 20 stt_serve-stt-1 2>&1
exit 1
