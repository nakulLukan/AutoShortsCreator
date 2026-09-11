import shutil
import traceback
from pathlib import Path

from autoshorts.config import AppConfig
from autoshorts.models import ProcessingOptions, LogLevel
from autoshorts.core.protocols import (
    Logger, ProgressReporter, HighlightStrategy, CancellationToken,
    CancellationError,
)
from autoshorts.core.downloader import VideoDownloader
from autoshorts.core.renderer import VideoRenderer
from autoshorts.core.analysis.heatmap import HeatmapAnalyzer
from autoshorts.core.analysis.multimodal import MultimodalAnalyzer


class VideoProcessorEngine:
    """
    Thin orchestrator that coordinates the video processing pipeline.

    All heavy lifting is delegated to injected components:
    - VideoDownloader for media ingestion
    - HighlightStrategy implementations for segment detection
    - VideoRenderer for final output encoding

    Dependencies are injected via the constructor, following the
    Dependency Inversion Principle.
    """

    def __init__(
        self,
        options: ProcessingOptions,
        config: AppConfig,
        logger: Logger,
        progress_reporter: ProgressReporter,
        cancellation_token: CancellationToken | None = None,
    ):
        self._options = options
        self._config = config
        self._log = logger
        self._progress = progress_reporter
        self._cancel = cancellation_token

        # Ensure temp directory exists
        self._config.temp_dir.mkdir(exist_ok=True)

        # Determine output filename
        if self._options.is_url:
            source_name = "youtube_video"
        else:
            source_name = Path(self._options.input_source).stem

        self._output_path = str(
            Path(self._options.output_dir) / f"{source_name}_short.mp4"
        )

    def _check_cancelled(self) -> None:
        """Raise CancellationError if the user requested a stop."""
        if self._cancel is not None and self._cancel.is_cancelled():
            raise CancellationError("Processing cancelled by user.")

    def process(self) -> None:
        """Run the full processing pipeline: ingest → analyze → render."""
        try:
            self._progress.report_progress(5, "Starting processing pipeline...")

            # ── Step 1: Ingestion ───────────────────────────────────
            self._check_cancelled()
            working_file, heatmap_data = self._ingest()
            self._progress.report_progress(25, f"Media ready: {working_file}")

            # ── Step 2: Highlight Detection ─────────────────────────
            self._check_cancelled()
            strategy = self._select_strategy(heatmap_data)
            start_time = strategy.find_highlight(
                working_file, self._options.target_duration,
            )
            self._progress.report_progress(
                75, f"Highlight identified at {start_time:.2f} seconds.",
            )

            # ── Step 3: Rendering ───────────────────────────────────
            self._check_cancelled()
            renderer = VideoRenderer(self._config, self._log, self._progress)
            renderer.render(
                working_file, start_time,
                self._output_path, self._options,
            )

            self._progress.report_progress(100, "Processing Complete!")
            self._log.log(
                f"Final video saved to: {self._output_path}", LogLevel.INFO,
            )

        except CancellationError:
            self._log.log("Pipeline cancelled by user.", LogLevel.WARN)
            raise
        except Exception as e:
            self._log.log(
                f"Pipeline Failed: {str(e)}\n{traceback.format_exc()}",
                LogLevel.ERROR,
            )
            raise
        finally:
            self._cleanup_temp_files()

    def _ingest(self):
        """Download from URL or validate local file. Returns (path, heatmap_or_None)."""
        if self._options.is_url:
            downloader = VideoDownloader(self._config, self._log, self._progress)
            return downloader.download(self._options.input_source)
        else:
            return self._options.input_source, None

    def _select_strategy(self, heatmap_data) -> HighlightStrategy:
        """Choose the appropriate highlight detection strategy."""
        if heatmap_data:
            self._log.log(
                "Using YouTube Heatmap data for highlight extraction.",
                LogLevel.INFO,
            )
            return HeatmapAnalyzer(heatmap_data, self._log, self._progress)
        else:
            self._log.log(
                "No heatmap data available. Starting Multimodal AI Analysis.",
                LogLevel.INFO,
            )
            return MultimodalAnalyzer(self._config, self._log, self._progress)

    def _cleanup_temp_files(self) -> None:
        """Remove temporary files created during processing."""
        try:
            temp_audio = self._config.temp_dir / "temp_audio.wav"
            if temp_audio.exists():
                temp_audio.unlink()
                self._log.log("Cleaned up temporary audio file.", LogLevel.DEBUG)
        except OSError as e:
            self._log.log(
                f"Warning: Could not clean up temp files: {e}",
                LogLevel.WARN,
            )
