#!/usr/bin/env bash
set -e
echo "===== 1) REPLAY: Kern Zug fuer Zug ueber alle Anrufe ====="
docker exec -w /app telefonki-bianca-1 python3 tools/kern_replay.py scan 2>&1 | tail -30
echo
echo "===== 2) WIRKUNG: Live vs Kern (super/gut/mittel/schlecht + Abschluss) ====="
docker exec -w /app/tools telefonki-bianca-1 python3 _kern_wirkung.py 2>&1 | tail -80
