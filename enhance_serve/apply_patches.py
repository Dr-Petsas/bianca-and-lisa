from pathlib import Path
import resemble_enhance

root = Path(resemble_enhance.__file__).parent
here = Path(__file__).resolve().parent / "patches"
(root / "utils" / "__init__.py").write_text((here / "utils_init.py").read_text(encoding="utf-8"), encoding="utf-8")
(root / "utils" / "distributed.py").write_text((here / "distributed.py").read_text(encoding="utf-8"), encoding="utf-8")
(root / "utils" / "train_loop.py").write_text((here / "train_loop.py").read_text(encoding="utf-8"), encoding="utf-8")
(root / "enhancer" / "inference.py").write_text((here / "enhancer_inference.py").read_text(encoding="utf-8"), encoding="utf-8")
(root / "denoiser" / "inference.py").write_text((here / "denoiser_inference.py").read_text(encoding="utf-8"), encoding="utf-8")
print("patched", root)
