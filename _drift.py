import sys


def lade(pfad):
    d = {}
    for ln in open(pfad, encoding="utf-8"):
        ln = ln.rstrip("\n")
        if not ln:
            continue
        h, _, f = ln.partition("  ")
        if f:
            d[f.strip()] = h.strip()
    return d


loc = lade("/tmp/_lokal_md5.txt")
srv = lade("/tmp/_server_md5.txt")
fehlt = sorted(f for f, h in srv.items() if h == "FEHLT")
anders = sorted(f for f in loc if f in srv and srv[f] != "FEHLT" and srv[f] != loc[f])
print("FEHLT", len(fehlt))
for f in fehlt:
    print("  +", f)
print("ANDERS", len(anders))
for f in anders:
    print("  ~", f)
