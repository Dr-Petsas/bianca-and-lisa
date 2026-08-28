"""Kurzdiagnose im Container: Welche Beschleunigungs-Parameter kennt AutoModel?"""
import inspect
import sys

sys.path.insert(0, "/opt/CosyVoice")
sys.path.insert(0, "/opt/CosyVoice/third_party/Matcha-TTS")

import cosyvoice.cli.cosyvoice as m  # noqa: E402

print("AutoModel:", inspect.signature(m.AutoModel))
for name in ("CosyVoice", "CosyVoice2", "CosyVoice3"):
    kl = getattr(m, name, None)
    if kl is not None:
        print(f"{name}.__init__:", inspect.signature(kl.__init__))
