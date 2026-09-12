#!/bin/bash
set -e
# Full log window of the "uhrzeit" follow-up call
docker logs --since 40m telefonki-bianca-1 2>&1 | grep -n 'morgen einen Termin\|um wie viel\|Tschüss\|Bitte\|morgen früh\|POST /api/start\|POST /api/hangup\|POST /api/listen\|call registriert\|ImportError\|listen ok\|verwalten\|gefunden\|list_appoint' | tail -n 80

echo '==== session dump from volume if any ===='
docker exec telefonki-bianca-1 ls -lt /app/.data 2>/dev/null | head -20
docker exec telefonki-bianca-1 sh -c 'ls -lt /app/.data/bianca_sessions 2>/dev/null | head -10; ls -lt /app/.data/sessions 2>/dev/null | head -10'

echo '==== download booking mp3 via host python in container ===='
docker cp /tmp/dl_mp3.py telefonki-bianca-1:/tmp/dl_mp3.py 2>/dev/null || true
cat > /tmp/dl_mp3.py <<'PY'
from kern import anrufaudio
import httpx, urllib.parse, pathlib
pcid="kONMVnLZKQGIkk1Dp9Mp"
pfad=f"clients/MEe4ZQHEzOPzLcexyhdT/locations/VjdvbRQHH8oTId4f0GiX/phoneCalls/{pcid}.mp3"
tok=anrufaudio._access_token()
url="https://storage.googleapis.com/storage/v1/b/docgenda.appspot.com/o/"+urllib.parse.quote(pfad,safe="")+"?alt=media"
r=httpx.get(url, headers={"Authorization": f"Bearer {tok}"}, timeout=120)
print(pcid, r.status_code, len(r.content))
pathlib.Path("/tmp/book-call.mp3").write_bytes(r.content)
print("ok")
PY
docker cp /tmp/dl_mp3.py telefonki-bianca-1:/tmp/dl_mp3.py
docker exec -w /app telefonki-bianca-1 python /tmp/dl_mp3.py
docker cp telefonki-bianca-1:/tmp/book-call.mp3 /tmp/book-call.mp3
ls -la /tmp/book-call.mp3

# silence / duration analysis
docker exec telefonki-bianca-1 ffmpeg -hide_banner -i /tmp/book-call.mp3 2>&1 | head -20
docker exec telefonki-bianca-1 ffmpeg -hide_banner -i /tmp/book-call.mp3 -af silencedetect=noise=-35dB:d=0.8 -f null - 2>&1 | grep -E 'silence_|Duration'

# STT transcript of booking call
docker exec -w /app telefonki-bianca-1 python - <<'PY'
from pathlib import Path
from kern import stt
import time
blob=Path('/tmp/book-call.mp3').read_bytes()
t=time.time()
text=stt.transcribe(blob, mime='audio/mpeg', name='book.mp3')
print('took', round(time.time()-t,1))
print(text)
PY
