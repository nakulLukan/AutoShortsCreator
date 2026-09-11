import sys
import os
import json
import threading
import subprocess
import traceback
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass
from pathlib import Path
import math

# Resolve paths to bundled FFmpeg binaries next to this script
_SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
FFMPEG_PATH = str(_SCRIPT_DIR / "ffmpeg.exe")
FFPROBE_PATH = str(_SCRIPT_DIR / "ffprobe.exe")

# PyQt6 for modern desktop UI
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QProgressBar, QFileDialog,
    QMessageBox, QComboBox, QGroupBox, QSpinBox, QTextEdit
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QIcon, QColor, QPalette

# Data processing and AI
import numpy as np
import cv2
import librosa
import yt_dlp

@dataclass
class ProcessingOptions:
    input_source: str
    is_url: bool
    output_dir: str
    target_duration: int
    hardware_accel: str
    fusion_weights: dict

class LogLevel:
    INFO = "INFO"
    WARN = "WARNING"
    ERROR = "ERROR"
    DEBUG = "DEBUG"

class VideoProcessorEngine:
    """
    Core engine handling downloading, analysis, and rendering.
    Follows Single Responsibility Principle by delegating tasks.
    """
    def __init__(self, options: ProcessingOptions, logger_callback, progress_callback):
        self.options = options
        self.log = logger_callback
        self.report_progress = progress_callback
        self.temp_dir = Path("temp_processing")
        self.temp_dir.mkdir(exist_ok=True)

        # Determine output filename
        source_name = "local_video" if not self.options.is_url else "youtube_video"
        if not self.options.is_url:
            source_name = Path(self.options.input_source).stem

        self.output_path = Path(self.options.output_dir) / f"{source_name}_short.mp4"
        self.working_file = ""

    def process(self):
        try:
            self.report_progress(5, "Starting processing pipeline...")

            # Step 1: Ingestion
            if self.options.is_url:
                self.working_file, heatmap_data = self._download_youtube_video(self.options.input_source)
            else:
                self.working_file = self.options.input_source
                heatmap_data = None

            self.report_progress(25, f"Media ready: {self.working_file}")

            # Step 2: Highlight Detection
            start_time = 0.0
            if heatmap_data:
                self.log("Using YouTube Heatmap data for highlight extraction.", LogLevel.INFO)
                start_time = self._analyze_heatmap(heatmap_data)
            else:
                self.log("No heatmap data available. Starting Multimodal AI Analysis.", LogLevel.INFO)
                start_time = self._multimodal_analysis(self.working_file)

            self.report_progress(75, f"Highlight identified at {start_time:.2f} seconds.")

            # Step 3: Cropping and Rendering
            self._render_final_video(self.working_file, start_time)

            self.report_progress(100, "Processing Complete!")
            self.log(f"Final video saved to: {self.output_path}", LogLevel.INFO)

        except Exception as e:
            self.log(f"Pipeline Failed: {str(e)}\n{traceback.format_exc()}", LogLevel.ERROR)
            raise e

    def _download_youtube_video(self, url: str) -> Tuple[str, Optional[List[Dict]]]:
        """Downloads video using yt-dlp and attempts to extract heatmap metadata."""
        self.log(f"Downloading video from {url}...", LogLevel.INFO)

        output_template = str(self.temp_dir / "%(id)s.%(ext)s")
        heatmap_data = None

        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': output_template,
            'quiet': True,
            'no_warnings': True,
            'dump_single_json': True, # We need to extract metadata first
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # First extract info to check for heatmap
            self.report_progress(10, "Extracting metadata...")
            info_dict = ydl.extract_info(url, download=False)

            # Check for heatmap (often embedded in annotations or heatmaps key depending on yt-dlp version)
            if 'heatmap' in info_dict:
                heatmap_data = info_dict['heatmap']

            # Now download
            self.report_progress(15, "Downloading media files (this may take a while)...")
            ydl_opts['dump_single_json'] = False
            with yt_dlp.YoutubeDL(ydl_opts) as ydl_download:
                error_code = ydl_download.download([url])
                if error_code != 0:
                    raise Exception("yt-dlp failed to download the video.")

            # yt-dlp cleans up names, so we construct the expected filename
            expected_file = self.temp_dir / f"{info_dict['id']}.mp4"
            if not expected_file.exists():
                 # Fallback search if format changed extension
                 files = list(self.temp_dir.glob(f"{info_dict['id']}.*"))
                 if not files:
                     raise FileNotFoundError("Downloaded file could not be located.")
                 expected_file = files[0]

        return str(expected_file), heatmap_data

    def _analyze_heatmap(self, heatmap: List[Dict]) -> float:
        """Finds the peak of the youtube heatmap."""
        self.report_progress(30, "Analyzing heatmap data...")
        if not heatmap:
            return 0.0

        peak_time = 0.0
        max_value = 0.0

        for point in heatmap:
            if 'value' in point and 'start_time' in point:
                if point['value'] > max_value:
                    max_value = point['value']
                    peak_time = point['start_time']

        # Ensure we don't start too close to the end
        safe_peak = max(0, peak_time - (self.options.target_duration / 2))
        return safe_peak

    def _multimodal_analysis(self, video_path: str) -> float:
        """
        Analyzes audio energy (RMS/Spectral Flux) and visual motion (Dense Optical Flow)
        to find the most engaging segment.
        """
        self.report_progress(35, "Extracting audio for analysis...")

        # 1. Audio Analysis (Energy / Volume peak)
        audio_path = str(self.temp_dir / "temp_audio.wav")
        result = subprocess.run([
            FFMPEG_PATH, '-y', '-i', video_path,
            '-vn', '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1',
            audio_path
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        if result.returncode != 0:
            self.log(f"FFmpeg audio extraction failed: {result.stderr}", LogLevel.ERROR)
            raise Exception(f"FFmpeg audio extraction failed: {result.stderr}")

        self.report_progress(45, "Calculating acoustic energy...")
        y, sr = librosa.load(audio_path, sr=16000)

        # Calculate RMS energy
        rms = librosa.feature.rms(y=y)[0]
        times = librosa.frames_to_time(np.arange(len(rms)), sr=sr)

        # Calculate Onset Strength (Spectral Flux)
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)

        # Normalize audio scores
        rms_norm = rms / np.max(rms) if np.max(rms) > 0 else rms
        onset_norm = onset_env / np.max(onset_env) if np.max(onset_env) > 0 else onset_env
        audio_score = (rms_norm * 0.5) + (onset_norm * 0.5)

        self.report_progress(55, "Calculating visual motion magnitude...")
        # 2. Visual Analysis (Optical Flow - sampled for speed)
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        video_duration = total_frames / fps

        # Sample rate: process 2 frames per second to save computation
        frame_step = int(fps / 2)

        visual_scores = []
        visual_times = []

        ret, prev_frame = cap.read()
        if ret:
            prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
            prev_gray = cv2.resize(prev_gray, (320, 180)) # Downscale for speed

            frame_count = 0
            while cap.isOpened():
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_count)
                ret, frame = cap.read()
                if not ret:
                    break

                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                gray = cv2.resize(gray, (320, 180))

                # Farneback Dense Optical Flow
                flow = cv2.calcOpticalFlowFarneback(prev_gray, gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
                mag, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
                mean_mag = np.mean(mag)

                visual_scores.append(mean_mag)
                visual_times.append(frame_count / fps)

                prev_gray = gray
                frame_count += frame_step

                if frame_count > total_frames:
                    break

        cap.release()

        # Normalize visual scores
        v_scores_arr = np.array(visual_scores)
        v_scores_norm = v_scores_arr / np.max(v_scores_arr) if np.max(v_scores_arr) > 0 else v_scores_arr

        self.report_progress(65, "Fusing multimodal scores...")

        # 3. Fusion using Sliding Window
        # Interpolate visual scores to match audio timeline resolution
        v_scores_interp = np.interp(times, visual_times, v_scores_norm)

        w_audio = self.options.fusion_weights.get('audio', 0.5)
        w_visual = self.options.fusion_weights.get('visual', 0.5)

        total_score = (audio_score * w_audio) + (v_scores_interp * w_visual)

        # Apply 1D Gaussian filter to smooth the scores
        smoothed_score = cv2.GaussianBlur(total_score.reshape(-1, 1), (51, 1), 0).flatten()

        # Find the window of `target_duration` with the highest integral (sum)
        samples_per_sec = len(smoothed_score) / video_duration
        window_size = int(self.options.target_duration * samples_per_sec)

        max_sum = -1
        best_start_idx = 0

        # Ensure window isn't larger than the video
        if window_size >= len(smoothed_score):
             return 0.0

        for i in range(len(smoothed_score) - window_size):
            window_sum = np.sum(smoothed_score[i:i+window_size])
            if window_sum > max_sum:
                max_sum = window_sum
                best_start_idx = i

        best_start_time = times[best_start_idx]
        return best_start_time

    def _render_final_video(self, video_path: str, start_time: float):
        """Uses FFmpeg to slice, crop to 9:16, and encode."""
        self.report_progress(80, "Rendering final vertical video...")

        # Construct FFmpeg command
        cmd = [FFMPEG_PATH, '-y', '-ss', str(start_time), '-i', video_path, '-t', str(self.options.target_duration)]

        # 1. Hardware Acceleration Selection
        hw_accel = self.options.hardware_accel
        vcodec = 'libx264' # Default software fallback

        if hw_accel == "NVENC":
            vcodec = 'h264_nvenc'
            # Note: Putting -hwaccel cuda before -i is best practice, but for simple setups this works
        elif hw_accel == "QSV":
            vcodec = 'h264_qsv'

        # 2. Smart Cropping (Center crop for 9:16)
        # In a full implementation, YOLOv8 object tracking would provide dynamic X coordinates here.
        # For this standalone file, we use a static center crop via FFmpeg filtergraph to ensure reliability.
        filter_complex = "[0:v]crop=ih*(9/16):ih[v_cropped]"

        cmd.extend([
            '-filter_complex', filter_complex,
            '-map', '[v_cropped]',
            '-map', '0:a',
            '-c:v', vcodec,
            '-preset', 'fast',
            '-crf', '23',
            '-c:a', 'aac',
            '-b:a', '128k',
            str(self.output_path)
        ])

        self.log(f"Executing FFmpeg: {' '.join(cmd)}", LogLevel.DEBUG)

        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)

        for line in process.stdout:
            # Parse FFmpeg output to update progress slightly if needed, though it's fast
            if "time=" in line:
                self.log(f"FFmpeg encoding... {line.strip()}", LogLevel.DEBUG)

        process.wait()
        if process.returncode != 0:
            raise Exception(f"FFmpeg rendering failed with exit code {process.returncode}")

class ProcessingWorker(QThread):
    """Background thread for executing the processing engine."""
    progress_signal = pyqtSignal(int, str)
    log_signal = pyqtSignal(str, str)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, options: ProcessingOptions):
        super().__init__()
        self.options = options
        self.engine = VideoProcessorEngine(
            self.options,
            self._log_callback,
            self._progress_callback
        )

    def _log_callback(self, message: str, level: str):
        self.log_signal.emit(message, level)

    def _progress_callback(self, percentage: int, message: str):
        self.progress_signal.emit(percentage, message)

    def run(self):
        try:
            self.engine.process()
            self.finished_signal.emit(True, "Processing completed successfully.")
        except Exception as e:
            self.finished_signal.emit(False, str(e))

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AutoShorts Creator (Local AI)")
        self.setMinimumSize(800, 600)
        self._setup_ui()
        self.worker = None

    def _setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # 1. Input Section
        input_group = QGroupBox("1. Source Media")
        input_layout = QVBoxLayout(input_group)

        url_layout = QHBoxLayout()
        self.url_radio = QPushButton("URL")
        self.url_radio.setCheckable(True)
        self.url_radio.setChecked(True)
        self.file_radio = QPushButton("Local File")
        self.file_radio.setCheckable(True)

        url_layout.addWidget(self.url_radio)
        url_layout.addWidget(self.file_radio)

        # Exclusive toggle logic
        self.url_radio.clicked.connect(lambda: self.file_radio.setChecked(False))
        self.file_radio.clicked.connect(lambda: self.url_radio.setChecked(False))
        self.file_radio.clicked.connect(self._browse_file)

        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Enter YouTube URL here...")

        input_layout.addLayout(url_layout)
        input_layout.addWidget(self.input_field)
        main_layout.addWidget(input_group)

        # 2. Configuration Section
        config_group = QGroupBox("2. Settings")
        config_layout = QHBoxLayout(config_group)

        # Duration
        dur_layout = QVBoxLayout()
        dur_layout.addWidget(QLabel("Target Duration (seconds):"))
        self.duration_spinbox = QSpinBox()
        self.duration_spinbox.setRange(15, 60)
        self.duration_spinbox.setValue(30)
        dur_layout.addWidget(self.duration_spinbox)
        config_layout.addLayout(dur_layout)

        # Hardware Acceleration
        hw_layout = QVBoxLayout()
        hw_layout.addWidget(QLabel("Hardware Acceleration:"))
        self.hw_combo = QComboBox()
        self.hw_combo.addItems(["CPU (Software)", "NVENC (NVIDIA GPU)", "QSV (Intel GPU)"])
        hw_layout.addWidget(self.hw_combo)
        config_layout.addLayout(hw_layout)

        main_layout.addWidget(config_group)

        # 3. Output Section
        out_group = QGroupBox("3. Output Destination")
        out_layout = QHBoxLayout(out_group)
        self.out_path_label = QLineEdit(str(Path.home() / "Desktop"))
        self.out_path_label.setReadOnly(True)
        browse_out_btn = QPushButton("Browse...")
        browse_out_btn.clicked.connect(self._browse_output)
        out_layout.addWidget(self.out_path_label)
        out_layout.addWidget(browse_out_btn)
        main_layout.addWidget(out_group)

        # 4. Action and Progress
        self.start_btn = QPushButton("Generate Short")
        self.start_btn.setMinimumHeight(50)
        self.start_btn.setStyleSheet("background-color: #2e8b57; color: white; font-weight: bold; font-size: 16px; border-radius: 5px;")
        self.start_btn.clicked.connect(self._start_processing)
        main_layout.addWidget(self.start_btn)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("Ready.")
        main_layout.addWidget(self.status_label)

        # 5. Log Output
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4; font-family: Consolas;")
        main_layout.addWidget(self.log_area)

    def _browse_file(self):
        fname, _ = QFileDialog.getOpenFileName(self, 'Open Video File', '', 'Video Files (*.mp4 *.mkv *.avi)')
        if fname:
            self.input_field.setText(fname)
            self.url_radio.setChecked(False)
            self.file_radio.setChecked(True)

    def _browse_output(self):
        directory = QFileDialog.getExistingDirectory(self, 'Select Output Directory')
        if directory:
             self.out_path_label.setText(directory)

    def log(self, message: str, level: str = LogLevel.INFO):
        color = "white"
        if level == LogLevel.ERROR: color = "red"
        elif level == LogLevel.WARN: color = "orange"
        elif level == LogLevel.DEBUG: color = "gray"

        self.log_area.append(f'<span style="color:{color}">[{level}] {message}</span>')
        # Auto-scroll to bottom
        scrollbar = self.log_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def update_progress(self, val: int, msg: str):
        self.progress_bar.setValue(val)
        self.status_label.setText(msg)

    def _start_processing(self):
        input_src = self.input_field.text().strip()
        if not input_src:
            QMessageBox.warning(self, "Error", "Please provide a valid URL or local file path.")
            return

        # Prepare Options
        hw_sel = self.hw_combo.currentText()
        hw_flag = "CPU"
        if "NVENC" in hw_sel: hw_flag = "NVENC"
        elif "QSV" in hw_sel: hw_flag = "QSV"

        opts = ProcessingOptions(
            input_source=input_src,
            is_url=self.url_radio.isChecked(),
            output_dir=self.out_path_label.text(),
            target_duration=self.duration_spinbox.value(),
            hardware_accel=hw_flag,
            fusion_weights={'audio': 0.6, 'visual': 0.4} # slightly favor audio events
        )

        # Update UI state
        self.start_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.log_area.clear()
        self.log("Starting AutoShorts Pipeline...", LogLevel.INFO)

        # Start Worker Thread
        self.worker = ProcessingWorker(opts)
        self.worker.progress_signal.connect(self.update_progress)
        self.worker.log_signal.connect(self.log)
        self.worker.finished_signal.connect(self._processing_finished)
        self.worker.start()

    def _processing_finished(self, success: bool, message: str):
        self.start_btn.setEnabled(True)
        if success:
            self.status_label.setText("Success!")
            self.progress_bar.setValue(100)
            QMessageBox.information(self, "Complete", "Short generated successfully!\nCheck your output directory.")
        else:
            self.status_label.setText("Failed.")
            QMessageBox.critical(self, "Error", f"Processing failed:\n{message}")

def check_dependencies():
    """Ensure FFmpeg is installed and accessible."""
    try:
        subprocess.run([FFMPEG_PATH, '-version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except FileNotFoundError:
        return False

if __name__ == "__main__":
    app = QApplication(sys.argv)

    # Set modern dark fusion style
    app.setStyle("Fusion")
    dark_palette = QPalette()
    dark_palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Base, QColor(25, 25, 25))
    dark_palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ColorRole.ToolTipBase, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.ToolTipText, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
    dark_palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)
    app.setPalette(dark_palette)

    if not check_dependencies():
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setText("FFmpeg not found!")
        msg.setInformativeText("FFmpeg is required for video manipulation. Please install it and add it to your system PATH.")
        msg.setWindowTitle("Missing Dependency")
        msg.exec()
        sys.exit(1)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())