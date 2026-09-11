import subprocess
import concurrent.futures
from typing import List

import numpy as np
import cv2
import librosa

from autoshorts.config import AppConfig
from autoshorts.core.protocols import Logger, ProgressReporter, HighlightStrategy
from autoshorts.models import LogLevel


class MultimodalAnalyzer:
    """
    Highlight detection strategy using audio energy, speech detection, and visual motion analysis.

    Combines:
    - Audio: RMS energy + spectral flux + Silero VAD (Voice Activity Detection)
    - Visual: Fast frame difference (absdiff) magnitude

    Scores are computed in parallel, fused with configurable weights, and smoothed with a Gaussian
    filter. A sliding window (O(n) via np.convolve) finds the segment with the highest score.
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

    def find_highlights(self, video_path: str, target_duration: int, max_clips: int, scene_list: list = None) -> list[tuple[float, float]]:
        """
        Analyze audio and visual features to find the most engaging segments.
        """
        self._progress.report_progress(30, "Starting parallel multimodal analysis...")

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            future_audio = executor.submit(self._analyze_audio, video_path)
            future_visual = executor.submit(self._analyze_visual, video_path)
            
            # Wait for both to complete
            audio_score, times = future_audio.result()
            visual_scores, visual_times, video_duration = future_visual.result()

        return self._fuse_and_search(
            audio_score, times,
            visual_scores, visual_times,
            video_duration, target_duration,
            max_clips,
            scene_list
        )

    # ── Audio Analysis ──────────────────────────────────────────────

    def _analyze_audio(self, video_path: str):
        """Extract audio track, compute RMS + spectral flux, and apply Silero VAD."""
        self._progress.report_progress(35, "[Audio] Extracting track...")

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

        self._progress.report_progress(40, "[Audio] Loading waveform...")
        y, sr = librosa.load(audio_path, sr=sr)
        audio_duration_sec = len(y) / sr

        self._progress.report_progress(45, "[Audio] Computing features (RMS & Onset)...")
        rms = librosa.feature.rms(y=y)[0]
        times = librosa.frames_to_time(np.arange(len(rms)), sr=sr)
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)

        rms_norm = rms / np.max(rms) if np.max(rms) > 0 else rms
        onset_norm = onset_env / np.max(onset_env) if np.max(onset_env) > 0 else onset_env

        # Run Silero VAD
        self._progress.report_progress(50, "[Audio] Running Silero VAD...")
        try:
            from silero_vad import load_silero_vad, get_speech_timestamps, read_audio
            import logging
            logging.getLogger("silero_vad").setLevel(logging.WARNING)

            vad_model = load_silero_vad(onnx=True)
            wav = read_audio(audio_path)
            speech_timestamps = get_speech_timestamps(wav, vad_model, return_seconds=True)
            
            vad_mask = np.zeros_like(rms_norm)
            hop_length = 512  # librosa default
            
            for seg in speech_timestamps:
                start_idx = int(seg['start'] * sr / hop_length)
                end_idx = int(seg['end'] * sr / hop_length)
                # Keep index within bounds
                start_idx = min(start_idx, len(vad_mask) - 1)
                end_idx = min(end_idx, len(vad_mask))
                vad_mask[start_idx:end_idx] = 1.0

            audio_score = (rms_norm * 0.3) + (onset_norm * 0.3) + (vad_mask * 0.4)
            self._log.log(
                f"Audio analysis complete with VAD. Found {len(speech_timestamps)} speech segments.", 
                LogLevel.INFO
            )
        except Exception as e:
            self._log.log(f"Silero VAD failed, falling back to basic audio scoring: {e}", LogLevel.WARN)
            audio_score = (rms_norm * 0.5) + (onset_norm * 0.5)

        return audio_score, times

    # ── Visual Analysis ─────────────────────────────────────────────

    def _analyze_visual(self, video_path: str):
        """Compute visual motion scores by sampling video frames using fast absdiff."""
        self._progress.report_progress(35, "[Visual] Opening video for motion analysis...")

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

                    # Fast Frame Difference instead of dense optical flow
                    diff = cv2.absdiff(prev_gray, gray)
                    mean_mag = float(cv2.mean(diff)[0])

                    visual_scores.append(mean_mag)
                    visual_times.append(frame_count / fps)

                    prev_gray = gray
                    frame_count += frame_step
                    samples_processed += 1

                    # Report progress
                    fraction = min(samples_processed / total_samples, 1.0)
                    current_pct = int(35 + fraction * 30)  # Map to 35-65%
                    if current_pct != last_reported_pct:
                        last_reported_pct = current_pct
                        time_pos = frame_count / fps
                        self._progress.report_progress(
                            current_pct,
                            f"[Visual] Motion: {samples_processed}/{total_samples} samples",
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
        max_clips: int,
        scene_list: list = None
    ) -> list[tuple[float, float]]:
        """Fuse audio and visual scores, then find the best highlight windows."""
        v_scores_arr = np.array(visual_scores)
        v_scores_norm = (
            v_scores_arr / np.max(v_scores_arr)
            if np.max(v_scores_arr) > 0
            else v_scores_arr
        )

        self._progress.report_progress(69, "Interpolating visual scores to audio timeline...")

        v_scores_interp = np.interp(times, visual_times, v_scores_norm)

        w_audio = self._config.analysis.default_fusion_weights.get('audio', 0.5)
        w_visual = self._config.analysis.default_fusion_weights.get('visual', 0.5)

        self._progress.report_progress(
            70, f"Fusing scores (audio weight={w_audio}, visual weight={w_visual})...",
        )
        total_score = (audio_score * w_audio) + (v_scores_interp * w_visual)

        kernel = self._config.analysis.gaussian_blur_kernel
        smoothed_score = cv2.GaussianBlur(
            total_score.reshape(-1, 1), kernel, 0,
        ).flatten()

        self._progress.report_progress(72, "Searching for best highlight windows...")

        samples_per_sec = len(smoothed_score) / video_duration
        window_size = int(target_duration * samples_per_sec)

        if window_size >= len(smoothed_score):
            self._log.log(
                "Video is shorter than target duration. Using start of video.",
                LogLevel.WARN,
            )
            return [(0.0, 0.0)]

        window_sums = np.convolve(smoothed_score, np.ones(window_size), mode='valid')

        self._log.log(
            f"Sliding window: size={window_size} samples, searched {len(window_sums)} positions.",
            LogLevel.INFO,
        )

        # Non-maximum suppression to find top `max_clips` non-overlapping windows
        sorted_indices = np.argsort(window_sums)[::-1]
        
        selected_clips = []
        for idx in sorted_indices:
            if len(selected_clips) >= max_clips:
                break
                
            overlap = False
            for selected_idx, _, _ in selected_clips:
                if abs(idx - selected_idx) < window_size:
                    overlap = True
                    break
                    
            if not overlap:
                best_start_time = float(times[idx])
                score = float(window_sums[idx])
                
                if scene_list:
                    nearest = min(scene_list, key=lambda s: abs(s[0] - best_start_time))
                    if abs(nearest[0] - best_start_time) < 5.0:
                        self._log.log(f"Snapping highlight from {best_start_time:.2f}s to scene boundary at {nearest[0]:.2f}s", LogLevel.INFO)
                        best_start_time = nearest[0]

                selected_clips.append((idx, best_start_time, score))
                self._log.log(
                    f"Best highlight found at {best_start_time:.2f}s (score: {score:.2f}).",
                    LogLevel.INFO,
                )

        if not selected_clips:
            return [(0.0, 0.0)]

        return [(clip[1], clip[2]) for clip in selected_clips]
