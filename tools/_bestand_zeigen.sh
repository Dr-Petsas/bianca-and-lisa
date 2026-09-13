#!/bin/sh
# Zeigt, was an Gespraechen und Ergebnissen auf pickadoc1 liegt (nur lesend).

echo "=== Volume telefonki-data (Anrufe, Sitzungen, Notizen) ==="
docker run --rm -v telefonki_telefonki-data:/d alpine sh -c '
  echo "Inhalt:"; ls -1 /d;
  for s in bianca lisa; do
    n=$(ls -1 /d/anrufe/$s 2>/dev/null | wc -l);
    echo "anrufe/$s: $n";
  done;
  for f in /d/*.jsonl /d/*.json; do
    [ -f "$f" ] || continue;
    echo "$f: $(wc -l < $f) Zeilen";
  done;
  for v in /d/*_sessions; do
    [ -d "$v" ] || continue;
    echo "$v: $(ls -1 $v | wc -l) Dateien";
  done;
  du -sh /d'

echo
echo "=== Volume telefonki-berichte (Studio-Ergebnisse) ==="
docker run --rm -v telefonki_telefonki-berichte:/b alpine sh -c '
  echo "Laeufe: $(ls -1d /b/*/ 2>/dev/null | wc -l)";
  ls -1 /b | tail -8;
  cat /b/autoloesch.json 2>/dev/null | head -c 300; echo;
  du -sh /b'
