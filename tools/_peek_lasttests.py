import json
from pathlib import Path

root = Path("/app/tests/baukasten/berichte")
dirs = sorted([p for p in root.iterdir() if p.is_dir()], key=lambda p: p.name)
print("BERICHTE", len(dirs))
for d in dirs[-8:]:
    print("\n====", d.name, "====")
    last = d / "lasttest.json"
    lauf = d / "lauf.json"
    if last.exists():
        data = json.loads(last.read_text(encoding="utf-8"))
        print("n", data.get("n"), "gehalten", data.get("gehalten"),
              "fehler", data.get("fehler"), "turns", data.get("turns"),
              "dauerS", data.get("dauerS"), "gesamt", data.get("gesamtSekunden"))
        print("dropouts", data.get("dropouts"))
        for x in data.get("laeufe") or []:
            print(" ", x.get("tenant"), "ok" if x.get("ok") else "FAIL",
                  (x.get("fehler") or "")[:220],
                  "turns", len(x.get("zuege") or []))
        base = data.get("baseline") or {}
        if isinstance(base, dict):
            for k, v in list(base.items())[:8]:
                if isinstance(v, dict):
                    print("  BASE", k, "ok" if v.get("ok") else "FAIL",
                          (v.get("fehler") or "")[:180])
        tr = data.get("transkript") or []
        sys_lines = [z for z in tr if z.get("wer") == "system"]
        print(" system", len(sys_lines))
        for z in sys_lines[-8:]:
            print("   SYS", z.get("phase"), z.get("nr"), (z.get("text") or "")[:200])
    elif lauf.exists():
        data = json.loads(lauf.read_text(encoding="utf-8"))
        stories = data.get("stories") or []
        print("einzel lauf stories", len(stories), "tenant", data.get("tenant"))
        for s in stories[:6]:
            print(" ", s.get("id"), "ok" if s.get("ok") else "FAIL",
                  (s.get("fehler") or "")[:200])
