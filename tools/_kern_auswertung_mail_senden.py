"""Ergebnisbericht "neuer Dialogkern" an Dr. Petsas senden (ueber MAS Nadine).

Interner Bericht, kein Kundenschreiben: Empfaenger ist der Chef selbst, darum
wird die Konto-/Praxis-Signatur NICHT umgestellt (anders als bei der
Blessing-Mail, siehe tools/_blessing_mail_senden.py).

Ohne --senden nur Trockenlauf. Schreibt zusaetzlich eine .eml zum Oeffnen in
Thunderbird.

    python tools/_kern_auswertung_mail_senden.py            # Trockenlauf + .eml
    python tools/_kern_auswertung_mail_senden.py --senden    # wirklich senden
"""
from __future__ import annotations

import argparse
import email.message
import email.utils
import pathlib

import httpx

MAS = "http://127.0.0.1:4000"
CID = "MEe4ZQHEzOPzLcexyhdT"          # meddent (dort liegt das Hauptkonto)
ACC = "7VH0vWRiGTEt57dV7ABv"          # info@pickadoc.de "Praxis Haupt"

EMPFAENGER = "dr.petsas@pickadoc.de"
BETREFF = "Neuer Dialogkern: Ergebnisse der Auswertung an 538 echten Anrufen"
HTML = pathlib.Path("docs/mails/dialogkern-vollauswertung-petsas-2026-09-19.html")


def _eml(html: str) -> pathlib.Path:
    m = email.message.EmailMessage()
    m["From"] = "Pickadoc <info@pickadoc.de>"
    m["To"] = EMPFAENGER
    m["Subject"] = BETREFF
    m["Date"] = email.utils.formatdate(localtime=True)
    m.set_content("Dieser Bericht braucht einen HTML-faehigen Mail-Client.")
    m.add_alternative(html, subtype="html")
    ziel = HTML.with_suffix(".eml")
    ziel.write_bytes(m.as_bytes())
    return ziel


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--senden", action="store_true", help="wirklich versenden")
    args = ap.parse_args()

    html = HTML.read_text(encoding="utf-8")
    print(f"An:      {EMPFAENGER}")
    print(f"Betreff: {BETREFF}")
    print(f"HTML:    {len(html)} Zeichen  ({HTML})")
    print(f"EML:     {_eml(html)}")

    if not args.senden:
        print("\nTROCKENLAUF - nichts gesendet. Mit --senden ausfuehren.")
        return 0

    r = httpx.post(
        f"{MAS}/mail/send",
        headers={"X-Client-Id": CID, "Content-Type": "application/json"},
        json={
            "accountId": ACC,
            "to": EMPFAENGER,
            "subject": BETREFF,
            "html": html,
            "logToBrain": False,
        },
        timeout=60.0,
    )
    print(f"\n/mail/send -> http {r.status_code}: {str(r.text)[:400]}")
    try:
        ok = r.status_code == 200 and r.json().get("ok") is True
    except Exception:
        ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
