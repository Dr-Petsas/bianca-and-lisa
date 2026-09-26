#!/usr/bin/env bash
# Produktionsstand V6.0 — vollständiger, unterbrechungsfreier Freeze.
# Kein Container wird gestoppt oder neu gestartet. vLLM wird nur inventarisiert.
set -euo pipefail

VERSION=${VERSION:-v6.0}
STAMP=${STAMP:-20260926}
MARKE="produktionsstand-$VERSION-$STAMP"
APP=/home/cursor/telefonki
BACKUPS=/home/cursor/telefonki-backups
ZIEL="$BACKUPS/$MARKE"
TMP="$BACKUPS/.${MARKE}.tmp.$$"
EIGNER="$(id -u):$(id -g)"

if [ -e "$ZIEL" ]; then
  echo "FEHLER: Ziel existiert bereits: $ZIEL"
  exit 1
fi
rm -rf "$TMP"
mkdir -p "$TMP"/{container-inspect,container-logs,image-inspect,volumes}
trap 'echo "Freeze abgebrochen; Zwischenstand bleibt unter $TMP"' ERR
cd "$APP"

echo "== 1/10 Live-Bianca einfrieren"
docker inspect telefonki-bianca-1 >/dev/null
docker commit --pause=false \
  -m "V6.0 Freeze $STAMP: laufende Live-Bianca inklusive Dateisystem-Patches" \
  telefonki-bianca-1 "telefonki:$MARKE" >/dev/null
docker tag "telefonki:$MARKE" telefonki:produktionsstand-v6.0
docker tag "telefonki:$MARKE" telefonki:v6.0
docker inspect "telefonki:$MARKE" > "$TMP/image-inspect/telefonki-v6.0.json"

echo "== 2/10 Konfiguration, Geheimnisse und Quellstände"
cp -a .env compose.yml Dockerfile .dockerignore requirements.txt "$TMP/"
for f in compose*.yml; do
  [ -f "$f" ] && cp -a "$f" "$TMP/"
done
docker compose config > "$TMP/compose-aufgeloest.yml"
tar czf "$TMP/tenants.tgz" tenants
tar czf "$TMP/secrets.tgz" secrets
[ -d tts_serve/stimmen ] && tar czf "$TMP/tts-stimmen.tgz" tts_serve/stimmen
[ -d stt_serve/modell ] && tar czf "$TMP/stt-bind-modell.tgz" stt_serve/modell
cp -a sip_bridge/extensions_bianca.conf "$TMP/extensions_bianca.repo.conf"
sha256sum sip_bridge/extensions_bianca.conf \
  | sed 's#sip_bridge/extensions_bianca.conf#extensions_bianca.repo.conf#' \
  > "$TMP/extensions_bianca.repo.sha256"
cat > "$TMP/asterisk-live-zugriff.txt" <<'EOF'
Live-Asterisk: root@212.132.104.205
Der SSH-Zugriff vom Entwicklungsrechner war beim V6.0-Freeze nicht
autorisiert (Permission denied (publickey)). Gemäß Freigabe wurde deshalb
die Repo-Referenz extensions_bianca.repo.conf mit SHA-256 gesichert.
EOF

# Kompletter Server-Arbeitsbaum einschließlich .git, .env und ignorierter
# Dateien. Laufzeitdaten aus Docker-Volumes werden separat konsistent gepackt.
tar czf "$TMP/server-source-tree.tgz" \
  --exclude='./.data' \
  --exclude='./_snapshot-produktionsstand-*' \
  --exclude='./app-deploy.zip' \
  -C "$APP" .

for d in "$APP/tts_serve" "$APP/stt_serve" /home/cursor/enhance_serve; do
  [ -d "$d" ] || continue
  n=$(basename "$d")
  tar czf "$TMP/source-${n}.tgz" -C "$(dirname "$d")" "$n"
done

echo "== 3/10 Laufende Container und exakte Images erfassen"
CONTAINER=(
  telefonki-lisa-1
  telefonki-bianca-1
  telefonki-bianca-test-1
  telefonki-studio-1
  telefonki-sipbridge-1
  telefonki-sipbridge-lisa-1
  telefonki-tunnel-1
  telefonki-lisa-public-1
  telefonki-bianca-v26-1
  tts_serve-qwen3-1
  stt_serve-stt-1
  enhance_serve-enhance-1
)
: > "$TMP/freeze-tags.txt"
SAVE_TAGS=("telefonki:$MARKE")
for c in "${CONTAINER[@]}"; do
  docker inspect "$c" > "$TMP/container-inspect/$c.json"
  docker logs --timestamps --tail 2000 "$c" > "$TMP/container-logs/$c.log" 2>&1 || true
  image_id=$(docker inspect -f '{{.Image}}' "$c")
  configured=$(docker inspect -f '{{.Config.Image}}' "$c")
  slug=${c%-1}
  slug=${slug//_/-}
  freeze_tag="telefonki-freeze:${MARKE}-${slug}"
  if docker image inspect "$image_id" >/dev/null 2>&1 \
     && docker tag "$image_id" "$freeze_tag" 2>/dev/null \
     && docker image inspect "$freeze_tag" >/dev/null 2>&1; then
    quelle="image"
  else
    docker image rm "$freeze_tag" >/dev/null 2>&1 || true
    if docker commit --pause=false \
      -m "V6.0 Freeze $STAMP: $c, ursprünglicher Layer nicht mehr vorhanden" \
      "$c" "$freeze_tag" >/dev/null 2>&1 \
      && docker image inspect "$freeze_tag" >/dev/null 2>&1; then
      quelle="container-commit"
    else
      # Ein laufender Container kann noch lesbar sein, obwohl Docker einen
      # alten Basis-Layer bereits verloren hat. Export/Import konserviert in
      # diesem Fall sein vollständiges Root-Dateisystem als flaches Image;
      # Entrypoint, Cmd, Env und Mounts bleiben im Container-Inspect erhalten.
      docker image rm "$freeze_tag" >/dev/null 2>&1 || true
      docker export "$c" | docker import - "$freeze_tag" >/dev/null
      quelle="container-export-import"
    fi
  fi
  docker image inspect "$freeze_tag" > "$TMP/image-inspect/$slug.json"
  echo "$c|configured=$configured|live=$image_id|freeze=$freeze_tag|quelle=$quelle" \
    >> "$TMP/freeze-tags.txt"
  SAVE_TAGS+=("$freeze_tag")
done

echo "== 4/10 Alle reproduzierbaren Images als Tar sichern"
docker save "${SAVE_TAGS[@]}" | gzip -1 > "$TMP/images-v6.0.tar.gz"
gzip -t "$TMP/images-v6.0.tar.gz"

echo "== 5/10 Laufzeit- und Modellvolumes sichern"
VOLUMES=(
  telefonki_telefonki-data
  telefonki_telefonki-berichte
  telefonki_telefonki-klang
  tts_serve_tts-models
  stt_serve_stt-models
  enhance_serve_enhance-hf
)
for v in "${VOLUMES[@]}"; do
  docker volume inspect "$v" > "$TMP/volumes/$v.inspect.json"
  docker run --rm -v "$v":/v:ro -v "$TMP/volumes":/out alpine:3.20 \
    sh -c "tar czf /out/$v.tgz -C /v . && chown $EIGNER /out/$v.tgz && chmod 600 /out/$v.tgz"
done

echo "== 6/10 Externes vLLM ausschließlich inventarisieren"
for c in pickadoc-vllm-1 pickadoc-vllm-vl-1 pickadoc-llm-proxy; do
  docker inspect "$c" > "$TMP/container-inspect/$c.json" 2>/dev/null || true
done
docker image inspect vllm/vllm-openai:latest > "$TMP/image-inspect/vllm-external.json" 2>/dev/null || true
{
  echo "vLLM wurde nicht getaggt, exportiert, gestoppt oder neu gestartet."
  echo
  docker inspect -f 'container={{.Name}} image={{.Image}} args={{json .Config.Cmd}} mounts={{json .Mounts}}' \
    pickadoc-vllm-1 2>/dev/null || true
} > "$TMP/vllm-nur-inventar.txt"

echo "== 7/10 Live-Code-Parität und Betriebszustand"
live_hash=$(docker exec telefonki-bianca-1 sh -c \
  'cd /app && find kern bianca -name "*.py" -exec sha256sum {} + | sort | sha256sum' | awk '{print $1}')
image_hash=$(docker run --rm --entrypoint sh "telefonki:$MARKE" -c \
  'cd /app && find kern bianca -name "*.py" -exec sha256sum {} + | sort | sha256sum' | awk '{print $1}')
[ "$live_hash" = "$image_hash" ]
{
  echo "live=$live_hash"
  echo "freeze=$image_hash"
} > "$TMP/code-paritaet.txt"
docker ps -a --no-trunc > "$TMP/docker-ps-a.txt"
docker images --no-trunc > "$TMP/docker-images.txt"
docker volume ls > "$TMP/docker-volumes.txt"
git status --short > "$TMP/server-git-status.txt" 2>&1 || true
git rev-parse HEAD > "$TMP/server-git-head.txt" 2>&1 || true
{
  echo "WRITE_LIVE=$(docker exec telefonki-bianca-1 printenv WRITE_LIVE)"
  echo "INTENT_NACHZUG=$(docker exec telefonki-bianca-1 printenv INTENT_NACHZUG 2>/dev/null || true)"
  echo "CLOUDFLARE_TELEFONKI_TOKEN-Zeilen=$(grep -c '^CLOUDFLARE_TELEFONKI_TOKEN=' .env || true)"
  echo "INTENT_NACHZUG-Zeilen=$(grep -c '^INTENT_NACHZUG=' .env || true)"
  echo "WRITE_LIVE-Zeilen=$(grep -c '^WRITE_LIVE=' .env || true)"
} > "$TMP/betriebswachen.txt"
curl -sf http://127.0.0.1:8095/health > "$TMP/health-8095.json"
curl -sf http://127.0.0.1:8096/health > "$TMP/health-8096.json"

echo "== 8/10 Archive testlesen"
for f in "$TMP"/*.tgz "$TMP"/volumes/*.tgz; do
  [ -f "$f" ] || continue
  tar tzf "$f" >/dev/null
done

echo "== 9/10 Inventar und Prüfsummen"
{
  echo "Produktionsstand $VERSION"
  echo "Erzeugt: $(date -Is)"
  echo "Marke: $MARKE"
  echo "Live-Bianca vor docker commit: $(docker inspect -f '{{.Config.Image}} {{.Image}}' telefonki-bianca-1)"
  echo "Freeze-Bianca: $(docker image inspect -f '{{.Id}}' "telefonki:$MARKE")"
  echo "Code-Parität: $live_hash"
  echo
  echo "Container:"
  cat "$TMP/freeze-tags.txt"
  echo
  echo "Dateien:"
  find "$TMP" -type f -printf '%s %p\n' | sort -n
  echo
  echo "Platte:"
  df -h /home
} > "$TMP/inventar.txt"
(cd "$TMP" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)

echo "== 10/10 Atomar veröffentlichen"
(cd "$TMP" && sha256sum -c SHA256SUMS >/dev/null)
chmod 700 "$TMP"
chmod 600 "$TMP/.env" "$TMP/secrets.tgz" "$TMP"/volumes/*.tgz
mv "$TMP" "$ZIEL"
trap - ERR
echo "FERTIG: $ZIEL"
du -sh "$ZIEL"
