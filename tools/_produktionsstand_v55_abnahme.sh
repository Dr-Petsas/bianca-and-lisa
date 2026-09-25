#!/usr/bin/env bash
# Abnahme Produktionsstand V5.5 — read-only, kein Container wird gestoppt.
# Aufruf auf pickadoc1 (LF-Zeilenenden!):  bash tools/_produktionsstand_v55_abnahme.sh
VERSION=${VERSION:-v5.5}
STAMP=${STAMP:-$(date +%Y%m%d)}
MARKE="produktionsstand-$VERSION-$STAMP"
S=/home/cursor/telefonki-backups/$MARKE
cd /home/cursor/telefonki || exit 1
echo "== Abnahme $MARKE"
echo
echo "== Sicherungs-Images vorhanden"
docker images --format '{{.Repository}}:{{.Tag}} {{.Size}}' | grep "$MARKE"
echo
# V5.5 ist ein docker-commit-Freeze (Live-Dateisystem mit docker-cp-Patches):
# das committete Image hat eine EIGENE Id, ungleich dem Start-Image des
# Containers. Deshalb NICHT live==tag pruefen, sondern Code-Paritaet zwischen
# dem committeten Image und der laufenden Bianca (das ist die echte Garantie).
echo "== Freeze-Image und Start-Image"
tag=$(docker inspect -f '{{.Id}}' "telefonki:$MARKE" 2>/dev/null || echo fehlt)
base=$(docker inspect -f '{{.Image}}' telefonki-bianca-1)
echo "  committet:   ${tag:7:12}  (telefonki:$MARKE)"
echo "  Start-Image: ${base:7:12}  (telefonki-bianca-1)"
[ "$tag" = fehlt ] && { echo "FEHLER: Freeze-Tag fehlt"; exit 1; }
echo
echo "== Code-Paritaet Freeze-Image == laufende Bianca (kern+bianca)"
liveh=$(docker exec telefonki-bianca-1 sh -c 'cd /app && find kern bianca -name "*.py" -exec sha256sum {} + | sort | sha256sum' | awk '{print $1}')
imgh=$(docker run --rm --entrypoint sh "telefonki:$MARKE" -c 'cd /app && find kern bianca -name "*.py" -exec sha256sum {} + | sort | sha256sum' | awk '{print $1}')
echo "  live=${liveh:0:16}"
echo "  img =${imgh:0:16}"
if [ "$liveh" = "$imgh" ]; then
  echo "OK  Freeze-Image ist byte-identisch zur laufenden Bianca"
else
  echo "FEHLER  Freeze-Image weicht vom Live-Code ab"
  exit 1
fi
echo
echo "== telefonki:v1 UNANGETASTET (darf nicht = V5.5 sein)"
v1=$(docker inspect -f '{{.Id}}' telefonki:v1 2>/dev/null || echo fehlt)
if [ "$v1" = "$tag" ]; then
  echo "WARNUNG  telefonki:v1 zeigt jetzt auf V5.5 — das war nicht gewollt!"
else
  echo "OK  telefonki:v1 = ${v1:7:12} (unveraendert)"
fi
echo
echo "== Archive lesbar (Stichprobe)"
for f in tenants secrets tts-stimmen; do
  [ -f "$S/$f.tgz" ] && echo "$f.tgz = $(tar tzf "$S/$f.tgz" | wc -l) Eintraege"
done
for v in data berichte klang; do
  f="$S/volume-telefonki_telefonki-$v.tgz"
  [ -f "$f" ] && echo "volume $v = $(tar tzf "$f" | wc -l) Eintraege"
done
[ -f "$S/image-bianca-v5.5.tar.gz" ] && ls -lh "$S/image-bianca-v5.5.tar.gz"
[ -f "$S/live-app-full-code.tgz" ] || { echo "FEHLER: vollstaendiger Quell-Tar fehlt"; exit 1; }
echo "Live-App-Quellen = $(tar tzf "$S/live-app-full-code.tgz" | wc -l) Eintraege"
sha256sum -c "$S/source-image-sha256.txt"
echo
echo "== Ohr = Scribe (STT_BASE leer)"
echo -n "STT_BASE=[";  docker exec telefonki-bianca-1 printenv STT_BASE 2>/dev/null; echo "]"
[ -f "$S/compose.scribe-heute.yml" ] && echo "compose.scribe-heute.yml gesichert: ja"
echo
echo "== Live-Code in den Containern (Stichprobe)"
echo -n "anrede_wache:  "; docker exec telefonki-bianca-1 python -c 'from kern import anrede_wache; print(anrede_wache.modus())'
echo -n "fach_wache:    "; docker exec telefonki-bianca-1 python -c 'from kern import fach_wache; print(fach_wache.modus())'
echo -n "auto-resume:   "; docker exec telefonki-bianca-1 python -c 'from kern import hirn; print(hirn.auto_resume_modus())'
echo -n "_telefon_tor:  "; docker exec telefonki-bianca-1 grep -c '_telefon_tor' /app/bianca/flow.py
echo -n "ersatz.py:     "; docker exec telefonki-bianca-1 test -f /app/kern/ersatz.py && echo da || echo FEHLT
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
