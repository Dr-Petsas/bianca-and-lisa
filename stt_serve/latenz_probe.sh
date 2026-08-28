#!/bin/sh
# Latenz-Probe direkt auf dem Server (ohne LAN-Anteil): 3 Laeufe je WAV.
W1=/home/cursor/telefonki/tts_serve/stimmen/cosyvoice/bianca.wav
W2=/home/cursor/telefonki/tts_serve/stimmen/cosyvoice/lisa.wav
echo "--- referenz-transkript bianca:"
cat /home/cursor/telefonki/tts_serve/stimmen/cosyvoice/bianca.txt
echo ""
for i in 1 2 3; do
  curl -s -o /tmp/stt-out.json -w "lauf $i: %{time_total}s http=%{http_code}\n" \
    -F "file=@$W1" -F "keywords=Petsas,Nikolaou,Patrikis" \
    http://127.0.0.1:8212/transcribe
done
echo "--- erkannt:"
cat /tmp/stt-out.json
echo ""
echo "--- lisa-wav (laenger):"
curl -s -o /tmp/stt-out2.json -w "lauf lisa: %{time_total}s http=%{http_code}\n" \
  -F "file=@$W2" http://127.0.0.1:8212/transcribe
cat /tmp/stt-out2.json
echo ""
