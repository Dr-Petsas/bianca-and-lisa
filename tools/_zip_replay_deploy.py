from pathlib import Path
import zipfile

files = """
web/replay.html
bianca_web/replay.html
lisa/server.py
bianca/server.py
kern/gedaechtnis.py
kern/agentprofil.py
bianca/gehirn.py
bianca/flow.py
bianca/agent.py
lisa/outbound.py
""".split()
z = Path("app-deploy.zip")
with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
    for p in files:
        f = Path(p)
        if not f.is_file():
            raise SystemExit(f"fehlt {p}")
        zf.write(f, f.as_posix())
print(z, z.stat().st_size)
