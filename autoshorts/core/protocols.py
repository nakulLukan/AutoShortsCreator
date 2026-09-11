from typing import Protocol, runtime_checkable


class CancellationError(Exception):
    """Raised when the processing pipeline is cancelled by the user."""
    pass


@runtime_checkable
class CancellationToken(Protocol):
    """Contract for checking whether the user has requested cancellation."""

    def is_cancelled(self) -> bool:
        """Return True if cancellation has been requested."""
        ...


@runtime_checkable
class Logger(Protocol):
    """Contract for logging messages with severity levels."""

    def log(self, message: str, level: str) -> None:
        """Log a message at the given severity level."""
        ...


@runtime_checkable
class ProgressReporter(Protocol):
    """Contract for reporting pipeline progress."""

    def report_progress(self, percentage: int, message: str) -> None:
        """Report progress as a percentage (0-100) with a status message."""
        ...


@runtime_checkable
class HighlightStrategy(Protocol):
    """
    Contract for highlight detection strategies.

    Implementations analyze a video to find the most engaging segment
    and return its start time in seconds.
    """

    def find_highlights(self, video_path: str, target_duration: int, max_clips: int, scene_list: list = None) -> list[tuple[float, float]]:
        """
        Analyze the video and return the start times and scores of the
        best highlight segments of the given target duration.
        Optional scene_list provides [(start, end)] bounds in seconds.
        """
        ...
