#!/usr/bin/env bash
# Harte, read-only Abnahme des vollständigen Produktionsstands V6.2.
set -euo pipefail

VERSION=${VERSION:-v6.2}
STAMP=${STAMP:-20261003}
MARKE="produktionsstand-$VERSION-$STAMP"
S="/home/cursor/telefonki-backups/$MARKE"
cd /home/cursor/telefonki

echo "== Abnahme $MARKE"
[ -d "$S" ]
[ -s "$S/SHA256SUMS" ]

echo "== Prüfsummen"
(cd "$S" && sha256sum -c SHA256SUMS)

echo "== Kanonische Freeze-Tags"
for tag in \
  "telefonki:$MARKE" \
  telefonki:produktionsstand-v6.2 \
  telefonki:v6.2
do
  docker image inspect "$tag" >/dev/null
  echo "OK $tag = $(docker image inspect -f '{{.Id}}' "$tag")"
done

echo "== Live-Code entspricht dem Freeze-Image"
live_hash=$(docker exec telefonki-bianca-1 sh -c \
  'cd /app && find kern bianca -name "*.py" -exec sha256sum {} + | sort | sha256sum' | awk '{print $1}')
image_hash=$(docker run --rm --entrypoint sh "telefonki:$MARKE" -c \
  'cd /app && find kern bianca -name "*.py" -exec sha256sum {} + | sort | sha256sum' | awk '{print $1}')
[ "$live_hash" = "$image_hash" ]
grep -qx "live=$live_hash" "$S/code-paritaet.txt"
grep -qx "freeze=$image_hash" "$S/code-paritaet.txt"
echo "OK $live_hash"

echo "== Git-Bundle und vollständige Archive"
bundle_repo=$(mktemp -d)
git init --bare -q "$bundle_repo"
git -C "$bundle_repo" bundle verify "$S/telefonki-v6.2.bundle"
rm -rf "$bundle_repo"
for f in \
  tenants.tgz \
  secrets.tgz \
  tts-stimmen.tgz \
  stt-bind-modell.tgz \
  server-source-tree.tgz \
  images-v6.2.tar.gz \
  host/host-konfiguration.tgz \
  host/cursor-ssh.tgz
do
  [ -s "$S/$f" ] || { echo "FEHLER: fehlt/leer: $f"; exit 1; }
done
for f in "$S"/*.tgz "$S"/host/*.tgz "$S"/volumes/*.tgz; do
  [ -f "$f" ] || continue
  tar tzf "$f" >/dev/null
  echo "OK ${f#$S/}"
done
gzip -t "$S/images-v6.2.tar.gz"
echo "OK images-v6.2.tar.gz"

echo "== Alle aufgezeichneten Volumes vorhanden"
while IFS= read -r v; do
  [ -n "$v" ] || continue
  [ -s "$S/volumes/$v.tgz" ]
  [ -s "$S/volumes/$v.inspect.json" ]
  tar tzf "$S/volumes/$v.tgz" >/dev/null
  echo "OK $v"
done < "$S/volumes/gesicherte-volumes.txt"

echo "== Container-, Image- und Netzwerk-Inventar"
for c in \
  telefonki-lisa-1 \
  telefonki-bianca-1 \
  telefonki-bianca-test-1 \
  telefonki-studio-1 \
  telefonki-sipbridge-1 \
  telefonki-sipbridge-lisa-1 \
  telefonki-tunnel-1 \
  telefonki-lisa-public-1
do
  [ -s "$S/container-inspect/$c.json" ]
  grep -q "^$c|" "$S/freeze-tags.txt"
  [ "$(docker inspect -f '{{.State.Running}}' "$c")" = "true" ]
  echo "OK $c läuft"
done
for n in telefonki_default bridge; do
  [ -s "$S/networks/$n.json" ]
done
[ -s "$S/vllm-nur-inventar.txt" ]
grep -q 'nicht getaggt, exportiert, gestartet, gestoppt oder neu gestartet' \
  "$S/vllm-nur-inventar.txt"

echo "== Rollback-Skripte vollständig"
for f in restore-image-tags.sh restore-volumes.sh restore-running-services.sh; do
  [ -s "$S/$f" ] && [ -x "$S/$f" ]
done
grep -q 'docker compose up -d --no-build' "$S/restore-running-services.sh"
grep -q 'CONFIRM_VOLUME_RESTORE' "$S/restore-volumes.sh"

echo "== Asterisk-Beweis"
(cd "$S" && sha256sum -c extensions_bianca.repo.sha256)
if grep -q '^live=gesichert$' "$S/asterisk-live-zugriff.txt"; then
  [ -s "$S/extensions_bianca.live.conf" ]
  echo "OK Live-Dialplan gesichert"
else
  grep -q '^live=nicht-lesbar$' "$S/asterisk-live-zugriff.txt"
  grep -q 'Rueckfall=extensions_bianca.repo.conf' "$S/asterisk-live-zugriff.txt"
  echo "OK Zugriffsausfall dokumentiert, Repo-Dialplan gesichert"
fi

echo "== Live-Health, Brücken und Schreibwachen"
curl -sf http://127.0.0.1:8095/health >/dev/null
curl -sf http://127.0.0.1:8096/health >/dev/null
[ "$(docker exec telefonki-bianca-1 printenv WRITE_LIVE)" = "1" ]
[ "$(grep -c '^CLOUDFLARE_TELEFONKI_TOKEN=' .env)" = "1" ]
[ "$(grep -c '^INTENT_NACHZUG=' .env)" = "1" ]
[ "$(grep -c '^WRITE_LIVE=' .env)" = "1" ]
[ "$(grep -c '^WRITE_LIVE=1' .env)" = "1" ]
[ "$(grep -c '^NAMENS_LINK=' .env)" = "1" ]
[ "$(grep -c '^NAMENS_LINK=0' .env)" = "1" ]
for c in telefonki-lisa-1 telefonki-bianca-1 telefonki-bianca-test-1 \
         telefonki-studio-1 telefonki-sipbridge-1 telefonki-sipbridge-lisa-1; do
  [ "$(docker inspect -f '{{.State.Health.Status}}' "$c")" = "healthy" ]
done

echo "== V6.2-Produktmarker"
docker exec -i telefonki-bianca-1 python - <<'PY'
from pathlib import Path

flow = Path("/app/bianca/flow.py").read_text(encoding="utf-8")
gehirn = Path("/app/bianca/gehirn.py").read_text(encoding="utf-8")
html = Path("/app/bianca_web/index.html").read_text(encoding="utf-8")
assert "anrufer-check-erklaert" in flow
assert "_ist_sicher_keine_namensantwort" in gehirn
assert "app.js?v=b89" in html
print("OK Audio-Turnaround-Fixes und Cache-Buster")
PY

echo "== Produktions-Smoke im Live-Container"
docker exec -w /app telefonki-bianca-1 python tools/prod_smoke.py

echo "ABNAHME GRÜN: $S"
