# -*- coding: utf-8 -*-
"""Read-only: zaehlt echte Notfall-Wortlaute in textIn."""
import json
import re
import glob

PAT = re.compile(
    r"notfall|lebensgefahr|atemnot|erstick|"
    r"bewusstlos|kollaps|dicke backe|"
    r"\b112\b|rettungswagen|krankenwagen|"
    r"blutung|blutet|ausgeschlag|"
    r"starke[nr]? schmerz|unertraeglich|"
    r"sofort (?:kommen|in die praxis)|heute noch.*schmerz",
    re.I,
)
AKUT = re.compile(r"\bakut", re.I)
SCHMERZ = re.compile(r"schmerz|tut weh|schmerzhaft", re.I)

n_notfall = n_akut = n_schmerz = 0
belege_n, belege_a, belege_s = [], [], []
anrufe_n, anrufe_a, anrufe_s = set(), set(), set()

for p in sorted(glob.glob("/app/.data/anrufe/bianca/*/anruf.json")):
    try:
        m = json.loads(open(p, encoding="utf-8").read())
    except Exception:
        continue
    if m.get("testAnruf"):
        continue
    sid = m.get("id") or p
    for z in m.get("zuege") or []:
        t = (z.get("textIn") or "").strip()
        if not t:
            continue
        if PAT.search(t):
            n_notfall += 1
            anrufe_n.add(sid)
            if len(belege_n) < 20:
                belege_n.append(t.replace("\n", " ")[:180])
        if AKUT.search(t):
            n_akut += 1
            anrufe_a.add(sid)
            if len(belege_a) < 12:
                belege_a.append(t.replace("\n", " ")[:160])
        if SCHMERZ.search(t):
            n_schmerz += 1
            anrufe_s.add(sid)
            if len(belege_s) < 12:
                belege_s.append(t.replace("\n", " ")[:160])

print("NOTFALL-Wort anrufe", len(anrufe_n), "saetze", n_notfall)
for b in belege_n:
    print("  N", b)
print("AKUT-Wort anrufe", len(anrufe_a), "saetze", n_akut)
for b in belege_a:
    print("  A", b)
print("SCHMERZ-Wort anrufe", len(anrufe_s), "saetze", n_schmerz)
for b in belege_s:
    print("  S", b)
