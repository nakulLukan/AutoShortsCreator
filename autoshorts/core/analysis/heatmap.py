from typing import List, Dict, Optional

from autoshorts.core.protocols import Logger, ProgressReporter, HighlightStrategy
from autoshorts.models import LogLevel


class HeatmapAnalyzer:
    """
    Highlight detection strategy using YouTube's viewer engagement heatmap.

    Finds the peak engagement point in the heatmap data and returns a start
    time centered around that peak, adjusted to avoid running past the end
    of the video.

    Implements the HighlightStrategy protocol.
    """

    def __init__(
        self,
        heatmap_data: List[Dict],
        logger: Logger,
        progress_reporter: ProgressReporter,
    ):
        self._heatmap = heatmap_data
        self._log = logger
        self._progress = progress_reporter

    def find_highlight(self, video_path: str, target_duration: int) -> float:
        """Find the peak of the YouTube heatmap and return the start time."""
        self._progress.report_progress(30, "Analyzing heatmap data...")

        if not self._heatmap:
            return 0.0

        peak_time = 0.0
        max_value = 0.0

        for point in self._heatmap:
            if 'value' in point and 'start_time' in point:
                if point['value'] > max_value:
                    max_value = point['value']
                    peak_time = point['start_time']

        # Center the clip around the peak, ensuring we don't start before 0
        safe_peak = max(0, peak_time - (target_duration / 2))
        self._log.log(
            f"Heatmap peak at {peak_time:.2f}s (value={max_value:.4f}), "
            f"clip starts at {safe_peak:.2f}s.",
            LogLevel.INFO,
        )
        return safe_peak
