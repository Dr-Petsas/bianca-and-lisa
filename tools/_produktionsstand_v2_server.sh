#!/usr/bin/env bash
# Produktionsstand-Schnappschuss auf pickadoc1 (erstmals V2.0, 13.09.2026).
#
# Sichert alles, was NICHT auf GitHub kommt: Live-.env (Tokens), secrets/,
# tenants/, Compose-Konfiguration, Asterisk-Dialplan und die Docker-Volumes
# (Sitzungen, Mitschnitte, Berichte, Klang-Cache). Zusaetzlich werden die
# LAUFENDEN Images unter produktionsstand-<VERSION>-<STAMP> getaggt, damit
# ein Rollback ohne Neubau moeglich ist.
#
# Kein Container wird gestoppt — laufende Telefonate bleiben unberuehrt.
# Aufruf (LF-Zeilenenden beachten, PowerShell schreibt CRLF):
#   Get-Content tools/_produktionsstand_v2_server.sh -Raw | ssh pickadoc1 "bash -s"
set -e
VERSION=${VERSION:-v2.0}
STAMP=${STAMP:-$(date +%Y%m%d)}
MARKE="produktionsstand-$VERSION-$STAMP"
ZIEL=/home/cursor/telefonki-backups/$MARKE
APP=/home/cursor/telefonki
mkdir -p "$ZIEL"
cd "$APP"

echo "== 1/5 Einstellungen und Geheimnisse"
cp -a .env "$ZIEL/.env"
cp -a compose.yml "$ZIEL/compose.yml"
tar czf "$ZIEL/tenants.tgz" tenants
tar czf "$ZIEL/secrets.tgz" secrets
for s in tts_serve stt_serve; do
  [ -f "$s/compose.yml" ] && cp -a "$s/compose.yml" "$ZIEL/compose-$s.yml"
  [ -f "$s/.env" ] && cp -a "$s/.env" "$ZIEL/env-$s"
done
[ -f sip_bridge/extensions_bianca.conf ] && cp -a sip_bridge/extensions_bianca.conf "$ZIEL/extensions_bianca.conf"

echo "== 2/5 Aufgeloeste Compose-Konfiguration (so lief es wirklich)"
docker compose config > "$ZIEL/compose-aufgeloest.yml" 2>/dev/null || true

echo "== 3/5 Volumes sichern"
for v in telefonki_telefonki-data telefonki_telefonki-berichte telefonki_telefonki-klang; do
  # Der Container schreibt als root — danach die Rechte wieder einsammeln.
  docker run --rm -v "$v":/v -v "$ZIEL":/ziel alpine:3.20 \
    sh -c "tar czf /ziel/volume-$v.tgz -C /v . && chmod 600 /ziel/volume-$v.tgz" \
    || echo "  (uebersprungen: $v)"
  echo "  $v -> volume-$v.tgz"
done

echo "== 4/5 Laufende Images taggen"
: > "$ZIEL/images.txt"
for c in telefonki-bianca-1 telefonki-lisa-1 telefonki-bianca-test-1 telefonki-studio-1 \
         telefonki-sipbridge-1 telefonki-sipbridge-lisa-1 telefonki-tunnel-1 \
         telefonki-lisa-public-1 tts_serve-qwen3-1 stt_serve-stt-1; do
  id=$(docker inspect -f '{{.Image}}' "$c" 2>/dev/null) || continue
  [ -z "$id" ] && continue
  name=$(docker inspect -f '{{.Config.Image}}' "$c" 2>/dev/null)
  neu="$(echo "$name" | cut -d: -f1):$MARKE"
  # Die SIP-Bruecken laufen historisch aus aufgeraeumten Layern: docker tag
  # und docker commit scheitern dort ("content digest not found"). Ihr Code
  # ist identisch mit telefonki:v1 (compose nutzt denselben *app-Block) —
  # der Rollback startet sie aus dem App-Sicherungstag.
  if docker tag "$id" "$neu" 2>/dev/null; then
    echo "  $c -> $neu"
    echo "$c | laeuft-als=$name | image=$id | gesichert-als=$neu" >> "$ZIEL/images.txt"
  else
    echo "  $c -> KEIN Tag moeglich (Layer aufgeraeumt), laeuft-als=$name"
    echo "$c | laeuft-als=$name | image=$id | kein Tag moeglich, Rollback ueber das App-Image" >> "$ZIEL/images.txt"
  fi
done

echo "== 5/5 Inventar"
{
  echo "Produktionsstand $VERSION — Schnappschuss $(date -Is)"
  echo
  echo "## Container (laufend)"
  docker ps --format '{{.Names}} | {{.Image}} | {{.Status}} | {{.Ports}}'
  echo
  echo "## Gesicherte Images"
  docker images --format '{{.Repository}}:{{.Tag}} {{.ID}} {{.Size}}' | grep "$MARKE" || true
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

chmod 700 "$ZIEL"
chmod 600 "$ZIEL"/.env "$ZIEL"/env-* "$ZIEL"/secrets.tgz 2>/dev/null || true
echo
echo "FERTIG: $ZIEL"
du -sh "$ZIEL"
ls -la "$ZIEL"
