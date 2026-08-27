"""SMS nur wenn Lisa standalone gruen ist. Keine Secrets im Log."""

from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:8095"


def peek(path: Path, name: str) -> str:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#") or "=" not in raw:
                continue
            k, _, v = raw.partition("=")
            if k.strip() == name:
                return v.strip().strip('"').strip("'")
    except OSError:
        return ""
    return ""


def token() -> str:
    p = ROOT / ".data" / "remote_token.txt"
    if p.is_file():
        t = p.read_text(encoding="utf-8").strip()
        if t:
            return t
    return ""


def ips() -> dict[str, str]:
    out = {"wlan": "", "tailscale": ""}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip.startswith("127."):
                continue
            if ip.startswith("100.") and not out["tailscale"]:
                out["tailscale"] = ip
            elif not ip.startswith("100.") and not out["wlan"]:
                out["wlan"] = ip
    except OSError:
        pass
    return out


def get(path: str, timeout: float = 8.0):
    req = Request(BASE + path, method="GET")
    with urlopen(req, timeout=timeout) as r:
        raw = r.read()
        return r.status, raw


def post(path: str, body: dict, timeout: float = 90.0):
    req = Request(
        BASE + path,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def ready() -> tuple[bool, str]:
    try:
        status, raw = get("/health")
        h = json.loads(raw.decode("utf-8"))
    except Exception as e:
        return False, f"health tot: {e}"
    if not h.get("ok") or h.get("service") != "lisa-telefonki":
        return False, "kein Lisa-Dienst"
    if not (h.get("llm") or {}).get("ok"):
        return False, "vLLM offline"
    if h.get("tts") != "elevenlabs":
        return False, "TTS fehlt"
    # WRITE_LIVE ist seit 26.08.2026 der gewollte Betriebszustand (echter
    # Kalender) — kein Versand-Blocker mehr, nur noch sichtbar im Log.
    print("writeLive:", "an (echter Kalender)" if h.get("writeLive") else "aus (Testmodus)")
    try:
        fs, fb = get("/fernsteuerung.html")
        if fs != 200 or b"Lisa-Draht" not in fb:
            return False, "fernsteuerung.html fehlt"
    except Exception as e:
        return False, f"draht tot: {e}"
    try:
        rs, rb = get("/remote/state")
        st = json.loads(rb.decode("utf-8"))
        if rs != 200 or not st.get("ok"):
            return False, "draht-api tot"
    except Exception as e:
        return False, f"draht-api: {e}"
    try:
        ss, data = post("/api/start", {
            "tenant": "meddent",
            "auftrag": "Bitte kurz ausrichten: Die Praxis bleibt am Freitag wegen Fortbildung geschlossen.",
            "patient": {
                "name": "Anna Test",
                "firstName": "Anna",
                "lastName": "Test",
                "devPhone": "0177 6004600",
                "devPhoneRaw": "01776004600",
            },
        })
    except Exception as e:
        return False, f"start tot: {e}"
    if ss != 200 or not data.get("ok") or not (data.get("text") or "").strip():
        return False, "start ohne Text"
    if not data.get("audioUrl"):
        return False, "start ohne Stimme"
    return True, "standalone gruen"


def sms_body() -> str:
    t = token()
    hash_t = f"#t={t}" if t else ""
    return (
        "BIANCA & LISA JETZT GESPRAECH.\n"
        "\n"
        "https://bianca-and-lisa.pickadoc-tunnel.com\n"
        "\n"
        "Mikrofon erlauben, Anruf starten, einfach reden.\n"
        "Start ist Bianca: du rufst an. Tab Lisa: sie ruft an.\n"
        "\n"
        "Draht:\n"
        f"https://bianca-and-lisa.pickadoc-tunnel.com/fernsteuerung.html{hash_t}"
    )


def send(body: str) -> int:
    sid = peek(Path(r"F:\MAS-2\backend\.env"), "TWILIO_ACCOUNT_SID") or os.environ.get("TWILIO_ACCOUNT_SID", "")
    auth = peek(Path(r"F:\MAS-2\backend\.env"), "TWILIO_AUTH_TOKEN") or os.environ.get("TWILIO_AUTH_TOKEN", "")
    frm = (
        peek(Path(r"F:\MAS-2\backend\.env"), "LISA_SMS_SENDER")
        or peek(Path(r"F:\MAS-2\backend\.env"), "TWILIO_FROM")
        or peek(Path(r"F:\MAS-2\backend\.env"), "TWILIO_PHONE")
    )
    if not (sid and auth and frm):
        raise SystemExit("SMS nicht gesendet: Twilio-Zeilen fehlen.")
    data = urlencode({"From": frm, "To": "+491776004600", "Body": body}).encode("utf-8")
    req = Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
        data=data,
        method="POST",
    )
    import base64
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{sid}:{auth}".encode()).decode())
    with urlopen(req, timeout=20) as r:
        return r.status


def main() -> None:
    ok, grund = ready()
    print("ready:", "ja" if ok else "nein", "—", grund)
    if not ok:
        sys.exit(2)
    status = send(sms_body())
    print("SMS Status", status, "an Dev-Nummer")


if __name__ == "__main__":
    main()
