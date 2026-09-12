"""Thaler-Kalender + Zimmer-Karte (read-only)."""
from __future__ import annotations

from kern import kalender_db, tenants, zimmer_map

CLIENT = "7tTnJZfJkb801r2rmYed"
LOC = "loc_m219jgfb"


def main() -> None:
    print("kalender_db.an", kalender_db.an())
    raeume = kalender_db.funktionsraeume(CLIENT, LOC)
    print("zimmer", len(raeume))
    for c in raeume:
        print(" ", tenants.zimmer_nr(c.get("name")), c.get("name"), c.get("id"))
    t = {
        "clientId": CLIENT,
        "locationId": LOC,
        "calendars": list(raeume),
        "zimmerMap": dict(zimmer_map.DEFAULT_MAP),
    }
    for grp in ("pzr", "akut", "behandlung"):
        ids = [(c.get("name"), c.get("id")) for c in zimmer_map.raeume(t, grp)]
        print(grp, ids)


if __name__ == "__main__":
    main()
