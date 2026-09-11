from PyQt6.QtCore import QThread, pyqtSignal

from autoshorts.config import AppConfig
from autoshorts.models import ProcessingOptions
from autoshorts.core.engine import VideoProcessorEngine
from autoshorts.core.protocols import CancellationError


class _WorkerLogger:
    """Adapter that bridges the Logger protocol to Qt signals."""

    def __init__(self, signal: pyqtSignal):
        self._signal = signal

    def log(self, message: str, level: str) -> None:
        self._signal.emit(message, level)


class _WorkerProgressReporter:
    """Adapter that bridges the ProgressReporter protocol to Qt signals."""

    def __init__(self, signal: pyqtSignal):
        self._signal = signal

    def report_progress(self, percentage: int, message: str) -> None:
        self._signal.emit(percentage, message)


class _WorkerCancellationToken:
    """Adapter that bridges QThread.isInterruptionRequested to the CancellationToken protocol."""

    def __init__(self, thread: QThread):
        self._thread = thread

    def is_cancelled(self) -> bool:
        return self._thread.isInterruptionRequested()


class ProcessingWorker(QThread):
    """
    Background thread for executing the video processing engine.

    Bridges the engine's Logger, ProgressReporter, and CancellationToken
    protocols to Qt signals so the UI stays responsive and receives live updates.
    """
    progress_signal = pyqtSignal(int, str)
    log_signal = pyqtSignal(str, str)
    finished_signal = pyqtSignal(bool, str)
    cancelled_signal = pyqtSignal()

    def __init__(self, options: ProcessingOptions, config: AppConfig):
        super().__init__()
        self._options = options
        self._config = config

    def run(self):
        try:
            logger = _WorkerLogger(self.log_signal)
            progress = _WorkerProgressReporter(self.progress_signal)
            cancel_token = _WorkerCancellationToken(self)

            engine = VideoProcessorEngine(
                options=self._options,
                config=self._config,
                logger=logger,
                progress_reporter=progress,
                cancellation_token=cancel_token,
            )
            engine.process()
            self.finished_signal.emit(True, "Processing completed successfully.")
        except CancellationError:
            self.cancelled_signal.emit()
        except Exception as e:
            self.finished_signal.emit(False, str(e))

