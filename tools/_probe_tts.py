#!/usr/bin/env python3
import json, time, urllib.request

def speak(text, voice="bianca"):
    body = json.dumps({"text": text, "voice": voice}).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:8213/speak",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
            print(f"speak ok {len(data)} B in {time.time()-t0:.2f}s ct={r.headers.get('Content-Type')}")
    except Exception as e:
        print(f"speak FAIL in {time.time()-t0:.2f}s: {e}")
        if hasattr(e, "read"):
            print(e.read()[:300])

if __name__ == "__main__":
    with urllib.request.urlopen("http://127.0.0.1:8213/health", timeout=5) as r:
        print(r.read().decode())
    speak("Hallo, gerne einen Termin.")
    # also through bianca tts module
    import sys
    sys.path.insert(0, "/home/cursor/telefonki")
    try:
        # inside container better
        pass
    except Exception:
        pass
