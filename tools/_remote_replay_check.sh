#!/bin/sh
set -e
echo "=== host replay ==="
ls -la /home/cursor/telefonki/web/replay.html /home/cursor/telefonki/bianca_web/replay.html
echo "=== GET lisa replay ==="
curl -s -o /tmp/rp.html -w "code=%{http_code} bytes=%{size_download}\n" http://127.0.0.1:8095/replay.html
echo "=== anrufe volume ==="
docker exec telefonki-bianca-1 sh -c 'ls /app/.data/anrufe/bianca | wc -l'
docker cp /tmp/_dump_anrufe_replay.py telefonki-bianca-1:/tmp/_dump_anrufe_replay.py
docker exec -w /app telefonki-bianca-1 python /tmp/_dump_anrufe_replay.py
docker cp telefonki-bianca-1:/tmp/replay-anrufe.json /tmp/replay-anrufe.json
ls -la /tmp/replay-anrufe.json
python3 -c "import json; r=json.load(open('/tmp/replay-anrufe.json',encoding='utf-8')); print('rows',len(r)); print('sids',len({x.get('sid') for x in r}))"
docker cp /tmp/_peek_herbst.py telefonki-bianca-1:/tmp/_peek_herbst.py
docker exec -w /app telefonki-bianca-1 python /tmp/_peek_herbst.py
