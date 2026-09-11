from enum import Enum
from dataclasses import dataclass
from typing import Dict


@dataclass
class ProcessingOptions:
    """User-configurable options for the video processing pipeline."""
    input_source: str
    is_url: bool
    output_dir: str
    target_duration: int
    hardware_accel: str
    fusion_weights: Dict[str, float]


class LogLevel(str, Enum):
    """Enumeration of log severity levels with string values for display."""
    INFO = "INFO"
    WARN = "WARNING"
    ERROR = "ERROR"
    DEBUG = "DEBUG"
