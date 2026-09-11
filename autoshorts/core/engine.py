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

            # ── Step 2a: Scene Detection ────────────────────────────
            self._check_cancelled()
            self._progress.report_progress(30, "Detecting scene boundaries...")
            try:
                from scenedetect import detect, ContentDetector
                import logging
                logging.getLogger("scenedetect").setLevel(logging.WARNING)
                
                scene_list = detect(working_file, ContentDetector())
                scene_bounds = [(s.get_seconds(), e.get_seconds()) for s, e in scene_list]
                self._log.log(f"Detected {len(scene_bounds)} scenes.", LogLevel.INFO)
            except Exception as e:
                self._log.log(f"Scene detection failed: {e}", LogLevel.WARN)
                scene_bounds = None

            # ── Step 2b: Highlight Detection ─────────────────────────
            self._check_cancelled()
            strategy = self._select_strategy(heatmap_data)
            
            max_clips = self._options.max_clips
            clip_duration = self._options.target_duration / max_clips
            
            highlights = strategy.find_highlights(
                working_file, clip_duration, max_clips, scene_bounds
            )
            
            if self._options.arrangement == "Linear":
                # Sort chronologically by start time
                highlights.sort(key=lambda x: x[0])
            else:
                # Sort by score descending
                highlights.sort(key=lambda x: x[1], reverse=True)

            self._progress.report_progress(
                75, f"Identified {len(highlights)} highlight(s).",
            )

            # ── Step 3: Rendering ───────────────────────────────────
            self._check_cancelled()
            renderer = VideoRenderer(self._config, self._log, self._progress)
            
            temp_clips = []
            for i, (start_time, score) in enumerate(highlights):
                self._check_cancelled()
                temp_clip_path = str(self._config.temp_dir / f"temp_clip_{i}.mp4")
                
                # Scale progress between 75 and 95
                pct = 75 + int(20 * (i / len(highlights)))
                self._progress.report_progress(
                    pct, f"Rendering clip {i+1}/{len(highlights)} (start: {start_time:.1f}s)..."
                )
                
                renderer.render(
                    working_file, start_time,
                    temp_clip_path, self._options, clip_duration
                )
                temp_clips.append(temp_clip_path)

            # ── Step 4: Concatenation ───────────────────────────────
            self._check_cancelled()
            self._progress.report_progress(95, "Concatenating clips into final video...")
            self._concatenate_clips(temp_clips, self._output_path)
            
            for temp_clip in temp_clips:
                Path(temp_clip).unlink(missing_ok=True)

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
            return downloader.download(self._options.input_source, self._options.browser_cookies)
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

    def _concatenate_clips(self, clip_paths: list[str], output_path: str) -> None:
        """Concatenate multiple video clips into a single output file using FFmpeg."""
        if not clip_paths:
            return
            
        if len(clip_paths) == 1:
            shutil.copy(clip_paths[0], output_path)
            return
            
        list_file = self._config.temp_dir / "concat_list.txt"
        with open(list_file, 'w', encoding='utf-8') as f:
            for path in clip_paths:
                safe_path = Path(path).as_posix()
                f.write(f"file '{safe_path}'\n")
                
        cmd = [
            str(self._config.ffmpeg_path), '-y',
            '-f', 'concat',
            '-safe', '0',
            '-i', str(list_file),
            '-c', 'copy',
            output_path
        ]
        
        self._log.log(f"Concatenating clips: {' '.join(cmd)}", LogLevel.DEBUG)
        
        import subprocess
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True
        )
        if result.returncode != 0:
            self._log.log(f"FFmpeg concat failed: {result.stderr}", LogLevel.ERROR)
            raise RuntimeError(f"FFmpeg concat failed: {result.stderr}")
            
        list_file.unlink(missing_ok=True)

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
