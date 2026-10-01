#!/usr/bin/env bash
# Findet Anruf-Aufzeichnungen zu gegebenen SIDs im Bianca-Datenvolume und
# kopiert anruf.json (+ Audio) nach /home/cursor/telefonki-backups/fixtures/<sid>/.
# Nur-Lesen aus dem Container; schreibt ausschliesslich in das Backup-Verzeichnis.
set -u
C=telefonki-bianca-1
IDS="28d34ffd c940da6a c4a9d298 9105345d 4b86b5dd 953f6b66 448c5c37 6e3337e1 062c4e1f 106935f8 54bfb354 a06f01a7 881ade70 c10a5b8f 8a2754f9 042fd880"
OUT=/home/cursor/telefonki-backups/fixtures
mkdir -p "$OUT"

echo "=== data roots in container ==="
docker exec -i -u 0 "$C" python3 - <<'PY'
import os, glob, json
root = "/app/.data"
print("exists", os.path.isdir(root))
try:
    print("top", sorted(os.listdir(root)))
except Exception as e:
    print("ERR", e)
js = glob.glob("/app/.data/**/anruf.json", recursive=True)
print("anruf.json total", len(js))
# Map: letzte 5 Verzeichnisnamen-Praefixe
dirs = set(os.path.dirname(p) for p in js)
print("sample dirs", [os.path.basename(d) for d in list(dirs)[:5]])
PY

echo "=== resolve + copy each sid ==="
for id in $IDS; do
  docker exec -i -u 0 "$C" python3 - "$id" <<'PY'
import os, glob, shutil, sys
sid = sys.argv[1]
hits = [d for d in glob.glob("/app/.data/**/", recursive=True)
        if os.path.basename(os.path.normpath(d)).startswith(sid)
        and os.path.isfile(os.path.join(d, "anruf.json"))]
if not hits:
    # auch: anruf.json irgendwo, dessen ordnername mit sid beginnt
    hits = [os.path.dirname(p) for p in glob.glob("/app/.data/**/anruf.json", recursive=True)
            if os.path.basename(os.path.dirname(p)).startswith(sid)]
print(sid, "->", hits[:1] if hits else "MISSING")
if hits:
    dst = "/tmp/fixpull/%s" % sid
    os.makedirs(dst, exist_ok=True)
    src = hits[0]
    for fn in os.listdir(src):
        fp = os.path.join(src, fn)
        if os.path.isfile(fp):
            shutil.copy2(fp, os.path.join(dst, fn))
PY
done

echo "=== extract /tmp/fixpull from container to host backups ==="
docker exec -u 0 "$C" sh -lc "cd /tmp && tar -czf /tmp/fixpull.tgz fixpull 2>/dev/null && echo packed || echo nothing"
docker cp "$C":/tmp/fixpull.tgz "$OUT/fixpull.tgz" 2>/dev/null && echo "copied to $OUT/fixpull.tgz"
cd "$OUT" && tar -xzf fixpull.tgz 2>/dev/null && echo "extracted:" && find "$OUT/fixpull" -maxdepth 2 -type f | head -60
