"""
AutoShorts Creator — Entry Point

Bootstraps the PyQt6 application with dark theme, verifies FFmpeg
availability, and launches the main window.
"""
import sys
import subprocess

from PyQt6.QtWidgets import QApplication, QMessageBox

from autoshorts.config import AppConfig
from autoshorts.ui.theme import apply_dark_theme
from autoshorts.ui.main_window import MainWindow


def _check_ffmpeg(config: AppConfig) -> bool:
    """Verify that the bundled FFmpeg binary is accessible."""
    try:
        subprocess.run(
            [config.ffmpeg_path, '-version'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except FileNotFoundError:
        return False


def main():
    config = AppConfig()
    app = QApplication(sys.argv)
    apply_dark_theme(app)

    if not _check_ffmpeg(config):
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setText("FFmpeg not found!")
        msg.setInformativeText(
            "FFmpeg is required for video manipulation. "
            "Please install it and add it to your system PATH."
        )
        msg.setWindowTitle("Missing Dependency")
        msg.exec()
        sys.exit(1)

    window = MainWindow(config)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()