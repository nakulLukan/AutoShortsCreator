from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QProgressBar, QFileDialog,
    QMessageBox, QComboBox, QGroupBox, QSpinBox, QTextEdit,
    QButtonGroup,
)

from autoshorts.config import AppConfig
from autoshorts.models import ProcessingOptions, LogLevel
from autoshorts.ui.worker import ProcessingWorker


class MainWindow(QMainWindow):
    """
    Main application window for AutoShorts Creator.

    Provides the UI for configuring source media, processing settings,
    and output destination. Launches the processing pipeline on a background
    thread and displays real-time progress and log output.
    """

    def __init__(self, config: AppConfig):
        super().__init__()
        self._config = config
        self.setWindowTitle("AutoShorts Creator (Local AI)")
        self.setMinimumSize(800, 600)
        self._setup_ui()
        self._worker = None

    def _setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # ── 1. Input Section ────────────────────────────────────────
        input_group = QGroupBox("1. Source Media")
        input_layout = QVBoxLayout(input_group)

        # Source toggle using QButtonGroup for correct exclusive behavior
        url_layout = QHBoxLayout()
        self._source_group = QButtonGroup(self)
        self._source_group.setExclusive(True)

        self._url_radio = QPushButton("URL")
        self._url_radio.setCheckable(True)
        self._url_radio.setChecked(True)
        self._file_radio = QPushButton("Local File")
        self._file_radio.setCheckable(True)

        self._source_group.addButton(self._url_radio)
        self._source_group.addButton(self._file_radio)

        self._file_radio.clicked.connect(self._browse_file)

        url_layout.addWidget(self._url_radio)
        url_layout.addWidget(self._file_radio)

        self._input_field = QLineEdit()
        self._input_field.setPlaceholderText("Enter YouTube URL here...")

        input_layout.addLayout(url_layout)
        input_layout.addWidget(self._input_field)
        main_layout.addWidget(input_group)

        # ── 2. Configuration Section ────────────────────────────────
        config_group = QGroupBox("2. Settings")
        config_layout = QHBoxLayout(config_group)

        # Duration
        dur_layout = QVBoxLayout()
        dur_layout.addWidget(QLabel("Target Duration (seconds):"))
        self._duration_spinbox = QSpinBox()
        self._duration_spinbox.setRange(15, 60)
        self._duration_spinbox.setValue(30)
        dur_layout.addWidget(self._duration_spinbox)
        config_layout.addLayout(dur_layout)

        # Hardware Acceleration
        hw_layout = QVBoxLayout()
        hw_layout.addWidget(QLabel("Hardware Acceleration:"))
        self._hw_combo = QComboBox()
        self._hw_combo.addItems([
            "CPU (Software)", "NVENC (NVIDIA GPU)", "QSV (Intel GPU)",
        ])
        hw_layout.addWidget(self._hw_combo)
        config_layout.addLayout(hw_layout)

        main_layout.addWidget(config_group)

        # ── 3. Output Section ───────────────────────────────────────
        out_group = QGroupBox("3. Output Destination")
        out_layout = QHBoxLayout(out_group)
        self._out_path_label = QLineEdit(str(Path.home() / "Desktop"))
        self._out_path_label.setReadOnly(True)
        browse_out_btn = QPushButton("Browse...")
        browse_out_btn.clicked.connect(self._browse_output)
        out_layout.addWidget(self._out_path_label)
        out_layout.addWidget(browse_out_btn)
        main_layout.addWidget(out_group)

        # ── 4. Action and Progress ──────────────────────────────────
        action_layout = QHBoxLayout()

        self._start_btn = QPushButton("Generate Short")
        self._start_btn.setMinimumHeight(50)
        self._start_btn.setStyleSheet(
            "background-color: #2e8b57; color: white; font-weight: bold; "
            "font-size: 16px; border-radius: 5px;"
        )
        self._start_btn.clicked.connect(self._start_processing)
        action_layout.addWidget(self._start_btn)

        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setMinimumHeight(50)
        self._stop_btn.setStyleSheet(
            "background-color: #b22222; color: white; font-weight: bold; "
            "font-size: 16px; border-radius: 5px;"
        )
        self._stop_btn.clicked.connect(self._stop_processing)
        self._stop_btn.setVisible(False)
        action_layout.addWidget(self._stop_btn)

        main_layout.addLayout(action_layout)

        self._progress_bar = QProgressBar()
        self._progress_bar.setValue(0)
        main_layout.addWidget(self._progress_bar)

        self._status_label = QLabel("Ready.")
        main_layout.addWidget(self._status_label)

        # ── 5. Log Output ───────────────────────────────────────────
        self._log_area = QTextEdit()
        self._log_area.setReadOnly(True)
        self._log_area.setStyleSheet(
            "background-color: #1e1e1e; color: #d4d4d4; font-family: Consolas;"
        )
        main_layout.addWidget(self._log_area)

    # ── Slot Handlers ───────────────────────────────────────────────

    def _browse_file(self):
        fname, _ = QFileDialog.getOpenFileName(
            self, 'Open Video File', '', 'Video Files (*.mp4 *.mkv *.avi)',
        )
        if fname:
            self._input_field.setText(fname)
            self._url_radio.setChecked(False)
            self._file_radio.setChecked(True)

    def _browse_output(self):
        directory = QFileDialog.getExistingDirectory(self, 'Select Output Directory')
        if directory:
            self._out_path_label.setText(directory)

    def log(self, message: str, level: str = LogLevel.INFO):
        """Append a colored log message to the log area."""
        color = "white"
        if level == LogLevel.ERROR:
            color = "red"
        elif level == LogLevel.WARN:
            color = "orange"
        elif level == LogLevel.DEBUG:
            color = "gray"

        self._log_area.append(
            f'<span style="color:{color}">[{level}] {message}</span>'
        )
        # Auto-scroll to bottom
        scrollbar = self._log_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def update_progress(self, val: int, msg: str):
        """Update progress bar and status label."""
        self._progress_bar.setValue(val)
        self._status_label.setText(msg)

    def _start_processing(self):
        input_src = self._input_field.text().strip()
        if not input_src:
            QMessageBox.warning(
                self, "Error", "Please provide a valid URL or local file path.",
            )
            return

        # Prepare Options
        hw_sel = self._hw_combo.currentText()
        hw_flag = "CPU"
        if "NVENC" in hw_sel:
            hw_flag = "NVENC"
        elif "QSV" in hw_sel:
            hw_flag = "QSV"

        opts = ProcessingOptions(
            input_source=input_src,
            is_url=self._url_radio.isChecked(),
            output_dir=self._out_path_label.text(),
            target_duration=self._duration_spinbox.value(),
            hardware_accel=hw_flag,
            fusion_weights=self._config.analysis.default_fusion_weights,
        )

        # Update UI state
        self._start_btn.setEnabled(False)
        self._stop_btn.setVisible(True)
        self._progress_bar.setValue(0)
        self._log_area.clear()
        self.log("Starting AutoShorts Pipeline...", LogLevel.INFO)

        # Start Worker Thread
        self._worker = ProcessingWorker(opts, self._config)
        self._worker.progress_signal.connect(self.update_progress)
        self._worker.log_signal.connect(self.log)
        self._worker.finished_signal.connect(self._processing_finished)
        self._worker.cancelled_signal.connect(self._processing_cancelled)
        self._worker.start()

    def _stop_processing(self):
        """Request cancellation of the running worker thread."""
        if self._worker is not None and self._worker.isRunning():
            self._stop_btn.setEnabled(False)
            self._status_label.setText("Stopping...")
            self.log("Stop requested — waiting for current step to finish...", LogLevel.WARN)
            self._worker.requestInterruption()

    def _processing_cancelled(self):
        """Handle worker cancellation."""
        self._start_btn.setEnabled(True)
        self._stop_btn.setVisible(False)
        self._stop_btn.setEnabled(True)
        self._status_label.setText("Cancelled.")
        self.log("Processing was stopped by user.", LogLevel.WARN)

    def _processing_finished(self, success: bool, message: str):
        self._start_btn.setEnabled(True)
        self._stop_btn.setVisible(False)
        self._stop_btn.setEnabled(True)
        if success:
            self._status_label.setText("Success!")
            self._progress_bar.setValue(100)
            QMessageBox.information(
                self, "Complete",
                "Short generated successfully!\nCheck your output directory.",
            )
        else:
            self._status_label.setText("Failed.")
            QMessageBox.critical(
                self, "Error", f"Processing failed:\n{message}",
            )
