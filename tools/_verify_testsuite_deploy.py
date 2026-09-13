import hashlib
import subprocess
from pathlib import Path

LIVE = "telefonki-bianca-1"
TEST = "telefonki-bianca-test-1"
STUDIO = "telefonki-studio-1"
HOST = Path("/home/cursor/telefonki")

CHECKS = [
    "bianca/agent.py",
    "bianca/flow.py",
    "bianca/gehirn.py",
    "kern/stt.py",
    "kern/webpfad.py",
    "tests/baukasten/geschichten.py",
]


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


def img(name: str) -> str:
    r = subprocess.run(
        ["docker", "inspect", name, "--format", "{{.Image}}"],
        capture_output=True, text=True,
    )
    return (r.stdout or "").strip()


print("=== Images ===")
print("live  ", img(LIVE))
print("test  ", img(TEST))
print("studio", img(STUDIO))
print()
print("Datei                              host           live           test           studio")
print("-" * 92)
for rel in CHECKS:
    host = hashlib.sha256((HOST / rel).read_bytes()).hexdigest()[:12] if (HOST / rel).exists() else "FEHLT"
    live = csha(LIVE, rel)
    test = csha(TEST, rel)
    studio = csha(STUDIO, rel)
    mark = "TEST=HOST" if host == test == studio and live != test else (
        "ALLE GLEICH" if host == live == test == studio else "PRUEFEN"
    )
    print(f"{rel:<34} {host:<14} {live:<14} {test:<14} {studio:<14} {mark}")
print()
subprocess.run([
    "docker", "ps", "--format", "{{.Names}} | {{.Status}}",
    "--filter", "name=telefonki-bianca",
    "--filter", "name=telefonki-studio",
])
