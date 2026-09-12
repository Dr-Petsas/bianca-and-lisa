import json
from pathlib import Path

root = Path("/app/tests/baukasten/berichte")
dirs = sorted([p for p in root.iterdir() if p.is_dir()], key=lambda p: p.name)
print("letzte laeufe:", [p.name for p in dirs[-5:]])
for d in dirs[-3:]:
    last = d / "lasttest.json"
    lauf = d / "lauf.json"
    print("\n====", d.name, "====")
    if last.exists():
        data = json.loads(last.read_text(encoding="utf-8"))
        print("gehalten", data.get("gehalten"), "fehler", data.get("fehler"),
              "turns", data.get("turns"))
        for x in data.get("laeufe") or []:
            print("-", x.get("tenant"), "ok" if x.get("ok") else "FAIL",
                  (x.get("fehler") or "")[:160])
            for z in (x.get("zuege") or [])[-8:]:
                print("   ANR", (z.get("baustein") or ""), "|", (z.get("soll") or "")[:90])
                print("   STT", (z.get("gehoert") or "")[:90],
                      "stt", (z.get("stt") or {}).get("winner") or (z.get("stt") or {}).get("gewinner") or "")
                print("   BIA", (z.get("text") or "")[:110])
    elif lauf.exists():
        data = json.loads(lauf.read_text(encoding="utf-8"))
        for s in data.get("stories") or []:
            print("-", s.get("id"), "ok" if s.get("ok") else "FAIL",
                  (s.get("fehler") or "")[:160])
            zuege = s.get("zuege") or []
            for z in zuege[-8:]:
                print("   ANR", (z.get("baustein") or z.get("wer") or ""),
                      (z.get("soll") or z.get("anrufer") or z.get("text") or "")[:90])
                print("   BIA", (z.get("bianca") or z.get("antwort") or "")[:110])
