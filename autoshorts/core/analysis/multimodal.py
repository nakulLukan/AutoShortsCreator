import subprocess
from typing import List

import numpy as np
import cv2
import librosa

from autoshorts.config import AppConfig
from autoshorts.core.protocols import Logger, ProgressReporter, HighlightStrategy
from autoshorts.models import LogLevel


class MultimodalAnalyzer:
    """
    Highlight detection strategy using audio energy and visual motion analysis.

    Combines:
    - Audio: RMS energy + spectral flux (onset strength)
    - Visual: Farneback dense optical flow magnitude

    Scores are fused with configurable weights and smoothed with a Gaussian
    filter. A sliding window (O(n) via np.convolve) finds the segment with
    the highest aggregate engagement score.

    Implements the HighlightStrategy protocol.
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

    def find_highlight(self, video_path: str, target_duration: int) -> float:
        """
        Analyze audio energy and visual motion to find the most engaging
        segment of `target_duration` seconds. Returns the start time in seconds.
        """
        # Progress allocation:
        #   30-40%  Audio extraction (FFmpeg)
        #   40-48%  Audio feature computation (librosa)
        #   48-68%  Visual motion analysis (optical flow) — the heavy part
        #   68-72%  Score fusion
        #   72-75%  Sliding window search

        audio_score, times = self._analyze_audio(video_path)
        visual_scores, visual_times, video_duration = self._analyze_visual(video_path)

        return self._fuse_and_search(
            audio_score, times,
            visual_scores, visual_times,
            video_duration, target_duration,
        )

    # ── Audio Analysis ──────────────────────────────────────────────

    def _analyze_audio(self, video_path: str):
        """Extract audio track and compute RMS + spectral flux scores."""
        self._progress.report_progress(30, "Extracting audio track from video...")

        sr = self._config.analysis.audio_sample_rate
        audio_path = str(self._config.temp_dir / "temp_audio.wav")

        result = subprocess.run(
            [
                self._config.ffmpeg_path, '-y', '-i', video_path,
                '-vn', '-acodec', 'pcm_s16le', '-ar', str(sr), '-ac', '1',
                audio_path,
            ],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
        )
        if result.returncode != 0:
            self._log.log(f"FFmpeg audio extraction failed: {result.stderr}", LogLevel.ERROR)
            raise RuntimeError(f"FFmpeg audio extraction failed: {result.stderr}")

        self._progress.report_progress(40, "Loading audio waveform...")
        y, sr = librosa.load(audio_path, sr=sr)
        audio_duration_sec = len(y) / sr
        self._log.log(f"Audio loaded: {audio_duration_sec:.1f}s at {sr}Hz", LogLevel.INFO)

        self._progress.report_progress(42, "Computing RMS energy...")
        rms = librosa.feature.rms(y=y)[0]
        times = librosa.frames_to_time(np.arange(len(rms)), sr=sr)

        self._progress.report_progress(44, "Computing spectral flux (onset strength)...")
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)

        self._progress.report_progress(46, "Normalizing audio features...")
        rms_norm = rms / np.max(rms) if np.max(rms) > 0 else rms
        onset_norm = onset_env / np.max(onset_env) if np.max(onset_env) > 0 else onset_env
        audio_score = (rms_norm * 0.5) + (onset_norm * 0.5)

        self._log.log(f"Audio analysis complete: {len(rms)} frames scored.", LogLevel.INFO)
        return audio_score, times

    # ── Visual Analysis ─────────────────────────────────────────────

    def _analyze_visual(self, video_path: str):
        """Compute dense optical flow motion scores by sampling video frames."""
        self._progress.report_progress(48, "Opening video for visual analysis...")

        resolution = self._config.analysis.optical_flow_resolution
        divisor = self._config.analysis.frame_sample_rate_divisor

        cap = cv2.VideoCapture(video_path)
        try:
            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            video_duration = total_frames / fps

            frame_step = max(1, int(fps / divisor))
            total_samples = max(1, total_frames // frame_step)

            self._log.log(
                f"Video: {video_duration:.1f}s, {fps:.1f}fps, {total_frames} frames. "
                f"Sampling every {frame_step} frames (~{total_samples} samples).",
                LogLevel.INFO,
            )

            visual_scores: List[float] = []
            visual_times: List[float] = []

            ret, prev_frame = cap.read()
            if ret:
                prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
                prev_gray = cv2.resize(prev_gray, resolution)

                frame_count = 0
                samples_processed = 0
                last_reported_pct = -1

                while cap.isOpened():
                    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_count)
                    ret, frame = cap.read()
                    if not ret:
                        break

                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    gray = cv2.resize(gray, resolution)

                    # Farneback Dense Optical Flow
                    flow = cv2.calcOpticalFlowFarneback(
                        prev_gray, gray, None, 0.5, 3, 15, 3, 5, 1.2, 0,
                    )
                    mag, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
                    mean_mag = float(np.mean(mag))

                    visual_scores.append(mean_mag)
                    visual_times.append(frame_count / fps)

                    prev_gray = gray
                    frame_count += frame_step
                    samples_processed += 1

                    # Report progress: map optical flow work to 48%–68% range
                    fraction = min(samples_processed / total_samples, 1.0)
                    current_pct = int(48 + fraction * 20)
                    if current_pct != last_reported_pct:
                        last_reported_pct = current_pct
                        time_pos = frame_count / fps
                        self._progress.report_progress(
                            current_pct,
                            f"Analyzing motion: {samples_processed}/{total_samples} samples "
                            f"({time_pos:.0f}s / {video_duration:.0f}s)",
                        )

                    if frame_count > total_frames:
                        break
        finally:
            cap.release()

        self._log.log(
            f"Visual analysis complete: {len(visual_scores)} motion samples computed.",
            LogLevel.INFO,
        )
        return visual_scores, visual_times, video_duration

    # ── Score Fusion & Sliding Window Search ────────────────────────

    def _fuse_and_search(
        self,
        audio_score, times,
        visual_scores, visual_times,
        video_duration: float, target_duration: int,
    ) -> float:
        """Fuse audio and visual scores, then find the best highlight window."""
        # Normalize visual scores
        v_scores_arr = np.array(visual_scores)
        v_scores_norm = (
            v_scores_arr / np.max(v_scores_arr)
            if np.max(v_scores_arr) > 0
            else v_scores_arr
        )

        self._progress.report_progress(69, "Interpolating visual scores to audio timeline...")

        # Interpolate visual scores to match audio timeline resolution
        v_scores_interp = np.interp(times, visual_times, v_scores_norm)

        w_audio = self._config.analysis.default_fusion_weights.get('audio', 0.5)
        w_visual = self._config.analysis.default_fusion_weights.get('visual', 0.5)

        self._progress.report_progress(
            70, f"Fusing scores (audio weight={w_audio}, visual weight={w_visual})...",
        )
        total_score = (audio_score * w_audio) + (v_scores_interp * w_visual)

        # Apply 1D Gaussian filter to smooth the scores
        kernel = self._config.analysis.gaussian_blur_kernel
        smoothed_score = cv2.GaussianBlur(
            total_score.reshape(-1, 1), kernel, 0,
        ).flatten()

        self._progress.report_progress(72, "Searching for best highlight window...")

        # Find the window of `target_duration` with the highest integral
        samples_per_sec = len(smoothed_score) / video_duration
        window_size = int(target_duration * samples_per_sec)

        # Ensure window isn't larger than the video
        if window_size >= len(smoothed_score):
            self._log.log(
                "Video is shorter than target duration. Using start of video.",
                LogLevel.WARN,
            )
            return 0.0

        # O(n) sliding window via convolution (replaces original O(n²) loop)
        window_sums = np.convolve(smoothed_score, np.ones(window_size), mode='valid')
        best_start_idx = int(np.argmax(window_sums))
        max_sum = float(window_sums[best_start_idx])

        self._log.log(
            f"Sliding window: size={window_size} samples, "
            f"searched {len(window_sums)} positions.",
            LogLevel.INFO,
        )

        best_start_time = float(times[best_start_idx])
        self._log.log(
            f"Best highlight found at {best_start_time:.2f}s (score: {max_sum:.2f}).",
            LogLevel.INFO,
        )
        return best_start_time
