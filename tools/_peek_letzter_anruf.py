import json, glob, os, sys

base = "/app/.data/anrufe/bianca"
dirs = sorted(glob.glob(base + "/*"), key=os.path.getmtime)
arg = sys.argv[1] if len(sys.argv) > 1 else "-1"
if arg.lstrip("-").isdigit():
    d = dirs[int(arg)]
else:
    d = [x for x in dirs if arg in os.path.basename(x)][-1]

m = json.load(open(d + "/anruf.json", encoding="utf-8"))
print("DIR", os.path.basename(d), "| startedAt", m.get("startedAt"))
print("=== VOLLES TRANSKRIPT (mit Anrufer) ===")
for i, z in enumerate(m.get("zuege", [])):
    # Anrufer-Seite: verschiedene moegliche Felder
    an = z.get("textIn") or z.get("gehoert") or ""
    if not an:
        for a in (z.get("aufnahmen") or []):
            if a.get("text"):
                an = (an + " | " + a["text"]).strip(" |")
    if an:
        print(f"[{i}] ANRUFER:", an)
    b = z.get("text") or z.get("reply") or ""
    if b:
        print(f"[{i}] BIANCA :", b)
    if i == 0:
        print("    (keys:", ",".join(sorted(z.keys())), ")")
