#!/bin/bash
# Second call: "Termin morgen Uhrzeit" after booking
docker logs --since 40m telefonki-bianca-1 2>&1 | awk '
/Guten Tag, ich habe morgen einen Termin/ {p=1}
p {print}
/anrufaudio hochgeladen/ && p {exit}
/call abgeschlossen/ && p {print; exit}
' | tail -n 80

echo '==== ALL listen after booking ===='
docker logs --since 40m telefonki-bianca-1 2>&1 | grep -A2 -E 'morgen einen Termin|um wie viel|verwalten|kein Termin|gefunden|absage|lookup|appointments|masPatient|phoneCallId=' | tail -n 60

echo '==== download latest two mp3s ===='
docker exec -w /app telefonki-bianca-1 python - <<'PY'
from kern import anrufaudio
import httpx, urllib.parse, pathlib
for pcid in ["kONMVnLZKQGIkk1Dp9Mp"]:
    # also search for any newer from logs - list via storage hard; use known
    pfad=f"clients/MEe4ZQHEzOPzLcexyhdT/locations/VjdvbRQHH8oTId4f0GiX/phoneCalls/{pcid}.mp3"
    tok=anrufaudio._access_token()
    url="https://storage.googleapis.com/storage/v1/b/docgenda.appspot.com/o/"+urllib.parse.quote(pfad,safe="")+"?alt=media"
    r=httpx.get(url, headers={"Authorization": f"Bearer {tok}"}, timeout=120)
    print(pcid, r.status_code, len(r.content))
    pathlib.Path(f"/tmp/{pcid}.mp3").write_bytes(r.content)
PY
docker cp telefonki-bianca-1:/tmp/kONMVnLZKQGIkk1Dp9Mp.mp3 /tmp/book-call.mp3
ls -la /tmp/book-call.mp3

# Find second call id from logs after booking
docker logs --since 40m telefonki-bianca-1 2>&1 | grep -E 'call registriert|call abgeschlossen|anrufaudio' | tail -n 20
