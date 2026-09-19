#!/usr/bin/env bash
# Read-only: zaehlt Anruf-Manifeste im laufenden Bianca-Container nach Tag.
set -e
docker exec -i telefonki-bianca-1 python3 - <<'PY'
import json, os, glob, collections
base = "/app/.data/anrufe/bianca"
tage = collections.Counter()
test = 0
gesamt = 0
for d in sorted(glob.glob(os.path.join(base, "*"))):
    f = os.path.join(d, "anruf.json")
    if not os.path.isfile(f):
        continue
    try:
        m = json.load(open(f, encoding="utf-8"))
    except Exception:
        continue
    gesamt += 1
    if m.get("testAnruf"):
        test += 1
    tag = str(m.get("startedAt") or "")[:10]
    tage[tag] += 1
print("Gesamt Manifeste:", gesamt, "| davon Testanrufe:", test)
for tag, n in sorted(tage.items())[-10:]:
    print(f"  {tag or '(ohne Datum)'}: {n}")
PY
