"""Dubletten (doppelt angelegte Patienten) im Blessing-Account finden.

READ-ONLY. Repliziert die Plattform-Logik aus
docgendaweb/functions/src/services/duplicatesService.ts:
  similarityScore = nameSimilarity*0.6 + phoneSimilarity*0.4
  nameSimilarity  = Levenshtein-gewichtet (firstName, lastName*1.5, title*0.5)
  phoneSimilarity = exakt 1.0 / ohne Landesvorwahl 0.95 / aehnlich 0.8 / sonst Levenshtein
  Schwelle        = 0.8   (== Merge-Vorschlag im Portal)

Blocking (damit kein O(n^2) ueber tausende): Nachname-Praefix (3),
Soundex(Nachname), Handy/Festnetz letzte 7 Ziffern. Union-Find -> Gruppen.

Ausgabe: docs/mails/blessing-dubletten.csv  (UTF-8 BOM, Excel-tauglich)
"""
from __future__ import annotations

import csv
import datetime as _dt
import functools
import pathlib
import re
import sys

import httpx

print = functools.partial(print, flush=True)  # noqa: A001 (unbuffered Fortschritt)

from kern import anrufaudio, standort

CID = "UUJnPzoYPa4yYyzcaGlm"
SCOPE = "https://www.googleapis.com/auth/datastore"
BASE = "https://firestore.googleapis.com/v1"
SCHWELLE = 0.8


def _pfad(rest: str) -> str:
    return f"projects/{standort._projekt()}/databases/(default)/documents/{rest}"


def _list(rest: str, page_size: int = 300):
    out, page, seiten = [], None, 0
    while True:
        token = anrufaudio._access_token(SCOPE)  # ggf. neu (Ablauf bei vielen Seiten)
        params = {"pageSize": page_size}
        if page:
            params["pageToken"] = page
        r = httpx.get(f"{BASE}/{_pfad(rest)}",
                      headers={"Authorization": f"Bearer {token}"},
                      params=params, timeout=30.0)
        if r.status_code != 200:
            return r.status_code, r.text
        j = r.json() or {}
        out.extend(j.get("documents", []))
        seiten += 1
        page = j.get("nextPageToken")
        if seiten % 5 == 0 or not page:
            sys.stdout.write(f"    ... {len(out)} Dokumente ({seiten} Seiten)\n")
            sys.stdout.flush()
        if not page:
            return 200, out


def _f(doc):
    fields = (doc or {}).get("fields", {})
    return {k: standort._decode(v) for k, v in fields.items()}


# ---- Plattform-treue String-Aehnlichkeit (Levenshtein-Ratio) ---------------
def _sim(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if not a:
        return 1.0 if not b else 0.0
    if not b:
        return 0.0
    m, n = len(b), len(a)
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        cur = [i] + [0] * n
        for j in range(1, n + 1):
            cost = 0 if b[i - 1] == a[j - 1] else 1
            cur[j] = min(prev[j - 1] + cost, cur[j - 1] + 1, prev[j] + 1)
        prev = cur
    dist = prev[n]
    return 1 - dist / max(len(a), len(b))


def _digits(s: str) -> str:
    return "".join(ch for ch in str(s or "") if ch.isdigit())


def _ohne_land(s: str) -> str:
    d = _digits(s)
    if d.startswith("0049"):
        d = d[4:]
    elif d.startswith("49") and len(d) > 10:
        d = d[2:]
    if d.startswith("0"):
        d = d[1:]
    return d


def _name_sim(p, q) -> float:
    score = 0.0
    checks = 0.0
    if p["firstName"] and q["firstName"]:
        score += _sim(p["firstName"].lower(), q["firstName"].lower()); checks += 1
    if p["lastName"] and q["lastName"]:
        score += _sim(p["lastName"].lower(), q["lastName"].lower()) * 1.5; checks += 1.5
    if p["title"] and q["title"]:
        score += _sim(p["title"].lower(), q["title"].lower()) * 0.5; checks += 0.5
    return score / checks if checks else 0.0


def _phone_sim(p, q) -> float:
    ph1 = [x for x in (p["mobile"], p["phone"]) if x]
    ph2 = [x for x in (q["mobile"], q["phone"]) if x]
    if not ph1 or not ph2:
        return 0.0
    best = 0.0
    for a in ph1:
        for b in ph2:
            da, db = _digits(a), _digits(b)
            if da and da == db:
                return 1.0
            la, lb = _ohne_land(a), _ohne_land(b)
            if la and la == lb:
                return 0.95
            best = max(best, _sim(la, lb))
            if abs(len(la) - len(lb)) <= 1 and _sim(la, lb) > 0.85:
                best = max(best, 0.8)
    return best


def _score(p, q) -> float:
    return _name_sim(p, q) * 0.6 + _phone_sim(p, q) * 0.4


# ---- Strenge "gleiche Person"-Pruefung (hohe Praezision) --------------------
# Die reine Plattform-Formel (Name+Telefon) flaggt auch Familienmitglieder mit
# gleichem Nachnamen + geteilter Rufnummer (Mutter/Kind). Fuer eine Liste, die
# der Praxis zum Zusammenfuehren geschickt wird, zaehlt nur, was WIRKLICH
# dieselbe Person ist: gleicher Vorname UND gleicher Nachname UND ein geteiltes
# hartes Merkmal (E-Mail / Telefon / Geburtsdatum) - und NIE bei
# widerspruechlichem Geburtsdatum.
def _umlaut(s: str) -> str:
    return (str(s or "").lower().strip()
            .replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
            .replace("ß", "ss"))


def _first_tok(p) -> str:
    fn = _umlaut(p["firstName"])
    fn = re.split(r"[\s\-]+", fn)[0] if fn else ""
    return fn


def _birth_norm(s: str) -> str:
    s = str(s or "").strip()
    if not s:
        return ""
    if re.fullmatch(r"-?\d{5,}", s):  # Epoch-Millis
        try:
            return (_dt.datetime(1970, 1, 1)
                    + _dt.timedelta(milliseconds=int(s))).strftime("%Y-%m-%d")
        except Exception:
            return ""
    return s[:10]


def _phone_eq(p, q) -> bool:
    a = {_ohne_land(x) for x in (p["mobile"], p["phone"]) if _ohne_land(x) and len(_ohne_land(x)) >= 7}
    b = {_ohne_land(x) for x in (q["mobile"], q["phone"]) if _ohne_land(x) and len(_ohne_land(x)) >= 7}
    return bool(a & b)


def _ist_dublette(p, q) -> bool:
    bp, bq = _birth_norm(p["birth"]), _birth_norm(q["birth"])
    if bp and bq and bp != bq:
        return False  # verschiedene Geburtsdaten = verschiedene Menschen
    ls = _sim(_umlaut(p["lastName"]), _umlaut(q["lastName"]))
    fs = _sim(_first_tok(p), _first_tok(q))
    if not (_first_tok(p) and _first_tok(q) and p["lastName"] and q["lastName"]):
        return False
    if ls < 0.6 or fs < 0.6:
        return False  # anderer Vorname (Familie) faellt hier raus
    email_eq = bool(p["email"]) and p["email"].lower() == q["email"].lower()
    phone_eq = _phone_eq(p, q)
    birth_eq = bool(bp) and bp == bq
    if email_eq:
        return True
    if phone_eq:
        return True
    if birth_eq and ls >= 0.8 and fs >= 0.7:
        return True
    return False


# ---- Soundex (wie Plattform) ----------------------------------------------
_SNDX = {**dict.fromkeys("bfpv", "1"), **dict.fromkeys("cgjkqsxz", "2"),
         **dict.fromkeys("dt", "3"), "l": "4", **dict.fromkeys("mn", "5"), "r": "6"}


def _soundex(name: str) -> str:
    name = "".join(ch for ch in str(name or "").lower() if ch.isalpha())
    if not name:
        return ""
    res = name[0].upper()
    prev = _SNDX.get(name[0], "")
    for ch in name[1:]:
        code = _SNDX.get(ch, "")
        if code and code != prev:
            res += code
        prev = code if ch not in "hw" else prev
        if len(res) >= 4:
            break
    return (res + "000")[:4]


def _norm_last(p) -> str:
    s = (p["lastName"] or "").lower()
    return (s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
             .replace("ß", "ss").replace(" ", ""))


# ---- Union-Find ------------------------------------------------------------
class UF:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def _laden_patienten():
    """alle Patienten aller Standorte -> Liste von Dicts."""
    st, locs = _list(f"clients/{CID}/locations")
    if st != 200:
        raise RuntimeError(f"locations nicht lesbar: {st} {str(locs)[:200]}")
    pats = []
    for loc in locs:
        lid = loc["name"].rsplit("/", 1)[-1]
        locname = _f(loc).get("name") or lid
        st, docs = _list(f"clients/{CID}/locations/{lid}/patients")
        if st != 200:
            print(f"  ! patients ({locname}) nicht lesbar: {st}")
            continue
        for d in docs:
            f = _f(d)
            bd = f.get("birthDate") or ""
            if isinstance(bd, str) and "T" in bd:
                bd = bd.split("T")[0]
            pats.append({
                "id": d["name"].rsplit("/", 1)[-1],
                "loc": locname,
                "lid": lid,
                "firstName": str(f.get("firstName") or "").strip(),
                "lastName": str(f.get("lastName") or "").strip(),
                "title": str(f.get("title") or "").strip(),
                "birth": str(bd or "").strip(),
                "mobile": str(f.get("mobilePhoneNumber") or "").strip(),
                "phone": str(f.get("phoneNumber") or "").strip(),
                "email": str(f.get("email") or "").strip(),
                "city": str(f.get("city") or "").strip(),
                "uid": str(f.get("uid") or "").strip(),
            })
        print(f"  Standort {locname!r}: {len(docs)} Patienten")
    return pats


def main() -> int:
    print("Lade Patienten (read-only) ...")
    pats = _laden_patienten()
    n = len(pats)
    print(f"Gesamt: {n} Patienten\n")

    # Blocking
    bloecke: dict[str, list[int]] = {}
    for i, p in enumerate(pats):
        keys = set()
        nl = _norm_last(p)
        if len(nl) >= 3:
            keys.add("L:" + nl[:3])
        sx = _soundex(p["lastName"])
        if sx:
            keys.add("S:" + sx)
        for tel in (p["mobile"], p["phone"]):
            d = _ohne_land(tel)
            if len(d) >= 7:
                keys.add("T:" + d[-7:])
        for k in keys:
            bloecke.setdefault(k, []).append(i)

    kand = 0
    for idxs in bloecke.values():
        if len(idxs) >= 2:
            kand += len(idxs) * (len(idxs) - 1) // 2
    print(f"Bloecke: {len(bloecke)}, Kandidatenpaare (mit Doppelungen): {kand}")

    uf = UF()
    paare = []
    gesehen = set()
    verglichen = 0
    for idxs in bloecke.values():
        if len(idxs) < 2:
            continue
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                i, j = idxs[a], idxs[b]
                key = (i, j) if i < j else (j, i)
                if key in gesehen:
                    continue
                gesehen.add(key)
                verglichen += 1
                if verglichen % 200000 == 0:
                    print(f"    ... {verglichen} Paare verglichen, {len(paare)} Treffer")
                if _ist_dublette(pats[i], pats[j]):
                    uf.union(pats[i]["id"], pats[j]["id"])
                    paare.append((key, _score(pats[i], pats[j])))
    print(f"Eindeutige Paare verglichen: {verglichen}, sichere Dubletten-Paare: {len(paare)}")

    # Gruppen bilden
    gruppen: dict[str, list[int]] = {}
    id2idx = {p["id"]: i for i, p in enumerate(pats)}
    for p in pats:
        r = uf.find(p["id"])
        if r in uf.p:  # nur Knoten, die je in einem Paar waren
            gruppen.setdefault(r, [])
    # nur echte Gruppen (>=2)
    for p in pats:
        if p["id"] in uf.p:
            gruppen[uf.find(p["id"])].append(id2idx[p["id"]])
    gruppen = {k: v for k, v in gruppen.items() if len(v) >= 2}

    dubl_patienten = sum(len(v) for v in gruppen.values())
    ueberzaehlig = sum(len(v) - 1 for v in gruppen.values())
    print(f"Dubletten-Gruppen: {len(gruppen)}")
    print(f"Betroffene Patienten-Datensaetze: {dubl_patienten}")
    print(f"Ueberzaehlige (loeschbar nach Merge): {ueberzaehlig}\n")

    # CSV schreiben
    out = pathlib.Path("docs/mails/blessing-dubletten.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["Gruppe", "Anzahl", "Nachname", "Vorname", "Titel",
                    "Geburtsdatum", "Handy", "Festnetz", "E-Mail", "Ort",
                    "hat Login", "Patienten-ID", "Standort"])
        gi = 0
        for r, idxs in sorted(gruppen.items(), key=lambda kv: -len(kv[1])):
            gi += 1
            grp = sorted(idxs, key=lambda x: (pats[x]["lastName"].lower(),
                                              pats[x]["firstName"].lower()))
            for x in grp:
                p = pats[x]
                w.writerow([f"G{gi:03d}", len(grp), p["lastName"], p["firstName"],
                            p["title"], p["birth"], p["mobile"], p["phone"],
                            p["email"], p["city"], "ja" if p["uid"] else "nein",
                            p["id"], p["loc"]])
    print(f"CSV -> {out}  ({out.stat().st_size} Bytes)")

    # kleine Vorschau der groessten Gruppen
    print("\nGroesste Gruppen:")
    for r, idxs in sorted(gruppen.items(), key=lambda kv: -len(kv[1]))[:12]:
        p = pats[idxs[0]]
        print(f"  {len(idxs)}x  {p['lastName']}, {p['firstName']}  "
              f"(Geb {p['birth'] or '-'})")

    # Zahlen fuer die Mail als Klartext
    print("\n--- FUER DIE MAIL ---")
    print(f"gesamt_patienten={n}")
    print(f"gruppen={len(gruppen)}")
    print(f"betroffen={dubl_patienten}")
    print(f"ueberzaehlig={ueberzaehlig}")
    if n:
        print(f"anteil_betroffen_prozent={round(100*dubl_patienten/n,1)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
