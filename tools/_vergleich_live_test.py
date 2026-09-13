import hashlib
import subprocess
from pathlib import Path

DATEIEN = [
    "bianca/agent.py",
    "bianca/flow.py",
    "bianca/gehirn.py",
    "bianca/prompt.py",
    "bianca/weiterleiten.py",
    "bianca/besuchsgrund.py",
    "kern/stt.py",
    "kern/gespraech.py",
    "kern/task_router.py",
    "kern/wissen.py",
    "tests/baukasten/geschichten.py",
    "tests/baukasten/lasttest.py",
    "tests/baukasten/editor.py",
    "tests/baukasten/editor_web/app.js",
]
CONTAINERS = [
    ("live", "telefonki-bianca-1"),
    ("test", "telefonki-bianca-test-1"),
    ("studio", "telefonki-studio-1"),
]
HOST = Path("/home/cursor/telefonki")


def csha(container: str, rel: str) -> str:
    code = (
        "import hashlib, pathlib, sys; "
        "p=pathlib.Path('/app')/sys.argv[1]; "
        "print(hashlib.sha256(p.read_bytes()).hexdigest()[:12] "
        "if p.exists() else 'FEHLT')"
    )
    r = subprocess.run(
        ["docker", "exec", container, "python3", "-c", code, rel],
        capture_output=True, text=True,
    )
    return (r.stdout or "").strip() or "ERR"


def hsha(rel: str) -> str:
    p = HOST / rel
    if not p.exists():
        return "FEHLT"
    return hashlib.sha256(p.read_bytes()).hexdigest()[:12]


print("=== Container ===")
subprocess.run([
    "docker", "ps", "--format",
    "{{.Names}} | {{.Status}} | {{.RunningFor}}",
    "--filter", "name=telefonki-bianca",
    "--filter", "name=telefonki-studio",
])
print()
print("Datei                              host           live           test           studio")
print("-" * 92)
diffs = 0
for rel in DATEIEN:
    host = hsha(rel)
    live = csha("telefonki-bianca-1", rel)
    test = csha("telefonki-bianca-test-1", rel)
    studio = csha("telefonki-studio-1", rel)
    mark = "OK" if host == live == test == studio else "DIFF"
    if mark == "DIFF":
        diffs += 1
    print(f"{rel:<34} {host:<14} {live:<14} {test:<14} {studio:<14} {mark}")
print()
print("DIFF-Dateien:", diffs)
print()
print("=== Images ===")
subprocess.run(["docker", "images", "telefonki:v1", "--format", "{{.ID}} created={{.CreatedSince}}"])
print()
for name in ("telefonki-bianca-1", "telefonki-bianca-test-1", "telefonki-studio-1"):
    subprocess.run([
        "docker", "inspect", name,
        "--format", "{{.Name}} created={{.Created}} image={{.Image}}",
    ])
