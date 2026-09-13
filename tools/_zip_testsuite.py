from pathlib import Path
import zipfile

files = [
    "bianca/agent.py",
    "bianca/anstand.py",
    "bianca/arzt.py",
    "bianca/besuchsgrund.py",
    "bianca/flow.py",
    "bianca/gehirn.py",
    "bianca/hintergrund.py",
    "bianca/prompt.py",
    "bianca/weiterleiten.py",
    "kern/config.py",
    "kern/fachprofil.py",
    "kern/gespraech.py",
    "kern/notes.py",
    "kern/praxisregeln.py",
    "kern/stt.py",
    "kern/task_router.py",
    "kern/turn_context.py",
    "kern/wissen.py",
    "kern/zimmer_map.py",
    "kern/webpfad.py",
    "stt_serve/postcorrect.py",
    "tests/baukasten/geschichten.py",
    "tests/baukasten/klang.py",
    "tests/baukasten/lasttest.py",
    "tests/baukasten/saetze.py",
]
z = Path("app-deploy.zip")
with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
    for p in files:
        f = Path(p)
        if not f.is_file():
            raise SystemExit(f"fehlt: {p}")
        zf.write(f, f.as_posix())
print(z, z.stat().st_size, "dateien", len(files))
