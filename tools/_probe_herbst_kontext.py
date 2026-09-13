"""Live: was Bianca zu Herbsts Nummer jetzt sieht."""
from __future__ import annotations

import json
import os

import httpx

from kern import gedaechtnis as ged
from kern.config import MAS_CLIENT_ID, MAS_URL

PHONE = "+491777074403"
NAME = "Patrick Herbst"


def main() -> None:
    print("MAS_URL", MAS_URL)
    print("enabled", ged.enabled())
    print("client", MAS_CLIENT_ID)
    text, ids = ged._kontext_stand(PHONE, NAME, MAS_CLIENT_ID or "")
    print("=== _kontext_stand ===")
    print("offen", ids)
    print(text or "(leer)")
    h = {"X-Client-Id": MAS_CLIENT_ID or "MEe4ZQHEzOPzLcexyhdT"}
    tok = os.environ.get("MAS_TOKEN")
    if tok:
        h["X-Service-Token"] = tok
    for label, url, params in (
        ("caller-context", f"{MAS_URL}/brain/caller-context", {"phone": PHONE}),
        ("search-phone", f"{MAS_URL}/brain/search",
         {"q": "01777074403", "kind": "event", "sinceDays": 14, "limit": 10}),
        ("karteikarte", f"{MAS_URL}/brain/karteikarte",
         {"name": NAME, "sinceDays": 14}),
    ):
        r = httpx.get(url, params=params, headers=h, timeout=20)
        print(f"\n=== {label} {r.status_code} ===")
        print(json.dumps(r.json(), ensure_ascii=False)[:1800])


if __name__ == "__main__":
    main()
