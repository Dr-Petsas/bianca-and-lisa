#!/bin/bash
set -e
cd /home/cursor/telefonki
cut -c35- /tmp/_lokal_md5.txt > /tmp/_liste.txt
: > /tmp/_server_md5.txt
while IFS= read -r f; do
  if [ -f "$f" ]; then
    md5sum "$f" >> /tmp/_server_md5.txt
  else
    echo "FEHLT  $f" >> /tmp/_server_md5.txt
  fi
done < /tmp/_liste.txt
python3 /tmp/_drift.py
