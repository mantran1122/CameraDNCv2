from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class HardwareProfile:
    chunk_seconds: int
    sample_fps: float
    max_new_tokens: int
    dtype: str
    attn_implementation: str
    cleanup_every: int
    chunk_encoder: str


PROFILES: Dict[str, HardwareProfile] = {
    "rtx5070ti_16gb": HardwareProfile(
        chunk_seconds=5,
        sample_fps=0.4,
        max_new_tokens=512,
        dtype="bfloat16",
        attn_implementation="sdpa",
        cleanup_every=4,
        chunk_encoder="nvenc",
    ),
    "speed": HardwareProfile(
        chunk_seconds=5,
        sample_fps=0.2,
        max_new_tokens=384,
        dtype="bfloat16",
        attn_implementation="sdpa",
        cleanup_every=6,
        chunk_encoder="nvenc",
    ),
    "accuracy": HardwareProfile(
        chunk_seconds=5,
        sample_fps=0.6,
        max_new_tokens=700,
        dtype="bfloat16",
        attn_implementation="sdpa",
        cleanup_every=2,
        chunk_encoder="nvenc",
    ),
}


def profile_names() -> list[str]:
    return list(PROFILES)


def get_profile(name: str) -> HardwareProfile:
    return PROFILES[name]


def configure_torch_runtime() -> None:
    try:
        import torch

        torch.set_float32_matmul_precision("high")
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
        torch.backends.cudnn.benchmark = True
    except Exception:
        pass
