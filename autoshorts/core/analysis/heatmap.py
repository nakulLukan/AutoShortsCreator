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

    def find_highlights(self, video_path: str, target_duration: int, max_clips: int, scene_list: list = None) -> list[tuple[float, float]]:
        """Find the top peaks of the YouTube heatmap and return their start times and scores."""
        self._progress.report_progress(30, "Analyzing heatmap data...")

        if not self._heatmap:
            return [(0.0, 0.0)]

        # Extract valid points
        points = [p for p in self._heatmap if 'value' in p and 'start_time' in p]
        
        # Sort points by value descending
        points.sort(key=lambda x: x['value'], reverse=True)

        selected_clips = []
        for point in points:
            if len(selected_clips) >= max_clips:
                break
                
            peak_time = point['start_time']
            score = point['value']
            
            safe_peak = max(0, peak_time - (target_duration / 2))
            
            if scene_list:
                nearest = min(scene_list, key=lambda s: abs(s[0] - safe_peak))
                if abs(nearest[0] - safe_peak) < 5.0:
                    self._log.log(f"Snapping heatmap peak from {safe_peak:.2f}s to scene boundary at {nearest[0]:.2f}s", LogLevel.INFO)
                    safe_peak = nearest[0]
            
            # Check for overlap with already selected clips
            overlap = False
            for selected_start, _ in selected_clips:
                if not (safe_peak + target_duration <= selected_start or safe_peak >= selected_start + target_duration):
                    overlap = True
                    break
            
            if not overlap:
                selected_clips.append((safe_peak, score))
                self._log.log(
                    f"Selected heatmap highlight at {safe_peak:.2f}s (score={score:.4f})",
                    LogLevel.INFO,
                )

        if not selected_clips:
            selected_clips.append((0.0, 0.0))

        return selected_clips
