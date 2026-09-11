import platform
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Tuple

# Project root is one level up from the autoshorts package
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class AnalysisConfig:
    """Tunable parameters for audio/visual highlight analysis."""
    audio_sample_rate: int = 16000
    optical_flow_resolution: Tuple[int, int] = (320, 180)
    frame_sample_rate_divisor: float = 2.0  # fps / this = samples per second
    gaussian_blur_kernel: Tuple[int, int] = (51, 1)
    default_fusion_weights: Dict[str, float] = field(
        default_factory=lambda: {'audio': 0.6, 'visual': 0.4}
    )


@dataclass
class RenderConfig:
    """FFmpeg encoding parameters."""
    default_crf: int = 23
    default_audio_bitrate: str = "128k"
    default_preset: str = "fast"
    crop_aspect_ratio: str = "9/16"


@dataclass
class AppConfig:
    """
    Central configuration for the entire application.

    Consolidates all hardcoded constants from the original monolithic main.py
    into a single, structured config with sensible defaults.
    Platform-aware FFmpeg path resolution.
    """
    ffmpeg_path: str = ""
    ffprobe_path: str = ""
    temp_dir: Path = field(default_factory=lambda: _PROJECT_ROOT / "temp_processing")
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    render: RenderConfig = field(default_factory=RenderConfig)

    def __post_init__(self):
        ext = ".exe" if platform.system() == "Windows" else ""
        if not self.ffmpeg_path:
            self.ffmpeg_path = str(_PROJECT_ROOT / f"ffmpeg{ext}")
        if not self.ffprobe_path:
            self.ffprobe_path = str(_PROJECT_ROOT / f"ffprobe{ext}")
