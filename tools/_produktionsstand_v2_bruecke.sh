#!/usr/bin/env bash
# Die beiden SIP-Bruecken laufen aus unbenannten (dangling) Images — per
# Tag nicht sicherbar. docker commit friert den laufenden Stand ein.
# --pause=false: kein Anhalten, laufende Telefonate bleiben unberuehrt.
set -e
STAMP=20260913
ZIEL=/home/cursor/telefonki-backups/produktionsstand-v2.0-$STAMP
for paar in "telefonki-sipbridge-1:telefonki-sipbridge" "telefonki-sipbridge-lisa-1:telefonki-sipbridge-lisa"; do
  c=${paar%%:*}; basis=${paar##*:}
  neu="$basis:produktionsstand-v2.0-$STAMP"
  id=$(docker commit --pause=false "$c" "$neu")
  echo "$c -> $neu ($id)"
  echo "$c | eingefroren-per-commit | gesichert-als=$neu | $id" >> "$ZIEL/images.txt"
done
docker images --format '{{.Repository}}:{{.Tag}} {{.ID}} {{.Size}}' | grep produktionsstand-v2.0
