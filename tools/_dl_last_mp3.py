#!/usr/bin/env python3
import pathlib
import urllib.parse
import httpx
from kern import anrufaudio

pfad = "clients/MEe4ZQHEzOPzLcexyhdT/locations/VjdvbRQHH8oTId4f0GiX/phoneCalls/7zXfn1dy87tnb8tFwk3G.mp3"
tok = anrufaudio._access_token()
url = (
    "https://storage.googleapis.com/storage/v1/b/docgenda.appspot.com/o/"
    + urllib.parse.quote(pfad, safe="")
    + "?alt=media"
)
r = httpx.get(url, headers={"Authorization": f"Bearer {tok}"}, timeout=120)
print("status", r.status_code, "bytes", len(r.content))
r.raise_for_status()
pathlib.Path("/tmp/last-call.mp3").write_bytes(r.content)
print("ok /tmp/last-call.mp3")
