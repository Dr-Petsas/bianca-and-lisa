#!/usr/bin/env bash
# Abnahme Produktionsstand V2.0 — read-only.
S=/home/cursor/telefonki-backups/produktionsstand-v2.0-20260913
cd /home/cursor/telefonki || exit 1
echo "== Sicherungs-Images vorhanden"
docker images --format '{{.Repository}}:{{.Tag}} {{.Size}}' | grep produktionsstand-v2.0
echo
echo "== Archive lesbar (Stichprobe)"
for f in tenants secrets; do
  n=$(tar tzf "$S/$f.tgz" | wc -l)
  echo "$f.tgz = $n Eintraege"
done
n=$(tar tzf "$S/volume-telefonki_telefonki-data.tgz" | wc -l)
echo "volume data = $n Eintraege"
echo
echo "== Live-Code in den Containern"
echo -n "anrede_wache in bianca: "; docker exec telefonki-bianca-1 python -c 'from kern import anrede_wache; print(anrede_wache.modus())'
echo -n "abschied in bianca:     "; docker exec telefonki-bianca-1 python -c 'from kern import abschied; print(abschied.an())'
echo -n "auflegen in der Bruecke: "; docker exec telefonki-sipbridge-1 grep -c ausklingen_und_auflegen /app/sip_bridge/server.py
echo -n "Dock-Cache-Buster:       "; docker exec telefonki-bianca-1 grep -o 'app.js?v=b[0-9]*' /app/bianca_web/index.html
echo
echo "== Health + Smoke"
curl -sf http://127.0.0.1:8096/health | head -c 90; echo
curl -sf http://127.0.0.1:8095/health | head -c 60; echo
docker exec -w /app telefonki-bianca-1 python tools/prod_smoke.py | tail -1
echo
echo "== .env unangetastet"
echo -n "CLOUDFLARE_TELEFONKI_TOKEN="; grep -c CLOUDFLARE_TELEFONKI_TOKEN .env
echo -n "INTENT_NACHZUG=";            grep -c INTENT_NACHZUG .env
echo -n "WRITE_LIVE=1=";              grep -c 'WRITE_LIVE=1' .env
ls -l --time-style=+%F_%H:%M .env
echo
echo "== Bruecke bereit"
docker logs --tail 3 telefonki-sipbridge-1 2>&1 | tail -3
