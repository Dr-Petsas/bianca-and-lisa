"""Read-only: Blessing-Benutzer auflisten + funktionierenden Arzt als Vorlage dumpen.

1) clients/<cid>/users  -> alle IDs mit Name/Rolle/hidden/allowOnline
2) Roh-Dokument des funktionierenden Arztes (Charlotte Blessing) als Feld-Vorlage
3) Roh-Dokument des kaputten Kalenders 'Dr.Ralf' (userId etc.)

NUR LESEN.
"""
from __future__ import annotations

import json

import httpx

from kern import anrufaudio, standort

CID = "UUJnPzoYPa4yYyzcaGlm"
LID = "dlxNwKLaA5VMEWQ5AjsL"
CAL_RALF = "TphQRh53x8SToBSa8DdB"
DOC_OK = "oX09QHERJLcnxq6eM73ssmbNEgl1"  # Charlotte Blessing (existiert)
SCOPE = "https://www.googleapis.com/auth/datastore"
BASE = "https://firestore.googleapis.com/v1"


def _pfad(rest: str) -> str:
    return f"projects/{standort._projekt()}/databases/(default)/documents/{rest}"


def _get(rest: str):
    token = anrufaudio._access_token(SCOPE)
    r = httpx.get(f"{BASE}/{_pfad(rest)}", headers={"Authorization": f"Bearer {token}"}, timeout=15.0)
    return r.status_code, (r.json() if r.status_code == 200 else r.text)


def _felder(doc):
    f = (doc or {}).get("fields") if isinstance(doc, dict) else None
    if not isinstance(f, dict):
        return {}
    return {k: standort._decode(v) for k, v in f.items()}


def main() -> int:
    # 1) Benutzerliste
    print("=" * 74)
    print("BENUTZER unter clients/%s/users" % CID)
    print("=" * 74)
    st, data = _get(f"clients/{CID}/users")
    ralf_kandidaten = []
    if st == 200 and isinstance(data, dict):
        for d in data.get("documents", []) or []:
            uid = str(d.get("name", "")).rsplit("/", 1)[-1]
            f = _felder(d)
            name = f"{f.get('firstName','')} {f.get('lastName','')}".strip()
            print(f"  {uid}  role={f.get('role')!r:12} hidden={f.get('hidden')} "
                  f"online={f.get('allowOnlineAppointments')}  name={name!r} titel={f.get('title')!r}")
            blob = json.dumps(f, ensure_ascii=False).lower()
            if "ralf" in blob:
                ralf_kandidaten.append((uid, name))
    else:
        print("  http", st, str(data)[:200])

    print()
    print("  Ralf-Treffer in der Benutzerliste:", ralf_kandidaten or "(keiner)")

    # 2) Vorlage: funktionierender Arzt
    print("=" * 74)
    print("VORLAGE (funktionierender Arzt Charlotte Blessing):")
    st, doc = _get(f"clients/{CID}/users/{DOC_OK}")
    print("  http", st)
    if st == 200:
        print(json.dumps(_felder(doc), ensure_ascii=False, indent=2))

    # 3) kaputter Kalender
    print("=" * 74)
    print("KALENDER 'Dr.Ralf':")
    st, doc = _get(f"clients/{CID}/locations/{LID}/calendars/{CAL_RALF}")
    print("  http", st)
    if st == 200:
        print(json.dumps(_felder(doc), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
