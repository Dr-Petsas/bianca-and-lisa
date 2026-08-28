#!/bin/bash
# Kurzdiagnose 2: der vllm-Ladeblock in model.py + Registrierung.
echo "=== model.py 260-320 ==="
sed -n '260,320p' /opt/CosyVoice/cosyvoice/cli/model.py
echo "=== cosyvoice/vllm/cosyvoice2.py (Kopf) ==="
head -60 /opt/CosyVoice/cosyvoice/vllm/cosyvoice2.py
echo "=== cli/cosyvoice.py CosyVoice3-Init ==="
grep -n "class CosyVoice3" -A 40 /opt/CosyVoice/cosyvoice/cli/cosyvoice.py | head -60
echo "=== vllm-Doku im Repo ==="
ls /opt/CosyVoice/docs 2>/dev/null
grep -rn "vllm" /opt/CosyVoice/README.md | head -10
