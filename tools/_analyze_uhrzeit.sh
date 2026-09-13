#!/bin/bash
# Extract second-call dialogue from bianca + sip logs
echo '==== BIANCA around uhrzeit call ===='
docker logs --since 40m telefonki-bianca-1 2>&1 | grep -n '.' | sed -n '290,340p'

echo '==== SIP around same time ===='
docker logs --since 40m telefonki-sipbridge-1 2>&1 | grep -E 'gehoert|antwort|ende|anruf|start' | tail -n 40

echo '==== newest sessions ===='
docker exec telefonki-bianca-1 ls -lt /app/.data/bianca_sessions | head -5
# any session newer than booking?
docker exec telefonki-bianca-1 sh -c 'ls -lt /app/.data/bianca_sessions/*.json | head -3'
# dump zuege of booking + search for any other recent
docker exec telefonki-bianca-1 python - <<'PY'
import json, glob, os
files=sorted(glob.glob('/app/.data/bianca_sessions/*.json'), key=os.path.getmtime, reverse=True)[:3]
for f in files:
    d=json.load(open(f))
    print('FILE', os.path.basename(f), 'started', d.get('startedAt') or d.get('id'))
    for i,z in enumerate(d.get('zuege') or []):
        print(f"  {i} {z.get('art')} IN={(z.get('textIn') or '')[:70]!r}")
        print(f"     OUT={(z.get('text') or '')[:120]!r}")
    print('  sammler', {k:d.get('sammler',{}).get(k) if isinstance(d.get('sammler'),dict) else None for k in ['modus','phase','nachname','arzt']})
    print('---')
PY

# STT of booking call (may take a few sec)
docker exec -w /app telefonki-bianca-1 python - <<'PY'
from pathlib import Path
from kern import stt
import time
p=Path('/tmp/book-call.mp3')
print('exists', p.exists(), p.stat().st_size if p.exists() else 0)
t=time.time()
print(stt.transcribe(p.read_bytes(), mime='audio/mpeg', name='book.mp3'))
print('took', round(time.time()-t,1))
PY

scp /tmp/book-call.mp3 /tmp/ 2>/dev/null || true
ls -la /tmp/book-call.mp3
