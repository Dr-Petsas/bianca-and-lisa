#!/usr/bin/env bash
# Produktionsstand V4 — 20.09.2026.
# Friert die V2.6-Canary (telefonki-bianca-v26-1) mit allen docker-cp-Patches
# als eigenes Image ein. Kein Container wird gestoppt. .env wird nur kopiert.
set -euo pipefail
VERSION=${VERSION:-v4}
STAMP=${STAMP:-$(date +%Y%m%d)}
MARKE="produktionsstand-$VERSION-$STAMP"
ZIEL=/home/cursor/telefonki-backups/$MARKE
APP=/home/cursor/telefonki
mkdir -p "$ZIEL"
cd "$APP"

echo "== 0/6 V2.6-Canary als eigenes V4-Image committen"
if ! docker inspect telefonki-bianca-v26-1 >/dev/null 2>&1; then
  echo "FEHLER: telefonki-bianca-v26-1 laeuft nicht — ohne dieses Image gibt es kein V4."
  exit 1
fi
docker commit \
  -m "V4 Freeze $STAMP: V2.6 plus Wunschzeit, Neusuche, SMS-Abschluss, Dokumente persoenlich" \
  telefonki-bianca-v26-1 \
  "telefonki:$MARKE"
docker tag "telefonki:$MARKE" telefonki:produktionsstand-v4
docker tag "telefonki:$MARKE" "telefonki:v4"
echo "  v26 -> telefonki:$MARKE"

echo "== 1/6 Einstellungen und Geheimnisse"
cp -a .env "$ZIEL/.env"
cp -a compose.yml "$ZIEL/compose.yml"
tar czf "$ZIEL/tenants.tgz" tenants
tar czf "$ZIEL/secrets.tgz" secrets
for s in tts_serve stt_serve; do
  [ -f "$s/compose.yml" ] && cp -a "$s/compose.yml" "$ZIEL/compose-$s.yml"
  [ -f "$s/.env" ] && cp -a "$s/.env" "$ZIEL/env-$s"
done
[ -d tts_serve/stimmen ] && tar czf "$ZIEL/tts-stimmen.tgz" tts_serve/stimmen
[ -f sip_bridge/extensions_bianca.conf ] && cp -a sip_bridge/extensions_bianca.conf "$ZIEL/extensions_bianca.conf"
# Laufende Canary-Quellen zusätzlich als Dateibaum (ohne .data)
docker cp telefonki-bianca-v26-1:/app/bianca "$ZIEL/v26-bianca"
docker cp telefonki-bianca-v26-1:/app/kern "$ZIEL/v26-kern"
docker cp telefonki-bianca-v26-1:/app/sip_bridge "$ZIEL/v26-sip_bridge" 2>/dev/null || true
tar czf "$ZIEL/v26-app-code.tgz" -C "$ZIEL" v26-bianca v26-kern
# Host-Compose-Profil v26, falls vorhanden
grep -n "bianca-v26\|BRIDGE_ALT\|8099" compose.yml > "$ZIEL/v26-compose-stellen.txt" || true

echo "== 2/6 Aufgeloeste Compose-Konfiguration"
docker compose config > "$ZIEL/compose-aufgeloest.yml" 2>/dev/null || true
docker compose --profile v26 config > "$ZIEL/compose-v26-aufgeloest.yml" 2>/dev/null || true

echo "== 3/6 Volumes sichern"
EIGNER="$(id -u):$(id -g)"
for v in telefonki_telefonki-data telefonki_telefonki-berichte telefonki_telefonki-klang; do
  docker run --rm -v "$v":/v -v "$ZIEL":/ziel alpine:3.20 \
    sh -c "tar czf /ziel/volume-$v.tgz -C /v . && chown $EIGNER /ziel/volume-$v.tgz && chmod 600 /ziel/volume-$v.tgz" \
    || echo "  (uebersprungen: $v)"
  echo "  $v -> volume-$v.tgz"
done

echo "== 4/6 Laufende Images taggen und V4 speichern"
: > "$ZIEL/images.txt"
# Zuerst die Canary — das IST V4.
echo "telefonki-bianca-v26-1 | laeuft-als=telefonki:produktionsstand-v2.6-20260914 | gesichert-als=telefonki:$MARKE (docker commit)" >> "$ZIEL/images.txt"
# Live-8096 (Dialogkern) extra, damit nichts verloren geht.
live_id=$(docker inspect -f '{{.Image}}' telefonki-bianca-1 2>/dev/null || true)
if [ -n "${live_id:-}" ]; then
  docker tag "$live_id" "telefonki:$MARKE-live8096" 2>/dev/null \
    && echo "telefonki-bianca-1 | image=$live_id | gesichert-als=telefonki:$MARKE-live8096" >> "$ZIEL/images.txt" \
    || echo "telefonki-bianca-1 | image=$live_id | kein Tag" >> "$ZIEL/images.txt"
fi
for c in telefonki-lisa-1 telefonki-bianca-test-1 telefonki-studio-1 \
         telefonki-sipbridge-1 telefonki-sipbridge-lisa-1 telefonki-tunnel-1 \
         telefonki-lisa-public-1 tts_serve-qwen3-1 stt_serve-stt-1; do
  id=$(docker inspect -f '{{.Image}}' "$c" 2>/dev/null) || continue
  [ -z "$id" ] && continue
  name=$(docker inspect -f '{{.Config.Image}}' "$c" 2>/dev/null)
  neu="$(echo "$name" | cut -d: -f1):$MARKE"
  vorhanden=$(docker inspect -f '{{.Id}}' "$neu" 2>/dev/null || true)
  if [ -n "${vorhanden:-}" ] && [ "$vorhanden" != "$id" ]; then
    kurz=$(echo "$c" | sed 's/^telefonki-//; s/-1$//; s/_serve-//; s/-1$//')
    neu="$neu-$kurz"
  fi
  if docker tag "$id" "$neu" 2>/dev/null; then
    echo "  $c -> $neu"
    echo "$c | laeuft-als=$name | image=$id | gesichert-als=$neu" >> "$ZIEL/images.txt"
  else
    echo "  $c -> KEIN Tag (Layer weg)"
    echo "$c | laeuft-als=$name | image=$id | kein Tag moeglich" >> "$ZIEL/images.txt"
  fi
done

echo "== 5/6 V4-Image als Tar (ladbar ohne Registry)"
docker save "telefonki:$MARKE" | gzip > "$ZIEL/image-bianca-v4.tar.gz"
chmod 640 "$ZIEL/image-bianca-v4.tar.gz"
ls -lh "$ZIEL/image-bianca-v4.tar.gz"

echo "== 6/6 Inventar"
{
  echo "Produktionsstand $VERSION — Schnappschuss $(date -Is)"
  echo
  echo "## V4-Kern"
  echo "telefonki-bianca-v26-1 committet nach telefonki:$MARKE"
  docker inspect -f 'v26 Image nach Commit: {{.Id}}' "telefonki:$MARKE"
  echo
  echo "## Container (laufend)"
  docker ps --format '{{.Names}} | {{.Image}} | {{.Status}} | {{.Ports}}'
  echo
  echo "## Gesicherte Images"
  docker images --format '{{.Repository}}:{{.Tag}} {{.ID}} {{.Size}}' | grep "$MARKE" || true
  echo
  echo "## Health 8096 / 8095 / 8099"
  curl -sf http://127.0.0.1:8096/health || true; echo
  curl -sf http://127.0.0.1:8095/health || true; echo
  curl -sf http://127.0.0.1:8099/health || true; echo
  echo
  echo "## .env-Schluessel (nur Namen)"
  grep -oE '^[A-Z0-9_]+' .env | sort
  echo
  echo "## Gesicherte Dateien"
  ls -la "$ZIEL"
  echo
  echo "## Plattenbelegung"
  df -h /home | tail -1
} > "$ZIEL/inventar.txt" 2>&1

chmod 700 "$ZIEL"
chmod 600 "$ZIEL"/.env "$ZIEL"/env-* "$ZIEL"/secrets.tgz 2>/dev/null || true
echo
echo "FERTIG: $ZIEL"
du -sh "$ZIEL"
ls -la "$ZIEL"
