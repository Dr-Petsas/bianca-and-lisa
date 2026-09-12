import urllib.error
import urllib.request

for url in (
    "http://127.0.0.1:8095/replay.html",
    "http://127.0.0.1:8095/static/replay.html",
    "http://127.0.0.1:8096/replay.html",
):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            body = r.read()
            print(url, r.status, len(body), b"Mitternacht" in body)
    except urllib.error.HTTPError as e:
        print(url, "http", e.code, e.read()[:80])
    except Exception as e:
        print(url, type(e).__name__, e)
