#!/usr/bin/env bash
# Harte, read-only Abnahme des vollständigen Produktionsstands V6.0.
set -euo pipefail

VERSION=${VERSION:-v6.0}
STAMP=${STAMP:-20260926}
MARKE="produktionsstand-$VERSION-$STAMP"
S="/home/cursor/telefonki-backups/$MARKE"
cd /home/cursor/telefonki

echo "== Abnahme $MARKE"
[ -d "$S" ]
[ ! -e "/home/cursor/telefonki-backups/.${MARKE}.tmp" ]

echo "== Prüfsummen"
(cd "$S" && sha256sum -c SHA256SUMS)

echo "== Freeze-Tags"
for tag in "telefonki:$MARKE" telefonki:produktionsstand-v6.0 telefonki:v6.0; do
  docker image inspect "$tag" >/dev/null
  echo "OK $tag = $(docker image inspect -f '{{.Id}}' "$tag")"
done

echo "== Live-Code == Freeze-Code"
live_hash=$(docker exec telefonki-bianca-1 sh -c \
  'cd /app && find kern bianca -name "*.py" -exec sha256sum {} + | sort | sha256sum' | awk '{print $1}')
image_hash=$(docker run --rm --entrypoint sh "telefonki:$MARKE" -c \
  'cd /app && find kern bianca -name "*.py" -exec sha256sum {} + | sort | sha256sum' | awk '{print $1}')
echo "live=$live_hash"
echo "freeze=$image_hash"
[ "$live_hash" = "$image_hash" ]
grep -qx "live=$live_hash" "$S/code-paritaet.txt"
grep -qx "freeze=$image_hash" "$S/code-paritaet.txt"

echo "== Archive vollständig und lesbar"
for f in \
  tenants.tgz secrets.tgz tts-stimmen.tgz stt-bind-modell.tgz \
  server-source-tree.tgz images-v6.0.tar.gz \
  volumes/telefonki_telefonki-data.tgz \
  volumes/telefonki_telefonki-berichte.tgz \
  volumes/telefonki_telefonki-klang.tgz \
  volumes/tts_serve_tts-models.tgz \
  volumes/stt_serve_stt-models.tgz \
  volumes/enhance_serve_enhance-hf.tgz
do
  [ -s "$S/$f" ] || { echo "FEHLER: fehlt/leer: $f"; exit 1; }
done
for f in "$S"/*.tgz "$S"/volumes/*.tgz; do
  tar tzf "$f" >/dev/null
  echo "OK $(basename "$f")"
done
gzip -t "$S/images-v6.0.tar.gz"
echo "OK images-v6.0.tar.gz"

echo "== Container- und Image-Inventar"
for c in \
  telefonki-lisa-1 telefonki-bianca-1 telefonki-bianca-test-1 \
  telefonki-studio-1 telefonki-sipbridge-1 telefonki-sipbridge-lisa-1 \
  telefonki-tunnel-1 telefonki-lisa-public-1 tts_serve-qwen3-1 \
  stt_serve-stt-1 enhance_serve-enhance-1
do
  [ -s "$S/container-inspect/$c.json" ]
  grep -q "^$c|" "$S/freeze-tags.txt"
done
[ -s "$S/vllm-nur-inventar.txt" ]
grep -q 'nicht getaggt, exportiert, gestoppt oder neu gestartet' "$S/vllm-nur-inventar.txt"

echo "== Asterisk-Ersatzbeweis"
(cd "$S" && sha256sum -c extensions_bianca.repo.sha256)
grep -q 'Permission denied' "$S/asterisk-live-zugriff.txt"

echo "== Live-Health und Schreibschutzwachen"
curl -sf http://127.0.0.1:8095/health
echo
curl -sf http://127.0.0.1:8096/health
echo
[ "$(docker exec telefonki-bianca-1 printenv WRITE_LIVE)" = "1" ]
[ "$(grep -c '^CLOUDFLARE_TELEFONKI_TOKEN=' .env)" = "1" ]
[ "$(grep -c '^INTENT_NACHZUG=' .env)" = "1" ]
[ "$(grep -c '^WRITE_LIVE=' .env)" = "1" ]
[ "$(grep -c '^WRITE_LIVE=1' .env)" = "1" ]

echo "== Produktions-Smoke im Live-Container"
docker exec -w /app telefonki-bianca-1 python tools/prod_smoke.py

echo "ABNAHME GRÜN: $S"
