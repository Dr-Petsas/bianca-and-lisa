#!/usr/bin/env bash
# Produktionsstand V2.0 (13.09.2026) — Nacharbeit: Bruecken-Images taggen,
# Inventar schreiben, Zugriffsrechte setzen. Idempotent, stoppt nichts.
set -e
STAMP=20260913
ZIEL=/home/cursor/telefonki-backups/produktionsstand-v2.0-$STAMP
APP=/home/cursor/telefonki
cd "$APP"

echo "== Bruecken-Images (laufen ohne Repo-Namen) taggen"
for paar in "telefonki-sipbridge-1:telefonki-sipbridge" "telefonki-sipbridge-lisa-1:telefonki-sipbridge-lisa"; do
  c=${paar%%:*}; basis=${paar##*:}
  id=$(docker inspect -f '{{.Image}}' "$c" 2>/dev/null) || continue
  neu="$basis:produktionsstand-v2.0-$STAMP"
  docker tag "$id" "$neu" && echo "  $c -> $neu"
  echo "$c | image=$id | gesichert-als=$neu" >> "$ZIEL/images.txt"
done

echo "== Inventar"
{
  echo "Produktionsstand V2.0 — Schnappschuss $(date -Is)"
  echo
  echo "## Container (laufend)"
  docker ps --format '{{.Names}} | {{.Image}} | {{.Status}} | {{.Ports}}'
  echo
  echo "## Gesicherte Images"
  docker images --format '{{.Repository}}:{{.Tag}} {{.ID}} {{.Size}}' | grep produktionsstand-v2.0 || true
  echo
  echo "## Alle telefonki-/TTS-/STT-Images"
  docker images --format '{{.Repository}}:{{.Tag}} {{.ID}} {{.Size}}' | grep -E 'telefonki|tts-qwen3|stt-parakeet|cloudflared' || true
  echo
  echo "## Health"
  curl -sf http://127.0.0.1:8096/health || true; echo
  curl -sf http://127.0.0.1:8095/health || true; echo
  echo
  echo "## .env-Schluessel (nur Namen — Werte in .env dieses Ordners)"
  grep -oE '^[A-Z0-9_]+' .env | sort
  echo
  echo "## Gesicherte Dateien"
  ls -la "$ZIEL"
  echo
  echo "## Plattenbelegung"
  df -h /home | tail -1
} > "$ZIEL/inventar.txt" 2>&1

echo "== Rechte"
chmod 700 "$ZIEL"
chmod 600 "$ZIEL"/.env "$ZIEL"/env-* "$ZIEL"/secrets.tgz 2>/dev/null || true
echo
echo "FERTIG: $ZIEL"
du -sh "$ZIEL"
ls -la "$ZIEL"
