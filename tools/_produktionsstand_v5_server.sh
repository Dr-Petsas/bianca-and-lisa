#!/usr/bin/env bash
# Produktionsstand V5 — 21.09.2026.
# Friert den LAUFENDEN Live-Mund (telefonki-bianca-1) inklusive aller
# docker-cp-Patches (Anrede/Hainz, ersatz.py, Verwaltungs-Quittung).
# Kein Container wird gestoppt. .env wird nur kopiert, nie ueberschrieben.
set -euo pipefail
VERSION=${VERSION:-v5}
STAMP=${STAMP:-$(date +%Y%m%d)}
MARKE="produktionsstand-$VERSION-$STAMP"
ZIEL=/home/cursor/telefonki-backups/$MARKE
APP=/home/cursor/telefonki
mkdir -p "$ZIEL"
cd "$APP"

echo "== 0/7 Live-8096 als eigenes V5-Image committen"
if ! docker inspect telefonki-bianca-1 >/dev/null 2>&1; then
  echo "FEHLER: telefonki-bianca-1 laeuft nicht — ohne diesen Mund gibt es kein V5."
  exit 1
fi
docker commit \
  -m "V5 Freeze $STAMP: Live-8096 plus Anrede Herr/Frau, erkannt_satz, Geschlecht-Kartei, ersatz.py, name_quittung" \
  telefonki-bianca-1 \
  "telefonki:$MARKE"
docker tag "telefonki:$MARKE" telefonki:produktionsstand-v5
docker tag "telefonki:$MARKE" telefonki:v5
echo "  bianca-1 -> telefonki:$MARKE"

if docker inspect telefonki-bianca-v26-1 >/dev/null 2>&1; then
  docker commit \
    -m "V5 Freeze $STAMP: V2.6-Canary unveraendert mitgesichert" \
    telefonki-bianca-v26-1 \
    "telefonki:$MARKE-v26"
  echo "  v26 -> telefonki:$MARKE-v26"
fi

echo "== 1/7 Einstellungen und Geheimnisse"
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
[ -f sip_bridge/server.py ] && cp -a sip_bridge/server.py "$ZIEL/sip_bridge_server.py"

# Laufende Live-Quellen als Dateibaum (ohne .data)
docker cp telefonki-bianca-1:/app/bianca "$ZIEL/live-bianca"
docker cp telefonki-bianca-1:/app/kern "$ZIEL/live-kern"
docker cp telefonki-bianca-1:/app/lisa "$ZIEL/live-lisa" 2>/dev/null || true
docker cp telefonki-bianca-1:/app/sip_bridge "$ZIEL/live-sip_bridge" 2>/dev/null || true
tar czf "$ZIEL/live-app-code.tgz" -C "$ZIEL" live-bianca live-kern
if docker inspect telefonki-bianca-v26-1 >/dev/null 2>&1; then
  docker cp telefonki-bianca-v26-1:/app/bianca "$ZIEL/v26-bianca"
  docker cp telefonki-bianca-v26-1:/app/kern "$ZIEL/v26-kern"
  tar czf "$ZIEL/v26-app-code.tgz" -C "$ZIEL" v26-bianca v26-kern
fi
grep -n "bianca-v26\|BRIDGE_ALT\|8099\|CONTROLLER_" compose.yml > "$ZIEL/compose-stellen.txt" || true

echo "== 2/7 Aufgeloeste Compose-Konfiguration"
docker compose config > "$ZIEL/compose-aufgeloest.yml" 2>/dev/null || true
docker compose --profile v26 config > "$ZIEL/compose-v26-aufgeloest.yml" 2>/dev/null || true

echo "== 3/7 Volumes sichern"
EIGNER="$(id -u):$(id -g)"
for v in telefonki_telefonki-data telefonki_telefonki-berichte telefonki_telefonki-klang; do
  docker run --rm -v "$v":/v -v "$ZIEL":/ziel alpine:3.20 \
    sh -c "tar czf /ziel/volume-$v.tgz -C /v . && chown $EIGNER /ziel/volume-$v.tgz && chmod 600 /ziel/volume-$v.tgz" \
    || echo "  (uebersprungen: $v)"
  echo "  $v -> volume-$v.tgz"
done

echo "== 4/7 Laufende Images taggen"
: > "$ZIEL/images.txt"
echo "telefonki-bianca-1 | committet-als=telefonki:$MARKE (docker commit, Dateisystem mit docker-cp)" >> "$ZIEL/images.txt"
for c in telefonki-lisa-1 telefonki-bianca-test-1 telefonki-studio-1 \
         telefonki-sipbridge-1 telefonki-sipbridge-lisa-1 telefonki-tunnel-1 \
         telefonki-lisa-public-1 telefonki-bianca-v26-1 \
         tts_serve-qwen3-1 stt_serve-stt-1; do
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

echo "== 5/7 V5-Image als Tar (ladbar ohne Registry)"
docker save "telefonki:$MARKE" | gzip > "$ZIEL/image-bianca-v5.tar.gz"
chmod 640 "$ZIEL/image-bianca-v5.tar.gz"
ls -lh "$ZIEL/image-bianca-v5.tar.gz"

echo "== 6/7 Printenv-Stichprobe (keine Werte in Git)"
{
  echo "WRITE_LIVE=$(docker exec telefonki-bianca-1 printenv WRITE_LIVE 2>/dev/null || true)"
  echo "CONTROLLER_ENFORCE=$(docker exec telefonki-bianca-1 printenv CONTROLLER_ENFORCE 2>/dev/null || true)"
  echo "CONTROLLER_SHADOW=$(docker exec telefonki-bianca-1 printenv CONTROLLER_SHADOW 2>/dev/null || true)"
  echo "INTENT_NACHZUG=$(docker exec telefonki-bianca-1 printenv INTENT_NACHZUG 2>/dev/null || true)"
  echo "TTS_BASE gesetzt=$(docker exec telefonki-bianca-1 sh -c 'test -n \"$TTS_BASE\" && echo ja || echo nein' 2>/dev/null || true)"
  echo "STT_BASE gesetzt=$(docker exec telefonki-bianca-1 sh -c 'test -n \"$STT_BASE\" && echo ja || echo nein' 2>/dev/null || true)"
} > "$ZIEL/printenv-stichprobe.txt"

echo "== 7/7 Inventar"
{
  echo "Produktionsstand $VERSION — Schnappschuss $(date -Is)"
  echo
  echo "## V5-Kern"
  echo "telefonki-bianca-1 committet nach telefonki:$MARKE"
  docker inspect -f 'V5 Image nach Commit: {{.Id}}' "telefonki:$MARKE"
  echo
  echo "## Marker im Live-Dateisystem"
  echo -n "erkannt_satz gehirn: "; grep -c 'def erkannt_satz' /dev/null 2>/dev/null || true
  docker exec telefonki-bianca-1 grep -c 'def erkannt_satz' /app/bianca/gehirn.py || true
  docker exec telefonki-bianca-1 grep -c 'geschlecht_aktualisieren' /app/kern/patients.py || true
  docker exec telefonki-bianca-1 grep -c 'name_quittung' /app/bianca/verwalten.py || true
  docker exec telefonki-bianca-1 test -f /app/kern/ersatz.py && echo "ersatz.py: da" || echo "ersatz.py: FEHLT"
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
  echo "## .env-Wachen (Zaehler, keine Werte)"
  echo -n "CLOUDFLARE_TELEFONKI_TOKEN Zeilen: "; grep -c '^CLOUDFLARE_TELEFONKI_TOKEN=' .env || true
  echo -n "INTENT_NACHZUG Zeilen: "; grep -c '^INTENT_NACHZUG=' .env || true
  echo -n "WRITE_LIVE Zeilen: "; grep -c '^WRITE_LIVE=' .env || true
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
