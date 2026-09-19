#!/usr/bin/env bash
set -e
docker exec -w /app telefonki-bianca-1 sh -lc '
  echo "== tools ==";
  ls tools/ | grep -E "kern_replay|_kern_wirkung|tages_scorer" || echo "(keine)";
  echo "== anrufe bianca ==";
  ls .data/anrufe/bianca 2>/dev/null | wc -l;
'
