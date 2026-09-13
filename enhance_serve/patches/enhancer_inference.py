import logging
from functools import cache
from pathlib import Path

import torch

from ..inference import inference
from .download import download
from .enhancer import Enhancer
from .hparams import HParams

logger = logging.getLogger(__name__)


@cache
def load_enhancer(run_dir: str | Path | None, device):
    run_dir = download(run_dir)
    hp = HParams.load(run_dir)
    enhancer = Enhancer(hp)
    path = run_dir / "ds" / "G" / "default" / "mp_rank_00_model_states.pt"
    state_dict = torch.load(path, map_location="cpu", weights_only=False)["module"]
    enhancer.load_state_dict(state_dict)
    enhancer.eval()
    enhancer.to(device)
    return enhancer


@torch.inference_mode()
def denoise(dwav, sr, device, run_dir=None):
    enhancer = load_enhancer(run_dir, device)
    return inference(model=enhancer.denoiser, dwav=dwav, sr=sr, device=device)


@torch.inference_mode()
def enhance(dwav, sr, device, nfe=32, solver="midpoint", lambd=0.5, tau=0.5, run_dir=None):
    enhancer = load_enhancer(run_dir, device)
    enhancer.configurate_(nfe=nfe, solver=solver, lambd=lambd, tau=tau)
    return inference(model=enhancer, dwav=dwav, sr=sr, device=device)
