"""Kurz-SMS an die Dev-Nummer, wenn ein Umbau zum Telefontest bereit ist.

Nutzt exakt denselben Versandweg wie tools/_sms_replay.py: Twilio aus der
MAS-.env, sonst smsflatrate-Key aus dem contractSign-Controller. Kein Secret
landet im Log. Aufruf:

    python tools/_notify_test_sms.py "Text der Nachricht"
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import quote

import httpx

MAS_ENV = Path(r"F:\MAS-2\backend\.env")
CF_SIGN = Path(r"F:\pickadoc-live-base\docgendaweb\functions\src\controllers\contractSign.ts")
CHEF = "01776004600"


def peek_env(name: str) -> str:
    if not MAS_ENV.is_file():
        return ""
    for line in MAS_ENV.read_text(encoding="utf-8-sig").splitlines():
        raw = line.strip()
        if raw.startswith(f"{name}="):
            return raw.partition("=")[2].strip().strip('"').strip("'")
    return ""


def peek_flatrate() -> str:
    if not CF_SIGN.is_file():
        return ""
    m = re.search(r'SMS_API_KEY\s*=\s*"([a-f0-9]+)"', CF_SIGN.read_text(encoding="utf-8"))
    return m.group(1) if m else ""


def sende(body: str) -> int:
    sid, token, sender = (
        peek_env("TWILIO_ACCOUNT_SID"),
        peek_env("TWILIO_AUTH_TOKEN"),
        peek_env("LISA_SMS_SENDER"),
    )
    if sid and token and sender:
        r = httpx.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
            auth=(sid, token),
            data={"To": "+49" + CHEF[1:], "From": sender, "Body": body[:640]},
            timeout=20.0,
        )
        if r.status_code in (200, 201):
            print("SMS Twilio", r.status_code)
            return 0
        print("Twilio", r.status_code, "-> smsflatrate")
    key = peek_flatrate()
    if not key:
        print("kein SMS-Zugang")
        return 2
    msg = body.replace(" ", "+").replace("\n", "%0a")
    url = (
        "https://www.smsflatrate.net/schnittstelle.php"
        f"?key={key}&from=Pickadoc&to={quote(CHEF)}&text={msg}&type=auto1or2&status=1&cost=1"
    )
    r = httpx.get(url, timeout=20.0)
    status = (str(r.text or "").split(",")[0] or "").strip()
    print("smsflatrate", r.status_code, "status", status)
    return 0 if status == "100" else 1


def main() -> int:
    body = " ".join(sys.argv[1:]).strip() or "Bianca-Umbau bereit zum Telefontest."
    return sende(body)


if __name__ == "__main__":
    raise SystemExit(main())
