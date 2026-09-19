"""Blessing-Dubletten-Mail ueber MAS Nadine versenden (info@pickadoc.de).

Wie tools/_blessing_mail_senden.py, zusaetzlich mit CSV-Anhang
(docs/mails/blessing-dubletten.csv). Signatur wird nur fuer DIESEN Versand
auf eine neutrale Pickadoc-Signatur gesetzt und danach zurueckgestellt.

Ohne --senden nur Trockenlauf.
"""
from __future__ import annotations

import argparse
import base64
import pathlib

import httpx

from kern import anrufaudio, standort

MAS = "http://127.0.0.1:4000"
CID = "MEe4ZQHEzOPzLcexyhdT"          # meddent (Hauptkonto liegt hier)
ACC = "7VH0vWRiGTEt57dV7ABv"          # info@pickadoc.de "Paraxis Haupt"
SCOPE = "https://www.googleapis.com/auth/datastore"
FBASE = "https://firestore.googleapis.com/v1"

EMPFAENGER = "kontakt@reutlingen-hautarzt.de"
CC = ["dr.petsas@pickadoc.de", "development@pickadoc.de"]
BETREFF = "Doppelte Patienten in Ihrer Kartei \u2013 Liste + wie Bianca dadurch besser wird"

HTML_PFAD = "docs/mails/blessing-dubletten.html"
CSV_PFAD = "docs/mails/blessing-dubletten.csv"

PICKADOC_SIG = (
    '<div style="font-family:Arial,Helvetica,sans-serif;font-size:11px;'
    'color:#9fb0c3;margin-top:6px;">Pickadoc \u00b7 '
    '<a href="https://pickadoc.de" style="color:#9fb0c3;">pickadoc.de</a></div>'
)


def _pfad() -> str:
    return (f"projects/{standort._projekt()}/databases/(default)/documents/"
            f"clients/{CID}/mas_mail_accounts/{ACC}")


def _get_sig() -> str:
    token = anrufaudio._access_token(SCOPE)
    r = httpx.get(f"{FBASE}/{_pfad()}", headers={"Authorization": f"Bearer {token}"}, timeout=15.0)
    r.raise_for_status()
    f = (r.json() or {}).get("fields", {})
    return standort._decode(f.get("emailSignatureHtml")) if "emailSignatureHtml" in f else ""


def _set_sig(html: str) -> int:
    token = anrufaudio._access_token(SCOPE)
    r = httpx.patch(
        f"{FBASE}/{_pfad()}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        params=[("updateMask.fieldPaths", "emailSignatureHtml")],
        json={"fields": {"emailSignatureHtml": {"stringValue": html}}},
        timeout=20.0,
    )
    if r.status_code != 200:
        print("   Firestore-Fehler:", r.status_code, str(r.text)[:300])
    return r.status_code


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--senden", action="store_true", help="wirklich versenden")
    args = ap.parse_args()

    html = pathlib.Path(HTML_PFAD).read_text(encoding="utf-8")
    csv_bytes = pathlib.Path(CSV_PFAD).read_bytes()
    csv_b64 = base64.b64encode(csv_bytes).decode("ascii")

    print(f"An:      {EMPFAENGER}")
    print(f"Cc:      {', '.join(CC)}")
    print(f"Betreff: {BETREFF}")
    print(f"HTML:    {len(html)} Zeichen")
    print(f"Anhang:  {CSV_PFAD}  ({len(csv_bytes)} Bytes, base64 {len(csv_b64)})")

    if not args.senden:
        print("\nTROCKENLAUF - nichts gesendet. Mit --senden ausfuehren.")
        return 0

    alt = _get_sig()
    print(f"\n1) alte Konto-Signatur gesichert ({len(alt)} Zeichen)")
    if _set_sig(PICKADOC_SIG) != 200:
        print("   Abbruch: Signatur konnte nicht gesetzt werden.")
        return 1
    print("2) Pickadoc-Signatur gesetzt")

    ok = False
    try:
        r = httpx.post(
            f"{MAS}/mail/send",
            headers={"X-Client-Id": CID, "Content-Type": "application/json"},
            json={
                "accountId": ACC,
                "to": EMPFAENGER,
                "cc": CC,
                "subject": BETREFF,
                "html": html,
                "attachments": [{"filename": "blessing-dubletten.csv", "content": csv_b64}],
                "logToBrain": False,
            },
            timeout=120.0,
        )
        print(f"3) /mail/send -> http {r.status_code}: {str(r.text)[:400]}")
        ok = r.status_code == 200 and r.json().get("ok") is True
    finally:
        rs = _set_sig(alt)
        print(f"4) Konto-Signatur zurueckgesetzt -> http {rs} "
              f"({'wieder leer' if not alt else 'alter Wert'})")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
