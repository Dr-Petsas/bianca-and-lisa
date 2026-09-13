#!/bin/bash
set -e
sleep 3
echo "=== health ==="
curl -sf http://127.0.0.1:8095/health; echo
curl -sf http://127.0.0.1:8096/health; echo
echo "=== replay HEAD/GET ==="
curl -sI http://127.0.0.1:8095/replay.html | head -n 8
curl -s -o /tmp/rp.html -w "GET8095 code=%{http_code} bytes=%{size_download}\n" http://127.0.0.1:8095/replay.html
curl -s -o /tmp/rp6.html -w "GET8096 code=%{http_code} bytes=%{size_download}\n" http://127.0.0.1:8096/replay.html
python3 - <<'PY'
import re, json
t = open("/tmp/rp.html", encoding="utf-8").read()
m = re.search(r'<script id="DATA" type="application/json">(.*?)</script>', t, re.S)
rows = json.loads(m.group(1)) if m else []
print("rows", len(rows), "herbst", sum(1 for r in rows if "herbst" in json.dumps(r, ensure_ascii=False).lower()))
print("title_ok", "Transkripte" in t)
PY
echo "=== container replay ==="
docker exec telefonki-lisa-1 wc -c /app/web/replay.html
echo "=== smoke ==="
docker exec -w /app telefonki-bianca-1 python tools/prod_smoke.py
