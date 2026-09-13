#!/bin/bash
set -e
sed -i 's/\r$//' /tmp/tts.py
for c in telefonki-bianca-1 telefonki-lisa-1 telefonki-bianca-test-1; do
  docker cp /tmp/tts.py "$c:/app/kern/tts.py"
  echo "copied -> $c"
done
docker restart telefonki-bianca-1 telefonki-lisa-1 telefonki-bianca-test-1
sleep 5
docker exec -w /app telefonki-bianca-1 python - <<'PY'
from kern import tts
tts.TTS_BASE = "http://x:8213"
p = tts._ziffern_einzeln("null eins sieben sieben, sechs null null, vier sechs, null null")
print("soll_qwen", repr(tts._ziffern_soll(p)))
print("ziffern_satz", tts.ziffern_satz(
    "Ich wiederhole die Nummer: null eins sieben sieben, sechs null null, vier sechs, null null."))
tts.TTS_BASE = "http://x:8211"
print("soll_cosy", repr(tts._ziffern_soll(p)))
PY
curl -sS -m 5 http://127.0.0.1:8096/health | head -c 180
echo
