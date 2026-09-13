#!/usr/bin/env bash
# Abnahme eines Produktionsstands — read-only, kein Container wird gestoppt.
#
# Aufruf (LF-Zeilenenden! PowerShell schreibt CRLF — deshalb vorher
# konvertieren oder die Datei per scp schicken und dort mit bash starten):
#   VERSION=v2.2 bash tools/_produktionsstand_v2_abnahme.sh
VERSION=${VERSION:-v2.2}
STAMP=${STAMP:-$(date +%Y%m%d)}
MARKE="produktionsstand-$VERSION-$STAMP"
S=/home/cursor/telefonki-backups/$MARKE
cd /home/cursor/telefonki || exit 1
echo "== Abnahme $MARKE"
echo
echo "== Sicherungs-Images vorhanden"
docker images --format '{{.Repository}}:{{.Tag}} {{.Size}}' | grep "$MARKE"
echo
# V2.3-Lektion (13.09.2026): der App-Tag zeigte auf das V2.2-Image, weil die
# sipbridge (nicht neu gebaut) als letzter Container den Tag ueberschrieb.
# Ein Rollback "auf V2.3" haette den Vor-Fix-Stand gebracht. Deshalb hier
# der harte Vergleich: Sicherungstag == Image der laufenden Bianca.
echo "== App-Tag zeigt auf die laufende Bianca"
live=$(docker inspect -f '{{.Image}}' telefonki-bianca-1)
tag=$(docker inspect -f '{{.Id}}' "telefonki:$MARKE" 2>/dev/null || echo fehlt)
if [ "$live" = "$tag" ]; then
  echo "OK  telefonki:$MARKE = ${live:7:12} (bianca live)"
else
  echo "FEHLER  telefonki:$MARKE = ${tag:7:12}, bianca laeuft aber aus ${live:7:12} -> docker tag ${live:7:12} telefonki:$MARKE"
fi
for c in telefonki-lisa-1 telefonki-sipbridge-1 telefonki-studio-1 telefonki-bianca-test-1; do
  i=$(docker inspect -f '{{.Image}}' "$c" 2>/dev/null) || continue
  [ "$i" = "$live" ] || echo "HINWEIS $c laeuft aus ${i:7:12} (anders als bianca) - Code-Unterschied pruefen"
done
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
echo -n "anrede_wache in bianca:  "; docker exec telefonki-bianca-1 python -c 'from kern import anrede_wache; print(anrede_wache.modus())'
echo -n "abschied in bianca:      "; docker exec telefonki-bianca-1 python -c 'from kern import abschied; print(abschied.an())'
# V2.2: Widerspruch zuerst korrigieren, jeden Zug auf das Gesagte beziehen,
# und die Job-Kette findet zurueck (Auto-Resume als Code-Default).
echo -n "einwand in bianca:       "; docker exec telefonki-bianca-1 python -c 'from kern import einwand; print(einwand.modus())'
echo -n "eingehen in bianca:      "; docker exec telefonki-bianca-1 python -c 'from kern import eingehen; print(eingehen.modus())'
echo -n "auto-resume in bianca:   "; docker exec telefonki-bianca-1 python -c 'from kern import hirn; print(hirn.auto_resume_modus())'
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
