#!/bin/sh
# Leert Gespraeche und Testergebnisse vor den Feldtests (Chef 13.09.2026).
#
# Vorher wird ein TEXT-Schnappschuss gesichert (Manifeste, Notizen, Berichte —
# ohne Audio), damit nachschlagbar bleibt, was gesagt wurde.
# NICHT angefasst: autoloesch.json/aufgeraeumt.json (die Warteschlange, die
# Test-Termine aus dem ECHTEN Kalender wieder entfernt), TTS-/Klang-Caches,
# tenants, .env, secrets.

SICHER="/home/cursor/telefonki-backups/vor-feldtest-20260913"
mkdir -p "$SICHER"

echo "=== 1) Text-Schnappschuss nach $SICHER ==="
docker run --rm -v telefonki_telefonki-data:/d -v "$SICHER":/out alpine sh -c '
  cd /d && tar czf /out/anrufe-manifeste.tgz \
    $(find anrufe -name "anruf.json" 2>/dev/null) 2>/dev/null
  cp -f /d/praxis_notizen.jsonl /out/ 2>/dev/null
  cd /d && tar czf /out/sitzungen.tgz bianca_sessions sessions 2>/dev/null
  ls -la /out'
docker run --rm -v telefonki_telefonki-berichte:/b -v "$SICHER":/out alpine sh -c '
  cd /b && tar czf /out/studio-berichte.tgz . 2>/dev/null; ls -la /out'

echo
echo "=== 2) Anrufe + Sitzungen + Notizen leeren ==="
docker run --rm -v telefonki_telefonki-data:/d alpine sh -c '
  rm -rf /d/anrufe/bianca /d/anrufe/lisa
  mkdir -p /d/anrufe/bianca /d/anrufe/lisa
  rm -rf /d/bianca_sessions /d/sessions
  mkdir -p /d/bianca_sessions /d/sessions
  : > /d/praxis_notizen.jsonl
  echo "{}" > /d/bianca_last_call.json
  echo "{}" > /d/last_call.json
  echo "danach:"; du -sh /d; ls -1 /d/anrufe/bianca | wc -l'

echo
echo "=== 3) Studio-Ergebnisse leeren (autoloesch/aufgeraeumt bleiben) ==="
docker run --rm -v telefonki_telefonki-berichte:/b alpine sh -c '
  cd /b || exit 0
  for e in *; do
    case "$e" in
      autoloesch.json|aufgeraeumt.json) echo "behalten: $e";;
      *) rm -rf "$e";;
    esac
  done
  echo "danach:"; ls -1 /b; du -sh /b'

echo
echo "=== 4) Gegenprobe ueber die API ==="
curl -sf http://127.0.0.1:8096/api/anrufe | head -c 200; echo
curl -sf http://127.0.0.1:8096/health >/dev/null && echo "bianca health ok"
curl -sf http://127.0.0.1:8095/health >/dev/null && echo "lisa health ok"
