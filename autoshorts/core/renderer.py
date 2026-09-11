import subprocess

from autoshorts.config import AppConfig
from autoshorts.core.protocols import Logger, ProgressReporter
from autoshorts.models import ProcessingOptions, LogLevel


class VideoRenderer:
    """
    Renders the final vertical (9:16) short video using FFmpeg.

    Handles hardware acceleration selection (CPU/NVENC/QSV), center cropping,
    and encoding with configurable quality parameters.
    """

    def __init__(
        self,
        config: AppConfig,
        logger: Logger,
        progress_reporter: ProgressReporter,
    ):
        self._config = config
        self._log = logger
        self._progress = progress_reporter

    def render(
        self,
        video_path: str,
        start_time: float,
        output_path: str,
        options: ProcessingOptions,
    ) -> None:
        """
        Slice, crop to 9:16, and encode the final video.

        Args:
            video_path: Path to the source video.
            start_time: Start time in seconds for the clip.
            output_path: Path for the output file.
            options: Processing options with duration, hw accel settings.
        """
        self._progress.report_progress(80, "Rendering final vertical video...")

        cmd = [
            self._config.ffmpeg_path, '-y',
            '-ss', str(start_time),
            '-i', video_path,
            '-t', str(options.target_duration),
        ]

        # Hardware Acceleration Selection
        hw_accel = options.hardware_accel
        vcodec = 'libx264'  # Default software fallback

        if hw_accel == "NVENC":
            vcodec = 'h264_nvenc'
        elif hw_accel == "QSV":
            vcodec = 'h264_qsv'

        # Smart Cropping (Center crop for 9:16)
        # In a full implementation, YOLOv8 object tracking would provide
        # dynamic X coordinates here. For now, static center crop.
        aspect = self._config.render.crop_aspect_ratio
        filter_complex = f"[0:v]crop=ih*({aspect}):ih[v_cropped]"

        cmd.extend([
            '-filter_complex', filter_complex,
            '-map', '[v_cropped]',
            '-map', '0:a',
            '-c:v', vcodec,
            '-preset', self._config.render.default_preset,
            '-crf', str(self._config.render.default_crf),
            '-c:a', 'aac',
            '-b:a', self._config.render.default_audio_bitrate,
            output_path,
        ])

        self._log.log(f"Executing FFmpeg: {' '.join(cmd)}", LogLevel.DEBUG)

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
        )

        for line in process.stdout:
            if "time=" in line:
                self._log.log(f"FFmpeg encoding... {line.strip()}", LogLevel.DEBUG)

        process.wait()
        if process.returncode != 0:
            raise RuntimeError(
                f"FFmpeg rendering failed with exit code {process.returncode}"
            )
