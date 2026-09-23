#!/usr/bin/env bash
# Abnahme V5.1 — read-only, kein Container wird gestoppt.
VERSION=${VERSION:-v5.1}
STAMP=${STAMP:-20260923}
MARKE="produktionsstand-$VERSION-$STAMP"
S=/home/cursor/telefonki-backups/$MARKE
cd /home/cursor/telefonki || exit 1
echo "== Abnahme $MARKE"
echo
echo "== Sicherungs-Images vorhanden"
docker images --format '{{.Repository}}:{{.Tag}} {{.Size}}' | grep "$MARKE"
echo
echo "== V5.1-Tag ist der docker-commit von Live-8096 (Dateisystem, nicht das Start-Image)"
commit=$(docker inspect -f '{{.Id}}' "telefonki:$MARKE" 2>/dev/null || echo fehlt)
live=$(docker inspect -f '{{.Image}}' telefonki-bianca-1)
echo "telefonki:$MARKE = ${commit:7:12}"
echo "bianca laeuft aus Start-Image ${live:7:12} (darf abweichen — V5 ist der Commit)"
echo
echo "== Archive lesbar"
for f in tenants secrets live-app-code; do
  n=$(tar tzf "$S/$f.tgz" | wc -l)
  echo "$f.tgz = $n Eintraege"
done
n=$(tar tzf "$S/volume-telefonki_telefonki-data.tgz" | wc -l)
echo "volume data = $n Eintraege"
echo
echo "== Marker im gesicherten Dateibaum"
echo -n "erkannt_satz: "; grep -c 'def erkannt_satz' "$S/live-bianca/gehirn.py"
echo -n "geschlecht_aktualisieren: "; grep -c 'def geschlecht_aktualisieren' "$S/live-kern/patients.py"
echo -n "name_quittung verwalten: "; grep -c 'name_quittung' "$S/live-bianca/verwalten.py"
test -f "$S/live-kern/ersatz.py" && echo "ersatz.py: da" || echo "ersatz.py: FEHLT"
echo
echo "== Health + WRITE_LIVE"
curl -sf http://127.0.0.1:8096/health | head -c 200; echo
echo -n "WRITE_LIVE="; docker exec telefonki-bianca-1 printenv WRITE_LIVE
echo
echo "== .env-Wachen im Snapshot (Zaehler)"
echo -n "CLOUDFLARE_TELEFONKI_TOKEN: "; grep -c '^CLOUDFLARE_TELEFONKI_TOKEN=' "$S/.env"
echo -n "INTENT_NACHZUG: "; grep -c '^INTENT_NACHZUG=' "$S/.env"
echo -n "WRITE_LIVE: "; grep -c '^WRITE_LIVE=' "$S/.env"
echo
echo "FERTIG Abnahme $MARKE"
