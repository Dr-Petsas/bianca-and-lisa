from pathlib import Path
from lisa.server import WEB_DIR
from lisa import server as s
import inspect
print("WEB_DIR", WEB_DIR)
print("exists", (WEB_DIR / "replay.html").is_file())
src = inspect.getsource(s.web_file)
print(src)
