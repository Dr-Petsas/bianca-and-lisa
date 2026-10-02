#!/usr/bin/env bash
# Produktionsstand V6.2 — vollständiger, unterbrechungsfreier Freeze.
#
# Sichert den laufenden TelefonKI-Stack auf pickadoc1 einschließlich Images,
# Containerzuständen, Volumes, Server-Arbeitsbaum, Live-Konfiguration,
# Geheimnissen, Stimmen, Modellen und Host-Einstellungen. Externe vLLM-
# Container werden gemäß Produktionsregel ausschließlich inventarisiert.
set -euo pipefail

VERSION=${VERSION:-v6.2}
STAMP=${STAMP:-20261003}
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
mkdir -p "$TMP"/{container-inspect,container-logs,image-inspect,volumes,networks,host}
chmod 700 "$TMP"
trap 'echo "Freeze abgebrochen; Zwischenstand bleibt unter $TMP"' ERR
cd "$APP"

TELEFONKI_CONTAINER=(
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

echo "== 1/12 Betriebszustand vor dem Freeze"
for c in telefonki-lisa-1 telefonki-bianca-1 telefonki-bianca-test-1 \
         telefonki-studio-1 telefonki-sipbridge-1 telefonki-sipbridge-lisa-1 \
         telefonki-tunnel-1 telefonki-lisa-public-1; do
  [ "$(docker inspect -f '{{.State.Running}}' "$c")" = "true" ] \
    || { echo "FEHLER: Produktionscontainer steht: $c"; exit 1; }
done
curl -sf http://127.0.0.1:8095/health > "$TMP/health-8095.json"
curl -sf http://127.0.0.1:8096/health > "$TMP/health-8096.json"
[ "$(docker exec telefonki-bianca-1 printenv WRITE_LIVE)" = "1" ]
docker exec -w /app telefonki-bianca-1 python tools/prod_smoke.py \
  > "$TMP/prod-smoke.txt"

echo "== 2/12 Live-Bianca als kanonisches V6.2-Image einfrieren"
docker commit --pause=false \
  -m "V6.2 Freeze $STAMP: laufende Live-Bianca inklusive Dateisystemstand" \
  telefonki-bianca-1 "telefonki:$MARKE" >/dev/null
docker tag "telefonki:$MARKE" "telefonki:produktionsstand-v6.2"
docker tag "telefonki:$MARKE" "telefonki:v6.2"
docker image inspect "telefonki:$MARKE" > "$TMP/image-inspect/telefonki-v6.2.json"

echo "== 3/12 Konfiguration, Secrets, Mandanten und Quellstände"
cp -a .env compose.yml Dockerfile .dockerignore requirements.txt "$TMP/"
for f in compose*.yml; do
  [ -f "$f" ] && cp -a "$f" "$TMP/"
done
docker compose config > "$TMP/compose-aufgeloest.yml"
docker compose ls --all > "$TMP/compose-projekte.txt"
docker compose ps -a > "$TMP/compose-telefonki-ps.txt"
tar czf "$TMP/tenants.tgz" tenants
tar czf "$TMP/secrets.tgz" secrets
[ -d tts_serve/stimmen ] && tar czf "$TMP/tts-stimmen.tgz" tts_serve/stimmen
[ -d stt_serve/modell ] && tar czf "$TMP/stt-bind-modell.tgz" stt_serve/modell
cp -a sip_bridge/extensions_bianca.conf "$TMP/extensions_bianca.repo.conf"
sha256sum sip_bridge/extensions_bianca.conf \
  | sed 's#sip_bridge/extensions_bianca.conf#extensions_bianca.repo.conf#' \
  > "$TMP/extensions_bianca.repo.sha256"

# Vollständiger Server-Arbeitsbaum inklusive .git, .env, ignorierter Dateien
# und Diagnosewerkzeuge. Laufzeitdaten der Volumes werden separat gesichert.
tar czf "$TMP/server-source-tree.tgz" \
  --exclude='./.data' \
  --exclude='./_snapshot-produktionsstand-*' \
  --exclude='./app-deploy.zip' \
  --exclude='./app-turnaround-deploy.zip' \
  -C "$APP" .

for d in "$APP/tts_serve" "$APP/stt_serve" /home/cursor/enhance_serve; do
  [ -d "$d" ] || continue
  n=$(basename "$d")
  tar czf "$TMP/source-${n}.tgz" -C "$(dirname "$d")" "$n"
done

# Das lokal erzeugte Bundle enthält den finalen annotierten Git-Tag. Es ist
# zusätzlich zum .git-Verzeichnis im Server-Arbeitsbaum der portable Rückweg.
if [ -s /tmp/telefonki-v6.2.bundle ]; then
  cp -a /tmp/telefonki-v6.2.bundle "$TMP/telefonki-v6.2.bundle"
  git bundle verify "$TMP/telefonki-v6.2.bundle" > "$TMP/git-bundle-verify.txt" 2>&1
else
  echo "FEHLER: /tmp/telefonki-v6.2.bundle fehlt"
  exit 1
fi

echo "== 4/12 Host-, SSH-, Docker- und Netzwerk-Einstellungen"
tar czf "$TMP/host/host-konfiguration.tgz" --ignore-failed-read \
  /etc/docker /etc/systemd/system /etc/ssh/ssh_config /etc/hosts \
  /etc/fstab /etc/netplan /etc/resolv.conf 2> "$TMP/host/host-tar-warnungen.txt" \
  || true
[ -d /home/cursor/.ssh ] \
  && tar czf "$TMP/host/cursor-ssh.tgz" -C /home/cursor .ssh
uname -a > "$TMP/host/uname.txt"
cp -a /etc/os-release "$TMP/host/os-release"
docker info > "$TMP/host/docker-info.txt" 2>&1
systemctl list-unit-files > "$TMP/host/systemd-unit-files.txt" 2>&1 || true
systemctl status docker --no-pager > "$TMP/host/systemd-docker.txt" 2>&1 || true
crontab -l > "$TMP/host/crontab-cursor.txt" 2>&1 || true
ip address > "$TMP/host/ip-address.txt" 2>&1 || true
ip route > "$TMP/host/ip-route.txt" 2>&1 || true
tailscale status > "$TMP/host/tailscale-status.txt" 2>&1 || true
df -h > "$TMP/host/df-h.txt"
lsblk -f > "$TMP/host/lsblk-f.txt"

echo "== 5/12 Live-Asterisk read-only sichern oder Zugriffsausfall belegen"
{
  echo "Live-Asterisk: root@212.132.104.205"
  echo "Versuch: $(date -Is)"
  remote_ip=$(timeout 12 ssh -o BatchMode=yes -o ConnectTimeout=8 \
    root@212.132.104.205 "hostname -I" 2> "$TMP/asterisk-live-fehler.txt" || true)
  echo "hostname-I=${remote_ip:-nicht-lesbar}"
  if [[ "$remote_ip" == *"212.132.104.205"* ]] \
     && timeout 12 ssh -o BatchMode=yes -o ConnectTimeout=8 \
       root@212.132.104.205 "cat /etc/asterisk/extensions_bianca.conf" \
       > "$TMP/extensions_bianca.live.conf" 2>> "$TMP/asterisk-live-fehler.txt"; then
    echo "live=gesichert"
    sha256sum "$TMP/extensions_bianca.live.conf"
  else
    echo "live=nicht-lesbar"
    cat "$TMP/asterisk-live-fehler.txt"
    echo "Rueckfall=extensions_bianca.repo.conf samt SHA-256"
  fi
} > "$TMP/asterisk-live-zugriff.txt"

echo "== 6/12 Container, Startzustände, Logs und exakte Images"
: > "$TMP/freeze-tags.txt"
: > "$TMP/running-at-freeze.txt"
cat > "$TMP/restore-image-tags.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
# Nach docker load ausführen: stellt die von Compose erwarteten Image-Tags her.
EOF
SAVE_TAGS=("telefonki:$MARKE")
for c in "${TELEFONKI_CONTAINER[@]}"; do
  docker inspect "$c" >/dev/null 2>&1 || continue
  docker inspect "$c" > "$TMP/container-inspect/$c.json"
  docker logs --timestamps --tail 4000 "$c" \
    > "$TMP/container-logs/$c.log" 2>&1 || true
  running=$(docker inspect -f '{{.State.Running}}' "$c")
  configured=$(docker inspect -f '{{.Config.Image}}' "$c")
  image_id=$(docker inspect -f '{{.Image}}' "$c")
  service=$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.service" }}' "$c" 2>/dev/null || true)
  [ "$running" = "true" ] && echo "$c|service=$service" >> "$TMP/running-at-freeze.txt"

  slug=${c%-1}
  slug=${slug//_/-}
  freeze_tag="telefonki-freeze:${MARKE}-${slug}"
  if docker image inspect "$image_id" >/dev/null 2>&1 \
     && docker tag "$image_id" "$freeze_tag" 2>/dev/null; then
    quelle=image
  else
    docker image rm "$freeze_tag" >/dev/null 2>&1 || true
    if docker commit --pause=false \
      -m "V6.2 Freeze $STAMP: $c, ursprünglicher Layer nicht mehr vorhanden" \
      "$c" "$freeze_tag" >/dev/null 2>&1; then
      quelle=container-commit
    else
      docker image rm "$freeze_tag" >/dev/null 2>&1 || true
      docker export "$c" | docker import - "$freeze_tag" >/dev/null
      quelle=container-export-import
    fi
  fi
  docker image inspect "$freeze_tag" > "$TMP/image-inspect/$slug.json"
  echo "$c|running=$running|service=$service|configured=$configured|live=$image_id|freeze=$freeze_tag|quelle=$quelle" \
    >> "$TMP/freeze-tags.txt"
  SAVE_TAGS+=("$freeze_tag")
  if [[ "$configured" != sha256:* && "$configured" == *:* ]]; then
    printf 'docker tag %q %q\n' "$freeze_tag" "$configured" \
      >> "$TMP/restore-image-tags.sh"
  fi
done
chmod 700 "$TMP/restore-image-tags.sh"

echo "== 7/12 Reproduzierbare Images als ladbares Archiv"
docker save "${SAVE_TAGS[@]}" | gzip -1 > "$TMP/images-v6.2.tar.gz"
gzip -t "$TMP/images-v6.2.tar.gz"

echo "== 8/12 Alle TelefonKI-, Sprach- und Modellvolumes"
mapfile -t VOLUMES < <(
  docker volume ls --format '{{.Name}}' \
    | grep -E '^(telefonki_|tts_serve_|stt_serve_|enhance_serve_|app_telefonki-data$)' \
    || true
)
: > "$TMP/volumes/gesicherte-volumes.txt"
for v in "${VOLUMES[@]}"; do
  [ -n "$v" ] || continue
  docker volume inspect "$v" > "$TMP/volumes/$v.inspect.json"
  docker run --rm -v "$v":/v:ro -v "$TMP/volumes":/out alpine:3.20 \
    sh -c "tar czf /out/$v.tgz -C /v . && chown $EIGNER /out/$v.tgz && chmod 600 /out/$v.tgz"
  echo "$v" >> "$TMP/volumes/gesicherte-volumes.txt"
done
cat > "$TMP/restore-volumes.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[ "${CONFIRM_VOLUME_RESTORE:-}" = "YES" ] || {
  echo "Abbruch: CONFIRM_VOLUME_RESTORE=YES setzen. Betroffene Dienste vorher stoppen."
  exit 2
}
S="$(cd "$(dirname "$0")" && pwd)"
while IFS= read -r v; do
  [ -n "$v" ] || continue
  docker volume create "$v" >/dev/null
  docker run --rm -v "$v":/v -v "$S/volumes":/in:ro alpine:3.20 \
    sh -c "rm -rf /v/* /v/.[!.]* /v/..?* 2>/dev/null || true; tar xzf /in/$v.tgz -C /v"
  echo "wiederhergestellt: $v"
done < "$S/volumes/gesicherte-volumes.txt"
EOF
chmod 700 "$TMP/restore-volumes.sh"

echo "== 9/12 Docker-Netzwerke und externer vLLM nur read-only"
for n in telefonki_default tts_serve_default stt_serve_default enhance_serve_default bridge; do
  docker network inspect "$n" > "$TMP/networks/$n.json" 2>/dev/null || true
done
for c in pickadoc-vllm-1 pickadoc-vllm-vl-1 pickadoc-llm-proxy; do
  docker inspect "$c" > "$TMP/container-inspect/$c.json" 2>/dev/null || true
done
docker image inspect vllm/vllm-openai:latest \
  > "$TMP/image-inspect/vllm-external.json" 2>/dev/null || true
{
  echo "vLLM wurde nicht getaggt, exportiert, gestartet, gestoppt oder neu gestartet."
  echo
  for c in pickadoc-vllm-1 pickadoc-vllm-vl-1 pickadoc-llm-proxy; do
    docker inspect -f 'container={{.Name}} running={{.State.Running}} image={{.Image}} args={{json .Config.Cmd}} mounts={{json .Mounts}}' \
      "$c" 2>/dev/null || true
  done
} > "$TMP/vllm-nur-inventar.txt"

echo "== 10/12 Parität, Inventare und Wiederanlauf-Skript"
live_hash=$(docker exec telefonki-bianca-1 sh -c \
  'cd /app && find kern bianca -name "*.py" -exec sha256sum {} + | sort | sha256sum' | awk '{print $1}')
image_hash=$(docker run --rm --entrypoint sh "telefonki:$MARKE" -c \
  'cd /app && find kern bianca -name "*.py" -exec sha256sum {} + | sort | sha256sum' | awk '{print $1}')
[ "$live_hash" = "$image_hash" ]
printf 'live=%s\nfreeze=%s\n' "$live_hash" "$image_hash" > "$TMP/code-paritaet.txt"
docker ps -a --no-trunc > "$TMP/docker-ps-a.txt"
docker images --no-trunc > "$TMP/docker-images.txt"
docker volume ls > "$TMP/docker-volumes.txt"
docker network ls > "$TMP/docker-networks.txt"
git status --short > "$TMP/server-git-status.txt" 2>&1 || true
git rev-parse HEAD > "$TMP/server-git-head.txt" 2>&1 || true
{
  echo "WRITE_LIVE=$(docker exec telefonki-bianca-1 printenv WRITE_LIVE)"
  echo "NAMENS_LINK=$(docker exec telefonki-bianca-1 printenv NAMENS_LINK 2>/dev/null || true)"
  echo "INTENT_NACHZUG=$(docker exec telefonki-bianca-1 printenv INTENT_NACHZUG 2>/dev/null || true)"
  echo "CLOUDFLARE_TELEFONKI_TOKEN-Zeilen=$(grep -c '^CLOUDFLARE_TELEFONKI_TOKEN=' .env || true)"
  echo "INTENT_NACHZUG-Zeilen=$(grep -c '^INTENT_NACHZUG=' .env || true)"
  echo "WRITE_LIVE-Zeilen=$(grep -c '^WRITE_LIVE=' .env || true)"
  echo "NAMENS_LINK-Zeilen=$(grep -c '^NAMENS_LINK=' .env || true)"
} > "$TMP/betriebswachen.txt"

mapfile -t RUN_SERVICES < <(
  awk -F'[|=]' '$2=="service" && $3!="" {print $3}' "$TMP/running-at-freeze.txt"
)
{
  echo '#!/usr/bin/env bash'
  echo 'set -euo pipefail'
  echo 'cd /home/cursor/telefonki'
  printf 'docker compose up -d --no-build'
  printf ' %q' "${RUN_SERVICES[@]}"
  echo
} > "$TMP/restore-running-services.sh"
chmod 700 "$TMP/restore-running-services.sh"

echo "== 11/12 Archive testlesen, Inventar und Prüfsummen"
for f in "$TMP"/*.tgz "$TMP"/host/*.tgz "$TMP"/volumes/*.tgz; do
  [ -f "$f" ] || continue
  tar tzf "$f" >/dev/null
done
{
  echo "Produktionsstand $VERSION"
  echo "Erzeugt: $(date -Is)"
  echo "Marke: $MARKE"
  echo "Live-Bianca: $(docker inspect -f '{{.Config.Image}} {{.Image}}' telefonki-bianca-1)"
  echo "Freeze-Bianca: $(docker image inspect -f '{{.Id}}' "telefonki:$MARKE")"
  echo "Code-Parität: $live_hash"
  echo
  echo "Container:"
  cat "$TMP/freeze-tags.txt"
  echo
  echo "Volumes:"
  cat "$TMP/volumes/gesicherte-volumes.txt"
  echo
  echo "Dateien:"
  find "$TMP" -type f -printf '%s %p\n' | sort -n
  echo
  echo "Platte:"
  df -h /home
} > "$TMP/inventar.txt"
(cd "$TMP" && find . -type f ! -name SHA256SUMS -print0 \
  | sort -z | xargs -0 sha256sum > SHA256SUMS)
(cd "$TMP" && sha256sum -c SHA256SUMS >/dev/null)

echo "== 12/12 Sicher schützen und atomar veröffentlichen"
chmod -R go-rwx "$TMP"
mv "$TMP" "$ZIEL"
trap - ERR
rm -f /tmp/telefonki-v6.2.bundle
echo "FERTIG: $ZIEL"
du -sh "$ZIEL"
