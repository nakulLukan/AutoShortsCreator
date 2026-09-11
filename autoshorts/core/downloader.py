from typing import Tuple, Optional, List, Dict
from pathlib import Path

import yt_dlp

from autoshorts.config import AppConfig
from autoshorts.core.protocols import Logger, ProgressReporter
from autoshorts.models import LogLevel


class VideoDownloader:
    """
    Downloads videos from YouTube using yt-dlp and extracts heatmap metadata
    when available.
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

    def download(self, url: str, browser_cookies: str = "None") -> Tuple[str, Optional[List[Dict]]]:
        """
        Download a video from the given URL.

        Returns:
            Tuple of (local_file_path, heatmap_data_or_None)
        """
        self._log.log(f"Downloading video from {url}...", LogLevel.INFO)

        output_template = str(self._config.temp_dir / "%(id)s.%(ext)s")
        heatmap_data = None

        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': output_template,
            'quiet': True,
            'no_warnings': True,
            'dump_single_json': True,
        }
        
        if browser_cookies and browser_cookies.lower() != "none":
            ydl_opts['cookiesfrombrowser'] = (browser_cookies.lower(),)

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # First extract info to check for heatmap
            self._progress.report_progress(10, "Extracting metadata...")
            info_dict = ydl.extract_info(url, download=False)

            # Check for heatmap data
            if 'heatmap' in info_dict:
                heatmap_data = info_dict['heatmap']

            # Now download
            self._progress.report_progress(
                15, "Downloading media files (this may take a while)...",
            )
            ydl_opts['dump_single_json'] = False
            with yt_dlp.YoutubeDL(ydl_opts) as ydl_download:
                error_code = ydl_download.download([url])
                if error_code != 0:
                    raise RuntimeError("yt-dlp failed to download the video.")

            # Locate the downloaded file
            expected_file = self._config.temp_dir / f"{info_dict['id']}.mp4"
            if not expected_file.exists():
                # Fallback search if format changed extension
                files = list(self._config.temp_dir.glob(f"{info_dict['id']}.*"))
                if not files:
                    raise FileNotFoundError("Downloaded file could not be located.")
                expected_file = files[0]

        return str(expected_file), heatmap_data
