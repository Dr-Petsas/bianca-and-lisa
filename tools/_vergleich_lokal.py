import hashlib
from pathlib import Path

root = Path(r"F:\Bianca&Lisa TelefonKI")
server = {
    "bianca/agent.py": "a494553349ca",
    "bianca/flow.py": "a42a5f60a0ec",
    "bianca/gehirn.py": "8cafc92b133a",
    "kern/stt.py": "3a3f568ac762",
    "tests/baukasten/geschichten.py": "35c1c595dbe1",
    "tests/baukasten/lasttest.py": "65b621829c3d",
}
print("Datei                              lokal          server")
print("-" * 70)
for rel, remote in server.items():
    local = hashlib.sha256((root / rel).read_bytes()).hexdigest()[:12]
    mark = "gleich" if local == remote else "LOKAL ANDERS"
    print(f"{rel:<34} {local:<14} {remote:<14} {mark}")
