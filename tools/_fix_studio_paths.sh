#!/bin/bash
set -e
sed -i 's/\r$//' /tmp/bianca_server.py /tmp/bianca_app.js
docker cp /tmp/bianca_server.py telefonki-bianca-1:/app/bianca/server.py
docker cp /tmp/bianca_app.js telefonki-bianca-1:/app/bianca_web/app.js
# Test-Bianca braucht die Studio-Routen nicht zwingend, aber gleicher Code-Stand
docker cp /tmp/bianca_server.py telefonki-bianca-test-1:/app/bianca/server.py 2>/dev/null || true
docker restart telefonki-bianca-1
sleep 5
echo "=== redirect ==="
curl -sS -m 5 -o /dev/null -w 'studio=%{http_code} redir=%{redirect_url}\n' http://127.0.0.1:8096/studio
echo "=== base tag ==="
curl -sS -m 5 -L http://127.0.0.1:8096/studio | head -n 12
echo "=== assets ==="
curl -sS -m 5 -o /dev/null -w 'css=%{http_code} js=%{http_code}\n' http://127.0.0.1:8096/studio/web/stil.css
curl -sS -m 5 -o /dev/null -w 'js=%{http_code}\n' http://127.0.0.1:8096/studio/web/app.js
curl -sS -m 5 -o /dev/null -w 'api=%{http_code}\n' http://127.0.0.1:8096/studio/api/katalog
curl -sS -m 5 -o /dev/null -w 'erg=%{http_code}\n' http://127.0.0.1:8096/studio/ergebnisse
echo OK
