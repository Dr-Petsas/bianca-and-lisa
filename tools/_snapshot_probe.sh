#!/usr/bin/env bash
# Bestandsaufnahme fuer den Produktionsstand-Schnappschuss (read-only).
cd /home/cursor/telefonki || exit 1
echo "== Was gehoerte zum Produktionsstand V1.0?"
ls -la /home/cursor | head -20
echo "== Snapshot-Ordner"
ls -la /home/cursor/snapshots 2>/dev/null || echo "kein /home/cursor/snapshots"
find /home/cursor -maxdepth 2 -iname '*produktionsstand*' 2>/dev/null | head -10
echo "== Volumes (Bytes)"
for v in telefonki_telefonki-data telefonki_telefonki-berichte telefonki_telefonki-klang app_telefonki-data; do
  s=$(docker run --rm -v "$v":/v alpine:3.20 du -sm /v 2>/dev/null | cut -f1)
  echo "$v = ${s:-?} MB"
done
echo "== Git im Serverrepo?"
git -C /home/cursor/telefonki log --oneline -2 2>/dev/null || echo "kein git auf dem Server"
echo "== Nebenstacks"
ls -d /home/cursor/telefonki/tts_serve /home/cursor/telefonki/stt_serve 2>/dev/null
