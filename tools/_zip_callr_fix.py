from pathlib import Path
import zipfile

files = ["bianca/flow.py", "kern/agentprofil.py"]
z = Path("app-deploy.zip")
with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
    for p in files:
        f = Path(p)
        zf.write(f, f.as_posix())
print(z, z.stat().st_size)
